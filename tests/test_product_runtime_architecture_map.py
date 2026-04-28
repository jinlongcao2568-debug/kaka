from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read_text(relative_path))


class ProductRuntimeArchitectureMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.architecture = read_yaml("control/product_runtime_architecture_map.yaml")
        self.task_library = read_yaml("control/product_task_library.yaml")
        self.checklist = read_yaml("control/product_acceptance_checklist.yaml")
        self.route_map_text = read_text("docs/AX9S_开发执行路由图.md")
        self.scheme_text = read_text("docs/AX9S_自动运营决策架构与商业钩子方案.md")

    def test_architecture_map_declares_autonomous_operating_loop_not_manual_url_picker(self) -> None:
        self.assertEqual(
            self.architecture["packet_ref"],
            "PTL-I100-143D-business-decision-architecture-and-hook-lead-roadmap-sync",
        )
        self.assertIn("manual_url_picker_as_primary_flow", self.architecture["business_goal"]["must_not_be"])
        steps = {step["step_id"]: step for step in self.architecture["primary_operating_loop"]}
        for required in (
            "market_scan_batch",
            "source_blueprint_orchestration",
            "public_capture_and_snapshot",
            "parser_candidate_extraction",
            "public_verification_strategy",
            "evidence_risk_and_rule_hit",
            "productization_and_hook_lead",
            "buyer_fit_and_offer",
            "governed_outreach",
            "order_payment_delivery_governance",
            "operator_workbench_and_customer_portal",
        ):
            self.assertIn(required, steps)
            self.assertTrue(steps[required]["autonomous_decision"])

        self.assertEqual(steps["productization_and_hook_lead"]["owner_stage"], "stage6_fact_review")
        self.assertEqual(steps["buyer_fit_and_offer"]["owner_stage"], "stage7_sales")

    def test_rules_compute_and_llm_boundaries_are_explicit(self) -> None:
        llm = self.architecture["llm_governance"]
        self.assertIn("stage3_field_candidate_extraction_assist", llm["allowed_roles"])
        self.assertIn("sales_hook_copy_draft", llm["allowed_roles"])
        for forbidden in (
            "fact_adjudication",
            "public_verification_decision",
            "legal_conclusion",
            "customer_visible_unreviewed_claim",
            "automatic_outreach_send",
            "automatic_refund",
        ):
            self.assertIn(forbidden, llm["forbidden_roles"])

        methods = {step["step_id"]: step["method"] for step in self.architecture["primary_operating_loop"]}
        self.assertEqual(methods["public_verification_strategy"], "rules")
        self.assertIn("llm_summary_assist", methods["productization_and_hook_lead"])
        self.assertIn("compute_plus_rules", methods["buyer_fit_and_offer"])

    def test_stage_1_to_9_improvement_assessment_is_explicit(self) -> None:
        assessment = self.architecture["stage_1_to_9_improvement_assessment"]
        self.assertEqual(
            assessment["conclusion"],
            "ALL_STAGES_HAVE_PRODUCTIZATION_OPTIMIZATION_SPACE",
        )
        stages = assessment["stages"]
        expected_stages = [
            "stage1_tasking",
            "stage2_ingestion",
            "stage3_parsing",
            "stage4_verification",
            "stage5_rules_evidence",
            "stage6_fact_review",
            "stage7_sales",
            "stage8_outreach",
            "stage9_delivery",
        ]
        self.assertEqual(list(stages), expected_stages)
        for stage_id, stage in stages.items():
            self.assertTrue(stage["optimization_spaces"], stage_id)
            self.assertTrue(stage["autonomous_decisions_to_add"], stage_id)
            self.assertTrue(stage["decision_method"], stage_id)
            self.assertTrue(stage["next_packet_refs"], stage_id)
            self.assertTrue(stage["acceptance_focus"], stage_id)

        self.assertIn("source_blueprint_batch_selection", stages["stage1_tasking"]["autonomous_decisions_to_add"])
        self.assertIn("commercial_hook_eligibility", stages["stage6_fact_review"]["autonomous_decisions_to_add"])
        self.assertIn("withheld_fields", stages["stage6_fact_review"]["autonomous_decisions_to_add"])
        self.assertIn("allowed_talking_points", stages["stage7_sales"]["autonomous_decisions_to_add"])
        self.assertEqual(stages["stage4_verification"]["llm_role"], "none_for_verification_decision")
        self.assertEqual(stages["stage9_delivery"]["llm_role"], "none")

    def test_autonomous_execution_brain_contract_records_existing_parts_and_missing_controller(self) -> None:
        brain = self.architecture["autonomous_execution_brain_contract"]
        self.assertEqual(brain["contract_id"], "AUTONOMOUS_RUN_CONTROLLER_V1")
        self.assertIn("does not yet have a product-grade", brain["current_assessment"])
        parts = {part["component"]: part for part in brain["existing_parts"]}
        self.assertIn("stage1_scheduler", parts)
        self.assertIn("durable_worker_queue", parts)
        self.assertIn("stage1_to_stage6_internal_orchestration", parts)
        self.assertIn("operator_action_and_workbench", parts)
        self.assertEqual(parts["stage1_scheduler"]["current_limit"], "stage1_scheduler_enabled_is_false_in_bootstrap")

        components = {component["component_id"]: component for component in brain["required_brain_components"]}
        for component_id in (
            "run_controller",
            "stage_state_machine",
            "decision_planner",
            "work_queue_dispatcher",
            "transition_guard",
            "operator_intervention_gate",
            "audit_replay_ledger",
        ):
            self.assertIn(component_id, components)
            self.assertTrue(components[component_id]["pushes_next_step_by"])

        self.assertEqual(
            brain["first_implementation_packet"],
            "PTL-I100-144-market-scan-opportunity-discovery-engine",
        )
        self.assertIn("stage2_capture_executor", {step["executor"] for step in brain["stage_progression_model"]})
        self.assertIn("codex_or_human_manually_selecting_each_url", brain["must_not_depend_on"])

    def test_elevated_remaining_product_readiness_gap_assessment_records_next_risks(self) -> None:
        assessment = self.architecture["remaining_product_readiness_gap_assessment"]
        self.assertEqual(assessment["assessment_id"], "PRODUCT_DELIVERY_GAP_ELEVATED_REVIEW_V1")
        dimensions = assessment["dimensions"]
        for dimension_id in (
            "autonomous_execution_brain",
            "market_and_source_strategy",
            "evidence_quality_and_parser_verification",
            "business_value_and_hook_conversion",
            "owner_operability_and_ui",
            "external_execution_and_customer_delivery",
            "real_world_sample_acceptance",
        ):
            self.assertIn(dimension_id, dimensions)
            self.assertTrue(dimensions[dimension_id]["risk_if_ignored"], dimension_id)
            self.assertTrue(dimensions[dimension_id]["required_upgrade"], dimension_id)
            self.assertTrue(dimensions[dimension_id]["primary_packets"], dimension_id)
            self.assertTrue(dimensions[dimension_id]["acceptance_question"], dimension_id)

        checks = set(assessment["non_negotiable_checks"])
        self.assertIn("no_codex_required_for_next_step_decision", checks)
        self.assertIn("no_presale_full_evidence_leak", checks)
        self.assertIn("automated_refund_execution_excluded", checks)

    def test_source_strategy_pilot_policy_excludes_beijing_commercial_pilot(self) -> None:
        policy = self.architecture["source_strategy_pilot_policy"]
        self.assertEqual(policy["packet_ref"], "PTL-I100-145-source-blueprint-orchestration-and-capture-plan")
        self.assertEqual(policy["conclusion"], "NATIONAL_AGGREGATOR_IS_NECESSARY_BUT_NOT_SUFFICIENT")
        self.assertIn("first_level_discovery", policy["national_aggregator_role"])
        self.assertIn("full_coverage", policy["national_aggregator_not_assumed"])
        self.assertIn("realtime_sync", policy["national_aggregator_not_assumed"])
        self.assertEqual(
            policy["beijing_policy"]["status"],
            "EXCLUDED_FROM_FIRST_COMMERCIAL_PILOT",
        )
        self.assertEqual(
            policy["beijing_policy"]["allowed_use"],
            "technical_regression_and_public_page_reachability_only",
        )
        provinces = {row["province"] for row in policy["first_batch_commercial_pilot_provinces"]}
        self.assertEqual(provinces, {"四川", "江苏", "浙江", "山东", "广东", "湖北"})
        self.assertIn("province_platform_missing_detail_or_attachment", policy["city_adapter_trigger_policy"])
        self.assertIn("blanket_all_city_adapter_rollout_before_pilot_evidence", policy["excluded_rollout_patterns"])

    def test_commercial_hook_lead_contract_prevents_presale_evidence_leakage(self) -> None:
        hook = self.architecture["commercial_hook_lead_contract"]
        self.assertEqual(hook["contract_id"], "COMMERCIAL_HOOK_LEAD_V1")
        self.assertEqual(hook["role"], "sales_teaser_without_full_evidence_leakage")
        for field in (
            "hook_lead_id",
            "source_product_package_id",
            "defect_category_public_label",
            "evidence_strength_label",
            "teaser_copy",
            "withheld_fields",
            "disclosure_level",
            "allowed_sales_talking_points",
            "forbidden_sales_claims",
            "leakage_risk",
        ):
            self.assertIn(field, hook["required_fields"])

        l1 = hook["disclosure_levels"]["L1_HOOK"]
        self.assertIn("defect_category_public_label", l1["allowed"])
        self.assertIn("source_url", l1["withheld"])
        self.assertIn("complete_verification_path", l1["withheld"])
        self.assertIn("raw_snapshot_or_attachment", l1["withheld"])
        self.assertIn(
            "concrete_source_url_that_reveals_full_evidence_path",
            hook["forbidden_pre_sale_disclosures"],
        )
        self.assertIn("leakage_risk_is_classified", hook["must_prove_before_sales_touch"])

    def test_143d_and_144_to_149_are_registered_in_task_pool_and_checklist(self) -> None:
        task_ids = {task["task_id"]: task for task in self.task_library["tasks"]}
        expected = [
            "PTL-I100-143D-business-decision-architecture-and-hook-lead-roadmap-sync",
            "PTL-I100-143E-autonomous-source-strategy-d-doc-sync",
            "PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync",
            "PTL-I100-143G-public-web-capture-doc-sync-and-order-review",
            "PTL-I100-144-market-scan-opportunity-discovery-engine",
            "PTL-I100-145-source-blueprint-orchestration-and-capture-plan",
            "PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation",
            "PTL-I100-151-public-web-captcha-suspend-and-operator-resume",
            "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy",
            "PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine",
            "PTL-I100-148-productized-autonomous-operator-workbench",
            "PTL-I100-149-real-sample-autonomous-opportunity-acceptance",
        ]
        for task_id in expected:
            self.assertIn(task_id, task_ids)
            self.assertIn(task_id, self.checklist["tasks"])

        self.assertEqual(task_ids[expected[0]]["status"], "COMPLETED")
        self.assertEqual(task_ids[expected[1]]["status"], "COMPLETED")
        self.assertEqual(task_ids[expected[2]]["status"], "COMPLETED")
        self.assertEqual(task_ids[expected[3]]["status"], "ACTIVE")
        for task_id in expected[4:]:
            self.assertEqual(task_ids[task_id]["status"], "PLANNED")
        self.assertEqual(
            self.task_library["current_mainline_next_candidate"]["task_id"],
            expected[3],
        )

        sequence = [item["packet_ref"] for item in self.architecture["implementation_sequence"]]
        self.assertEqual(sequence, expected)

    def test_route_map_and_human_scheme_record_the_same_business_direction(self) -> None:
        for phrase in (
            "系统每天自动找工程项目里的可售硬伤",
            "商业钩子线索",
            "Stage1-9 逐阶段优化评估",
            "系统执行大脑",
            "高维剩余缺口评估",
            "卖前给价值感，不给可复现路径",
            "全国聚合平台只作为一级发现",
            "北京不进入首批商业线索试点",
            "PTL-I100-143E-autonomous-source-strategy-d-doc-sync",
            "PTL-I100-143G-public-web-capture-doc-sync-and-order-review",
            "公开网抓取失败优先自动升级",
            "验证码检测挂起",
            "144 -> 145 -> 150 -> 151 -> 146 -> 147 -> 148 -> 149",
            "PTL-I100-144-market-scan-opportunity-discovery-engine",
            "PTL-I100-149-real-sample-autonomous-opportunity-acceptance",
        ):
            self.assertIn(phrase, self.route_map_text + self.scheme_text)

    def test_redlines_stay_closed(self) -> None:
        redlines = self.architecture["redlines_preserved"]
        self.assertEqual(redlines["external_software_release"], "BLOCKED")
        self.assertEqual(redlines["arbitrary_crawler"], "BLOCKED")
        self.assertEqual(redlines["login_captcha_antibot_bypass"], "BLOCKED")
        self.assertEqual(redlines["unapproved_provider_call"], "BLOCKED")
        self.assertEqual(redlines["automated_refund_execution"], "EXCLUDED")


if __name__ == "__main__":
    unittest.main()
