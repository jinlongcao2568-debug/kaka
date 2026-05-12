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

    def test_flow_08_is_register_only_by_default(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]["flow_08_registry_only_policy"]
        post_flow_policy = {
            item["flow_no"]: item
            for item in contract["analysis_strategy_policy"]["post_candidate_flow_policy"]
        }

        self.assertEqual(policy["policy_id"], "FLOW-08-REGISTRY-ONLY-BY-DEFAULT-V1")
        self.assertEqual(policy["default_download_policy"], "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED")
        self.assertEqual(policy["default_parse_depth"], "LIST_ONLY")
        self.assertFalse(policy["default_download_required"])
        self.assertFalse(policy["default_parse_required"])
        self.assertIn("attachment_names", policy["must_record_fields"])
        self.assertIn("do_not_parse_all_flow_08_by_default", policy["must_not"])
        self.assertEqual(
            post_flow_policy["08"]["download_policy"],
            "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED",
        )
        self.assertEqual(post_flow_policy["08"]["parse_depth"], "LIST_ONLY")
        self.assertFalse(post_flow_policy["08"]["default_parse_required"])

    def test_responsible_person_early_probe_policy_prioritizes_07_then_company_first_then_08(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]["responsible_person_early_probe_policy"]

        self.assertEqual(policy["policy_id"], "RESPONSIBLE-PERSON-EARLY-PROBE-V1")
        self.assertTrue(policy["required_before_stage4_live_verification"])
        self.assertEqual(policy["applies_to_product_mode"], "POST_CANDIDATE_EVIDENCE_PACK")
        group_policy = policy["candidate_group_binding_policy"]
        self.assertTrue(group_policy["must_bind_by_candidate_row"])
        self.assertEqual(
            group_policy["group_resolution_rule"],
            "ANY_CONSORTIUM_MEMBER_MATCH_RESOLVES_THE_CANDIDATE_GROUP",
        )
        self.assertIn("candidate_group_members", group_policy["candidate_group_fields"])
        self.assertIn(
            "do_not_cross_match_company_person_certificate_between_candidate_rows",
            group_policy["must_not"],
        )
        self.assertIn("do_not_only_verify_consortium_lead_company", group_policy["must_not"])

        evidence_order = {item["order"]: item for item in policy["preferred_evidence_order"]}
        self.assertEqual(evidence_order[1]["flow_no"], "07")
        self.assertEqual(evidence_order[1]["source"], "candidate_notice_detail_html")
        self.assertEqual(evidence_order[2]["source"], "candidate_notice_small_pdf_or_evaluation_report_pdf")
        self.assertEqual(evidence_order[3]["action"], "OCR_ONLY_WHEN_MARKITDOWN_TEXT_EMPTY_AND_TARGET_FIELDS_MISSING")
        self.assertEqual(evidence_order[4]["flow_no"], "08")
        self.assertEqual(evidence_order[4]["action"], "TARGETED_PARSE_ONLY")
        self.assertIn("证书", evidence_order[4]["preferred_file_name_keywords"])

        decision_states = {item["state"]: item for item in policy["stage4_supplement_decision_tree"]}
        self.assertEqual(
            decision_states["CERTIFICATE_READY_FROM_07"]["next_action"],
            "STAGE4_VERIFY_CERTIFICATE_AND_REGISTERED_UNIT",
        )
        self.assertEqual(
            decision_states["COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED"]["next_action"],
            "QUERY_CANDIDATE_COMPANY_PERSONNEL_LIST_THEN_WRITE_BACK_CERTIFICATE_NO",
        )
        self.assertEqual(
            decision_states["NAME_ENUMERATION_FALLBACK_REQUIRED"]["next_action"],
            "ENUMERATE_PUBLIC_PERSONS_BY_NAME_UNTIL_REGISTERED_UNIT_MATCHES_CANDIDATE_COMPANY_OR_JOINT_VENTURE_MEMBER",
        )
        self.assertEqual(
            decision_states["FLOW_08_TARGETED_PARSE_REQUIRED"]["next_action"],
            "ESCALATE_RISK_AND_PARSE_FLOW_08_TARGET_FILES_FOR_CERTIFICATE_NO",
        )
        self.assertEqual(
            decision_states["STRONG_CONFLICT_CLUE_AFTER_08"]["next_action"],
            "RAISE_PERSON_COMPANY_MISMATCH_RISK_AND_SEND_TO_STAGE5_EVIDENCE_GATE",
        )

        self.assertIn(
            "do_not_deep_parse_all_flow_08_by_default",
            policy["must_not"],
        )
        self.assertIn(
            "do_not_treat_company_first_no_match_as_final_conflict_without_flow_08_or_stage4_readback",
            policy["must_not"],
        )

    def test_responsible_person_early_probe_policy_raises_risk_without_legal_conclusion(self) -> None:
        contract = self._contract()
        risk_policy = contract["analysis_strategy_policy"]["responsible_person_early_probe_policy"][
            "risk_escalation_policy"
        ]

        self.assertEqual(risk_policy["company_first_no_match_risk"], "HIGH_CLUE_REVIEW")
        self.assertEqual(risk_policy["flow_08_certificate_registered_unit_mismatch_risk"], "STRONG_CLUE_REVIEW")
        self.assertTrue(risk_policy["must_not_treat_as_final_legal_conclusion"])
        self.assertIn("项目负责人注册单位不一致线索", risk_policy["allowed_internal_phrases"])
        self.assertIn("冲突成立", risk_policy["forbidden_phrases"])

    def test_public_registration_match_policy_forbids_person_identity_claim_and_limits_jzsc_active_conflict(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]["public_registration_match_and_conflict_probe_policy"]

        self.assertEqual(policy["policy_id"], "PUBLIC-REGISTRATION-MATCH-AND-CONFLICT-PROBE-V1")
        self.assertIn("公开注册信息匹配", policy["language_boundary"]["allowed_terms"])
        self.assertIn("是不是本人", policy["language_boundary"]["forbidden_terms"])
        self.assertTrue(
            policy["match_acceptance_policy"][
                "do_not_require_flow_08_when_flow_07_public_registration_match_succeeds"
            ]
        )
        routes = [item["route_id"] for item in policy["route_order"]]
        self.assertEqual(
            routes,
            [
                "PERSON_NAME_WITH_COMPANY_QUERY",
                "COMPANY_SEARCH_THEN_PERSON_QUERY",
                "PERSON_NAME_ONLY_FILTER_COMPANY",
            ],
        )
        self.assertFalse(policy["flow_08_trigger_policy"]["default_parse_flow_08_for_certificate_check"])
        conflict_policy = policy["performance_and_active_conflict_policy"]
        self.assertTrue(conflict_policy["jzsc_lagging_risk_acknowledged"])
        self.assertTrue(conflict_policy["jzsc_not_unique_active_conflict_source"])
        self.assertIn("construction_permit", conflict_policy["active_conflict_priority_sources"])
        self.assertIn(
            "do_not_use_jzsc_as_realtime_active_conflict_single_source",
            conflict_policy["must_not"],
        )

    def test_evidence_report_and_active_conflict_policy_are_internal_only(self) -> None:
        contract = self._contract()
        evidence_policy = contract["analysis_strategy_policy"]["evidence_report_v1_policy"]
        conflict_policy = contract["analysis_strategy_policy"]["active_conflict_external_source_policy"]

        self.assertEqual(evidence_policy["policy_id"], "GUANGZHOU-EVIDENCE-REPORT-V1")
        self.assertEqual(
            evidence_policy["report_sections"],
            ["verification_evidence", "process_stability", "optimization_recommendations"],
        )
        self.assertEqual(evidence_policy["flow_08_default_handling"], "REGISTER_ONLY_NO_DEFAULT_PARSE")
        self.assertFalse(evidence_policy["customer_visible_allowed"])
        self.assertTrue(evidence_policy["no_legal_conclusion"])
        self.assertIn("是不是本人", evidence_policy["forbidden_terms"])

        self.assertEqual(conflict_policy["first_version_execution_mode"], "PLAN_ONLY")
        self.assertIn("construction_permit", conflict_policy["source_categories"])
        major_region_policy = conflict_policy["major_target_region_source_catalog_policy"]
        self.assertEqual(
            major_region_policy["scope_mode"],
            "NATIONAL_DISCOVERY_THEN_MAJOR_REGION_TARGETED_VERIFICATION",
        )
        self.assertFalse(major_region_policy["all_region_bruteforce_required"])
        self.assertEqual(
            major_region_policy["default_execution_state"],
            "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED",
        )
        for region_code in ("CN-ZJ", "CN-SC", "CN-JS", "CN-HB", "CN-SD", "CN-HN", "CN-HA"):
            self.assertIn(region_code, major_region_policy["target_region_codes"])
        self.assertIn(
            "do_not_treat_plan_only_source_as_live_verified",
            major_region_policy["must_not"],
        )
        query_probe_policy = conflict_policy["major_region_query_probe_v1_policy"]
        self.assertEqual(query_probe_policy["default_execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
        self.assertEqual(query_probe_policy["optional_execution_mode"], "LIVE_REACHABILITY_ATTEMPTED")
        self.assertIn("CN-ZJ", query_probe_policy["default_region_codes"])
        self.assertIn("CN-SD", query_probe_policy["default_region_codes"])
        self.assertIn(
            "do_not_treat_reachability_as_field_verification",
            query_probe_policy["must_not"],
        )
        guangdong_policy = conflict_policy["guangdong_local_verification_probe_v1_policy"]
        self.assertEqual(guangdong_policy["default_execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
        self.assertEqual(guangdong_policy["optional_execution_mode"], "LIVE_REACHABILITY_ATTEMPTED")
        self.assertIn("GUANGDONG-GDCIC-SKYPT-OPENPLATFORM", guangdong_policy["source_profile_ids"])
        self.assertIn("GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY", guangdong_policy["source_profile_ids"])
        self.assertEqual(
            guangdong_policy["source_scope_policy"],
            "GUANGDONG_PROVINCE_FIRST_WITH_CURRENT_CITY_SUPPLEMENT_FOR_GUANGZHOU",
        )
        self.assertIn("guangdong_gdcic_query_probe_v1", guangdong_policy["implemented_separate_field_adapters"])
        self.assertIn(
            "do_not_limit_guangdong_verification_to_guangzhou_only",
            guangdong_policy["must_not"],
        )
        self.assertIn(
            "do_not_output_final_active_conflict_conclusion_without_replayable_sources",
            conflict_policy["must_not"],
        )

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
