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
                "MOT_HIGHWAY_MARKET_PERSON_TITLE_QUERY",
                "COMPANY_SEARCH_THEN_PERSON_QUERY",
                "PERSON_NAME_ONLY_FILTER_COMPANY",
            ],
        )
        highway_route = next(
            item for item in policy["route_order"] if item["route_id"] == "MOT_HIGHWAY_MARKET_PERSON_TITLE_QUERY"
        )
        self.assertIn("交通运输部全国公路建设市场监督管理查询系统", highway_route["description"])
        self.assertFalse(policy["flow_08_trigger_policy"]["default_parse_flow_08_for_certificate_check"])
        conflict_policy = policy["performance_and_active_conflict_policy"]
        self.assertTrue(conflict_policy["jzsc_lagging_risk_acknowledged"])
        self.assertTrue(conflict_policy["jzsc_not_unique_active_conflict_source"])
        self.assertIn("construction_permit", conflict_policy["active_conflict_priority_sources"])
        self.assertIn(
            "do_not_use_jzsc_as_realtime_active_conflict_single_source",
            conflict_policy["must_not"],
        )
        official_policy = conflict_policy["official_active_conflict_evidence_policy"]
        self.assertEqual(
            official_policy["policy_id"],
            "PROJECT-MANAGER-ACTIVE-CONFLICT-OFFICIAL-EVIDENCE-V1",
        )
        self.assertIn("completion_acceptance_or_completion_filing", official_policy["release_evidence"])
        self.assertIn(
            "non_contractor_suspension_over_120_days_with_construction_unit_consent",
            official_policy["release_evidence"],
        )
        self.assertIn(
            "guangzhou_construction_project_safety_standardization_assessment_result_notice",
            official_policy["release_evidence"],
        )
        self.assertIn(
            "do_not_treat_missing_completion_certificate_as_final_active_conflict",
            official_policy["must_not"],
        )
        self.assertIn(
            "do_not_output_no_active_project_or_no_risk_without_release_chain_readback",
            official_policy["must_not"],
        )
        self.assertIn(
            "GUANGZHOU_PROJECT_RESPONSIBLE_PERSON_MANAGEMENT_NOTICE",
            official_policy["official_basis_refs"],
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
        hardening_policy = evidence_policy["formal_evidence_hardening_policy"]
        self.assertEqual(hardening_policy["policy_id"], "FORMAL-EVIDENCE-HARDENING-V1")
        self.assertIn("source_url", hardening_policy["minimum_required_trace_fields"])
        self.assertIn("capture_time", hardening_policy["minimum_required_trace_fields"])
        self.assertIn("snapshot_or_readback_ref", hardening_policy["minimum_required_trace_fields"])
        self.assertIn("sha256_or_hash", hardening_policy["minimum_required_trace_fields"])
        self.assertIn("redaction_log", hardening_policy["minimum_required_trace_fields"])
        self.assertIn("competing_explanations", hardening_policy["minimum_required_trace_fields"])
        self.assertIn("trusted_timestamp_id", hardening_policy["deferred_enhancement_fields"])
        self.assertEqual(hardening_policy["deferred_enhancement_state"], "RESERVED_NOT_IMPLEMENTED")
        self.assertIn(
            "do_not_claim_trusted_timestamp_or_notarization_before_integration",
            hardening_policy["must_not"],
        )
        delivery_boundary = evidence_policy["customer_delivery_boundary"]
        self.assertIn("facts", delivery_boundary["allowed_output_groups"])
        self.assertIn("risk_clues", delivery_boundary["allowed_output_groups"])
        self.assertIn("competing_explanations", delivery_boundary["allowed_output_groups"])
        self.assertIn("paid_whistleblower_front_role", delivery_boundary["forbidden_business_routes"])
        self.assertIn("paid_silence_or_withdrawal", delivery_boundary["forbidden_business_routes"])
        self.assertIn("internal_leaked_material_use", delivery_boundary["forbidden_business_routes"])
        self.assertIn("ai_one_click_legal_conclusion", delivery_boundary["forbidden_business_routes"])
        self.assertEqual(
            delivery_boundary["commercial_sequence"][0],
            "post_candidate_evidence_pack_or_public_data_review_report",
        )
        self.assertIn("cross_project_relationship_graph", delivery_boundary["midterm_capability_backlog"])
        self.assertIn("bid_file_similarity_engine", delivery_boundary["midterm_capability_backlog"])
        self.assertIn("quote_pattern_anomaly_engine", delivery_boundary["midterm_capability_backlog"])
        self.assertFalse(evidence_policy["customer_visible_allowed"])
        self.assertTrue(evidence_policy["no_legal_conclusion"])
        self.assertIn("是不是本人", evidence_policy["forbidden_terms"])
        self.assertIn("无风险", evidence_policy["forbidden_terms"])
        self.assertIn("无冲突", evidence_policy["forbidden_terms"])

        self.assertEqual(conflict_policy["first_version_execution_mode"], "PLAN_ONLY")
        self.assertIn("construction_permit", conflict_policy["source_categories"])
        objection_policy = conflict_policy["objection_evidence_package_policy"]
        self.assertEqual(
            objection_policy["policy_id"],
            "ACTIVE-CONFLICT-OBJECTION-EVIDENCE-PACKAGE-V1",
        )
        self.assertIn(
            "release_evidence_or_missing_release_source_attempts",
            objection_policy["required_evidence_groups"],
        )
        self.assertIn("项目负责人未释放风险线索", objection_policy["allowed_internal_outputs"])
        self.assertIn("在建冲突成立", objection_policy["forbidden_outputs"])
        self.assertIn("无风险", objection_policy["forbidden_outputs"])
        self.assertFalse(objection_policy["customer_visible_allowed"])
        self.assertTrue(objection_policy["no_legal_conclusion"])
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
        subsources = {sub["subsource_id"]: sub for sub in guangdong_policy["verified_official_city_subsources"]}
        self.assertEqual(
            subsources["gz_zfcj_construction_permit_public_api"]["api_url"],
            "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/jzgdsgxkxxlb.ashx",
        )
        self.assertEqual(
            subsources["gz_zfcj_completion_acceptance_public_api"]["api_url"],
            "https://zfcj.gz.gov.cn/ysqgk/Api/WebApi/gcjgysxxlb.ashx",
        )
        self.assertEqual(
            subsources["gz_zfcj_completion_acceptance_public_api"]["runtime_status"],
            "PUBLIC_POST_JSON_API_VERIFIED",
        )
        self.assertEqual(
            subsources["gz_zfcj_contract_credit_public_portal"]["source_url"],
            "https://113.108.173.251:8080/",
        )
        self.assertIn(
            "do_not_limit_guangdong_verification_to_guangzhou_only",
            guangdong_policy["must_not"],
        )
        guangdong_field_policy = conflict_policy["guangdong_local_field_query_probe_v1_policy"]
        self.assertEqual(
            guangdong_field_policy["default_execution_mode"],
            "PLAN_ONLY_NOT_EXECUTED",
        )
        self.assertEqual(
            guangdong_field_policy["optional_execution_mode"],
            "LIVE_PUBLIC_FIELD_QUERY_ATTEMPTED",
        )
        self.assertEqual(
            guangdong_field_policy["input_manifest"],
            "guangdong_local_verification_probe_v1_manifest",
        )
        self.assertIn("guangdong_gdcic_query_probe_v1", guangdong_field_policy["delegated_field_adapters"])
        self.assertIn(
            "guangzhou_zfcj_xyxx_api_query_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangzhou_zfcj_construction_permit_public_api_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangzhou_zfcj_completion_acceptance_public_api_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangdong_credit_gd_public_credit_query_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangdong_gdcic_contract_performance_public_page_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangdong_tzxm_project_approval_publicity_api_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangdong_zfcxjst_penalty_publicity_page_v1",
            guangdong_field_policy["source_specific_field_adapters"],
        )
        self.assertIn(
            "guangzhou_zfcj_xyxx_api_query_for_city_double_publicity",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangzhou_zfcj_construction_permit_public_api_probe",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangzhou_zfcj_completion_acceptance_public_api_probe",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_gdcic_contract_performance_public_page_probe",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_public_credit_query_probe",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_session_readback_v1_browser_prewarm_and_api_prefix_discovery",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_public_list_readback_first_when_targeted_query_forbidden",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_session_refresh_retry_public_list_once_on_site_guard",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_playwright_rendered_public_list_text_fallback_after_api_block",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_targeted_query_deferred_preserves_manual_captcha_rerun_entry",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_targeted_query_403_is_review_not_source_unavailable",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_request_throttle_and_per_task_cap",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_credit_gd_site_guard_or_rate_limit_deferred_review",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_tzxm_project_approval_publicity_api_probe",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "guangdong_zfcxjst_penalty_publicity_list_and_detail_probe",
            guangdong_field_policy["query_route_policy"],
        )
        self.assertIn(
            "do_not_treat_query_miss_as_no_risk",
            guangdong_field_policy["must_not"],
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

    def test_next_phase_execution_plan_locks_current_focus_and_order(self) -> None:
        contract = self._contract()
        plan = contract["next_phase_execution_plan"]
        phases = [phase["phase_id"] for phase in plan["phases"]]

        self.assertEqual(plan["current_focus"], "P13B_EXTERNAL_AWARD_OVERLAP_TRIAGE_V1")
        self.assertEqual(
            phases,
            [
                "P1_GUANGZHOU_EVIDENCE_REPORT_CLOSEOUT_V1",
                "P2_GUANGDONG_OFFICIAL_SOURCE_READBACK_V1",
                "P3_GUANGZHOU_20_PROJECT_STABILITY_V1",
                "P4_ZHEJIANG_REGION_ADAPTER_V1",
                "P5_GDCIC_FIELD_QUALITY_V1",
                "P6_CERTIFICATE_SUPPLEMENT_CLOSEOUT_V1",
                "P7_INTERNAL_EVIDENCE_PACKAGE_MANIFEST_V1",
                "P8_EVIDENCE_FIXATION_BACKFILL_V1",
                "P9_EVIDENCE_FIXATION_RECAPTURE_V1",
                "P10_P9_AWARE_READABLE_CLOSEOUT_V1",
                "P11_GUANGZHOU_10_PROJECT_STABILITY_V1",
                "P12_GUANGZHOU_10_PROJECT_VALUE_CLOSEOUT_V1",
                "P13B_EXTERNAL_AWARD_OVERLAP_TRIAGE_V1",
            ],
        )
        p1 = plan["phases"][0]
        self.assertIn("ParseProbe missing 不再阻断未触发 08 的项目", p1["success_criteria"])
        self.assertIn("12 个候选组均有负责人公开注册信息匹配结果", p1["success_criteria"])
        self.assertIn("do_not_expand_to_20_or_50_before_p11_batch_stability_closeout", plan["must_not"])
        self.assertIn("do_not_expand_to_20_or_50_before_p12_value_closeout", plan["must_not"])
        self.assertIn("do_not_expand_to_20_or_50_before_p13b_overlap_triage", plan["must_not"])
        self.assertIn("do_not_start_with_full_province_construction_permit_sweep", plan["must_not"])
        self.assertIn("do_not_default_parse_flow_08_without_trigger", plan["must_not"])
        self.assertIn("do_not_treat_plan_only_region_sources_as_live_verified", plan["must_not"])
        phase_by_id = {phase["phase_id"]: phase for phase in plan["phases"]}
        p9 = phase_by_id["P9_EVIDENCE_FIXATION_RECAPTURE_V1"]
        self.assertEqual(p9["phase_id"], "P9_EVIDENCE_FIXATION_RECAPTURE_V1")
        self.assertIn(
            "Stage4/JZSC readback 只生成字段摘要 hash 和 route attempts，不改变核验结论",
            p9["success_criteria"],
        )
        self.assertIn("P8 消费 RecaptureRoot 后 backfilled_no_remaining_gap_count 高于 32，剩余缺口有 route taxonomy", p9["success_criteria"])
        p10 = phase_by_id["P10_P9_AWARE_READABLE_CLOSEOUT_V1"]
        self.assertEqual(p10["phase_id"], "P10_P9_AWARE_READABLE_CLOSEOUT_V1")
        self.assertIn("P10 完成后才进入广州 10 项目稳定性验证", p10["success_criteria"])
        p11 = phase_by_id["P11_GUANGZHOU_10_PROJECT_STABILITY_V1"]
        self.assertEqual(p11["phase_id"], "P11_GUANGZHOU_10_PROJECT_STABILITY_V1")
        self.assertIn("P11 EvidenceReport 使用 NoDefaultOptionalRoots 隔离旧 5 项目 GDCIC/local/active conflict 产物", p11["success_criteria"])
        self.assertIn("08 未触发时不作为 blocker，且不默认深解析 08", p11["success_criteria"])
        p12 = phase_by_id["P12_GUANGZHOU_10_PROJECT_VALUE_CLOSEOUT_V1"]
        self.assertEqual(p12["phase_id"], "P12_GUANGZHOU_10_PROJECT_VALUE_CLOSEOUT_V1")
        self.assertIn(
            "身份/证书已通但缺施工许可、合同备案、竣工验收、项目经理变更、处罚投诉等外部源时输出 EXTERNAL_CONFLICT_SOURCE_REQUIRED",
            p12["success_criteria"],
        )
        self.assertIn("报告保持 customer_delivery_ready=false，不输出客户可见法律定性", p12["success_criteria"])
        p13b = phase_by_id["P13B_EXTERNAL_AWARD_OVERLAP_TRIAGE_V1"]
        self.assertIn("8 个 EXTERNAL_CONFLICT_SOURCE_REQUIRED 项目均生成 data.ggzy 公司历史成交宽筛任务", p13b["success_criteria"])
        self.assertIn("每个公司历史成交记录保留 uniscid、bid_list 记录、bid_show 正文摘要和原文链接", p13b["success_criteria"])
        self.assertIn("只有命中重叠线索的项目才生成施工许可、合同备案、竣工验收、项目经理变更等释放证据补查任务", p13b["success_criteria"])
        self.assertIn("未命中、接口阻断、bid_show 缺负责人或地区 adapter 未完成不写排除结论", p13b["success_criteria"])

    def test_p13b_external_award_overlap_triage_policy(self) -> None:
        contract = self._contract()
        policy = contract["analysis_strategy_policy"]["active_conflict_external_source_policy"][
            "external_award_overlap_triage_v1_policy"
        ]

        self.assertEqual(policy["current_phase_id"], "P13B_EXTERNAL_AWARD_OVERLAP_TRIAGE_V1")
        self.assertEqual(policy["external_conflict_first_pass"], "PRIOR_AWARD_AND_CANDIDATE_OVERLAP_TRIAGE")
        self.assertEqual(policy["release_evidence_probe_trigger"], "ONLY_AFTER_TIME_WINDOW_OVERLAP_SIGNAL")
        self.assertTrue(policy["do_not_start_with_full_province_construction_permit_sweep"])
        self.assertTrue(policy["query_miss_is_not_clearance"])
        self.assertFalse(policy["flow_08_default_parse_required"])
        self.assertEqual(policy["primary_company_history_source_profile_id"], "NATIONAL-GGZY-DATA-SERVICE-COMPANY-AWARD-HISTORY")
        self.assertEqual(policy["primary_company_history_source_url"], "https://data.ggzy.gov.cn/")
        self.assertIn("data.ggzy.yjcx.index.search_by_company_name_or_unified_social_credit_code", policy["primary_company_history_query_flow"])
        self.assertIn("data.ggzy.yjcx.index.bid_show_by_record_id_for_notice_content_and_original_url", policy["primary_company_history_query_flow"])
        self.assertIn("data_ggzy_company_award_history_search_by_company_name_or_uniscid", policy["first_pass_sources"])
        self.assertIn("data_ggzy_bid_show_notice_content_and_original_url", policy["first_pass_sources"])
        self.assertIn("ORIGINAL_NOTICE_BACKTRACE_REQUIRED", policy["first_pass_output_states"])
        self.assertIn("construction_permit", policy["release_evidence_sources_after_overlap"])
        self.assertIn("do_not_treat_prior_award_or_candidate_record_as_final_unreleased_proof", policy["must_not"])
        self.assertIn("do_not_treat_no_prior_award_match_as_no_risk", policy["must_not"])
        self.assertIn("do_not_use_legacy_dealList_find_as_p13b_primary_company_history_source", policy["must_not"])
        self.assertEqual(policy["company_history_smoke_findings"]["input_company_count"], 25)
        self.assertEqual(policy["company_history_smoke_findings"]["company_search_hit_count"], 23)
        self.assertEqual(policy["company_history_smoke_findings"]["bid_list_hit_count"], 23)
        facts = policy["current_verified_run_facts"]
        self.assertEqual(facts["p13a_fixed_project_id"], "JG2026-11215")
        self.assertEqual(facts["p12_project_count"], 10)
        self.assertEqual(facts["p12_candidate_group_count"], 26)
        self.assertEqual(facts["p12_process_blocked_project_count"], 0)
        self.assertEqual(facts["p12_flow_08_targeted_parse_required_count"], 0)
        self.assertEqual(facts["p12_external_conflict_source_required_project_count"], 8)
        self.assertEqual(facts["p12_low_value_or_not_applicable_project_count"], 2)


if __name__ == "__main__":
    unittest.main()
