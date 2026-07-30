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

from storage.stage1_6_limited_success_attribution import (
    build_stage1_6_limited_success_attribution,
    discover_limited_success_attribution_context,
)


class StageOneSixLimitedSuccessAttributionTests(unittest.TestCase):
    def test_attributes_success_to_b_or_c_release_evidence_not_public_identifier_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            success = root / "live12.json"
            target = root / "live15.json"
            out = root / "out"
            _write_json(
                success,
                {
                    "scoreboard": {
                        "candidate_count": 12,
                        "limited_sellable_review_candidate_count": 1,
                        "real_public_sellable_pack_rate": 0.0833,
                        "stage5_operational_primary_track_counts": {"strong_lead": 1},
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-LIVE12",
                            "project_name": "live12 success",
                            "stage5_operational_primary_track": "strong_lead",
                            "stage5_operational_review_bucket": "STRONG_LEAD_INTERNAL_REVIEW",
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "limited_sellable_review_evidence_grade_counts": {
                                "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                            },
                            "stage4_project_code_backfill_state": (
                                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                            ),
                        }
                    ],
                },
            )
            _write_json(
                target,
                {
                    "scoreboard": {
                        "candidate_count": 15,
                        "limited_sellable_review_candidate_count": 0,
                        "real_public_sellable_pack_rate": 0.0,
                        "stage5_operational_primary_track_counts": {"official_readback_ready": 1},
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-LIVE15",
                            "project_name": "live15 blocked",
                            "stage5_operational_primary_track": "official_readback_ready",
                            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                            "stage4_project_code_backfill_state": (
                                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                            ),
                            "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                        }
                    ],
                },
            )

            result = build_stage1_6_limited_success_attribution(
                success_scoreboard_json=success,
                target_scoreboard_json=target,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        self.assertEqual(result["success_limited_path"]["record_count"], 1)
        self.assertEqual(
            result["success_limited_path"]["evidence_grade_counts"],
            {"B_ENHANCEMENT_OFFICIAL_READBACK": 1, "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
        )
        self.assertEqual(result["target_not_limited_path"]["record_count"], 1)
        self.assertEqual(
            result["target_not_limited_path"]["review_blocker_state_counts"],
            {"PUBLIC_IDENTIFIER_READY_NOT_RELEASE_EVIDENCE": 1},
        )
        self.assertEqual(
            result["attribution_summary"]["primary_difference"],
            "SUCCESS_HAS_B_OR_C_RELEASE_EVIDENCE_TARGET_ONLY_HAS_PUBLIC_IDENTIFIER_READY",
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_attributes_r108_style_target_to_d_grade_or_browser_blocked_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            success = root / "live12.json"
            target = root / "live15-r108.json"
            out = root / "out"
            _write_json(
                success,
                {
                    "scoreboard": {
                        "candidate_count": 12,
                        "limited_sellable_review_candidate_count": 1,
                        "real_public_sellable_pack_rate": 0.0833,
                        "stage4_adapter_result_state_counts": {"MATCHED": 2, "NOT_FOUND": 1},
                        "stage4_downstream_abcd_grade_counts": {
                            "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                            "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                        },
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-LIVE12",
                            "project_name": "live12 success",
                            "stage5_operational_primary_track": "strong_lead",
                            "stage5_operational_review_bucket": "STRONG_LEAD_INTERNAL_REVIEW",
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "limited_sellable_review_evidence_grade_counts": {
                                "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                            },
                            "stage4_adapter_result_state_counts": {"MATCHED": 2, "NOT_FOUND": 1},
                            "stage4_downstream_abcd_grade_counts": {
                                "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                                "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1,
                            },
                            "stage4_public_identifier_backfill_source": "DATA_GGZY_BID_SHOW_ORIGINAL_URL|YGP_PROJECT_CODE",
                            "limited_sellable_review_official_readback_task_count": 2,
                            "limited_sellable_review_official_readback_records": [
                                {"public_source_chain": "YGP_ORIGINAL_READBACK_BACKFILL"},
                                {"public_source_chain": "LOCAL_AUTHORITY_PUBLIC_API_READBACK"},
                            ],
                        }
                    ],
                },
            )
            _write_json(
                target,
                {
                    "scoreboard": {
                        "candidate_count": 15,
                        "limited_sellable_review_candidate_count": 0,
                        "real_public_sellable_pack_rate": 0.0,
                        "stage4_adapter_result_state_counts": {"NOT_FOUND": 10, "NEEDS_BROWSER": 3},
                        "stage4_downstream_abcd_grade_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 13},
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-R108-D",
                            "project_name": "r108 d grade",
                            "stage5_operational_primary_track": "official_readback_ready",
                            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                            "stage5_operational_review_families": [
                                "official_readback_ready",
                                "evidence_insufficient",
                                "source_not_found",
                            ],
                            "limited_sellable_review_candidate_state": "NOT_READY",
                            "stage4_adapter_result_state_counts": {"NOT_FOUND": 1},
                            "stage4_downstream_abcd_grade_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 2},
                            "limited_sellable_review_gap_grade_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 2},
                            "stage4_project_code_backfill_state": (
                                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                            ),
                            "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE|YGP_BIZ_CODE",
                            "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                        },
                        {
                            "project_id": "PROJ-R108-BROWSER",
                            "project_name": "r108 browser",
                            "stage5_operational_primary_track": "official_readback_ready",
                            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                            "stage5_operational_review_families": [
                                "official_readback_ready",
                                "authorization_blocked",
                                "evidence_insufficient",
                            ],
                            "limited_sellable_review_candidate_state": "NOT_READY",
                            "stage4_adapter_result_state_counts": {"NEEDS_BROWSER": 1},
                            "stage4_downstream_abcd_grade_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 2},
                            "limited_sellable_review_gap_grade_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 2},
                            "p13b_local_authority_executed_readback_state_counts": {"BLOCKED": 1},
                        },
                    ],
                },
            )

            result = build_stage1_6_limited_success_attribution(
                success_scoreboard_json=success,
                target_scoreboard_json=target,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        self.assertEqual(
            result["target_not_limited_path"]["failure_mode_counts"]["TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED"],
            2,
        )
        self.assertEqual(result["target_not_limited_path"]["stage4_adapter_result_state_counts"], {"NOT_FOUND": 1, "NEEDS_BROWSER": 1})
        self.assertEqual(
            result["attribution_summary"]["primary_difference"],
            "TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED",
        )
        self.assertEqual(
            result["attribution_summary"]["recommended_next_action"],
            "continue_fallback_readback_or_browser_authorized_replay_before_limited_review",
        )
        self.assertTrue(result["attribution_summary"]["query_miss_is_not_clearance"])

    def test_auto_discovers_success_and_target_scoreboards_for_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            success = root / "stage1-6-sellable-rate-regression-live12-r64" / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            target = root / "stage1-6-sellable-rate-regression-live15-r67" / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            _write_json(
                success,
                {
                    "scoreboard": {
                        "candidate_count": 12,
                        "limited_sellable_review_candidate_count": 5,
                        "real_public_sellable_pack_rate": 0.4167,
                        "stage4_matched_task_count": 12,
                        "stage4_needs_browser_task_count": 39,
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-LIVE12",
                            "project_name": "live12 success",
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "limited_sellable_review_evidence_grade_counts": {
                                "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                            },
                            "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE",
                        }
                    ],
                },
            )
            _write_json(
                target,
                {
                    "scoreboard": {
                        "candidate_count": 15,
                        "limited_sellable_review_candidate_count": 0,
                        "real_public_sellable_pack_rate": 0.0,
                        "stage4_matched_task_count": 0,
                        "stage4_needs_browser_task_count": 3,
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-LIVE15",
                            "project_name": "live15 blocked",
                            "limited_sellable_review_candidate_state": "NOT_READY",
                            "stage4_adapter_result_state_counts": {"NEEDS_BROWSER": 1},
                            "stage4_downstream_abcd_grade_counts": {
                                "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1,
                            },
                            "limited_sellable_review_gap_grade_counts": {
                                "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1,
                            },
                        }
                    ],
                },
            )

            discovered = discover_limited_success_attribution_context(search_root=root)
            result = build_stage1_6_limited_success_attribution(
                search_root=root,
                output_root=out,
                created_at="2026-05-26T00:00:00+08:00",
            )

        self.assertEqual(discovered["success_scoreboard_json"], str(success))
        self.assertEqual(discovered["target_scoreboard_json"], str(target))
        self.assertEqual(result["discovery"]["discovery_state"], "AUTO_DISCOVERED_LIMITED_SUCCESS_ATTRIBUTION_CONTEXT")
        self.assertEqual(result["input_refs"]["success_scoreboard_json"], str(success))
        self.assertEqual(result["input_refs"]["target_scoreboard_json"], str(target))
        self.assertEqual(
            result["discovery"]["success_candidate_summary"]["limited_sellable_review_candidate_count"],
            5,
        )
        self.assertEqual(
            result["target_not_limited_path"]["failure_mode_counts"],
            {"TARGET_EXECUTED_BUT_ONLY_D_OR_BROWSER_BLOCKED": 1, "NEEDS_BROWSER_OR_AUTH_SESSION": 1},
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
