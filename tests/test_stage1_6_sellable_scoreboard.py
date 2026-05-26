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

from storage.stage1_6_sellable_scoreboard import (
    _merge_incremental_target_prior_public_source_evidence,
    build_stage1_6_sellable_scoreboard,
)


class StageOneSixSellableScoreboardTests(unittest.TestCase):
    def test_incremental_public_source_preservation_does_not_overwrite_limited_projection(self) -> None:
        current = {
            "project_id": "PROJ-A",
            "stage5_operational_primary_track": "strong_lead",
            "stage5_operational_review_bucket": "STRONG_LEAD_INTERNAL_REVIEW",
            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
        }
        prior = {
            "project_id": "PROJ-A",
            "stage5_operational_primary_track": "official_readback_ready",
            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
            "stage4_project_code_backfill_state": (
                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
            ),
            "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE",
            "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
            "blocking_bucket": "ygp_stage4_backfill_ready_review",
        }

        row = _merge_incremental_target_prior_public_source_evidence(current, prior)

        self.assertEqual(row["stage5_operational_primary_track"], "strong_lead")
        self.assertEqual(row["stage5_operational_review_bucket"], "STRONG_LEAD_INTERNAL_REVIEW")
        self.assertEqual(row["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(
            row["stage4_project_code_backfill_state"],
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        )
        self.assertEqual(row["stage4_public_identifier_backfill_source"], "YGP_PROJECT_CODE")
        self.assertNotEqual(row.get("blocking_bucket"), "ygp_stage4_backfill_ready_review")

    def test_scoreboard_emits_continuation_input_refs_for_followup_runners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            supplemental_field_query = root / "field-query-ygp-backfill"
            gdcic_readback = root / "gdcic-readback"
            stage6 = root / "stage6"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            supplemental_field_query.mkdir()
            gdcic_readback.mkdir()
            stage6.mkdir()
            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(pressure / "stage1-6-readiness-table.json", {"records": [{"project_id": "PROJ-A"}]})
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(pressure / "stage4-release-adapter-bridge-plan.json", {"tasks": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {"manifest": {"field_task_records": [{"project_id": "PROJ-A", "adapter_result_state": "MATCHED"}]}},
            )
            _write_json(
                supplemental_field_query / "guangdong-local-field-query-probe-v1.json",
                {"manifest": {"field_task_records": [{"project_id": "PROJ-A", "adapter_result_state": "MATCHED"}]}},
            )
            _write_json(
                gdcic_readback / "gdcic-browser-authorized-readback-v1.json",
                {"summary": {"authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT"}},
            )
            _write_json(
                stage6 / "stage6-review-loop-project-status-table.json",
                {"records": [{"project_id": "PROJ-A", "stage6_ready": False}]},
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                supplemental_field_query_root=supplemental_field_query,
                gdcic_browser_readback_root=gdcic_readback,
                stage6_status_root=stage6,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        refs = result["continuation_input_refs"]
        self.assertEqual(refs["prior_scoreboard_json"], str(out / "stage1-6-sellable-scoreboard-v1.json"))
        self.assertEqual(refs["effective_pressure_root"], str(pressure))
        self.assertEqual(refs["effective_release_field_query_root"], str(field_query))
        self.assertEqual(
            refs["effective_supplemental_release_field_query_json"],
            str(supplemental_field_query / "guangdong-local-field-query-probe-v1.json"),
        )
        self.assertEqual(refs["effective_supplemental_release_field_query_root"], str(supplemental_field_query))
        self.assertEqual(refs["effective_gdcic_browser_readback_root"], str(gdcic_readback))
        self.assertEqual(refs["effective_stage6_status_root"], str(stage6))
        self.assertEqual(refs["pressure_root_resolution_state"], "RESOLVED_FROM_SCOREBOARD_INPUT_REFS")
        self.assertEqual(
            refs["supplemental_release_field_query_root_resolution_state"],
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS",
        )
        self.assertEqual(refs["stage6_status_root_resolution_state"], "RESOLVED_FROM_SCOREBOARD_INPUT_REFS")
        self.assertFalse(refs["customer_visible_allowed"])
        self.assertTrue(refs["query_miss_is_not_clearance"])

    def test_scoreboard_marks_review_candidates_without_stage123_as_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            p13b_history = root / "p13b-history"
            stage6 = root / "stage6"
            out = root / "out"
            for path in (pressure, p13b_history, stage6, out):
                path.mkdir(parents=True, exist_ok=True)
            _write_json(pressure / "pressure-summary.json", {"candidate_count": 0})
            _write_json(pressure / "stage1-6-readiness-table.json", {"records": []})
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "summary": {
                        "input_mode": "STAGE4_BACKFILL_FOLLOWUP_PUBLIC_SOURCE_ROUTES",
                        "customer_visible_allowed": False,
                        "query_miss_is_not_clearance": True,
                        "no_legal_conclusion": True,
                    }
                },
            )
            _write_json(
                stage6 / "stage6-review-loop-project-status-table.json",
                {
                    "summary": {"stage6_review_cycle_input_mode": "RUNTIME_BLOCKER_SUBQUEUE_ONLY"},
                    "records": [
                        {
                            "project_id": "PROJ-PROJECTION",
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
                            "stage7_commercial_input_allowed": False,
                        }
                    ],
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                p13b_company_history_root=p13b_history,
                stage6_status_root=stage6,
                output_root=out,
                created_at="2026-05-26T00:00:00+08:00",
            )

        scoreboard = result["scoreboard"]
        self.assertEqual(scoreboard["candidate_count"], 1)
        self.assertEqual(scoreboard["stage2_success_count"], 0)
        self.assertEqual(scoreboard["stage3_success_count"], 0)
        self.assertEqual(scoreboard["limited_sellable_review_candidate_count"], 1)
        self.assertEqual(scoreboard["input_mode"], "STAGE4_BACKFILL_FOLLOWUP_PUBLIC_SOURCE_ROUTES")
        self.assertEqual(scoreboard["denominator_kind"], "FOLLOWUP_PROJECT_ROWS")
        self.assertFalse(scoreboard["clean_batch_comparable"])
        self.assertEqual(scoreboard["projection_or_merge_state"], "FOLLOWUP_OR_MERGED_PROJECTION")
        self.assertIn("not clean batch conversion KPI", scoreboard["input_lineage_warning"])
        self.assertFalse(result["safety"]["customer_visible_allowed"])

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
            company_first = root / "company-first-stage4"
            stage6 = root / "stage6"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            gdcic_readback.mkdir()
            p13b_history.mkdir()
            p13b_original.mkdir()
            p13b_ygp.mkdir()
            p13b_overlap.mkdir()
            company_first.mkdir()
            stage6.mkdir()

            _write_json(
                pressure / "pressure-summary.json",
                {
                    "candidate_count": 5,
                    "stage5_rule_gate_status_counts": {"REVIEW": 5},
                    "customer_sellable_evidence_ready_count": 0,
                    "stage1_6_readiness_state_counts": {
                        "STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED": 1,
                        "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED": 4,
                    },
                    "stage1_6_bottleneck_stage_counts": {"Stage3": 1, "Stage4": 4},
                    "stage1_3_stability_summary": {
                        "stage3_responsible_role_gap_count": 1,
                        "stage3_parse_blocker_count": 0,
                    },
                    "stage1_3_long_tail_bucket_counts": {
                        "COMPANY_FIRST_RESPONSIBLE_ROLE_RESOLUTION_REQUIRED": 1,
                    },
                    "stage1_3_long_tail_signal_counts": {
                        "responsible_role_missing_company_first_required": 1,
                    },
                    "stage1_3_identity_confirmation_state_counts": {
                        "REVIEW_REQUIRED_NOT_CONFIRMED": 1,
                    },
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
                        "limited_sellable_review_public_source_chain_counts": {
                            "YGP_ORIGINAL_READBACK_BACKFILL": 1,
                        },
                        "limited_sellable_review_stage4_bridge_backfill_state_counts": {
                            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 1,
                        },
                        "limited_sellable_review_gdcic_project_code_route_policy_counts": {
                            "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 1,
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
                            "limited_sellable_review_official_readback_task_count": 1,
                            "limited_sellable_review_evidence_grade_counts": {
                                "B_ENHANCEMENT_OFFICIAL_READBACK": 1
                            },
                            "limited_sellable_review_gap_grade_counts": {},
                            "limited_sellable_review_required_actions": [
                                "manual_stage5_stage6_review_before_limited_sellable_internal_package",
                                "keep_customer_download_delivery_payment_refund_disabled",
                            ],
                            "limited_sellable_review_official_readback_records": [
                                {
                                    "field_query_task_id": "GD-FIELD-TASK-1",
                                    "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                                    "customer_visible_allowed": False,
                                    "query_miss_is_not_clearance": True,
                                }
                            ],
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
                        "ygp_readback_ready_count": 1,
                        "browser_readback_ready_count": 1,
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
            _write_json(
                company_first / "company-first-stage4-execution.json",
                {
                    "summary": {
                        "project_count": 1,
                        "job_count": 1,
                        "stage4_execution_state_counts": {"QUEUED_NOT_EXECUTED": 1},
                        "identity_resolution_state_counts": {"NOT_RUN": 1},
                        "supplement_after_execution_state_counts": {
                            "COMPANY_FIRST_PROVIDER_TASKS_READY": 1,
                        },
                        "stage4_input_count": 0,
                        "flow_08_targeted_parse_required_count": 0,
                    },
                    "manifest": {
                        "items": [
                            {
                                "project_id": "PROJ-B",
                                "stage4_execution_state": "QUEUED_NOT_EXECUTED",
                                "identity_resolution_state": "NOT_RUN",
                                "supplement_after_execution_state": "COMPANY_FIRST_PROVIDER_TASKS_READY",
                                "stage4_readiness_state": "STAGE4_PROVIDER_TASKS_READY_NOT_EXECUTED",
                                "next_actions": ["EXECUTE_AUTHORIZED_COMPANY_FIRST_PROVIDER_TASKS"],
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                            }
                        ]
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
                company_first_stage4_execution_root=company_first,
                stage6_status_root=stage6,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        scoreboard = result["scoreboard"]
        self.assertEqual(scoreboard["candidate_count"], 5)
        self.assertEqual(scoreboard["stage2_success_count"], 5)
        self.assertEqual(scoreboard["stage3_success_count"], 5)
        self.assertEqual(
            scoreboard["stage1_6_readiness_state_counts"],
            {
                "STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED": 1,
                "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED": 4,
            },
        )
        self.assertEqual(scoreboard["stage1_6_bottleneck_stage_counts"], {"Stage3": 1, "Stage4": 4})
        self.assertEqual(
            scoreboard["stage1_3_stability_summary"],
            {"stage3_responsible_role_gap_count": 1, "stage3_parse_blocker_count": 0},
        )
        self.assertEqual(
            scoreboard["stage1_3_long_tail_bucket_counts"],
            {"COMPANY_FIRST_RESPONSIBLE_ROLE_RESOLUTION_REQUIRED": 1},
        )
        self.assertEqual(
            scoreboard["stage1_3_long_tail_signal_counts"],
            {"responsible_role_missing_company_first_required": 1},
        )
        self.assertEqual(
            scoreboard["stage1_3_identity_confirmation_state_counts"],
            {"REVIEW_REQUIRED_NOT_CONFIRMED": 1},
        )
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
            scoreboard["stage6_limited_sellable_review_public_source_chain_counts"],
            {"YGP_ORIGINAL_READBACK_BACKFILL": 1},
        )
        self.assertEqual(
            scoreboard["stage6_limited_sellable_review_stage4_bridge_backfill_state_counts"],
            {"PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 1},
        )
        self.assertEqual(
            scoreboard["stage6_limited_sellable_review_gdcic_project_code_route_policy_counts"],
            {"YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 1},
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
                "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                "authorization_readiness_state_raw": "NOT_ATTEMPTED_PLAN_ONLY",
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
                "company_first_provider_tasks_ready": 1,
            },
        )
        self.assertEqual(
            scoreboard["company_first_stage4_execution_status"],
            {
                "artifact_state": "BUILT",
                "project_count": 1,
                "job_count": 1,
                "provider_tasks_ready_project_count": 1,
                "target_fields_missing_project_count": 0,
                "certificate_resolved_project_count": 0,
                "flow_08_targeted_parse_required_project_count": 0,
                "design_survey_public_registry_fallback_required_project_count": 0,
                "stage4_input_count": 0,
                "flow_08_targeted_parse_required_count": 0,
                "stage4_execution_state_counts": {"QUEUED_NOT_EXECUTED": 1},
                "identity_resolution_state_counts": {"NOT_RUN": 1},
                "supplement_after_execution_state_counts": {
                    "COMPANY_FIRST_PROVIDER_TASKS_READY": 1,
                },
                "projected_stage5_queue_counts": {
                    "COMPANY_FIRST_PROVIDER_TASKS_READY_REVIEW": 1,
                },
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
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
        self.assertEqual(
            scoreboard["stage4_public_readback_outcome_counts"],
            {"BLOCKED": 2, "NOT_FOUND": 1, "READBACK_READY": 1},
        )
        self.assertEqual(
            scoreboard["stage4_public_readback_channel_outcome_counts"],
            {
                "ORIGINAL_NOTICE:BLOCKED": 1,
                "ORIGINAL_NOTICE:NOT_FOUND": 1,
                "YGP:YGP_BLOCKED": 1,
                "YGP:YGP_READBACK_READY": 1,
            },
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
        self.assertEqual(scoreboard["p13b_original_notice_readback_status"]["ygp_readback_ready_count"], 1)
        self.assertEqual(scoreboard["p13b_original_notice_readback_status"]["browser_readback_ready_count"], 1)
        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(rows["PROJ-A"]["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(rows["PROJ-A"]["stage5_operational_review_bucket"], "STRONG_LEAD_INTERNAL_REVIEW")
        self.assertEqual(rows["PROJ-A"]["stage5_operational_primary_track"], "strong_lead")
        self.assertEqual(rows["PROJ-A"]["stage5_operational_priority_bucket"], "P0_LIMITED_SELLABLE_REVIEW")
        self.assertEqual(rows["PROJ-A"]["stage5_operational_priority_rank"], 0)
        self.assertEqual(
            rows["PROJ-A"]["stage5_operational_safety_boundary"],
            "INTERNAL_LIMITED_SELLABLE_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        )
        self.assertEqual(
            rows["PROJ-A"]["limited_sellable_review_reason"],
            "official_b_or_c_readback_requires_manual_stage5_stage6_review",
        )
        self.assertEqual(
            rows["PROJ-A"]["commercialization_boundary_state"],
            "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        )
        self.assertEqual(rows["PROJ-A"]["limited_sellable_review_official_readback_task_count"], 1)
        self.assertEqual(
            rows["PROJ-A"]["limited_sellable_review_evidence_grade_counts"],
            {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
        )
        self.assertIn(
            "keep_customer_download_delivery_payment_refund_disabled",
            rows["PROJ-A"]["limited_sellable_review_required_actions"],
        )
        self.assertFalse(
            rows["PROJ-A"]["limited_sellable_review_official_readback_records"][0]["customer_visible_allowed"]
        )
        self.assertEqual(rows["PROJ-B"]["stage5_operational_review_bucket"], "ORIGINAL_NOTICE_BLOCKED_REVIEW")
        self.assertEqual(rows["PROJ-B"]["company_first_stage4_execution_state"], "QUEUED_NOT_EXECUTED")
        self.assertEqual(
            rows["PROJ-B"]["company_first_supplement_after_execution_state"],
            "COMPANY_FIRST_PROVIDER_TASKS_READY",
        )
        self.assertIn("COMPANY_FIRST_PROVIDER_TASKS_READY_REVIEW", rows["PROJ-B"]["stage5_operational_review_queues"])
        self.assertEqual(rows["PROJ-C"]["stage5_operational_review_bucket"], "SOURCE_NOT_FOUND_REVIEW")
        self.assertEqual(rows["PROJ-C"]["stage5_operational_primary_track"], "source_not_found")
        self.assertEqual(rows["PROJ-C"]["stage5_operational_priority_bucket"], "P2_NOT_FOUND_NON_CLEARANCE_DEEPENING")
        self.assertEqual(rows["PROJ-D"]["stage5_operational_review_bucket"], "ORIGINAL_NOTICE_NOT_FOUND_REVIEW")
        self.assertEqual(rows["PROJ-D"]["p13b_public_source_readback_state"], "ORIGINAL_NOTICE_BACKTRACE_REQUIRED")
        self.assertEqual(rows["PROJ-D"]["p13b_original_notice_readback_state"], "NOT_FOUND")
        self.assertEqual(rows["PROJ-D"]["p13b_ygp_project_code_variants"], ["E4401002701500571001"])
        self.assertEqual(rows["PROJ-E"]["stage5_operational_review_bucket"], "WEAK_LEAD_OFFICIAL_SIGNAL_REVIEW")
        self.assertEqual(rows["PROJ-E"]["stage5_operational_priority_bucket"], "P1_OFFICIAL_READBACK_DEEPENING")
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
            result["scoreboard"]["stage5_operational_review_queue_counts"],
            {
                "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 1,
                "FIELD_AMBIGUITY_REVIEW": 2,
                "EVIDENCE_INSUFFICIENT_REVIEW": 4,
                "RESPONSIBLE_ROLE_GAP_REVIEW": 1,
                "PROJECT_CODE_BACKFILL_GAP_REVIEW": 1,
            },
        )
        self.assertEqual(
            result["scoreboard"]["stage5_operational_review_family_counts"],
            {
                "responsible_person_certificate_gap": 1,
                "field_ambiguity": 2,
                "evidence_insufficient": 4,
                "responsible_role_gap": 1,
                "project_code_backfill_gap": 1,
            },
        )
        self.assertEqual(
            result["scoreboard"]["stage5_operational_primary_track_counts"],
            {
                "responsible_person_certificate_gap": 1,
                "responsible_role_gap": 1,
                "project_code_backfill_gap": 1,
                "field_ambiguity": 1,
            },
        )
        self.assertEqual(
            result["scoreboard"]["stage5_operational_priority_bucket_counts"],
            {"P2_INPUT_REPAIR_AND_DISAMBIGUATION": 4},
        )
        self.assertEqual(
            result["scoreboard"]["stage5_operational_safety_boundary_counts"],
            {"INTERNAL_REVIEW_ONLY_NOT_CLEARANCE": 4},
        )
        self.assertEqual(
            rows["PROJ-CERT"]["stage5_operational_review_queues"],
            [
                "RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW",
                "FIELD_AMBIGUITY_REVIEW",
                "EVIDENCE_INSUFFICIENT_REVIEW",
            ],
        )
        self.assertEqual(rows["PROJ-CERT"]["stage5_operational_review_family"], "responsible_person_certificate_gap")
        self.assertEqual(
            rows["PROJ-CERT"]["stage5_operational_review_families"],
            ["responsible_person_certificate_gap", "field_ambiguity", "evidence_insufficient"],
        )
        self.assertEqual(
            rows["PROJ-CERT"]["stage5_operational_next_action"],
            "run_company_first_certificate_supplement_and_attachment_ocr_without_identity_confirmation",
        )
        self.assertEqual(rows["PROJ-CERT"]["stage5_operational_primary_track"], "responsible_person_certificate_gap")
        self.assertEqual(rows["PROJ-CERT"]["stage5_operational_priority_bucket"], "P2_INPUT_REPAIR_AND_DISAMBIGUATION")
        self.assertEqual(rows["PROJ-CERT"]["stage5_operational_priority_rank"], 2)
        self.assertEqual(rows["PROJ-CERT"]["stage5_operational_safety_boundary"], "INTERNAL_REVIEW_ONLY_NOT_CLEARANCE")
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
        self.assertEqual(
            result["scoreboard"]["stage5_operational_review_family_counts"],
            {"authorization_blocked": 1, "source_not_found": 1, "evidence_insufficient": 1},
        )
        self.assertTrue(row["stage5_query_miss_is_not_clearance"])

    def test_supplemental_field_query_merges_ygp_backfill_without_replacing_primary_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            supplemental_field_query = root / "field-query-ygp-backfill"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            supplemental_field_query.mkdir()

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 2})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-BLOCKED",
                            "project_name": "blocked then ygp matched",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        },
                        {
                            "project_id": "PROJ-ONLY-BLOCKED",
                            "project_name": "still blocked",
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
                            {
                                "project_id": "PROJ-BLOCKED",
                                "adapter_result_state": "NEEDS_BROWSER",
                                "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                                "blocker_taxonomy": ["gd_gdcic_contract_system_sso_login_required"],
                            },
                            {
                                "project_id": "PROJ-ONLY-BLOCKED",
                                "adapter_result_state": "NEEDS_BROWSER",
                                "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                            },
                        ]
                    },
                    "summary": {"adapter_result_state_counts": {"NEEDS_BROWSER": 2}},
                },
            )
            _write_json(
                supplemental_field_query / "guangdong-local-field-query-probe-v1.json",
                {
                    "manifest": {
                        "field_task_records": [
                            {
                                "project_id": "PROJ-BLOCKED",
                                "adapter_result_state": "MATCHED",
                                "field_readback_state": "YGP_ORIGINAL_NOTICE_READBACK_READY_REVIEW_REQUIRED",
                                "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                            }
                        ]
                    },
                    "summary": {"adapter_result_state_counts": {"MATCHED": 1}},
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                supplemental_field_query_root=supplemental_field_query,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(
            result["scoreboard"]["stage4_adapter_result_state_counts"],
            {"NEEDS_BROWSER": 2, "MATCHED": 1},
        )
        self.assertEqual(
            rows["PROJ-BLOCKED"]["stage4_adapter_result_state_counts"],
            {"NEEDS_BROWSER": 1, "MATCHED": 1},
        )
        self.assertEqual(
            rows["PROJ-BLOCKED"]["limited_sellable_review_candidate_state"],
            "REVIEW_CANDIDATE",
        )
        self.assertFalse(rows["PROJ-BLOCKED"]["customer_visible_allowed"])
        self.assertTrue(rows["PROJ-BLOCKED"]["query_miss_is_not_clearance"])
        self.assertEqual(
            result["blocker_summary"]["authorization_blocked_task_count"],
            2,
        )

    def test_gdcic_authorization_blocker_projects_alternative_public_routes_without_auth_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            gdcic_readback = root / "missing-gdcic-readback"
            p13b_history = root / "p13b-history"
            p13b_original = root / "p13b-original"
            p13b_ygp = root / "p13b-ygp"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            gdcic_readback.mkdir()
            p13b_history.mkdir()
            p13b_original.mkdir()
            p13b_ygp.mkdir()

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-AUTH-BLOCKED",
                            "project_name": "auth blocked but public routes exist",
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
                                "project_id": "PROJ-AUTH-BLOCKED",
                                "adapter_result_state": "NEEDS_BROWSER",
                                "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                            }
                        ]
                    },
                    "summary": {"adapter_result_state_counts": {"NEEDS_BROWSER": 1}},
                },
            )
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "manifest": {
                        "bid_show_records": [
                            {
                                "project_id": "PROJ-AUTH-BLOCKED",
                                "bid_show_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            }
                        ],
                        "local_authority_source_tasks": [
                            {
                                "project_id": "PROJ-AUTH-BLOCKED",
                                "source_task_state": "PLAN_READY",
                            }
                        ],
                    },
                    "summary": {
                        "input_mode": "GDCIC_ALTERNATIVE_PUBLIC_SOURCE_ROUTES",
                        "gdcic_alternative_public_source_route_count": 2,
                        "bid_show_record_count": 1,
                        "local_authority_source_task_count": 1,
                        "query_miss_is_not_clearance": True,
                        "customer_visible_allowed": False,
                    },
                },
            )
            _write_json(
                p13b_original / "original-notice-backtrace-v1.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-AUTH-BLOCKED",
                            "p13b_original_notice_readback_state": "BLOCKED",
                        }
                    ],
                    "summary": {"fetch_blocked_count": 1},
                },
            )
            _write_json(
                p13b_ygp / "ygp-original-readback-v1.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-AUTH-BLOCKED",
                            "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
                        }
                    ],
                    "summary": {"ygp_readback_ready_count": 1},
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                gdcic_browser_readback_root=gdcic_readback,
                p13b_company_history_root=p13b_history,
                p13b_original_notice_backtrace_root=p13b_original,
                p13b_ygp_original_readback_root=p13b_ygp,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        status = result["scoreboard"]["gdcic_authorized_readback_status"]
        self.assertEqual(status["artifact_state"], "MISSING_OR_NOT_BUILT")
        self.assertEqual(status["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
        self.assertEqual(status["target_real_readback_success_count"], 0)
        self.assertEqual(status["real_readback_success_proof_state"], "NO_REAL_AUTHORIZED_READBACK_SUCCESS")
        self.assertTrue(status["authorization_blocker_is_not_terminal_if_alternative_public_sources_exist"])
        self.assertGreaterEqual(status["alternative_public_source_route_count"], 2)
        self.assertEqual(
            status["alternative_operator_next_action"],
            "continue_alternative_public_source_release_evidence_readback_chain",
        )
        self.assertFalse(status["customer_visible_allowed"])
        self.assertTrue(status["query_miss_is_not_clearance"])
        self.assertIn("data_ggzy_bid_show", status["alternative_public_source_route_target_type_counts"])

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
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        },
                        {
                            "project_id": "PROJ-NOTFOUND",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
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
        self.assertEqual(
            rows["PROJ-BLOCKED"]["stage4_project_code_backfill_gap_detail"],
            "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED",
        )
        self.assertEqual(rows["PROJ-NOTFOUND"]["stage5_operational_review_bucket"], "ORIGINAL_NOTICE_NOT_FOUND_REVIEW")
        self.assertEqual(rows["PROJ-NOTFOUND"]["blocking_bucket"], "original_notice_not_found_review")
        self.assertEqual(
            rows["PROJ-NOTFOUND"]["stage4_project_code_backfill_gap_detail"],
            "ORIGINAL_NOTICE_NOT_FOUND_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
        )
        self.assertEqual(
            result["scoreboard"]["stage4_project_code_backfill_gap_detail_counts"],
            {
                "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 1,
                "ORIGINAL_NOTICE_NOT_FOUND_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 1,
            },
        )
        self.assertEqual(
            result["blocker_summary"]["blocking_bucket_counts"],
            {
                "public_source_blocked_review": 1,
                "original_notice_not_found_review": 1,
            },
        )

    def test_ygp_stage4_backfill_ready_is_projected_without_limited_sellable_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_ygp = root / "p13b-ygp"
            p13b_overlap = root / "p13b-overlap"
            out = root / "out"
            pressure.mkdir()
            field_query.mkdir()
            p13b_ygp.mkdir()
            p13b_overlap.mkdir()

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-YGP",
                            "project_name": "YGP candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {"manifest": {"field_task_records": [{"project_id": "PROJ-YGP", "adapter_result_state": "NEEDS_BROWSER"}]}},
            )
            _write_json(
                p13b_ygp / "ygp-original-readback-v1.json",
                {
                    "manifest": {
                        "ygp_original_readback_records": [
                            {
                                "project_id": "PROJ-YGP",
                                "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                                "ygp_project_code": "E4401002701501867001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "440100",
                                "ygp_notice_id": "notice-3C52",
                            }
                        ],
                    },
                    "summary": {
                        "ygp_readback_ready_count": 1,
                        "stage4_ygp_project_code_backfill_record_count": 1,
                        "stage4_ygp_backfill_state_counts": {"YGP_STAGE4_BACKFILL_READY": 1},
                        "stage4_ygp_gdcic_route_allowed_count": 0,
                    },
                },
            )
            _write_json(
                p13b_overlap / "p13b-overlap-triage-closeout-v1.json",
                {
                    "manifest": {
                        "project_overlap_triage_records": [
                            {
                                "project_id": "PROJ-YGP",
                                "project_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                                "ygp_stage4_backfill_ready_count": 1,
                                "ygp_stage4_gdcic_route_allowed_count": 0,
                            }
                        ],
                        "ygp_stage4_backfill_candidate_records": [
                            {
                                "project_id": "PROJ-YGP",
                                "p13b_backfill_state": "P13B_YGP_STAGE4_BACKFILL_READY",
                                "ygp_project_code": "E4401002701501867001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "440100",
                                "ygp_notice_id": "notice-3C52",
                                "gdcic_project_code_route_allowed": False,
                                "recommended_next_action": "feed_ygp_identifiers_to_p13b_or_stage4_bridge_without_gdcic_route_claim",
                            }
                        ],
                        "release_evidence_adapter_task_records": [
                            {
                                "project_id": "PROJ-YGP",
                                "release_evidence_target_type": "ygp_original_readback_backfill",
                                "initial_release_evidence_abcd_grade": "STAGE4_YGP_BACKFILL_READY_NOT_A_SIGNAL",
                                "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
                            }
                        ],
                    },
                    "summary": {
                        "ygp_stage4_backfill_ready_count": 1,
                        "ygp_stage4_release_adapter_task_count": 1,
                        "ygp_stage4_gdcic_route_allowed_count": 0,
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_ygp_original_readback_root=p13b_ygp,
                p13b_overlap_triage_closeout_root=p13b_overlap,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["stage5_operational_review_bucket"], "YGP_STAGE4_BACKFILL_READY_REVIEW")
        self.assertEqual(row["blocking_bucket"], "ygp_stage4_backfill_ready_review")
        self.assertEqual(row["p13b_ygp_stage4_backfill_ready_count"], 1)
        self.assertEqual(row["p13b_ygp_gdcic_route_allowed_count"], 0)
        self.assertEqual(
            row["stage4_project_code_backfill_state"],
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        )
        self.assertEqual(
            row["stage4_public_identifier_backfill_source"],
            "YGP_PROJECT_CODE|YGP_BIZ_CODE|YGP_SITE_CODE|YGP_NOTICE_ID|P13B_YGP_STAGE4_BACKFILL",
        )
        self.assertFalse(row["stage4_gdcic_project_code_route_allowed"])
        self.assertEqual(
            row["stage4_gdcic_project_code_route_policy"],
            "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
        )
        self.assertEqual(result["scoreboard"]["stage4_ygp_backfill_ready_project_count"], 1)
        self.assertEqual(result["scoreboard"]["stage4_ygp_backfill_ready_task_count"], 1)
        self.assertEqual(result["scoreboard"]["stage4_ygp_gdcic_route_allowed_count"], 0)
        self.assertEqual(
            result["scoreboard"]["stage4_project_code_backfill_state_counts"],
            {"PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 1},
        )
        self.assertEqual(
            result["scoreboard"]["stage4_public_identifier_backfill_source_counts"],
            {
                "YGP_PROJECT_CODE": 1,
                "YGP_BIZ_CODE": 1,
                "YGP_SITE_CODE": 1,
                "YGP_NOTICE_ID": 1,
                "P13B_YGP_STAGE4_BACKFILL": 1,
            },
        )
        self.assertEqual(
            result["scoreboard"]["stage4_gdcic_project_code_route_policy_counts"],
            {"YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 1},
        )
        self.assertEqual(result["scoreboard"]["stage4_public_identifier_backfill_project_count"], 1)
        self.assertEqual(result["scoreboard"]["stage4_gdcic_project_code_route_ready_project_count"], 0)
        self.assertEqual(result["scoreboard"]["stage4_gdcic_route_blocked_by_policy_project_count"], 1)
        self.assertEqual(result["scoreboard"]["limited_sellable_review_candidate_count"], 0)
        self.assertEqual(result["scoreboard"]["real_public_sellable_pack_rate"], 0.0)
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_ygp_original_readback_backfill_ready_projects_without_overlap_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_ygp = root / "p13b-ygp"
            out = root / "out"
            for path in (pressure, field_query, p13b_ygp, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-YGP-DIRECT",
                            "project_name": "YGP direct readback candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {"manifest": {"field_task_records": [{"project_id": "PROJ-YGP-DIRECT", "adapter_result_state": "NEEDS_BROWSER"}]}},
            )
            _write_json(
                p13b_ygp / "ygp-original-readback-v1.json",
                {
                    "manifest": {
                        "ygp_original_readback_records": [
                            {
                                "project_id": "PROJ-YGP-DIRECT",
                                "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                                "ygp_project_code": "E4413000835979563001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "441300",
                                "ygp_notice_id": "notice-ready",
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                        "stage4_ygp_project_code_backfill_records": [
                            {
                                "project_id": "PROJ-YGP-DIRECT",
                                "stage4_ygp_backfill_state": "YGP_STAGE4_BACKFILL_READY",
                                "ygp_project_code": "E4413000835979563001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "441300",
                                "ygp_notice_id": "notice-ready",
                                "gdcic_project_code_route_allowed": False,
                                "recommended_next_action": "feed_ygp_identifiers_to_p13b_or_stage4_bridge_without_gdcic_route_claim",
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                                "no_legal_conclusion": True,
                            }
                        ],
                    },
                    "summary": {
                        "ygp_readback_ready_count": 1,
                        "stage4_ygp_project_code_backfill_record_count": 1,
                        "stage4_ygp_backfill_state_counts": {"YGP_STAGE4_BACKFILL_READY": 1},
                        "stage4_ygp_gdcic_route_allowed_count": 0,
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_ygp_original_readback_root=p13b_ygp,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["stage5_operational_review_bucket"], "YGP_STAGE4_BACKFILL_READY_REVIEW")
        self.assertIn("ygp_stage4_backfill_ready", row["stage5_operational_signal_flags"])
        self.assertEqual(row["p13b_ygp_stage4_backfill_ready_count"], 1)
        self.assertEqual(row["p13b_ygp_stage4_backfill_state_counts"], {"YGP_STAGE4_BACKFILL_READY": 1})
        self.assertFalse(row["stage4_gdcic_project_code_route_allowed"])
        self.assertEqual(result["scoreboard"]["stage4_ygp_backfill_ready_project_count"], 1)
        self.assertEqual(result["scoreboard"]["stage4_ygp_backfill_ready_task_count"], 1)
        self.assertEqual(result["scoreboard"]["stage4_ygp_gdcic_route_allowed_count"], 0)
        self.assertEqual(result["scoreboard"]["limited_sellable_review_candidate_count"], 0)
        self.assertEqual(result["scoreboard"]["real_public_sellable_pack_rate"], 0.0)
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_executed_ygp_backfill_not_found_overrides_bridge_ready_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_ygp = root / "p13b-ygp"
            out = root / "out"
            for path in (pressure, field_query, p13b_ygp, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {"records": [{"project_id": "PROJ-YGP-NOT-FOUND", "stage5_rule_gate_status": "REVIEW"}]},
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {
                    "manifest": {
                        "field_task_records": [
                            {
                                "project_id": "PROJ-YGP-NOT-FOUND",
                                "adapter_result_state": "NOT_FOUND",
                                "field_readback_state": "YGP_ORIGINAL_NOTICE_QUERIED_NO_KEYWORD_MATCH",
                                "release_evidence_target_type": "ygp_original_readback_backfill",
                            }
                        ]
                    }
                },
            )
            _write_json(
                p13b_ygp / "ygp-original-readback-v1.json",
                {
                    "manifest": {
                        "ygp_original_readback_records": [
                            {
                                "project_id": "PROJ-YGP-NOT-FOUND",
                                "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                            }
                        ],
                        "stage4_ygp_project_code_backfill_records": [
                            {
                                "project_id": "PROJ-YGP-NOT-FOUND",
                                "stage4_ygp_backfill_state": "YGP_STAGE4_BACKFILL_READY",
                                "gdcic_project_code_route_allowed": False,
                            }
                        ],
                    },
                    "summary": {
                        "ygp_readback_ready_count": 1,
                        "stage4_ygp_project_code_backfill_record_count": 1,
                        "stage4_ygp_backfill_state_counts": {"YGP_STAGE4_BACKFILL_READY": 1},
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_ygp_original_readback_root=p13b_ygp,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["stage5_operational_review_bucket"], "SOURCE_NOT_FOUND_REVIEW")
        self.assertEqual(row["stage5_operational_primary_track"], "source_not_found")
        self.assertIn("YGP_STAGE4_BACKFILL_READY_REVIEW", row["stage5_operational_review_queues"])
        self.assertIn("SOURCE_NOT_FOUND_REVIEW", row["stage5_operational_review_queues"])
        self.assertTrue(row["stage5_query_miss_is_not_clearance"])
        self.assertFalse(row["customer_visible_allowed"])

    def test_data_ggzy_bid_show_original_url_is_backfill_input_not_gdcic_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_history = root / "p13b-history"
            out = root / "out"
            for path in (pressure, field_query, p13b_history, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(
                pressure / "pressure-summary.json",
                {
                    "candidate_count": 1,
                    "stage1_6_readiness_state_counts": {"STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED": 1},
                    "stage1_6_bottleneck_stage_counts": {"Stage4": 1},
                },
            )
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-BIDSHOW",
                            "project_name": "bid show candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(
                field_query / "guangdong-local-field-query-probe-v1.json",
                {"manifest": {"field_task_records": [{"project_id": "PROJ-BIDSHOW", "adapter_result_state": "NEEDS_BROWSER"}]}},
            )
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "manifest": {
                        "bid_show_records": [
                            {
                                "project_id": "PROJ-BIDSHOW",
                                "bid_show_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                                "original_notice_url": "https://example.gov.cn/original-notice.html",
                                "responsible_person_names": ["张三"],
                            }
                        ],
                        "overlap_signal_records": [
                            {
                                "project_id": "PROJ-BIDSHOW",
                                "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            }
                        ],
                    },
                    "summary": {"bid_show_record_count": 1},
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_company_history_root=p13b_history,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["p13b_bid_show_original_notice_url_count"], 1)
        self.assertEqual(row["p13b_bid_show_responsible_person_present_count"], 1)
        self.assertEqual(
            row["stage4_project_code_backfill_state"],
            "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        )
        self.assertEqual(
            row["stage4_public_identifier_backfill_source"],
            "DATA_GGZY_BID_SHOW_ORIGINAL_URL|DATA_GGZY_BID_SHOW_RESPONSIBLE_PERSON",
        )
        self.assertFalse(row["stage4_gdcic_project_code_route_allowed"])
        self.assertEqual(
            row["stage4_gdcic_project_code_route_policy"],
            "DATA_GGZY_BID_SHOW_ORIGINAL_URL_NOT_SENT_TO_GDCIC_PROJECT_CODE",
        )
        self.assertEqual(
            result["scoreboard"]["stage4_project_code_backfill_state_counts"],
            {"DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 1},
        )
        self.assertEqual(
            result["scoreboard"]["stage4_public_identifier_backfill_source_counts"],
            {
                "DATA_GGZY_BID_SHOW_ORIGINAL_URL": 1,
                "DATA_GGZY_BID_SHOW_RESPONSIBLE_PERSON": 1,
            },
        )
        self.assertEqual(
            result["scoreboard"]["stage4_gdcic_project_code_route_policy_counts"],
            {"DATA_GGZY_BID_SHOW_ORIGINAL_URL_NOT_SENT_TO_GDCIC_PROJECT_CODE": 1},
        )

    def test_local_authority_source_plan_enters_stage5_operational_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_history = root / "p13b-history"
            out = root / "out"
            for path in (pressure, field_query, p13b_history, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-LOCAL-AUTH",
                            "project_name": "阳江市历史项目地方主管源补查样本",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {"field_task_records": []}})
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "manifest": {
                        "local_authority_source_task_records": [
                            {
                                "project_id": "PROJ-LOCAL-AUTH",
                                "source_task_state": "LOCAL_AUTHORITY_SOURCE_PLAN_READY",
                                "local_authority_readback_state": "PLAN_ONLY_NOT_EXECUTED",
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                        "local_authority_source_readback_records": [
                            {
                                "project_id": "PROJ-LOCAL-AUTH",
                                "local_authority_readback_state": "NOT_FOUND",
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                        "stage4_official_readback_input_records": [
                            {
                                "project_id": "PROJ-LOCAL-AUTH",
                                "readback_input_state": "YGP_PUBLIC_IDENTIFIER_READY_FOR_ORIGINAL_READBACK",
                                "ygp_project_code": "E4417000000000001001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "441700",
                                "ygp_notice_id": "notice-local-auth",
                                "gdcic_project_code_route_allowed": False,
                                "gdcic_project_code_route_policy": (
                                    "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"
                                ),
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                    },
                    "summary": {"local_authority_source_task_count": 1},
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_company_history_root=p13b_history,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["p13b_public_source_readback_state"], "LOCAL_AUTHORITY_NOT_FOUND_REVIEW")
        self.assertEqual(row["p13b_local_authority_source_task_count"], 1)
        self.assertEqual(row["p13b_local_authority_source_readback_count"], 1)
        self.assertEqual(row["stage5_operational_review_bucket"], "LOCAL_AUTHORITY_NOT_FOUND_REVIEW")
        self.assertIn("local_authority_source_plan_ready", row["stage5_operational_signal_flags"])
        self.assertIn("local_authority_not_found", row["stage5_operational_signal_flags"])
        self.assertEqual(row["p13b_ygp_project_code_variants"], ["E4417000000000001001"])
        self.assertEqual(row["p13b_ygp_biz_code_variants"], ["3C52"])
        self.assertEqual(row["p13b_ygp_site_code_variants"], ["441700"])
        self.assertEqual(row["p13b_ygp_notice_id_variants"], ["notice-local-auth"])
        self.assertEqual(
            row["stage4_project_code_backfill_state"],
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        )
        self.assertEqual(
            row["stage4_public_identifier_backfill_source"],
            "YGP_PROJECT_CODE|YGP_BIZ_CODE|YGP_SITE_CODE|YGP_NOTICE_ID",
        )
        self.assertFalse(row["stage4_gdcic_project_code_route_allowed"])
        self.assertEqual(
            row["stage4_gdcic_project_code_route_policy"],
            "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
        )
        self.assertEqual(
            result["scoreboard"]["stage4_public_readback_outcome_counts"],
            {"LOCAL_AUTHORITY_PLAN_READY": 1, "NOT_FOUND": 1},
        )
        self.assertFalse(row["customer_visible_allowed"])
        self.assertTrue(row["query_miss_is_not_clearance"])

    def test_local_authority_region_resolution_required_is_explicit_stage5_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_history = root / "p13b-history"
            out = root / "out"
            for path in (pressure, field_query, p13b_history, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-REGION-MISSING",
                            "project_name": "地方源地区待解析样本",
                            "stage5_rule_gate_status": "REVIEW",
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {"field_task_records": []}})
            _write_json(
                p13b_history / "company-history-overlap-triage-v1.json",
                {
                    "manifest": {
                        "local_authority_source_task_records": [
                            {
                                "project_id": "PROJ-REGION-MISSING",
                                "source_task_state": "LOCAL_AUTHORITY_SOURCE_PLAN_READY",
                                "local_authority_readback_state": "PLAN_ONLY_NOT_EXECUTED",
                                "local_authority_resolution_state": "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED",
                                "local_authority_source_url_resolution_state": "SOURCE_URL_BLOCKED_BY_REGION_UNRESOLVED",
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                        "local_authority_source_readback_records": [
                            {
                                "project_id": "PROJ-REGION-MISSING",
                                "local_authority_readback_state": "BLOCKED",
                                "local_authority_resolution_state": "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED",
                                "local_authority_source_url_resolution_state": "SOURCE_URL_BLOCKED_BY_REGION_UNRESOLVED",
                                "recommended_next_action": "resolve_historical_project_jurisdiction_before_local_authority_readback",
                                "blocker_taxonomy": ["local_authority_region_unresolved"],
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                    },
                    "summary": {"local_authority_source_task_count": 1},
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_company_history_root=p13b_history,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["p13b_public_source_readback_state"], "LOCAL_AUTHORITY_BLOCKED_REVIEW")
        self.assertEqual(
            row["p13b_local_authority_resolution_state_counts"],
            {"LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED": 1},
        )
        self.assertEqual(
            row["p13b_local_authority_source_url_resolution_state_counts"],
            {"SOURCE_URL_BLOCKED_BY_REGION_UNRESOLVED": 1},
        )
        self.assertEqual(row["stage5_operational_review_bucket"], "LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED_REVIEW")
        self.assertIn("LOCAL_AUTHORITY_REGION_RESOLUTION_REQUIRED_REVIEW", row["stage5_operational_review_queues"])
        self.assertIn("local_authority_region_resolution_required", row["stage5_operational_signal_flags"])
        self.assertEqual(
            row["stage5_operational_next_action"],
            "resolve_historical_project_jurisdiction_before_local_authority_readback",
        )
        self.assertEqual(row["stage5_operational_primary_track"], "local_authority_region_resolution_required")
        self.assertEqual(row["stage5_operational_priority_bucket"], "P1_BLOCKER_RETRY_OR_ALTERNATE_SOURCE")
        self.assertEqual(row["blocking_bucket"], "local_authority_region_resolution_required_review")
        self.assertFalse(row["customer_visible_allowed"])
        self.assertTrue(row["query_miss_is_not_clearance"])

    def test_incremental_scoreboard_preserves_non_target_public_source_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            p13b_ygp = root / "p13b-ygp"
            prior = root / "prior-scoreboard.json"
            out = root / "out"
            for path in (pressure, field_query, p13b_ygp, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 2})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-KEEP",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        },
                        {
                            "project_id": "PROJ-TARGET",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
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
                            {"project_id": "PROJ-KEEP", "adapter_result_state": "NEEDS_BROWSER"},
                            {"project_id": "PROJ-TARGET", "adapter_result_state": "NEEDS_BROWSER"},
                        ]
                    }
                },
            )
            _write_json(
                p13b_ygp / "ygp-original-readback-v1.json",
                {
                    "manifest": {
                        "ygp_original_readback_records": [
                            {
                                "project_id": "PROJ-TARGET",
                                "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                                "ygp_project_code": "E4401002701502338001",
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "440100",
                                "ygp_notice_id": "notice-target",
                            }
                        ]
                    }
                },
            )
            _write_json(
                prior,
                {
                    "project_rows": [
                        {
                            "project_id": "PROJ-KEEP",
                            "stage5_operational_review_bucket": "STRONG_LEAD_INTERNAL_REVIEW",
                            "stage5_operational_review_families": ["strong_lead", "official_readback_ready"],
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
                            "stage4_project_code_backfill_state": (
                                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                            ),
                            "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE",
                            "stage4_gdcic_project_code_route_policy": (
                                "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"
                            ),
                            "customer_visible_allowed": False,
                            "query_miss_is_not_clearance": True,
                            "no_legal_conclusion": True,
                        }
                    ]
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                p13b_ygp_original_readback_root=p13b_ygp,
                prior_scoreboard_json=prior,
                incremental_project_ids=["PROJ-TARGET"],
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        rows = {row["project_id"]: row for row in result["project_rows"]}
        self.assertEqual(
            rows["PROJ-KEEP"]["incremental_scoreboard_merge_state"],
            "PRESERVED_FROM_PRIOR_SCOREBOARD_NON_TARGET",
        )
        self.assertEqual(rows["PROJ-KEEP"]["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(rows["PROJ-TARGET"]["incremental_scoreboard_merge_state"], "CURRENT_INCREMENTAL_TARGET")
        self.assertEqual(result["scoreboard"]["limited_sellable_review_candidate_count"], 1)
        self.assertEqual(result["scoreboard"]["stage5_operational_review_family_counts"]["strong_lead"], 1)
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_incremental_target_preserves_prior_public_identifier_when_retry_regresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            prior = root / "prior-scoreboard.json"
            out = root / "out"
            for path in (pressure, field_query, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-TARGET",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "fail_closed_reasons": ["gdcic_project_code_not_resolved"],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {"field_task_records": []}})
            _write_json(
                prior,
                {
                    "project_rows": [
                        {
                            "project_id": "PROJ-TARGET",
                            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                            "stage5_operational_review_family": "official_readback_ready",
                            "stage5_operational_review_families": ["official_readback_ready"],
                            "stage5_operational_review_queues": ["YGP_STAGE4_BACKFILL_READY_REVIEW"],
                            "stage5_operational_signal_flags": ["ygp_stage4_backfill_ready"],
                            "stage5_operational_primary_track": "official_readback_ready",
                            "stage5_operational_priority_bucket": "P1_OFFICIAL_READBACK_DEEPENING",
                            "stage5_operational_priority_rank": 1,
                            "stage5_operational_safety_boundary": "INTERNAL_REVIEW_ONLY_NOT_CLEARANCE",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
                            "p13b_ygp_project_code_variants": ["E4401002701502338001"],
                            "stage4_project_code_backfill_state": (
                                "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                            ),
                            "stage4_project_code_backfill_gap_detail": "",
                            "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE",
                            "stage4_gdcic_project_code_route_allowed": False,
                            "stage4_gdcic_project_code_route_policy": (
                                "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE"
                            ),
                            "blocking_bucket": "ygp_stage4_backfill_ready_review",
                            "customer_visible_allowed": False,
                            "query_miss_is_not_clearance": True,
                            "no_legal_conclusion": True,
                        }
                    ]
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                prior_scoreboard_json=prior,
                incremental_project_ids=["PROJ-TARGET"],
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(
            row["incremental_scoreboard_merge_state"],
            "CURRENT_INCREMENTAL_TARGET_WITH_PRIOR_PUBLIC_SOURCE_EVIDENCE",
        )
        self.assertTrue(row["incremental_scoreboard_preserved_public_source_evidence"])
        self.assertEqual(row["stage5_operational_primary_track"], "official_readback_ready")
        self.assertEqual(row["p13b_ygp_original_readback_state"], "YGP_READBACK_READY")
        self.assertEqual(
            row["stage4_project_code_backfill_state"],
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        )
        self.assertEqual(row["stage4_public_identifier_backfill_source"], "YGP_PROJECT_CODE")
        self.assertFalse(row["customer_visible_allowed"])
        self.assertTrue(row["query_miss_is_not_clearance"])

    def test_incremental_scoreboard_preserves_top_level_stage123_counts_from_prior_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            prior = root / "prior-scoreboard.json"
            out = root / "out"
            for path in (pressure, field_query, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-TARGET",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {"field_task_records": []}})
            _write_json(
                prior,
                {
                    "scoreboard": {
                        "candidate_count": 15,
                        "stage2_success_count": 15,
                        "stage3_success_count": 15,
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-KEEP",
                            "stage5_operational_review_bucket": "ORIGINAL_NOTICE_NOT_FOUND_REVIEW",
                            "customer_visible_allowed": False,
                            "query_miss_is_not_clearance": True,
                        }
                    ]
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                prior_scoreboard_json=prior,
                incremental_project_ids=["PROJ-TARGET"],
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        self.assertEqual(result["scoreboard"]["candidate_count"], 15)
        self.assertEqual(result["scoreboard"]["stage2_success_count"], 15)
        self.assertEqual(result["scoreboard"]["stage3_success_count"], 15)

    def test_company_first_flow08_targeted_parse_required_is_stage5_operational_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            company_first = root / "company-first"
            out = root / "out"
            for path in (pressure, field_query, company_first, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-FLOW08",
                            "project_name": "flow08 candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": [
                                "notice_has_company_and_project_manager_but_missing_certificate_no",
                            ],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {}})
            _write_json(
                company_first / "company-first-stage4-execution.json",
                {
                    "summary": {
                        "project_count": 1,
                        "job_count": 1,
                        "stage4_execution_state_counts": {"FAIL_CLOSED": 1},
                        "identity_resolution_state_counts": {"UNKNOWN": 1},
                        "supplement_after_execution_state_counts": {
                            "FLOW_08_TARGETED_PARSE_REQUIRED": 1,
                        },
                        "stage4_input_count": 0,
                        "flow_08_targeted_parse_required_count": 1,
                    },
                    "manifest": {
                        "items": [
                            {
                                "project_id": "PROJ-FLOW08",
                                "stage4_execution_state": "FAIL_CLOSED",
                                "identity_resolution_state": "",
                                "supplement_after_execution_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
                                "stage4_readiness_state": (
                                    "STAGE4_BLOCKED_COMPANY_FIRST_AND_NAME_ENUMERATION_NO_MATCH"
                                ),
                                "flow_08_targeted_parse_required": True,
                                "next_actions": ["FLOW_08_TARGETED_PARSE", "DO_NOT_OUTPUT_FINAL_CONFLICT"],
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                            }
                        ]
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                company_first_stage4_execution_root=company_first,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["company_first_stage4_execution_state"], "FAIL_CLOSED")
        self.assertEqual(row["company_first_supplement_after_execution_state"], "FLOW_08_TARGETED_PARSE_REQUIRED")
        self.assertTrue(row["company_first_flow_08_targeted_parse_required"])
        self.assertEqual(row["stage5_operational_review_bucket"], "COMPANY_FIRST_FLOW08_TARGETED_PARSE_REVIEW")
        self.assertIn("COMPANY_FIRST_FLOW08_TARGETED_PARSE_REVIEW", row["stage5_operational_review_queues"])
        self.assertIn("company_first_flow08_targeted_parse_required", row["stage5_operational_signal_flags"])
        self.assertEqual(
            result["scoreboard"]["company_first_stage4_execution_status"][
                "flow_08_targeted_parse_required_project_count"
            ],
            1,
        )
        self.assertEqual(
            result["scoreboard"]["company_first_stage4_execution_status"]["projected_stage5_queue_counts"],
            {"COMPANY_FIRST_FLOW08_TARGETED_PARSE_REVIEW": 1},
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_design_survey_public_registry_fallback_required_is_stage5_operational_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            company_first = root / "company-first"
            out = root / "out"
            for path in (pressure, field_query, company_first, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-DESIGN-FALLBACK",
                            "project_name": "design survey fallback candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                            "fail_closed_reasons": [
                                "notice_has_company_and_project_manager_but_missing_certificate_no",
                            ],
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {}})
            _write_json(
                company_first / "company-first-stage4-execution.json",
                {
                    "summary": {
                        "project_count": 1,
                        "job_count": 1,
                        "stage4_execution_state_counts": {"FAIL_CLOSED": 1},
                        "identity_resolution_state_counts": {"UNKNOWN": 1},
                        "supplement_after_execution_state_counts": {
                            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED": 1,
                        },
                        "stage4_input_count": 0,
                    },
                    "manifest": {
                        "items": [
                            {
                                "project_id": "PROJ-DESIGN-FALLBACK",
                                "stage4_execution_state": "FAIL_CLOSED",
                                "identity_resolution_state": "",
                                "supplement_after_execution_state": (
                                    "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
                                ),
                                "stage4_readiness_state": (
                                    "STAGE4_BLOCKED_COMPANY_FIRST_AND_DESIGN_SURVEY_REGISTRY_REQUIRED"
                                ),
                                "next_actions": [
                                    "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK",
                                    "DO_NOT_OUTPUT_FINAL_CONFLICT",
                                ],
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                            }
                        ]
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                company_first_stage4_execution_root=company_first,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(
            row["company_first_supplement_after_execution_state"],
            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
        )
        self.assertEqual(row["stage5_operational_review_bucket"], "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW")
        self.assertEqual(row["blocking_bucket"], "design_survey_public_registry_fallback_review")
        self.assertIn("DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW", row["stage5_operational_review_queues"])
        self.assertIn(
            "design_survey_public_registry_fallback_required",
            row["stage5_operational_signal_flags"],
        )
        self.assertEqual(row["stage5_operational_review_family"], "public_registration_fallback_required")
        self.assertEqual(result["scoreboard"]["limited_sellable_review_candidate_count"], 0)
        self.assertEqual(result["scoreboard"]["sellable_or_limited_review_candidate_count"], 0)
        self.assertEqual(
            result["scoreboard"]["stage5_operational_review_bucket_counts"],
            {"DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW": 1},
        )
        self.assertEqual(
            result["scoreboard"]["company_first_stage4_execution_status"][
                "design_survey_public_registry_fallback_required_project_count"
            ],
            1,
        )
        self.assertEqual(
            result["scoreboard"]["company_first_stage4_execution_status"]["projected_stage5_queue_counts"],
            {"DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW": 1},
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_design_survey_public_registry_not_found_readback_replaces_fallback_queue_without_sale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure = root / "pressure"
            field_query = root / "field-query"
            company_first = root / "company-first"
            registry_readback = root / "registry-readback"
            out = root / "out"
            for path in (pressure, field_query, company_first, registry_readback, out):
                path.mkdir(parents=True, exist_ok=True)

            _write_json(pressure / "pressure-summary.json", {"candidate_count": 1})
            _write_json(
                pressure / "stage1-6-readiness-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-DESIGN-NOT-FOUND",
                            "project_name": "design survey fallback candidate",
                            "stage2_detail_capture_state": "FETCHED",
                            "stage3_field_parse_state": "PARSED_FROM_FIELD_SIGNALS",
                            "stage5_rule_gate_status": "REVIEW",
                            "stage5_gate_state": "REVIEW_REQUIRED",
                        }
                    ]
                },
            )
            _write_json(pressure / "stage1-6-gap-summary-table.json", {"records": []})
            _write_json(field_query / "guangdong-local-field-query-probe-v1.json", {"manifest": {}})
            _write_json(
                company_first / "company-first-stage4-execution.json",
                {
                    "summary": {
                        "project_count": 1,
                        "job_count": 1,
                        "supplement_after_execution_state_counts": {
                            "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED": 1,
                        },
                    },
                    "manifest": {
                        "items": [
                            {
                                "project_id": "PROJ-DESIGN-NOT-FOUND",
                                "stage4_execution_state": "FAIL_CLOSED",
                                "supplement_after_execution_state": (
                                    "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED"
                                ),
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                            }
                        ]
                    },
                },
            )
            _write_json(
                registry_readback / "design-survey-public-registry-readback-v1.json",
                {
                    "summary": {
                        "readback_record_count": 1,
                        "project_count": 1,
                        "provider_result_state_counts": {"READBACK_READY": 1},
                        "readback_state_counts": {"NOT_FOUND": 1},
                        "verification_result_counts": {"REVIEW_REQUIRED": 1},
                        "matched_count": 0,
                        "review_required_count": 1,
                    },
                    "manifest": {
                        "public_registry_readback_table": {
                            "records": [
                                {
                                    "project_id": "PROJ-DESIGN-NOT-FOUND",
                                    "provider_result_state": "READBACK_READY",
                                    "readback_state": "NOT_FOUND",
                                    "verification_result": "REVIEW_REQUIRED",
                                    "customer_visible_allowed": False,
                                    "no_legal_conclusion": True,
                                }
                            ]
                        }
                    },
                },
            )

            result = build_stage1_6_sellable_scoreboard(
                pressure_root=pressure,
                field_query_root=field_query,
                company_first_stage4_execution_root=company_first,
                design_survey_public_registry_readback_root=registry_readback,
                output_root=out,
                created_at="2026-05-24T00:00:00+08:00",
            )

        row = result["project_rows"][0]
        self.assertEqual(row["design_survey_public_registry_readback_state"], "NOT_FOUND")
        self.assertEqual(row["stage5_operational_review_bucket"], "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW")
        self.assertEqual(row["blocking_bucket"], "design_survey_public_registry_not_found_review")
        self.assertIn("design_survey_public_registry_not_found", row["stage5_operational_signal_flags"])
        self.assertEqual(result["scoreboard"]["limited_sellable_review_candidate_count"], 0)
        self.assertEqual(result["scoreboard"]["sellable_or_limited_review_candidate_count"], 0)
        self.assertEqual(
            result["scoreboard"]["design_survey_public_registry_readback_status"]["readback_state_counts"],
            {"NOT_FOUND": 1},
        )
        self.assertEqual(
            result["scoreboard"]["stage4_public_readback_outcome_counts"],
            {"NOT_FOUND": 1},
        )
        self.assertEqual(
            result["scoreboard"]["stage4_public_readback_channel_outcome_counts"],
            {"DESIGN_SURVEY_PUBLIC_REGISTRY:NOT_FOUND": 1},
        )
        self.assertEqual(
            result["scoreboard"]["design_survey_public_registry_readback_status"]["projected_stage5_queue_counts"],
            {
                "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REVIEW": 1,
                "DESIGN_SURVEY_PUBLIC_REGISTRY_NOT_FOUND_REVIEW": 1,
            },
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
