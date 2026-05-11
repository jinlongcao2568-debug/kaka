from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class BusinessDirectionStrategyContractTests(unittest.TestCase):
    def _contract(self) -> dict:
        path = ROOT / "contracts" / "evaluation" / "business_direction_strategy_contract.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_post_candidate_evidence_pack_is_default_commercial_mainline(self) -> None:
        contract = self._contract()

        self.assertEqual(contract["primary_commercial_line"], "POST_CANDIDATE_EVIDENCE_PACK")
        self.assertEqual(contract["default_when_ambiguous"], "POST_CANDIDATE_EVIDENCE_PACK")
        post_candidate = next(
            line for line in contract["product_lines"] if line["line_id"] == "POST_CANDIDATE_EVIDENCE_PACK"
        )
        self.assertEqual(post_candidate["business_priority"], "PRIMARY")
        self.assertEqual(post_candidate["default_entry_document_kinds"], ["candidate_notice"])
        for document_kind in ("evaluation_result", "opening_record", "award_result"):
            self.assertIn(document_kind, post_candidate["related_non_default_entry_document_kinds"])
        for backtrace_kind in ("tender_file", "clarification_or_addendum", "bid_file_publicity"):
            self.assertIn(backtrace_kind, post_candidate["required_backtrace_document_kinds"])
        self.assertFalse(
            post_candidate["recent_candidate_late_stage_policy"][
                "flow_11_contract_public_info_required_for_current_sales_window"
            ]
        )
        self.assertFalse(
            post_candidate["recent_candidate_late_stage_policy"][
                "flow_12_project_exception_required_for_current_sales_window"
            ]
        )

    def test_pre_bid_prediction_is_secondary_and_does_not_claim_candidate_outputs(self) -> None:
        contract = self._contract()
        pre_bid = next(line for line in contract["product_lines"] if line["line_id"] == "PRE_BID_PREDICTION")

        self.assertEqual(pre_bid["business_priority"], "SECONDARY")
        self.assertEqual(
            pre_bid["default_entry_document_kinds"],
            ["tender_file_publicity", "tender_notice", "clarification_or_addendum"],
        )
        self.assertIn("candidate_verification", pre_bid["must_not_output"])
        self.assertIn("real_competitor_conclusion", pre_bid["must_not_output"])

    def test_analysis_strategy_v1_blocks_pre_bid_after_opening_and_candidate(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]
        blockers = {item["blocker_id"]: item for item in policy["pre_bid_hard_blockers"]}
        routing_states = {item["state"]: item for item in policy["routing_order"]}

        self.assertTrue(policy["required_before_download_or_parse"])
        self.assertIn("PRE_BID_NOT_ELIGIBLE_OPENING_STARTED", blockers)
        self.assertEqual(
            blockers["PRE_BID_NOT_ELIGIBLE_OPENING_STARTED"]["condition"],
            "flow_05_opening_info_present",
        )
        self.assertEqual(
            routing_states["PRE_BID_NOT_ELIGIBLE_OPENING_STARTED"]["product_mode"],
            "POST_OPENING_EVIDENCE_TRACK",
        )
        self.assertEqual(routing_states["POST_CANDIDATE_READY"]["condition"], "flow_07_candidate_notice_present")
        self.assertIn("PRE_BID_NOT_ELIGIBLE_CANDIDATE_PRESENT", blockers)
        self.assertEqual(
            blockers["PRE_BID_NOT_ELIGIBLE_CANDIDATE_PRESENT"]["route_to"],
            "POST_CANDIDATE_EVIDENCE_PACK",
        )

    def test_analysis_strategy_v1_records_recent_source_and_clarification_recalc_policy(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]

        source_window = policy["default_source_time_window_policy"]
        self.assertTrue(source_window["website_default_recent_first"])
        self.assertEqual(source_window["default_recent_window_unit"], "WORKING_HOURS")
        self.assertEqual(source_window["default_recent_working_hours"], 72)
        self.assertEqual(source_window["default_recent_window_state"], "RECENT_72_WORKING_HOURS")
        self.assertTrue(source_window["explicit_time_window_filter_planned"])
        self.assertIn(7, source_window["planned_time_window_options_days"])
        self.assertIn("30 天或更长窗口只用于广州 01-12 流程接口覆盖", source_window["notes"])

        clarification = policy["pre_bid_clarification_recalculation_policy"]
        self.assertEqual(clarification["before_flow_04_state"], "PREDICTION_BEFORE_CLARIFICATION")
        self.assertEqual(clarification["new_flow_04_or_supplement_state"], "PREDICTION_RECALC_REQUIRED")
        self.assertEqual(clarification["after_flow_04_state"], "PREDICTION_AFTER_CLARIFICATION")

    def test_analysis_strategy_v1_does_not_require_11_12_for_recent_candidate_window(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]["post_candidate_late_stage_policy"]
        post_flow_policy = {
            item["flow_no"]: item
            for item in contract["analysis_strategy_policy"]["post_candidate_flow_policy"]
        }

        self.assertEqual(policy["recent_candidate_default_entry_flow_no"], "07")
        self.assertTrue(policy["flow_11_contract_public_info_absent_expected_for_recent_candidate"])
        self.assertTrue(policy["flow_12_project_exception_absent_expected_for_recent_candidate"])
        self.assertFalse(post_flow_policy["11"]["required_for_recent_candidate_sales_window"])
        self.assertFalse(post_flow_policy["12"]["required_for_recent_candidate_sales_window"])

    def test_analysis_strategy_v1_has_failure_repair_gate_taxonomy(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]["failure_repair_gate_policy"]

        self.assertTrue(policy["visible_page_or_attachment_but_fetch_failed_requires_repair_queue"])
        for taxonomy in (
            "code_or_adapter_bug",
            "detail_transport_blocked",
            "attachment_challenge_required",
            "tls_or_waf_or_proxy_issue",
            "login_or_ca_required",
            "platform_sync_delay_or_no_public_endpoint",
        ):
            self.assertIn(taxonomy, policy["must_distinguish_taxonomy"])

    def test_analysis_strategy_v1_uses_realistic_pre_bid_time_windows(self) -> None:
        contract = self._contract()
        windows = {
            item["state"]: item
            for item in contract["analysis_strategy_policy"]["pre_bid_time_window_policy"]
        }

        self.assertEqual(
            windows["PRE_BID_STANDARD_PREDICTION_READY"]["min_hours_to_bid_deadline_or_opening"],
            168,
        )
        self.assertEqual(
            windows["PRE_BID_LIMITED_FAST_REVIEW"]["min_hours_to_bid_deadline_or_opening"],
            72,
        )
        self.assertEqual(
            windows["PRE_BID_LIMITED_FAST_REVIEW"]["max_hours_to_bid_deadline_or_opening_exclusive"],
            168,
        )
        self.assertEqual(
            windows["PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE"]["max_hours_to_bid_deadline_or_opening_exclusive"],
            72,
        )

    def test_analysis_strategy_v1_keeps_adapter_urls_out_of_production_crawl(self) -> None:
        contract = self._contract()
        adapter_policy = contract["analysis_strategy_policy"]["adapter_validation_policy"]

        self.assertTrue(adapter_policy["guangzhou_12_flow_samples_are_adapter_validation_only"])
        self.assertFalse(adapter_policy["human_provided_flow_urls_default_crawl_target_allowed"])
        self.assertFalse(adapter_policy["human_provided_flow_urls_production_crawl_source_allowed"])
        self.assertIn("relationInfo", adapter_policy["production_crawl_must_use"])

    def test_source_policy_keeps_guangzhou_primary_and_deletes_incomplete_province_source(self) -> None:
        contract = self._contract()
        source_policy = contract["source_policy"]
        primary_profile_ids = {
            item["source_profile_id"] for item in source_policy["primary_friendly_sources"]
        }

        self.assertIn("GUANGZHOU-YWTB-CONSTRUCTION-LIST", primary_profile_ids)
        self.assertIn("ZHEJIANG-GGZY-JYXXGK-LIST", primary_profile_ids)
        self.assertIn("SICHUAN-GGZY-TRANSACTION-INFO", primary_profile_ids)
        self.assertNotIn("GUANGDONG-PROVINCE-INCOMPLETE-SUMMARY-SOURCE", primary_profile_ids)

    def test_run_modes_distinguish_pre_bid_smoke_from_available_backtrace(self) -> None:
        contract = self._contract()
        run_modes = {item["run_mode_id"]: item for item in contract["run_modes"]}

        self.assertEqual(run_modes["GUANGZHOU_TENDER_FILE_SMOKE"]["line_id"], "PRE_BID_PREDICTION")
        self.assertEqual(run_modes["GUANGZHOU_TENDER_FILE_SMOKE"]["status"], "AVAILABLE")
        self.assertEqual(run_modes["POST_CANDIDATE_BACKTRACE_V1"]["line_id"], "POST_CANDIDATE_EVIDENCE_PACK")
        self.assertEqual(run_modes["POST_CANDIDATE_BACKTRACE_V1"]["status"], "AVAILABLE")
        self.assertEqual(
            run_modes["POST_CANDIDATE_BACKTRACE_V1"]["script"],
            "scripts/run-guangzhou-post-candidate-backtrace-v1.ps1",
        )

    def test_project_level_audit_fields_are_required_by_contract(self) -> None:
        contract = self._contract()
        fields = set(contract["project_level_audit_required_fields"])

        for field in (
            "project_id",
            "project_name",
            "verification_urls.all_urls",
            "file_inventory",
            "replayable_file_count",
            "parsed_file_count",
            "download_completeness_state",
            "parse_completeness_state",
            "post_candidate_entry_state",
            "backtrace_stage_attempts",
            "matched_project_keys",
            "missing_stage_kinds",
            "backtrace_completeness_state",
            "ready_for_tailored_analysis",
        ):
            self.assertIn(field, fields)


if __name__ == "__main__":
    unittest.main()
