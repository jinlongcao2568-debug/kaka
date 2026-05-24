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

from storage.stage1_6_sellable_scoreboard import build_stage1_6_sellable_scoreboard


class StageOneSixSellableScoreboardTests(unittest.TestCase):
    def test_scoreboard_counts_sellable_funnel_and_blocker_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            stage6 = root / "stage6"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            stage6.mkdir()

            _write_json(
                pressure / "pressure-summary.json",
                {
                    "candidate_count": 2,
                    "stage5_rule_gate_status_counts": {"REVIEW": 2},
                    "customer_sellable_evidence_ready_count": 0,
                },
            )
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-A",
                            "project_name": "A candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "remaining_real_world_gaps": ["missing_stage4_5_source_type:contract_public_info"],
                            "fail_closed_reasons": ["contract_public_info_empty_result"],
                        },
                        {
                            "project_id": "PROJ-B",
                            "project_name": "B candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "RESPONSIBLE_ROLE_GAP_REVIEW_REQUIRED",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        },
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": [{"gap": "x"}]})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {
                    "manifest": {
                        "field_task_records": [
                            {
                                "project_id": "PROJ-A",
                                "adapter_result_state": "MATCHED",
                                "downstream_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                            },
                            {
                                "project_id": "PROJ-B",
                                "adapter_result_state": "NEEDS_BROWSER",
                                "blocker_taxonomy": ["gd_gdcic_contract_system_sso_login_required"],
                            },
                        ]
                    },
                    "summary": {
                        "adapter_result_state_counts": {"MATCHED": 1, "NEEDS_BROWSER": 1},
                        "release_evidence_downstream_abcd_grade_counts": {
                            "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                            "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1,
                        },
                        "operator_next_action_counts": {
                            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1,
                        },
                    },
                },
            )
            _write_json(
                stage6 / "stage6-review-loop-project-status-table.json",
                {
                    "summary": {
                        "release_field_query_project_count": 2,
                        "release_field_query_state_counts": {
                            "RELEASE_FIELD_QUERY_REVIEW_READY": 1,
                            "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW": 1,
                        },
                    },
                    "records": [
                        {
                            "project_id": "PROJ-A",
                            "stage6_ready": False,
                            "stage6_fact_package_state": "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY",
                            "stage7_commercial_input_allowed": False,
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "limited_sellable_review_reason": "official_b_or_c_readback_requires_manual_stage5_stage6_review",
                            "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
                            "release_field_query_downstream_abcd_grade_counts": {
                                "B_ENHANCEMENT_OFFICIAL_READBACK": 1
                            },
                        },
                        {
                            "project_id": "PROJ-B",
                            "stage6_ready": False,
                            "stage7_commercial_input_allowed": False,
                            "release_field_query_adapter_result_state_counts": {"NEEDS_BROWSER": 1},
                        },
                    ],
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                stage6_status_root=stage6,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        scoreboard = result["scoreboard"]
        self.assertEqual(scoreboard["candidate_count"], 2)
        self.assertEqual(scoreboard["stage2_success_count"], 2)
        self.assertEqual(scoreboard["stage3_success_count"], 2)
        self.assertEqual(scoreboard["stage4_matched_task_count"], 1)
        self.assertEqual(scoreboard["stage4_needs_browser_task_count"], 1)
        self.assertEqual(scoreboard["stage5_review_count"], 2)
        self.assertEqual(scoreboard["stage6_fact_ready_count"], 0)
        self.assertEqual(scoreboard["stage7_sellable_count"], 0)
        self.assertEqual(scoreboard["limited_sellable_review_candidate_count"], 1)
        self.assertEqual(scoreboard["real_public_sellable_pack_rate"], 0.5)
        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(rows["PROJ-A"]["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(
            rows["PROJ-A"]["limited_sellable_review_reason"],
            "official_b_or_c_readback_requires_manual_stage5_stage6_review",
        )
        self.assertEqual(
            rows["PROJ-A"]["commercialization_boundary_state"],
            "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        )
        self.assertEqual(
            result["blocker_summary"]["blocking_bucket_counts"],
            {
                "stage4_matched_needs_manual_limited_sellable_review": 1,
                "authorization_or_browser_blocked": 1,
            },
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])
        self.assertTrue(result["safety"]["query_miss_is_not_clearance"])


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
