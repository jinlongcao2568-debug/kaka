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
            gdcic_readback = root / "gdcic-readback"
            p13b_history = root / "p13b-history"
            p13b_original = root / "p13b-original"
            p13b_ygp = root / "p13b-ygp"
            p13b_overlap = root / "p13b-overlap"
            stage6 = root / "stage6"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            gdcic_readback.mkdir()
            p13b_history.mkdir()
            p13b_original.mkdir()
            p13b_ygp.mkdir()
            p13b_overlap.mkdir()
            stage6.mkdir()

            _write_json(
                pressure / "pressure-summary.json",
                {
                    "candidate_count": 5,
                    "stage5_rule_gate_status_counts": {"REVIEW": 5},
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
                            "fail_closed_reasons": [
                                "contract_public_info_empty_result",
                                "gdcic_project_code_candidates_present_but_not_matched",
                                "gdcic_project_code_not_resolved",
                            ],
                        },
                        {
                            "project_id": "PROJ-B",
                            "project_name": "B candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "RESPONSIBLE_ROLE_GAP_REVIEW_REQUIRED",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        },
                        {
                            "project_id": "PROJ-C",
                            "project_name": "C candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        },
                        {
                            "project_id": "PROJ-D",
                            "project_name": "D candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "remaining_real_world_gaps": ["missing_stage4_5_source_type:completion_filing"],
                        },
                        {
                            "project_id": "PROJ-E",
                            "project_name": "E candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
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
                                "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                            },
                            {
                                "project_id": "PROJ-B",
                                "adapter_result_state": "NEEDS_BROWSER",
                                "blocker_taxonomy": ["gd_gdcic_contract_system_sso_login_required"],
                            },
                            {
                                "project_id": "PROJ-C",
                                "adapter_result_state": "NOT_FOUND",
                                "downstream_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                            },
                            {
                                "project_id": "PROJ-E",
                                "adapter_result_state": "MATCHED",
                            },
                        ]
                    },
                    "summary": {
                        "adapter_result_state_counts": {"MATCHED": 2, "NEEDS_BROWSER": 1, "NOT_FOUND": 1},
                        "release_evidence_downstream_abcd_grade_counts": {
                            "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                            "D_INSUFFICIENT_OR_BLOCKED_READBACK": 2,
                        },
                        "operator_next_action_counts": {
                            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1,
                        },
                    },
                },
            )
            _write_json(
                gdcic_readback / "gdcic-browser-authorized-readback-v1.json",
                {
                    "summary": {
                        "authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT",
                        "authorized_session_input_ready": False,
                        "gdcic_authorized_session_overall_state": "NOT_ATTEMPTED_PLAN_ONLY",
                        "target_real_readback_success_count": 0,
                        "target_project_manager_change_real_readback_success_count": 0,
                        "real_readback_success_not_faked": True,
                        "real_readback_success_proof_state": "NO_REAL_AUTHORIZED_READBACK_SUCCESS",
                        "authorization_blocker_operator_next_action": (
                            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"
                        ),
                        "authorization_blocker_alternative_operator_next_action": (
                            "run_alternative_public_source_release_evidence_readback_chain"
                        ),
                        "authorization_blocker_is_not_terminal_if_alternative_public_sources_exist": True,
                        "alternative_public_source_route_count": 2,
                        "alternative_public_source_route_records": [
                            {"release_evidence_target_type": "contract_performance"},
                            {"release_evidence_target_type": "project_manager_change_notice"},
                        ],
                    }
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
                        "limited_sellable_review_candidate_count": 1,
                        "limited_sellable_review_candidate_state_counts": {
                            "REVIEW_CANDIDATE": 1,
                            "NOT_READY": 4,
                        },
                        "strong_lead_candidate_state_counts": {
                            "STRONG_LEAD_REVIEW_CANDIDATE": 1,
                            "NOT_READY": 4,
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
                            "release_field_query_operator_next_actions": [
                                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                            ],
                        },
                        {
                            "project_id": "PROJ-C",
                            "stage6_ready": False,
                            "stage7_commercial_input_allowed": False,
                            "release_field_query_adapter_result_state_counts": {"NOT_FOUND": 1},
                            "release_field_query_downstream_abcd_grade_counts": {
                                "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1
                            },
                        },
                        {
                            "project_id": "PROJ-D",
                            "stage6_ready": False,
                            "stage7_commercial_input_allowed": False,
                        },
                        {
                            "project_id": "PROJ-E",
                            "stage6_ready": False,
                            "stage7_commercial_input_allowed": False,
                            "release_field_query_adapter_result_state_counts": {"MATCHED": 1},
                        },
                    ],
                },
            )
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "manifest": {
                        "company_history_query_records": [
                            {"project_id": "PROJ-D", "query_state": "COMPANY_HISTORY_RECORD_FOUND"},
                            {"project_id": "PROJ-D", "query_state": "SOURCE_BLOCKED_RETRY_REQUIRED"},
                        ],
                        "bid_show_records": [
                            {"project_id": "PROJ-D", "bid_show_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"},
                        ],
                        "overlap_signal_records": [
                            {
                                "project_id": "PROJ-D",
                                "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            },
                            {"project_id": "PROJ-E", "overlap_signal_state": "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"},
                        ],
                    },
                    "summary": {
                        "input_mode": "GDCIC_ALTERNATIVE_PUBLIC_SOURCE_ROUTES",
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                        "gdcic_alternative_public_source_route_count": 2,
                        "queried_company_count": 2,
                        "company_search_hit_count": 1,
                        "bid_show_record_count": 1,
                        "overlap_signal_review_required_count": 0,
                        "original_notice_backtrace_required_count": 1,
                        "source_blocked_count": 1,
                        "company_query_state_counts": {
                            "COMPANY_HISTORY_RECORD_FOUND": 1,
                            "SOURCE_BLOCKED_RETRY_REQUIRED": 1,
                        },
                        "bid_show_state_counts": {"ORIGINAL_NOTICE_BACKTRACE_REQUIRED": 1},
                        "overlap_signal_state_counts": {
                            "ORIGINAL_NOTICE_BACKTRACE_REQUIRED": 1,
                            "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW": 1,
                        },
                        "query_miss_is_not_clearance": True,
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                },
            )
            _write_json(
                p13b_original / "original-notice-backtrace-v1.json",
                {
                    "manifest": {
                        "original_notice_fetch_records": [
                            {"project_id": "PROJ-D", "fetch_state": "ORIGINAL_NOTICE_FETCHED"},
                            {"project_id": "PROJ-B", "fetch_state": "ORIGINAL_NOTICE_FETCH_BLOCKED"},
                        ],
                        "original_notice_overlap_signal_records": [
                            {
                                "project_id": "PROJ-D",
                                "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                                "original_notice_backtrace_match_state": "NO_COMPANY_PERSON_PERIOD_MATCH",
                            }
                        ],
                    },
                    "summary": {
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                        "original_notice_task_count": 2,
                        "live_processed_count": 1,
                        "fetched_count": 1,
                        "fetch_blocked_count": 1,
                        "original_notice_overlap_signal_review_required_count": 0,
                        "no_match_review_count": 1,
                        "source_unsupported_count": 0,
                        "fetch_state_counts": {
                            "ORIGINAL_NOTICE_FETCHED": 1,
                            "ORIGINAL_NOTICE_FETCH_BLOCKED": 1,
                        },
                        "overlap_signal_state_counts": {"ORIGINAL_NOTICE_NO_MATCH_REVIEW": 1},
                        "original_notice_backtrace_match_state_counts": {
                            "NO_COMPANY_PERSON_PERIOD_MATCH": 1,
                        },
                        "query_miss_is_not_clearance": True,
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                },
            )
            _write_json(
                p13b_ygp / "ygp-original-readback-v1.json",
                {
                    "manifest": {
                        "ygp_original_readback_records": [
                            {
                                "project_id": "PROJ-D",
                                "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                                "ygp_project_code": "E4401002701500571001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "440900",
                                "ygp_notice_id": "notice-1",
                            },
                            {
                                "project_id": "PROJ-B",
                                "ygp_readback_state": "YGP_ORIGINAL_URL_BLOCKED",
                            },
                        ],
                    },
                    "summary": {
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                        "ygp_original_readback_task_count": 2,
                        "ygp_readback_ready_count": 1,
                        "ygp_person_period_extracted_count": 0,
                        "ygp_readback_state_counts": {
                            "YGP_ORIGINAL_URL_READBACK_READY": 1,
                            "YGP_ORIGINAL_URL_BLOCKED": 1,
                        },
                        "ygp_api_discovery_state_counts": {"YGP_DETAIL_API_DISCOVERED": 1},
                        "stage4_ygp_project_code_backfill_record_count": 1,
                        "stage4_ygp_backfill_state_counts": {"YGP_STAGE4_BACKFILL_READY": 1},
                        "stage4_ygp_gdcic_route_allowed_count": 0,
                        "blocker_taxonomy_counts": {"max_live_original_notices_deferred": 1},
                        "query_miss_is_not_clearance": True,
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                },
            )
            _write_json(
                p13b_overlap / "p13b-overlap-triage-closeout-v1.json",
                {
                    "summary": {
                        "p13b_overlap_triage_closeout_state": "P13B_OVERLAP_TRIAGE_CLOSEOUT_READY",
                        "project_count": 5,
                        "ygp_stage4_backfill_candidate_count": 1,
                        "ygp_stage4_backfill_ready_count": 1,
                        "ygp_stage4_backfill_state_counts": {
                            "P13B_YGP_STAGE4_BACKFILL_READY": 1,
                        },
                        "ygp_stage4_release_adapter_task_count": 1,
                        "ygp_stage4_release_adapter_task_state_counts": {
                            "PLAN_ONLY_NOT_EXECUTED": 1,
                        },
                        "ygp_stage4_gdcic_route_allowed_count": 0,
                        "project_state_counts": {
                            "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE": 1,
                        },
                        "original_notice_state_counts": {"NO_OVERLAP_SIGNAL_REVIEW": 1},
                        "original_notice_backtrace_match_state_counts": {
                            "NO_COMPANY_PERSON_PERIOD_MATCH": 1,
                        },
                        "release_evidence_trigger_count": 0,
                        "query_miss_is_not_clearance": True,
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                gdcic_browser_readback_root=gdcic_readback,
                p13b_company_history_root=p13b_history,
                p13b_original_notice_backtrace_root=p13b_original,
                p13b_ygp_original_readback_root=p13b_ygp,
                p13b_overlap_triage_closeout_root=p13b_overlap,
                stage6_status_root=stage6,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        scoreboard = result["scoreboard"]
        self.assertEqual(scoreboard["candidate_count"], 5)
        self.assertEqual(scoreboard["stage2_success_count"], 5)
        self.assertEqual(scoreboard["stage3_success_count"], 5)
        self.assertEqual(scoreboard["stage4_matched_task_count"], 2)
        self.assertEqual(scoreboard["stage4_needs_browser_task_count"], 1)
        self.assertEqual(scoreboard["stage5_review_count"], 5)
        self.assertEqual(scoreboard["stage6_fact_ready_count"], 0)
        self.assertEqual(scoreboard["stage6_limited_sellable_review_candidate_count"], 1)
        self.assertEqual(
            scoreboard["stage6_limited_sellable_review_candidate_state_counts"],
            {"REVIEW_CANDIDATE": 1, "NOT_READY": 4},
        )
        self.assertEqual(
            scoreboard["stage6_strong_lead_candidate_state_counts"],
            {"STRONG_LEAD_REVIEW_CANDIDATE": 1, "NOT_READY": 4},
        )
        self.assertEqual(scoreboard["stage7_sellable_count"], 0)
        self.assertEqual(scoreboard["limited_sellable_review_candidate_count"], 1)
        self.assertEqual(scoreboard["real_public_sellable_pack_rate"], 0.2)
        self.assertEqual(
            scoreboard["gdcic_authorized_readback_status"],
            {
                "artifact_state": "BUILT",
                "authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT",
                "authorized_session_input_ready": False,
                "authorization_readiness_state": "NOT_ATTEMPTED_PLAN_ONLY",
                "target_real_readback_success_count": 0,
                "target_project_manager_change_real_readback_success_count": 0,
                "real_readback_success_not_faked": True,
                "real_readback_success_proof_state": "NO_REAL_AUTHORIZED_READBACK_SUCCESS",
                "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                "alternative_operator_next_action": "run_alternative_public_source_release_evidence_readback_chain",
                "authorization_blocker_is_not_terminal_if_alternative_public_sources_exist": True,
                "alternative_public_source_route_count": 2,
                "alternative_public_source_route_target_type_counts": {
                    "contract_performance": 1,
                    "project_manager_change_notice": 1,
                },
                "customer_visible_allowed": False,
                "query_miss_is_not_clearance": True,
            },
        )
        self.assertIn(
            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            result["recommended_next_actions"],
        )
        self.assertIn(
            "run_alternative_public_source_release_evidence_readback_chain",
            result["recommended_next_actions"],
        )
        self.assertEqual(
            scoreboard["stage5_operational_review_bucket_counts"],
            {
                "STRONG_LEAD_INTERNAL_REVIEW": 1,
                "ORIGINAL_NOTICE_BLOCKED_REVIEW": 1,
                "SOURCE_NOT_FOUND_REVIEW": 1,
                "ORIGINAL_NOTICE_NOT_FOUND_REVIEW": 1,
                "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW": 1,
            },
        )
        self.assertEqual(
            scoreboard["stage5_operational_signal_counts"],
            {
                "strong_lead": 1,
                "authorization_blocked": 1,
                "source_not_found": 1,
                "evidence_insufficient": 5,
                "original_notice_backtrace_required": 1,
                "original_notice_not_found": 1,
                "original_notice_blocked": 1,
                "ygp_readback_ready": 1,
                "ygp_readback_blocked": 1,
                "public_source_blocked": 1,
                "weak_lead": 1,
                "public_source_not_found": 1,
                "responsible_role_gap": 1,
                "project_code_backfill_gap": 1,
            },
        )
        self.assertEqual(
            scoreboard["p13b_public_source_readback_status"]["original_notice_backtrace_required_count"],
            1,
        )
        self.assertEqual(
            scoreboard["stage4_public_source_readback_state_counts"],
            {
                "ORIGINAL_NOTICE_BACKTRACE_REQUIRED": 1,
                "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW": 1,
            },
        )
        self.assertEqual(
            scoreboard["stage4_original_notice_readback_state_counts"],
            {"BLOCKED": 1, "NOT_FOUND": 1},
        )
        self.assertEqual(
            scoreboard["stage4_ygp_original_readback_state_counts"],
            {"YGP_BLOCKED": 1, "YGP_READBACK_READY": 1},
        )
        self.assertEqual(scoreboard["p13b_ygp_original_readback_status"]["ygp_readback_ready_count"], 1)
        self.assertEqual(
            scoreboard["p13b_ygp_original_readback_status"]["stage4_ygp_backfill_state_counts"],
            {"YGP_STAGE4_BACKFILL_READY": 1},
        )
        self.assertEqual(
            scoreboard["p13b_ygp_original_readback_status"]["stage4_ygp_gdcic_route_allowed_count"],
            0,
        )
        self.assertEqual(
            scoreboard["p13b_overlap_triage_closeout_status"]["ygp_stage4_backfill_ready_count"],
            1,
        )
        self.assertEqual(
            scoreboard["p13b_overlap_triage_closeout_status"]["ygp_stage4_gdcic_route_allowed_count"],
            0,
        )
        self.assertEqual(
            scoreboard["p13b_overlap_triage_closeout_status"]["ygp_stage4_release_adapter_task_count"],
            1,
        )
        self.assertEqual(scoreboard["p13b_original_notice_readback_status"]["fetch_blocked_count"], 1)
        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(rows["PROJ-A"]["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(rows["PROJ-A"]["stage5_operational_review_bucket"], "STRONG_LEAD_INTERNAL_REVIEW")
        self.assertEqual(
            rows["PROJ-A"]["limited_sellable_review_reason"],
            "official_b_or_c_readback_requires_manual_stage5_stage6_review",
        )
        self.assertEqual(
            rows["PROJ-A"]["commercialization_boundary_state"],
            "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        )
        self.assertEqual(rows["PROJ-B"]["stage5_operational_review_bucket"], "ORIGINAL_NOTICE_BLOCKED_REVIEW")
        self.assertEqual(rows["PROJ-C"]["stage5_operational_review_bucket"], "SOURCE_NOT_FOUND_REVIEW")
        self.assertEqual(rows["PROJ-D"]["stage5_operational_review_bucket"], "ORIGINAL_NOTICE_NOT_FOUND_REVIEW")
        self.assertEqual(rows["PROJ-D"]["p13b_public_source_readback_state"], "ORIGINAL_NOTICE_BACKTRACE_REQUIRED")
        self.assertEqual(rows["PROJ-D"]["p13b_original_notice_readback_state"], "NOT_FOUND")
        self.assertEqual(rows["PROJ-D"]["p13b_ygp_project_code_variants"], ["E4401002701500571001"])
        self.assertEqual(rows["PROJ-E"]["stage5_operational_review_bucket"], "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW")
        self.assertTrue(all(row["stage5_query_miss_is_not_clearance"] for row in rows.values()))
        self.assertEqual(
            result["blocker_summary"]["blocking_bucket_counts"],
            {
                "stage4_matched_needs_manual_limited_sellable_review": 1,
                "original_notice_blocked_review": 1,
                "source_not_found_review": 1,
                "original_notice_not_found_review": 1,
                "weak_lead_official_signal_review": 1,
            },
        )
        self.assertEqual(
            result["blocker_summary"]["fail_closed_reason_counts"][
                "gdcic_project_code_candidates_present_but_not_matched"
            ],
            1,
        )
        self.assertNotIn(
            "gdcic_project_code_candidates_present_but_not_matched",
            result["blocker_summary"]["active_fail_closed_reason_counts"],
        )
        self.assertEqual(
            result["blocker_summary"][
                "gdcic_project_code_candidates_present_but_not_matched_resolved_by_public_readback_count"
            ],
            1,
        )
        self.assertNotIn(
            "gdcic_project_code_not_resolved",
            result["blocker_summary"]["active_fail_closed_reason_counts"],
        )
        self.assertEqual(
            result["blocker_summary"]["gdcic_project_code_not_resolved_resolved_by_public_readback_count"],
            1,
        )
        self.assertIn("run_p13b_original_notice_backtrace_for_bid_show_records", result["recommended_next_actions"])
        self.assertIn("continue_p13b_original_notice_backtrace_or_route_blocked_sources", result["recommended_next_actions"])
        self.assertIn(
            "feed_ygp_stage4_backfill_candidates_to_p13b_or_stage4_bridge_without_gdcic_route_claim",
            result["recommended_next_actions"],
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])
        self.assertTrue(result["safety"]["query_miss_is_not_clearance"])

    def test_stage5_review_buckets_split_stage1_3_and_backfill_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()

            _write_json(
                pressure / "pressure-summary.json",
                {
                    "candidate_count": 4,
                    "stage5_rule_gate_status_counts": {"REVIEW": 4},
                    "customer_sellable_evidence_ready_count": 0,
                },
            )
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-CERT",
                            "project_name": "certificate gap",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": [
                                "notice_has_company_and_project_manager_but_missing_certificate_no",
                                "same_name_not_disambiguated",
                            ],
                        },
                        {
                            "project_id": "PROJ-ROLE",
                            "project_name": "role gap",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "RESPONSIBLE_ROLE_GAP_REVIEW_REQUIRED",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": ["notice_has_company_but_missing_responsible_role_name"],
                        },
                        {
                            "project_id": "PROJ-CODE",
                            "project_name": "project code gap",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        },
                        {
                            "project_id": "PROJ-AMB",
                            "project_name": "ambiguity gap",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": ["same_name_not_disambiguated"],
                        },
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {}})

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(
            result["scoreboard"]["stage5_operational_review_bucket_counts"],
            {
                "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 1,
                "RESPONSIBLE_ROLE_GAP_REVIEW": 1,
                "PROJECT_CODE_BACKFILL_GAP_REVIEW": 1,
                "FIELD_AMBIGUITY_REVIEW": 1,
            },
        )
        self.assertEqual(
            rows["PROJ-CERT"]["stage5_operational_next_action"],
            "run_company_first_certificate_supplement_and_attachment_ocr_without_identity_confirmation",
        )
        self.assertEqual(
            rows["PROJ-CODE"]["stage5_operational_next_action"],
            "backfill_project_code_from_notice_data_ggzy_bid_show_or_local_source_without_digit_guessing",
        )
        self.assertTrue(all(row["stage5_query_miss_is_not_clearance"] for row in rows.values()))

    def test_stage5_keeps_authorization_and_source_not_found_as_compound_operational_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-COMPOUND",
                            "project_name": "compound blocked candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {
                    "manifest": {
                        "field_task_records": [
                            {
                                "project_id": "PROJ-COMPOUND",
                                "adapter_result_state": "NOT_FOUND",
                                "downstream_release_evidence_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                            },
                            {
                                "project_id": "PROJ-COMPOUND",
                                "adapter_result_state": "NEEDS_BROWSER",
                                "blocker_taxonomy": [
                                    "guangdong_project_manager_change_notice_requires_browser_or_authorized_runtime"
                                ],
                            },
                        ]
                    }
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["stage5_operational_review_bucket"], "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW")
        self.assertEqual(
            row["stage5_operational_next_action"],
            "provide_authorized_session_or_fallback_source_without_treating_not_found_as_clearance",
        )
        self.assertEqual(
            result["blocker_summary"]["blocking_bucket_counts"],
            {"authorization_or_browser_blocked_with_source_not_found": 1},
        )
        self.assertTrue(row["stage5_query_miss_is_not_clearance"])

    def test_blocking_bucket_uses_p13b_stage5_public_source_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_history = root / "p13b-history"
            p13b_original = root / "p13b-original"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            p13b_history.mkdir()
            p13b_original.mkdir()

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 2})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-BLOCKED",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        },
                        {
                            "project_id": "PROJ-NOTFOUND",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        },
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {
                    "manifest": {
                        "field_task_records": [
                            {"project_id": "PROJ-BLOCKED", "adapter_result_state": "NEEDS_BROWSER"},
                            {"project_id": "PROJ-BLOCKED", "adapter_result_state": "NOT_FOUND"},
                            {"project_id": "PROJ-NOTFOUND", "adapter_result_state": "NEEDS_BROWSER"},
                            {"project_id": "PROJ-NOTFOUND", "adapter_result_state": "NOT_FOUND"},
                        ]
                    }
                },
            )
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "manifest": {
                        "company_history_query_records": [
                            {"project_id": "PROJ-BLOCKED", "query_state": "SOURCE_BLOCKED_RETRY_REQUIRED"}
                        ],
                        "overlap_signal_records": [
                            {
                                "project_id": "PROJ-BLOCKED",
                                "overlap_signal_state": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            },
                            {
                                "project_id": "PROJ-NOTFOUND",
                                "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            },
                        ],
                    },
                },
            )
            _write_json(
                p13b_original / "original-notice-backtrace-v1.json",
                {
                    "manifest": {
                        "original_notice_overlap_signal_records": [
                            {
                                "project_id": "PROJ-NOTFOUND",
                                "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                                "original_notice_backtrace_match_state": "NO_COMPANY_PERSON_PERIOD_MATCH",
                            }
                        ],
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_company_history_root=p13b_history,
                p13b_original_notice_backtrace_root=p13b_original,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(rows["PROJ-BLOCKED"]["stage5_operational_review_bucket"], "PUBLIC_SOURCE_BLOCKED_REVIEW")
        self.assertEqual(rows["PROJ-BLOCKED"]["blocking_bucket"], "public_source_blocked_review")
        self.assertEqual(rows["PROJ-NOTFOUND"]["stage5_operational_review_bucket"], "ORIGINAL_NOTICE_NOT_FOUND_REVIEW")
        self.assertEqual(rows["PROJ-NOTFOUND"]["blocking_bucket"], "original_notice_not_found_review")
        self.assertEqual(
            result["blocker_summary"]["blocking_bucket_counts"],
            {
                "public_source_blocked_review": 1,
                "original_notice_not_found_review": 1,
            },
        )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
