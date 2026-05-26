from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage1_6_latest_scoreboard_diagnostic import (
    build_stage1_6_latest_scoreboard_diagnostic,
    discover_latest_scoreboard_context,
)


class StageOneSixLatestScoreboardDiagnosticTests(unittest.TestCase):
    def test_diagnostic_summarizes_latest_scoreboard_comparison_and_followup_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            previous = root / "previous.json"
            latest = root / "latest.json"
            comparison = root / "comparison.json"
            followup = root / "followup.json"
            out = root / "out"
            _write_scoreboard(
                previous,
                missing_backfill=15,
                public_identifier_backfilled=0,
                official_ready=0,
                public_blocked=5,
                source_not_found=10,
                limited=0,
                rate=0.0,
            )
            _write_scoreboard(
                latest,
                missing_backfill=0,
                public_identifier_backfilled=10,
                official_ready=7,
                public_blocked=3,
                source_not_found=5,
                limited=0,
                rate=0.0,
            )
            _write_json(
                comparison,
                {
                    "delta_from_previous_row": [
                        {
                            "public_source_deepening_effect_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILL_EFFECTIVE",
                            "regression_flags": [],
                        }
                    ],
                    "public_source_deepening_recommendations": [
                        {
                            "decision": "CONTINUE_PUBLIC_SOURCE_DEEPENING",
                            "effect_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILL_EFFECTIVE",
                        }
                    ],
                },
            )
            _write_json(
                followup,
                {
                    "summary": {
                        "followup_record_count": 3,
                        "followup_route_counts": {"ygp_retry_then_local_authority_fallback": 2},
                        "execution_priority_counts": {"HIGH_PUBLIC_SOURCE_DEEPENING": 3},
                        "public_source_deepening_recommended_counts": {"true": 3},
                    },
                    "next_regression_execution_plan": {
                        "plan_state": "PUBLIC_SOURCE_DEEPENING_RUN_RECOMMENDED"
                    },
                },
            )

            result = build_stage1_6_latest_scoreboard_diagnostic(
                latest_scoreboard_json=latest,
                previous_scoreboard_json=previous,
                scoreboard_comparison_json=comparison,
                followup_queue_json=followup,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )
            json_exists = (out / "stage1-6-latest-scoreboard-diagnostic-v1.json").exists()
            markdown_exists = (out / "stage1-6-latest-scoreboard-diagnostic-v1.md").exists()

        self.assertEqual(result["delta_from_previous"]["missing_project_code_backfill_input_delta"], -15)
        self.assertEqual(result["delta_from_previous"]["public_identifier_backfilled_delta"], 10)
        self.assertEqual(
            result["stage5_diagnosis"]["diagnosis_state"],
            "OFFICIAL_READBACK_READY_NEEDS_B_OR_C_RELEASE_EVIDENCE_REVIEW",
        )
        self.assertEqual(result["p0_gap_summary"]["official_readback_ready_not_limited_count"], 7)
        self.assertEqual(result["official_readback_ready_review_queue"]["record_count"], 1)
        self.assertEqual(
            result["official_readback_ready_review_queue"]["review_blocker_state_counts"],
            {"PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE": 1},
        )
        self.assertEqual(
            result["official_readback_ready_review_queue"]["records"][0]["recommended_next_action"],
            "feed_public_identifier_to_release_evidence_adapter_before_limited_review",
        )
        self.assertEqual(result["release_evidence_promotion_queue"]["record_count"], 1)
        self.assertEqual(
            result["release_evidence_promotion_queue"]["records"][0]["promotion_state"],
            "PUBLIC_IDENTIFIER_READY_NEEDS_B_OR_C_RELEASE_EVIDENCE_READBACK",
        )
        self.assertEqual(
            result["release_evidence_promotion_queue"]["records"][0]["ygp_project_code_variants"],
            ["E4413000835979563001"],
        )
        self.assertFalse(result["release_evidence_promotion_queue"]["records"][0]["gdcic_project_code_route_allowed"])
        self.assertIn(
            "promote_public_identifiers_to_b_or_c_release_evidence_readback_before_limited_projection",
            result["recommended_next_actions"],
        )
        self.assertEqual(result["p0_gap_summary"]["followup_queue_remaining_count"], 3)
        self.assertEqual(result["p0_gap_summary"]["release_evidence_promotion_required_count"], 1)
        self.assertTrue(result["p0_gap_summary"]["comparison_recommends_deepening"])
        self.assertIn(
            "run_stage4_followup_queue_through_controller_before_manual_triage",
            result["recommended_next_actions"],
        )
        self.assertIn("keep_not_found_blocked_as_non_clearance", result["recommended_next_actions"])
        self.assertFalse(result["safety"]["customer_visible_allowed"])
        self.assertTrue(json_exists)
        self.assertTrue(markdown_exists)

    def test_diagnostic_surfaces_projection_input_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            latest = root / "latest.json"
            out = root / "out"
            _write_json(
                latest,
                {
                    "scoreboard": {
                        "candidate_count": 23,
                        "stage2_success_count": 0,
                        "stage3_success_count": 0,
                        "input_mode": "STAGE4_BACKFILL_FOLLOWUP_PUBLIC_SOURCE_ROUTES",
                        "denominator_kind": "FOLLOWUP_PROJECT_ROWS",
                        "clean_batch_comparable": False,
                        "projection_or_merge_state": "FOLLOWUP_OR_MERGED_PROJECTION",
                        "input_lineage_warning": "treat rate as follow-up/projection",
                        "limited_sellable_review_candidate_count": 6,
                        "real_public_sellable_pack_rate": 0.2609,
                        "stage5_operational_primary_track_counts": {"strong_lead": 6},
                        "stage5_operational_priority_bucket_counts": {"P0_LIMITED_SELLABLE_REVIEW": 6},
                    },
                    "project_rows": [],
                },
            )

            result = build_stage1_6_latest_scoreboard_diagnostic(
                latest_scoreboard_json=latest,
                output_root=out,
                created_at="2026-05-26T00:00:00+08:00",
            )

        self.assertEqual(result["latest_run"]["input_mode"], "STAGE4_BACKFILL_FOLLOWUP_PUBLIC_SOURCE_ROUTES")
        self.assertEqual(result["latest_run"]["denominator_kind"], "FOLLOWUP_PROJECT_ROWS")
        self.assertFalse(result["latest_run"]["clean_batch_comparable"])
        self.assertEqual(result["latest_run"]["projection_or_merge_state"], "FOLLOWUP_OR_MERGED_PROJECTION")
        self.assertEqual(result["p0_gap_summary"]["projection_or_merge_state"], "FOLLOWUP_OR_MERGED_PROJECTION")
        self.assertFalse(result["p0_gap_summary"]["clean_batch_comparable"])
        self.assertIn("follow-up/projection", result["p0_gap_summary"]["input_lineage_warning"])

    def test_diagnostic_auto_discovers_latest_scoreboard_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            previous = root / "run-previous" / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            latest = root / "run-latest" / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            comparison = root / "run-latest" / "comparison" / "stage1-6-scoreboard-comparison-v1.json"
            followup = root / "run-latest" / "stage4-followup" / "stage4-backfill-followup-queue-v1.json"
            out = root / "out"
            _write_scoreboard(
                previous,
                missing_backfill=10,
                public_identifier_backfilled=0,
                official_ready=0,
                public_blocked=4,
                source_not_found=6,
                limited=0,
                rate=0.0,
            )
            _write_scoreboard(
                latest,
                missing_backfill=0,
                public_identifier_backfilled=3,
                official_ready=3,
                public_blocked=1,
                source_not_found=2,
                limited=3,
                rate=0.2,
            )
            _write_json(
                comparison,
                {
                    "delta_from_previous_row": [
                        {
                            "public_source_deepening_effect_state": "LIMITED_SELLABLE_RATE_IMPROVED",
                            "regression_flags": [],
                        }
                    ],
                    "public_source_deepening_recommendations": [],
                },
            )
            _write_json(
                followup,
                {
                    "summary": {
                        "followup_record_count": 1,
                        "followup_route_counts": {"local_authority_not_found_specific_endpoint_or_manual_source": 1},
                    },
                    "next_regression_execution_plan": {"plan_state": "FOLLOWUP_CONTROLLER_CHAIN_READY"},
                },
            )
            os.utime(previous, (1, 1))
            os.utime(latest, (2, 2))
            os.utime(comparison, (2, 2))
            os.utime(followup, (2, 2))

            discovered = discover_latest_scoreboard_context(search_root=root)
            result = build_stage1_6_latest_scoreboard_diagnostic(
                search_root=root,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        self.assertEqual(discovered["latest_scoreboard_json"], str(latest))
        self.assertEqual(discovered["previous_scoreboard_json"], str(previous))
        self.assertEqual(discovered["scoreboard_comparison_json"], str(comparison))
        self.assertEqual(discovered["followup_queue_json"], str(followup))
        self.assertEqual(result["discovery"]["discovery_state"], "AUTO_DISCOVERED_LATEST_SCOREBOARD")
        self.assertEqual(result["input_refs"]["latest_scoreboard_json"], str(latest))
        self.assertEqual(result["input_refs"]["previous_scoreboard_json"], str(previous))
        self.assertEqual(result["p0_gap_summary"]["followup_queue_remaining_count"], 1)
        self.assertEqual(result["stage5_diagnosis"]["diagnosis_state"], "LIMITED_SELLABLE_REVIEW_CANDIDATES_PRESENT")

    def test_diagnostic_surfaces_local_authority_region_resolution_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            latest = root / "latest.json"
            out = root / "out"
            _write_scoreboard(
                latest,
                missing_backfill=0,
                public_identifier_backfilled=0,
                official_ready=0,
                public_blocked=0,
                source_not_found=9,
                limited=0,
                rate=0.0,
                local_authority_region_resolution_required=6,
            )

            result = build_stage1_6_latest_scoreboard_diagnostic(
                latest_scoreboard_json=latest,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        self.assertEqual(
            result["stage5_diagnosis"]["diagnosis_state"],
            "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED_BEFORE_READBACK",
        )
        self.assertEqual(result["stage5_diagnosis"]["local_authority_region_resolution_required_count"], 6)
        self.assertEqual(
            result["stage5_diagnosis"]["local_authority_resolution_state_counts"],
            {"LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED": 6},
        )
        self.assertEqual(result["p0_gap_summary"]["local_authority_region_resolution_required_count"], 6)
        self.assertIn(
            "resolve_local_authority_region_before_retrying_public_readback",
            result["recommended_next_actions"],
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])
        self.assertTrue(result["safety"]["query_miss_is_not_clearance"])


def _write_scoreboard(
    path: Path,
    *,
    missing_backfill: int,
    public_identifier_backfilled: int,
    official_ready: int,
    public_blocked: int,
    source_not_found: int,
    limited: int,
    rate: float,
    local_authority_region_resolution_required: int = 0,
) -> None:
    primary_track_counts = {
        "official_readback_ready": official_ready,
        "public_source_blocked": public_blocked,
        "source_not_found": source_not_found,
    }
    priority_bucket_counts = {
        "P1_OFFICIAL_READBACK_DEEPENING": official_ready,
        "P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE": public_blocked + local_authority_region_resolution_required,
        "P2_NOT_FOUND_NON_CLEARANCE_DEEPENING": source_not_found,
    }
    if local_authority_region_resolution_required:
        primary_track_counts["local_authority_region_resolution_required"] = local_authority_region_resolution_required
    _write_json(
        path,
        {
            "scoreboard": {
                "candidate_count": 15,
                "stage2_success_count": 15,
                "stage3_success_count": 15,
                "limited_sellable_review_candidate_count": limited,
                "real_public_sellable_pack_rate": rate,
                "stage5_operational_primary_track_counts": primary_track_counts,
                "stage5_operational_priority_bucket_counts": priority_bucket_counts,
                "stage4_public_readback_channel_outcome_counts": {
                    "YGP:YGP_READBACK_READY": official_ready,
                    "LOCAL_AUTHORITY:BLOCKED": public_blocked,
                    "LOCAL_AUTHORITY:NOT_FOUND": source_not_found,
                },
                "stage4_project_code_backfill_state_counts": {
                    "MISSING_PROJECT_CODE_BACKFILL_INPUT": missing_backfill,
                    "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": public_identifier_backfilled,
                },
            },
            "project_rows": [
                {
                    "project_id": "PROJ-A",
                    "project_name": "样本项目",
                    "stage5_operational_primary_track": "official_readback_ready",
                    "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                    "stage5_operational_review_families": [
                        "official_readback_ready",
                        "evidence_insufficient",
                    ],
                    "stage4_project_code_backfill_state": (
                        "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                    ),
                    "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE",
                    "p13b_overlap_ygp_project_code_variants": ["E4413000835979563001"],
                    "p13b_overlap_ygp_biz_code_variants": ["3C52"],
                    "p13b_overlap_ygp_site_code_variants": ["441300"],
                    "p13b_overlap_ygp_notice_id_variants": ["notice-1"],
                    "stage4_gdcic_project_code_route_policy": "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
                    "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    "p13b_original_notice_readback_state": "PENDING_OR_NOT_RUN",
                    "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
                    "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                    "customer_visible_allowed": False,
                    "query_miss_is_not_clearance": True,
                }
            ]
            + (
                [
                    {
                        "project_id": f"PROJ-REGION-{index}",
                        "project_name": "地方源地区待解析样本",
                        "stage5_operational_primary_track": "local_authority_region_resolution_required",
                        "stage5_operational_review_bucket": "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED_REVIEW",
                        "p13b_public_source_readback_state": "LOCAL_AUTHORITY_BLOCKED_REVIEW",
                        "p13b_local_authority_resolution_state_counts": {
                            "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED": 1
                        },
                        "customer_visible_allowed": False,
                        "query_miss_is_not_clearance": True,
                    }
                    for index in range(local_authority_region_resolution_required)
                ]
                if local_authority_region_resolution_required
                else []
            ),
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
