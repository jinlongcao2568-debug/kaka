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
    def test_preserves_data_ggzy_urls_hashes_and_project_context_for_stage4_followup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            p13b_history = root / "p13b" / "company-history-overlap-triage-v1.json"
            original = root / "original" / "original-notice-backtrace-v1.json"
            _write_json(
                scoreboard,
                {
                    "input_refs": {
                        "p13b_company_history_json": str(p13b_history),
                        "p13b_original_notice_backtrace_json": str(original),
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-DATA-GGZY-CONTEXT",
                            "project_name": "data ggzy context project",
                            "stage4_project_code_backfill_state": (
                                "DATA_GGZY_BID_SHOW_ORIGINAL_URL_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY"
                            ),
                            "stage5_operational_review_bucket": "ORIGINAL_NOTICE_NOT_FOUND_REVIEW",
                            "p13b_local_authority_executed_readback_state_counts": {"NOT_FOUND": 1},
                            "p13b_candidate_companies": ["广东甲公司"],
                            "p13b_responsible_person_names": ["张三"],
                            "p13b_candidate_notice_source_urls": [
                                "https://ywtb.gzggzy.cn/jyfw/current.html"
                            ],
                            "p13b_project_source_urls": [
                                "https://ywtb.gzggzy.cn/jyfw/current.html"
                            ],
                            "p13b_data_ggzy_bid_show_urls": [
                                "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1"
                            ],
                            "p13b_data_ggzy_original_notice_urls": [
                                "https://example.gov.cn/original.html"
                            ],
                            "p13b_data_ggzy_bid_show_record_ids": ["P13B-BID-SHOW-1"],
                            "p13b_data_ggzy_readback_payload_sha256s": ["b" * 64],
                            "p13b_data_ggzy_extracted_responsible_person_names": ["李四"],
                            "stage4_public_identifier_backfill_source": (
                                "DATA_GGZY_BID_SHOW_ORIGINAL_URL|DATA_GGZY_BID_SHOW_RESPONSIBLE_PERSON"
                            ),
                        }
                    ],
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        record = result["records"][0]
        self.assertEqual(record["candidate_companies"], ["广东甲公司"])
        self.assertEqual(record["responsible_person_names"], ["张三"])
        self.assertEqual(
            record["candidate_notice_source_urls"],
            ["https://ywtb.gzggzy.cn/jyfw/current.html"],
        )
        self.assertIn("https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1", record["source_refs"])
        self.assertIn("https://example.gov.cn/original.html", record["source_refs"])
        self.assertEqual(record["data_ggzy_readback_payload_sha256s"], ["b" * 64])
        self.assertIn(str(p13b_history), record["artifact_refs"])
        self.assertIn(str(original), record["artifact_refs"])
        context = record["stage4_official_readback_context"]
        self.assertEqual(
            context["stage4_official_readback_context_state"],
            "DATA_GGZY_READBACK_FIXED_STAGE4_BACKFILL_INPUT_READY",
        )
        self.assertEqual(
            context["data_ggzy_bid_show_urls"],
            ["https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1"],
        )
        self.assertEqual(context["data_ggzy_readback_payload_sha256s"], ["b" * 64])
        self.assertFalse(context["gdcic_project_code_route_allowed"])

    def test_emits_continuation_input_refs_from_scoreboard_input_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure_root = root / "pressure"
            field_root = root / "field-query"
            supplemental_field_root = root / "field-query-ygp-backfill"
            gdcic_root = root / "gdcic-browser-authorized-readback"
            stage6_root = root / "stage6-loop-merged"
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            pressure_summary = pressure_root / "pressure-summary.json"
            release_plan = pressure_root / "stage4-release-adapter-bridge-plan.json"
            field_json = field_root / "guangdong-local-field-query-probe-v1.json"
            supplemental_field_json = supplemental_field_root / "guangdong-local-field-query-probe-v1.json"
            gdcic_json = gdcic_root / "gdcic-browser-authorized-readback-v1.json"
            stage6_json = stage6_root / "stage6-review-loop-project-status-table.json"
            _write_json(pressure_summary, {"summary": {"candidate_count": 1}})
            _write_json(release_plan, {"tasks": []})
            _write_json(field_json, {"summary": {"adapter_result_state_counts": {"MATCHED": 1}}})
            _write_json(supplemental_field_json, {"summary": {"adapter_result_state_counts": {"MATCHED": 1}}})
            _write_json(gdcic_json, {"summary": {"authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED"}})
            _write_json(stage6_json, {"summary": {"project_status_record_count": 1}})
            _write_json(
                scoreboard,
                {
                    "input_refs": {
                        "pressure_summary_json": str(pressure_summary),
                        "release_field_query_json": str(field_json),
                        "supplemental_release_field_query_json": str(supplemental_field_json),
                        "gdcic_browser_authorized_readback_json": str(gdcic_json),
                        "stage6_status_json": str(stage6_json),
                    },
                    "project_rows": [
                        {
                            "project_id": "PROJ-GDCIC-UNRESOLVED",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "GDCIC_IDENTIFIER_UNRESOLVED_AFTER_PUBLIC_BACKFILL_REQUIRED",
                        }
                    ],
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        refs = result["continuation_input_refs"]
        self.assertEqual(refs["prior_scoreboard_json"], str(scoreboard))
        self.assertEqual(refs["effective_pressure_root"], str(pressure_root))
        self.assertEqual(refs["effective_release_field_query_root"], str(field_root))
        self.assertEqual(refs["effective_supplemental_release_field_query_root"], str(supplemental_field_root))
        self.assertEqual(refs["effective_supplemental_release_field_query_json"], str(supplemental_field_json))
        self.assertEqual(refs["effective_gdcic_browser_readback_root"], str(gdcic_root))
        self.assertEqual(refs["effective_stage6_status_root"], str(stage6_root))
        self.assertEqual(refs["pressure_root_resolution_state"], "RESOLVED_FROM_SCOREBOARD_INPUT_REFS")
        self.assertEqual(
            refs["supplemental_release_field_query_root_resolution_state"],
            "RESOLVED_FROM_SCOREBOARD_INPUT_REFS",
        )
        self.assertFalse(refs["customer_visible_allowed"])
        self.assertTrue(refs["query_miss_is_not_clearance"])
        self.assertEqual(result["next_regression_execution_plan"]["continuation_input_refs"], refs)

    def test_continuation_input_refs_fall_back_to_prior_scoreboard_refs_for_incremental_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prior_pressure = root / "prior-pressure"
            prior_field = root / "prior-field-query"
            prior_stage6 = root / "prior-stage6"
            prior_scoreboard = root / "prior" / "stage1-6-sellable-scoreboard-v1.json"
            scoreboard = root / "current" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            _write_json(prior_pressure / "pressure-summary.json", {"summary": {"candidate_count": 2}})
            _write_json(prior_pressure / "stage4-release-adapter-bridge-plan.json", {"tasks": []})
            _write_json(prior_field / "guangdong-local-field-query-probe-v1.json", {"summary": {}})
            _write_json(prior_stage6 / "stage6-review-loop-project-status-table.json", {"summary": {}})
            _write_json(
                prior_scoreboard,
                {
                    "input_refs": {
                        "pressure_summary_json": str(prior_pressure / "pressure-summary.json"),
                        "release_field_query_json": str(prior_field / "guangdong-local-field-query-probe-v1.json"),
                        "stage6_status_json": str(prior_stage6 / "stage6-review-loop-project-status-table.json"),
                    }
                },
            )
            _write_json(
                scoreboard,
                {
                    "input_refs": {
                        "pressure_summary_json": str(root / "missing" / "pressure-summary.json"),
                        "release_field_query_json": str(root / "missing" / "guangdong-local-field-query-probe-v1.json"),
                        "stage6_status_json": str(root / "missing" / "stage6-review-loop-project-status-table.json"),
                        "prior_scoreboard_json": str(prior_scoreboard),
                    },
                    "project_rows": [],
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        refs = result["continuation_input_refs"]
        self.assertEqual(refs["effective_pressure_root"], str(prior_pressure))
        self.assertEqual(refs["effective_release_field_query_root"], str(prior_field))
        self.assertEqual(refs["effective_stage6_status_root"], str(prior_stage6))

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

    def test_executed_local_authority_readbacks_get_actionable_followup_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_root = root / "stage1-6-sellable-rate-regression-live15-r2"
            scoreboard = run_root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            p13b = run_root / "p13b-company-history" / "company-history-overlap-triage-v1.json"
            comparison = root / "comparison.json"
            out = root / "out"
            _write_json(
                p13b,
                {
                    "manifest": {
                        "local_authority_source_readback_records": [
                            {
                                "project_id": "PROJ-LOCAL-BLOCKED-SECONDARY",
                                "local_authority_region_code": "CN-GD-YJ",
                                "source_name": "阳江市住房和城乡建设局 / 政府信息公开",
                                "source_url": "https://www.yangjiang.gov.cn/yjzjj/gkmlpt/index",
                                "local_authority_readback_state": "BLOCKED",
                                "http_status_code": 0,
                                "blocker_taxonomy": ["local_authority_source_http_blocked_or_unavailable"],
                            },
                            {
                                "project_id": "PROJ-LOCAL-NOT-FOUND-SECONDARY",
                                "local_authority_region_code": "CN-GD-GZ",
                                "source_name": "广州市住房和城乡建设局 / 信用信息双公示",
                                "source_url": "https://zfcj.gz.gov.cn/zfcj/xyxx/",
                                "local_authority_readback_state": "NOT_FOUND",
                                "http_status_code": 200,
                                "blocker_taxonomy": ["local_authority_portal_reachable_no_project_keyword_match"],
                            },
                        ]
                    }
                },
            )
            _write_json(
                scoreboard,
                {
                    "input_refs": {"p13b_company_history_json": str(p13b)},
                    "project_rows": [
                        {
                            "project_id": "PROJ-LOCAL-BLOCKED",
                            "project_name": "Local authority blocked project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "LOCAL_AUTHORITY_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "LOCAL_AUTHORITY_BLOCKED_REVIEW",
                            "p13b_overlap_triage_state": "NO_OVERLAP_SIGNAL_REVIEW",
                        },
                        {
                            "project_id": "PROJ-LOCAL-NOT-FOUND",
                            "project_name": "Local authority not found project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "LOCAL_AUTHORITY_NOT_FOUND_REVIEW",
                            "p13b_public_source_readback_state": "LOCAL_AUTHORITY_NOT_FOUND_REVIEW",
                            "p13b_overlap_triage_state": "NO_OVERLAP_SIGNAL_REVIEW",
                        },
                        {
                            "project_id": "PROJ-LOCAL-BLOCKED-SECONDARY",
                            "project_name": "Local authority blocked while main track stays YGP",
                            "stage4_project_code_backfill_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_local_authority_executed_readback_state_counts": {"BLOCKED": 1},
                            "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                        },
                        {
                            "project_id": "PROJ-LOCAL-NOT-FOUND-SECONDARY",
                            "project_name": "Local authority not found while main track stays strong lead",
                            "stage4_project_code_backfill_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                            "stage5_operational_review_bucket": "STRONG_LEAD_INTERNAL_REVIEW",
                            "p13b_public_source_readback_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                            "p13b_local_authority_executed_readback_state_counts": {"NOT_FOUND": 1},
                            "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                        },
                    ]
                },
            )
            _write_json(
                comparison,
                {
                    "public_source_deepening_recommendations": [
                        {
                            "run_label": "stage1-6-sellable-rate-regression-live15-r2",
                            "previous_run_label": "stage1-6-sellable-rate-regression-live15-r1",
                            "decision": "CONTINUE_PUBLIC_SOURCE_DEEPENING",
                            "reason": "same_candidate_count_public_source_followup_classified_blocked_or_not_found_without_clearance",
                            "recommended_budget_focus": [
                                "retry_blocked_local_authority_sources_with_alternate_official_entries",
                                "deepen_not_found_with_specific_search_endpoint_or_manual_source_path",
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

        records = {record["project_id"]: record for record in result["records"]}
        self.assertEqual(
            records["PROJ-LOCAL-BLOCKED"]["stage4_project_code_backfill_gap_detail"],
            "LOCAL_AUTHORITY_BLOCKED_RETRY_OR_ALTERNATE_SOURCE_REQUIRED",
        )
        self.assertEqual(
            records["PROJ-LOCAL-BLOCKED"]["followup_route"],
            "local_authority_blocked_retry_or_alternate_source",
        )
        self.assertEqual(records["PROJ-LOCAL-BLOCKED"]["execution_priority"], "HIGH_PUBLIC_SOURCE_DEEPENING")
        self.assertEqual(
            records["PROJ-LOCAL-NOT-FOUND"]["stage4_project_code_backfill_gap_detail"],
            "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED",
        )
        self.assertEqual(
            records["PROJ-LOCAL-NOT-FOUND"]["followup_route"],
            "local_authority_not_found_specific_endpoint_or_manual_source",
        )
        self.assertEqual(
            records["PROJ-LOCAL-BLOCKED-SECONDARY"]["followup_route"],
            "local_authority_blocked_retry_or_alternate_source",
        )
        self.assertEqual(
            records["PROJ-LOCAL-NOT-FOUND-SECONDARY"]["followup_route"],
            "local_authority_not_found_specific_endpoint_or_manual_source",
        )
        self.assertEqual(
            records["PROJ-LOCAL-BLOCKED-SECONDARY"]["local_authority_readback_context"]["local_authority_region_code"],
            "CN-GD-YJ",
        )
        self.assertEqual(
            records["PROJ-LOCAL-NOT-FOUND-SECONDARY"]["alternate_local_authority_source_candidates"][0]["candidate_source_id"],
            "gz_zfcj_construction_permit_public_api",
        )
        self.assertEqual(records["PROJ-LOCAL-NOT-FOUND"]["execution_priority"], "MEDIUM_LOCAL_AUTHORITY_FALLBACK")
        self.assertEqual(
            result["summary"]["execution_priority_counts"],
            {"HIGH_PUBLIC_SOURCE_DEEPENING": 2, "MEDIUM_LOCAL_AUTHORITY_FALLBACK": 2},
        )
        for record in result["records"]:
            self.assertTrue(record["public_source_deepening_recommended"])
            self.assertFalse(record["customer_visible_allowed"])
            self.assertTrue(record["query_miss_is_not_clearance"])

    def test_official_readback_ready_rows_queue_stage4_bridge_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            _write_json(
                scoreboard,
                {
                    "project_rows": [
                        {
                            "project_id": "PROJ-OFFICIAL-READY",
                            "project_name": "Official ready project",
                            "stage5_operational_primary_track": "official_readback_ready",
                            "stage5_operational_review_bucket": "YGP_STAGE4_BACKFILL_READY_REVIEW",
                            "limited_sellable_review_candidate_state": "NOT_READY",
                            "p13b_ygp_original_readback_state": "YGP_READBACK_READY",
                            "p13b_ygp_stage4_backfill_ready_count": 1,
                            "p13b_ygp_stage4_release_adapter_task_count": 1,
                            "p13b_ygp_source_urls": ["https://ygp.gdzwfw.gov.cn/detail-ready"],
                            "p13b_ygp_original_notice_urls": [
                                "https://ygp.gdzwfw.gov.cn/original-ready"
                            ],
                            "p13b_ygp_readback_payload_sha256s": ["c" * 64],
                            "p13b_ygp_record_payload_sha256s": ["d" * 64],
                            "p13b_ygp_node_id_variants": ["node-ready"],
                            "stage4_project_code_backfill_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                            "p13b_overlap_triage_state": "YGP_STAGE4_BACKFILL_READY_FOR_P13B_OR_STAGE4_BRIDGE",
                        },
                        {
                            "project_id": "PROJ-ALREADY-LIMITED",
                            "stage5_operational_primary_track": "official_readback_ready",
                            "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                            "p13b_ygp_stage4_release_adapter_task_count": 1,
                        },
                    ]
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        self.assertEqual(result["summary"]["followup_record_count"], 1)
        record = result["records"][0]
        self.assertEqual(record["project_id"], "PROJ-OFFICIAL-READY")
        self.assertEqual(
            record["stage4_project_code_backfill_gap_detail"],
            "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED",
        )
        self.assertEqual(record["followup_route"], "official_readback_ready_stage4_bridge_followup")
        self.assertEqual(record["execution_priority"], "NORMAL_STAGE4_BRIDGE_PROMOTION")
        self.assertEqual(
            record["recommended_next_action"],
            "feed_public_identifier_to_release_evidence_adapter_before_limited_review",
        )
        self.assertIn("https://ygp.gdzwfw.gov.cn/detail-ready", record["source_refs"])
        self.assertEqual(record["ygp_readback_payload_sha256s"], ["c" * 64, "d" * 64])
        self.assertEqual(record["ygp_node_id_variants"], ["node-ready"])
        self.assertEqual(
            record["stage4_official_readback_context"]["ygp_source_urls"],
            ["https://ygp.gdzwfw.gov.cn/detail-ready", "https://ygp.gdzwfw.gov.cn/original-ready"],
        )
        self.assertEqual(
            [step["source_kind"] for step in record["public_source_fallback_sequence"]],
            [
                "ygp_original_notice_readback",
                "stage4_release_adapter_bridge",
                "stage6_limited_sellable_projection",
            ],
        )
        self.assertEqual(
            record["public_source_fallback_sequence"][1]["input_state"],
            "P13B_RELEASE_ADAPTER_TASK_READY",
        )
        plan = result["next_regression_execution_plan"]
        self.assertEqual(plan["target_project_ids"], ["PROJ-OFFICIAL-READY"])
        self.assertEqual(plan["recommended_parameter_overrides"]["MaxLiveYgpBackfillTasks"], 8)
        self.assertFalse(record["customer_visible_allowed"])
        self.assertTrue(record["query_miss_is_not_clearance"])

    def test_followup_records_include_pressure_context_for_p13b_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure_root = root / "pressure"
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            pressure_summary = pressure_root / "pressure-summary.json"
            release_plan = pressure_root / "stage4-release-adapter-bridge-plan.json"
            _write_json(pressure_summary, {"summary": {"candidate_count": 1}})
            _write_json(
                release_plan,
                {
                    "release_evidence_adapter_task_records": [
                        {
                            "project_id": "PROJ-CONTEXT",
                            "candidate_company_name": "广东甲公司",
                            "matched_person_names": ["张三"],
                            "trigger_source_url": "https://ywtb.gzggzy.cn/jyfw/context.html",
                            "query_params": {
                                "companyVariants": ["广东甲公司", "广东甲公司"],
                                "projectManagerName": "张三",
                            },
                        }
                    ]
                },
            )
            _write_json(
                scoreboard,
                {
                    "input_refs": {"pressure_summary_json": str(pressure_summary)},
                    "project_rows": [
                        {
                            "project_id": "PROJ-CONTEXT",
                            "project_name": "广州上下文项目中标候选人公示",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                        }
                    ],
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        record = result["records"][0]
        self.assertEqual(record["candidate_companies"], ["广东甲公司"])
        self.assertEqual(record["responsible_person_names"], ["张三"])
        self.assertEqual(record["candidate_notice_source_urls"], ["https://ywtb.gzggzy.cn/jyfw/context.html"])
        self.assertEqual(record["context_source"], "stage4_release_adapter_bridge_plan")
        self.assertFalse(record["customer_visible_allowed"])

    def test_followup_infers_local_authority_region_from_guangzhou_trade_platform_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure_root = root / "pressure"
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            pressure_summary = pressure_root / "pressure-summary.json"
            release_plan = pressure_root / "stage4-release-adapter-bridge-plan.json"
            _write_json(pressure_summary, {"summary": {"candidate_count": 1}})
            _write_json(
                release_plan,
                {
                    "release_evidence_adapter_task_records": [
                        {
                            "project_id": "PROJ-GZ-DOMAIN",
                            "candidate_company_name": "广东乙公司",
                            "trigger_source_url": "https://ywtb.gzggzy.cn/jyfw/domain-only.html",
                        }
                    ]
                },
            )
            _write_json(
                scoreboard,
                {
                    "input_refs": {"pressure_summary_json": str(pressure_summary)},
                    "project_rows": [
                        {
                            "project_id": "PROJ-GZ-DOMAIN",
                            "project_name": "无城市标记项目中标候选人公示",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                        }
                    ],
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-26T00:00:00+08:00",
            )

        record = result["records"][0]
        self.assertEqual(record["local_authority_readback_context"]["local_authority_region_code"], "CN-GD-GZ")
        self.assertEqual(
            record["local_authority_readback_context"]["local_authority_region_basis"],
            "current_candidate_trade_platform_domain",
        )
        self.assertEqual(
            record["alternate_local_authority_source_candidates"][0]["candidate_source_id"],
            "gz_zfcj_construction_permit_public_api",
        )
        self.assertFalse(record["customer_visible_allowed"])
        self.assertTrue(record["query_miss_is_not_clearance"])


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
