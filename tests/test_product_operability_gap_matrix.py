from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


class ProductOperabilityGapMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = read_yaml("control/product_doc_runtime_coverage_ledger.yaml")
        self.matrix = read_yaml("control/product_operability_gap_matrix.yaml")
        self.task_library = read_yaml("control/product_task_library.yaml")

    def test_matrix_covers_every_product_doc_capability_once(self) -> None:
        ledger_ids = {row["capability_id"] for row in self.ledger["capabilities"]}
        matrix_ids = [row["capability_id"] for row in self.matrix["capability_assessments"]]

        self.assertEqual(len(matrix_ids), len(set(matrix_ids)))
        self.assertEqual(set(matrix_ids), ledger_ids)
        self.assertEqual(self.matrix["source_ledger"], "control/product_doc_runtime_coverage_ledger.yaml")

    def test_rollup_counts_match_assessment_rows(self) -> None:
        counts = Counter(row["operability_state"] for row in self.matrix["capability_assessments"])
        rollup = self.matrix["rollup_counts"]

        for state in self.matrix["operability_state_vocabulary"]:
            self.assertEqual(rollup[state], counts[state], state)
        self.assertEqual(rollup["TOTAL_CAPABILITIES"], len(self.matrix["capability_assessments"]))

    def test_next_packet_refs_are_registered_or_explicit_none(self) -> None:
        task_ids = {row["task_id"] for row in self.task_library["tasks"]}
        suggested_packet_refs = {
            packet_ref
            for row in self.task_library["tasks"]
            for packet_ref in row.get("suggested_packet_refs", [])
        }
        registered_refs = task_ids | suggested_packet_refs
        none_refs = {"NONE_CURRENTLY_REQUIRED", "NONE_PRODUCT_GOAL"}

        for row in self.matrix["capability_assessments"]:
            next_packet_ref = row["next_packet_ref"]
            if next_packet_ref in none_refs:
                continue
            self.assertIn(next_packet_ref, registered_refs, row["capability_id"])

    def test_missing_runtime_rows_are_product_implementation_gaps(self) -> None:
        ledger_by_id = {row["capability_id"]: row for row in self.ledger["capabilities"]}
        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}

        missing_runtime_ids = {
            capability_id
            for capability_id, row in ledger_by_id.items()
            if "MISSING_RUNTIME" in row["classification"]
        }

        self.assertEqual(missing_runtime_ids, {"POSTGRES_REDIS_OBJECT_STORAGE_DOCKER_BACKENDS"})
        for capability_id in missing_runtime_ids:
            row = matrix_by_id[capability_id]
            self.assertEqual(row["operability_state"], "NEEDS_PRODUCT_IMPLEMENTATION")
            self.assertEqual(row["next_packet_ref"], "PTL-I100-112-production-platform-infrastructure")

    def test_external_or_live_readiness_is_not_misclassified_as_operable(self) -> None:
        ledger_by_id = {row["capability_id"]: row for row in self.ledger["capabilities"]}

        for row in self.matrix["capability_assessments"]:
            ledger_row = ledger_by_id[row["capability_id"]]
            if ledger_row["external_or_live_capability"]:
                self.assertNotEqual(row["operability_state"], "OPERABLE_NOW_INTERNAL", row["capability_id"])
                self.assertFalse(row["ready_for_live_execution"], row["capability_id"])

    def test_sales_touch_delivery_and_payment_gaps_have_implementation_packets(self) -> None:
        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}

        expected_packets = {
            "STAGE8_REAL_OUTREACH_EXECUTION": "PTL-I100-111B-sales-outreach-adapter-execution",
            "STAGE7_FULL_CRM_ORCHESTRATION_AND_EXTERNAL_QUOTE": "PTL-I100-111C-crm-quote-and-delivery-page-adapters",
            "FORMAL_CLIENT_EXPORT_AND_PAGE_LAYER": "PTL-I100-111C-crm-quote-and-delivery-page-adapters",
            "STAGE9_LIVE_PAYMENT_DELIVERY_REFUND_EXECUTION": (
                "PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund"
            ),
        }
        for capability_id, packet_ref in expected_packets.items():
            self.assertEqual(matrix_by_id[capability_id]["operability_state"], "NEEDS_PRODUCT_IMPLEMENTATION")
            self.assertEqual(matrix_by_id[capability_id]["next_packet_ref"], packet_ref)

    def test_stage9_internal_order_payment_delivery_ledger_is_owner_operable(self) -> None:
        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}

        h08_row = matrix_by_id["STAGE9_H08_ORDER_PAYMENT_DELIVERY_TYPED_LIFECYCLE"]
        self.assertEqual(h08_row["operability_state"], "OPERABLE_NOW_INTERNAL")
        self.assertTrue(h08_row["owner_usable_now"])
        self.assertEqual(h08_row["next_packet_ref"], "NONE_CURRENTLY_REQUIRED")
        self.assertFalse(h08_row["ready_for_live_execution"])

        live_row = matrix_by_id["STAGE9_LIVE_PAYMENT_DELIVERY_REFUND_EXECUTION"]
        self.assertEqual(live_row["operability_state"], "NEEDS_PRODUCT_IMPLEMENTATION")
        self.assertFalse(live_row["owner_usable_now"])
        self.assertFalse(live_row["ready_for_live_execution"])
        self.assertEqual(live_row["refund_boundary"], "do_not_implement_automated_refund_program")

    def test_business_model_separates_internal_software_from_sold_evidence_pack(self) -> None:
        product_model = self.matrix["product_model"]
        self.assertEqual(product_model["sold_product"], "evidence_pack_and_leadpack")
        self.assertEqual(product_model["not_sold_product"], "external_software_platform")
        self.assertIn("sales_outreach_execution", product_model["required_business_capabilities"])
        self.assertIn("leadpack_export_and_delivery", product_model["required_business_capabilities"])

        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}
        self.assertEqual(
            matrix_by_id["EXTERNAL_SOFTWARE_RELEASE"]["operability_state"],
            "NOT_REQUIRED_FOR_EVIDENCE_PACK_BUSINESS",
        )

    def test_refund_policy_remains_manual_exception_only(self) -> None:
        refund_policy = self.matrix["product_model"]["refund_policy"]
        self.assertFalse(refund_policy["automated_refund_program"])
        self.assertEqual(refund_policy["allowed_refund_handling"], "manual_exception_record_and_governed_review_only")

        matrix_by_id = {row["capability_id"]: row for row in self.matrix["capability_assessments"]}
        self.assertEqual(
            matrix_by_id["STAGE9_LIVE_PAYMENT_DELIVERY_REFUND_EXECUTION"]["refund_boundary"],
            "do_not_implement_automated_refund_program",
        )

    def test_open_capability_policy_targets_business_functions_except_automated_refund(self) -> None:
        matrix_policy = self.matrix["product_model"]["open_capability_policy"]
        task_policy = self.task_library["open_capability_policy"]

        self.assertEqual(matrix_policy["policy_id"], "PTL-I100-OPEN-CAPABILITY-BASELINE")
        self.assertEqual(task_policy["policy_id"], matrix_policy["policy_id"])
        self.assertEqual(matrix_policy["live_default"], "CONTROLLED_OPENING_REQUIRED")
        self.assertEqual(task_policy["live_default"], "CONTROLLED_OPENING_REQUIRED")
        self.assertEqual(matrix_policy["completion_gate"], "PTL-I100-118-full-product-operational-acceptance")
        self.assertEqual(task_policy["final_product_closure_gate"], matrix_policy["completion_gate"])

        required_targets = {
            "real_public_source_collection",
            "real_parser_ocr_attachment_extraction",
            "public_verification_adapters",
            "real_challenger_identification",
            "crm_sync",
            "quote_execution",
            "leadpack_customer_visible_page",
            "formal_export_artifacts",
            "sales_outreach_execution",
            "payment_collection",
            "charge_execution",
            "delivery_fulfillment",
            "production_monitoring_alerting_rollback",
        }
        self.assertTrue(
            required_targets.issubset(set(matrix_policy["target_capabilities_to_open_under_control"]))
        )
        self.assertTrue(
            required_targets.issubset(set(task_policy["target_capabilities_to_open_under_control"]))
        )

        excluded = set(matrix_policy["excluded_capabilities"]) | set(task_policy["excluded_capabilities"])
        self.assertIn("automated_refund_execution", excluded)
        self.assertNotIn("automated_refund_execution", matrix_policy["target_capabilities_to_open_under_control"])
        self.assertNotIn("automated_refund_execution", task_policy["target_capabilities_to_open_under_control"])
        self.assertIn("APPROVAL_READY", matrix_policy["state_order"])
        self.assertIn("PRODUCTION_READY", task_policy["state_order"])

    def test_next_sequence_records_completed_111a_then_open_execution_packets(self) -> None:
        sequence = self.matrix["next_implementation_sequence"]
        self.assertEqual(sequence[0]["packet_ref"], "PTL-I100-110A-platform-backend-operability-foundation")
        refs = [entry["packet_ref"] for entry in sequence]
        self.assertIn("PTL-I100-111A-provider-config-and-sandbox-seam", refs)
        self.assertIn("PTL-I100-111B-sales-outreach-adapter-execution", refs)
        self.assertIn("PTL-I100-111C-crm-quote-and-delivery-page-adapters", refs)
        self.assertIn("PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund", refs)
        self.assertEqual(
            refs[-1],
            "PTL-I100-118-full-product-operational-acceptance",
        )

    def test_production_gap_task_map_records_all_open_gap_packets(self) -> None:
        task_map = self.matrix["production_gap_task_map"]
        mapped_refs = {row["packet_ref"] for row in task_map}
        required_refs = {
            "PTL-I100-111A-provider-config-and-sandbox-seam",
            "PTL-I100-111B-sales-outreach-adapter-execution",
            "PTL-I100-111C-crm-quote-and-delivery-page-adapters",
            "PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund",
            "PTL-I100-112-production-platform-infrastructure",
            "PTL-I100-113-stage1-scheduler-production-loop",
            "PTL-I100-114-stage2-real-public-source-adapters",
            "PTL-I100-115-stage3-real-parser-ocr-attachments",
            "PTL-I100-116-stage4-public-verification-adapters",
            "PTL-I100-116A-project-manager-active-conflict-vertical-slice",
            "PTL-I100-117-rule-factory-expansion-and-golden-cases",
            "PTL-I100-119A-real-challenger-identification-hardening",
            "PTL-I100-119-stage6-product-package-hardening",
            "PTL-I100-111E-provider-reliability-and-circuit-breaker",
            "PTL-I100-120-operator-customer-access-and-go-live-readiness",
            "PTL-I100-121A-sales-outreach-live-pilot",
            "PTL-I100-121B-payment-delivery-live-pilot-no-auto-refund",
            "PTL-I100-121C-production-slo-monitoring-incident-readiness",
            "PTL-I100-118-full-product-operational-acceptance",
            "PTL-I100-118R-final-product-operational-reacceptance",
            "PTL-I100-127-owner-operator-frontend-and-customer-portal",
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
            "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
            "PTL-I100-133B-national-verification-source-entry-fetchers",
            "PTL-I100-133C-representative-local-platform-entry-fetchers",
            "PTL-I100-133D-public-attachment-original-link-fetching",
            "PTL-I100-134-owner-task-runner-real-source-ui",
            "PTL-I100-135-owner-real-source-task-workbench",
            "PTL-I100-136-real-public-url-fetcher-bulk-hardening",
            "PTL-I100-137-degraded-real-public-site-hardening",
            "PTL-I100-138-real-public-snapshot-to-parser-pilot",
            "PTL-I100-139-real-public-parser-to-verification-pilot",
            "PTL-I100-140-real-public-verification-to-rule-evidence-pilot",
            "PTL-I100-141-real-public-rule-evidence-to-stage6-product-package-pilot",
            "PTL-I100-142-real-public-product-package-to-stage7-sales-leadpack-pilot",
            "PTL-I100-143-real-public-stage7-to-stage8-stage9-controlled-execution-readback-pilot",
            "PTL-I100-143D-business-decision-architecture-and-hook-lead-roadmap-sync",
            "PTL-I100-143E-autonomous-source-strategy-d-doc-sync",
            "PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync",
            "PTL-I100-143G-public-web-capture-doc-sync-and-order-review",
            "PTL-I100-144-market-scan-opportunity-discovery-engine",
            "PTL-I100-145-source-blueprint-orchestration-and-capture-plan",
            "PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation",
            "PTL-I100-151-public-web-captcha-automated-resolution-and-resume",
            "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy",
            "PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine",
            "PTL-I100-148-productized-autonomous-operator-workbench",
            "PTL-I100-149-real-sample-autonomous-opportunity-acceptance",
        }

        self.assertTrue(required_refs.issubset(mapped_refs))
        for row in task_map:
            self.assertTrue(row["covered_capabilities"], row["gap_group"])

    def test_gap_matrix_task_statuses_match_product_task_library(self) -> None:
        task_statuses = {row["task_id"]: row["status"] for row in self.task_library["tasks"]}
        sections = (
            ("production_gap_task_map", "status"),
            ("next_implementation_sequence", "implementation_status"),
        )

        for section_name, status_key in sections:
            with self.subTest(section=section_name):
                for row in self.matrix[section_name]:
                    packet_ref = row["packet_ref"]
                    if packet_ref not in task_statuses:
                        continue
                    self.assertEqual(row[status_key], task_statuses[packet_ref], packet_ref)

    def test_source_strategy_pilot_portfolio_records_national_and_beijing_policy(self) -> None:
        section = self.matrix["source_strategy_pilot_portfolio_after_143D"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-145-source-blueprint-orchestration-and-capture-plan",
        )
        self.assertEqual(section["national_aggregator_assessment"], "NOT_FULL_COVERAGE_NOT_RELIABLY_REALTIME")
        self.assertIn("first_level_discovery", section["national_aggregator_role"])
        self.assertEqual(
            section["beijing_policy"]["status"],
            "EXCLUDED_FROM_FIRST_COMMERCIAL_PILOT",
        )
        self.assertEqual(
            section["beijing_policy"]["allowed_use"],
            "technical_regression_and_public_page_reachability_only",
        )
        self.assertEqual(
            set(section["first_batch_commercial_pilot_provinces"]),
            {"四川", "江苏", "浙江", "山东", "广东", "湖北"},
        )
        self.assertIn("province_platform_missing_detail_or_attachment", section["city_adapter_trigger_policy"])
        self.assertIn("beijing_not_first_batch_commercial_pilot", section["must_prove"])

    def test_133a_real_public_entry_fetcher_records_total_entry_gap(self) -> None:
        section = self.matrix["real_public_source_operationalization_after_132"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-133A-real-public-entry-url-fetcher-and-allowlist",
        )
        self.assertIn(section["status"], {"ACTIVE", "COMPLETED"})
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertEqual(
            section["first_batch_entry_urls"],
            [
                "https://www.ggzy.gov.cn/deal/dealList.html",
                "https://www.ccgp.gov.cn/cggg/zygg/",
                "https://www.ccgp.gov.cn/cggg/zygg/zbgg/",
            ],
        )
        self.assertIn("browser_verified_total_entry_urls", section["must_prove"])
        self.assertIn("total_entry_page_snapshot_not_detail_only", section["must_prove"])
        self.assertIn("same_site_detail_link_discovery", section["must_prove"])

    def test_143d_records_autonomous_business_decision_architecture_and_followup_sequence(self) -> None:
        section = self.matrix["autonomous_business_decision_architecture_after_143"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-143D-business-decision-architecture-and-hook-lead-roadmap-sync",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertEqual(section["architecture_map_ref"], "control/product_runtime_architecture_map.yaml")
        self.assertEqual(section["human_scheme_ref"], "docs/AX9S_自动运营决策架构与商业钩子方案.md")
        self.assertIn("autonomous_execution_brain_contract_records_existing_parts_and_missing_run_controller", section["must_prove"])
        self.assertIn("elevated_remaining_product_readiness_gap_assessment_records_next_product_risks", section["must_prove"])
        self.assertIn("stage1_to_stage9_improvement_assessment_with_decision_method_and_llm_boundary", section["must_prove"])
        self.assertIn("commercial_hook_lead_presale_disclosure_does_not_leak_reproducible_evidence_chain", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_143D_passes"],
            [
                "PTL-I100-143E-autonomous-source-strategy-d-doc-sync",
                "PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync",
                "PTL-I100-143G-public-web-capture-doc-sync-and-order-review",
                "PTL-I100-144-market-scan-opportunity-discovery-engine",
                "PTL-I100-145-source-blueprint-orchestration-and-capture-plan",
                "PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation",
                "PTL-I100-151-public-web-captcha-automated-resolution-and-resume",
                "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy",
                "PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine",
                "PTL-I100-148-productized-autonomous-operator-workbench",
                "PTL-I100-149-real-sample-autonomous-opportunity-acceptance",
            ],
        )

        task_map = {row["packet_ref"]: row for row in self.matrix["production_gap_task_map"]}
        task_statuses = {row["task_id"]: row["status"] for row in self.task_library["tasks"]}
        self.assertEqual(
            task_map["PTL-I100-143-real-public-stage7-to-stage8-stage9-controlled-execution-readback-pilot"]["status"],
            "COMPLETED",
        )
        for packet_ref in section["next_packets_if_143D_passes"]:
            self.assertEqual(task_map[packet_ref]["status"], task_statuses[packet_ref])

    def test_143e_records_d_doc_sync_for_autonomous_source_strategy(self) -> None:
        section = self.matrix["autonomous_source_strategy_d_doc_sync_after_143D"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-143E-autonomous-source-strategy-d-doc-sync",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("docs/D13_公开可查边界能力清单.md", section["authority_docs_to_sync"])
        self.assertIn("docs/D11_测试验收与金标回归清单.md", section["authority_docs_to_sync"])
        self.assertIn("docs/D14_AI模型治理规范.md", section["cross_reference_docs_to_sync"])
        self.assertIn("d13_records_national_aggregator_and_beijing_commercial_pilot_boundary", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_143E_passes"],
            [
                "PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync",
            ],
        )

    def test_143f_registers_public_web_capture_and_captcha_resume_tasks(self) -> None:
        section = self.matrix["public_web_capture_and_captcha_task_pool_sync_after_143E"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-143F-public-web-capture-and-captcha-task-pool-sync",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("task_pool_registers_public_web_capture_hardening", section["must_prove"])
        self.assertIn("task_pool_registers_captcha_automated_resolution_path", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_143F_passes"],
            [
                "PTL-I100-143G-public-web-capture-doc-sync-and-order-review",
            ],
        )

    def test_143g_records_doc_sync_and_reordered_runtime_sequence_after_143f(self) -> None:
        section = self.matrix["public_web_capture_doc_sync_and_order_review_after_143F"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-143G-public-web-capture-doc-sync-and-order-review",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("docs_reference_143g_public_web_capture_and_captcha_resume_policy", section["must_prove"])
        self.assertIn("route_map_and_scheme_doc_reorder_144_145_150_151_146_147_148_149", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_143G_passes"],
            [
                "PTL-I100-144-market-scan-opportunity-discovery-engine",
                "PTL-I100-145-source-blueprint-orchestration-and-capture-plan",
                "PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation",
                "PTL-I100-151-public-web-captcha-automated-resolution-and-resume",
                "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy",
                "PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine",
                "PTL-I100-148-productized-autonomous-operator-workbench",
                "PTL-I100-149-real-sample-autonomous-opportunity-acceptance",
            ],
        )

        market_gap = next(
            item
            for item in self.matrix["production_gap_task_map"]
            if item["packet_ref"] == "PTL-I100-144-market-scan-opportunity-discovery-engine"
        )
        source_blueprint_gap = next(
            item
            for item in self.matrix["production_gap_task_map"]
            if item["packet_ref"] == "PTL-I100-145-source-blueprint-orchestration-and-capture-plan"
        )
        public_web_gap = next(
            item
            for item in self.matrix["production_gap_task_map"]
            if item["packet_ref"] == "PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation"
        )
        captcha_resume_gap = next(
            item
            for item in self.matrix["production_gap_task_map"]
            if item["packet_ref"] == "PTL-I100-151-public-web-captcha-automated-resolution-and-resume"
        )
        evidence_risk_gap = next(
            item
            for item in self.matrix["production_gap_task_map"]
            if item["packet_ref"] == "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy"
        )
        self.assertEqual(market_gap["status"], "COMPLETED")
        self.assertEqual(source_blueprint_gap["status"], "COMPLETED")
        self.assertEqual(public_web_gap["status"], "COMPLETED")
        self.assertEqual(captcha_resume_gap["status"], "COMPLETED")
        self.assertEqual(evidence_risk_gap["status"], "ACTIVE")
        self.assertEqual(
            self.matrix["current_gap_sync_2026_04_29"]["current_active_packet"],
            "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy",
        )

    def test_133b_national_verification_entry_fetcher_records_blocked_runtime_gap(self) -> None:
        section = self.matrix["national_verification_source_operationalization_after_133A"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-133B-national-verification-source-entry-fetchers",
        )
        self.assertIn(section["status"], {"ACTIVE", "COMPLETED"})
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertEqual(
            section["official_entry_urls"],
            [
                "https://jzsc.mohurd.gov.cn/home",
                "https://jzsc.mohurd.gov.cn/data/company",
                "https://jzsc.mohurd.gov.cn/data/person",
                "https://jzsc.mohurd.gov.cn/data/project",
                "https://www.creditchina.gov.cn/",
                "https://www.gsxt.gov.cn/index.html",
            ],
        )
        self.assertIn("jzsc_raw_shell_fail_closed", section["must_prove"])
        self.assertIn("creditchina_412_fail_closed", section["must_prove"])
        self.assertIn("gsxt_521_fail_closed", section["must_prove"])

    def test_133c_local_platform_entry_fetcher_records_success_and_shell_gap(self) -> None:
        section = self.matrix["representative_local_platform_operationalization_after_133B"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-133C-representative-local-platform-entry-fetchers",
        )
        self.assertIn(section["status"], {"ACTIVE", "COMPLETED"})
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertEqual(
            section["official_entry_urls"],
            [
                "https://ggzyfw.beijing.gov.cn/",
                "https://ggzyfw.beijing.gov.cn/tyrkgcjs/index.html",
                "https://ggzyjy.bda.gov.cn/",
                "https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/440000/index",
                "https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/445300/index",
            ],
        )
        self.assertIn("beijing_local_platform_html_success_path", section["must_prove"])
        self.assertIn("beijing_bda_html_success_path", section["must_prove"])
        self.assertIn("guangdong_portal_raw_shell_fail_closed", section["must_prove"])

    def test_133d_public_attachment_fetcher_records_binary_attachment_gap(self) -> None:
        section = self.matrix["public_attachment_original_link_operationalization_after_133C"]

        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-133D-public-attachment-original-link-fetching",
        )
        self.assertIn(section["status"], {"ACTIVE", "COMPLETED"})
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertEqual(
            section["official_attachment_urls"],
            [
                "https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202506/9426015154001.pdf",
                "https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202410/25172947ch03.pdf",
            ],
        )
        self.assertIn("public_attachment_original_url_fetch", section["must_prove"])
        self.assertIn("binary_attachment_snapshot_hash_readback", section["must_prove"])
        self.assertIn("html_disguised_download_fail_closed", section["must_prove"])

    def test_134_owner_task_runner_real_source_ui_records_console_execution_gap(self) -> None:
        section = self.matrix["owner_task_runner_real_source_ui_operationalization_after_133D"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-134-owner-task-runner-real-source-ui",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("owner_console_runs_real_public_entry_capture", section["must_prove"])
        self.assertIn("owner_console_runs_real_public_attachment_capture", section["must_prove"])
        self.assertIn("source_capture_readback_is_repository_backed_and_fail_closed", section["must_prove"])

    def test_135_owner_real_source_task_workbench_records_run_history_gap(self) -> None:
        section = self.matrix["owner_real_source_task_workbench_after_134"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-135-owner-real-source-task-workbench",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("owner_console_lists_real_source_task_runs", section["must_prove"])
        self.assertIn("run_records_are_repository_backed_operator_actions", section["must_prove"])
        self.assertIn("source_capture_readback_links_are_visible_and_fail_closed", section["must_prove"])

    def test_136_real_public_url_fetcher_bulk_hardening_records_batch_gap(self) -> None:
        section = self.matrix["real_public_url_fetcher_bulk_hardening_after_135"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-136-real-public-url-fetcher-bulk-hardening",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("registered_14_entry_and_2_attachment_profiles_are_bulk_hardened", section["must_prove"])
        self.assertIn("tls_incompatible_public_sites_use_controlled_fallback_transport", section["must_prove"])
        self.assertIn("blocked_or_spa_profiles_fail_closed_with_taxonomy", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_136_passes"],
            ["PTL-I100-137-degraded-real-public-site-hardening"],
        )

    def test_137_degraded_real_public_site_hardening_records_site_level_gap(self) -> None:
        section = self.matrix["degraded_real_public_site_hardening_after_136"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-137-degraded-real-public-site-hardening",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("degraded_profile_set_is_explicit_from_136_results", section["must_prove"])
        self.assertIn("site_level_public_paths_are_hardened_or_fail_closed", section["must_prove"])
        self.assertIn("spa_or_upstream_blocked_profiles_keep_taxonomy", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_137_passes"],
            ["PTL-I100-138-real-public-snapshot-to-parser-pilot"],
        )

    def test_138_real_public_snapshot_to_parser_pilot_records_parser_gap(self) -> None:
        section = self.matrix["real_public_snapshot_to_parser_pilot_after_137"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-138-real-public-snapshot-to-parser-pilot",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("real_public_html_and_attachment_snapshots_enter_stage3_parser", section["must_prove"])
        self.assertIn("parsed_fields_keep_source_slice_confidence_and_parser_audit", section["must_prove"])
        self.assertIn("parser_outputs_remain_unverified_and_review_required", section["must_prove"])
        self.assertIn("no_stage4_stage5_or_customer_visible_promotion", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_138_passes"],
            ["PTL-I100-139-real-public-parser-to-verification-pilot"],
        )

    def test_139_real_public_parser_to_verification_pilot_records_stage4_gap(self) -> None:
        section = self.matrix["real_public_parser_to_verification_pilot_after_138"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-139-real-public-parser-to-verification-pilot",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("real_public_parsed_fields_enter_stage4_public_verification", section["must_prove"])
        self.assertIn("verification_carrier_binds_parsed_field_refs_and_replayable_snapshot_refs", section["must_prove"])
        self.assertIn("weak_or_missing_identifier_public_evidence_fails_closed", section["must_prove"])
        self.assertIn("no_stage5_stage6_or_customer_visible_promotion", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_139_passes"],
            ["PTL-I100-140-real-public-verification-to-rule-evidence-pilot"],
        )

    def test_140_real_public_verification_to_rule_evidence_pilot_records_stage5_gap(self) -> None:
        section = self.matrix["real_public_verification_to_rule_evidence_pilot_after_139"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-140-real-public-verification-to-rule-evidence-pilot",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn("real_public_stage4_verification_readback_enters_stage5_rule_evidence_gate", section["must_prove"])
        self.assertIn("rule_hit_and_evidence_bind_verification_run_snapshot_and_parsed_field_refs", section["must_prove"])
        self.assertIn("weak_or_review_public_verification_fails_closed_to_stage5_review", section["must_prove"])
        self.assertIn("no_stage6_or_customer_visible_promotion", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_140_passes"],
            ["PTL-I100-141-real-public-rule-evidence-to-stage6-product-package-pilot"],
        )

    def test_141_real_public_rule_evidence_to_stage6_product_package_records_stage6_gap(self) -> None:
        section = self.matrix["real_public_rule_evidence_to_stage6_product_package_pilot_after_140"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-141-real-public-rule-evidence-to-stage6-product-package-pilot",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn(
            "real_public_stage5_rule_evidence_enters_stage6_product_package_readiness",
            section["must_prove"],
        )
        self.assertIn(
            "stage6_product_package_refs_bind_verification_snapshot_parse_and_gate_refs",
            section["must_prove"],
        )
        self.assertIn(
            "weak_or_review_stage5_result_fails_closed_to_stage6_product_review",
            section["must_prove"],
        )
        self.assertIn("no_customer_visible_publication_or_downstream_execution", section["must_prove"])
        self.assertEqual(
            section["next_packets_if_141_passes"],
            ["PTL-I100-142-real-public-product-package-to-stage7-sales-leadpack-pilot"],
        )

    def test_142_real_public_product_package_to_stage7_sales_leadpack_records_stage7_gap(self) -> None:
        section = self.matrix["real_public_product_package_to_stage7_sales_leadpack_pilot_after_141"]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-142-real-public-product-package-to-stage7-sales-leadpack-pilot",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn(
            "real_public_stage6_product_package_enters_stage7_sales_and_leadpack_readback",
            section["must_prove"],
        )
        self.assertIn(
            "stage7_sales_lead_offer_crm_quote_and_leadpack_refs_bind_stage6_real_public_chain",
            section["must_prove"],
        )
        self.assertIn(
            "weak_or_review_stage6_package_fails_closed_before_customer_delivery",
            section["must_prove"],
        )
        self.assertIn(
            "no_customer_visible_publication_provider_execution_or_stage8_stage9_trigger",
            section["must_prove"],
        )

    def test_143_real_public_stage7_to_stage8_stage9_records_execution_readback_gap(self) -> None:
        section = self.matrix[
            "real_public_stage7_to_stage8_stage9_controlled_execution_readback_pilot_after_142"
        ]
        self.assertEqual(
            section["packet_ref"],
            "PTL-I100-143-real-public-stage7-to-stage8-stage9-controlled-execution-readback-pilot",
        )
        self.assertEqual(section["status"], "COMPLETED")
        self.assertEqual(section["target_capability_state"], "INTERNAL_READY")
        self.assertIn(
            "real_public_stage7_sales_leadpack_enters_stage8_outbox_readback",
            section["must_prove"],
        )
        self.assertIn(
            "real_public_stage8_outbox_enters_stage9_order_payment_delivery_ledger_readback",
            section["must_prove"],
        )
        self.assertIn("stage8_stage9_refs_bind_stage7_stage6_real_public_chain", section["must_prove"])
        self.assertIn("no_customer_visible_delivery_provider_execution_or_refund", section["must_prove"])

    def test_task_library_records_fine_grained_capability_gaps(self) -> None:
        tasks_by_id = {row["task_id"]: row for row in self.task_library["tasks"]}
        task_111 = tasks_by_id["PTL-I100-111-live-provider-adapters-no-auto-refund"]
        subpackets = {row["subpacket_id"]: row for row in task_111["planned_subpackets"]}

        self.assertIn("email_provider_adapter", subpackets["PTL-I100-111B-sales-outreach-adapter-execution"]["capability_gaps_covered"])
        self.assertIn("crm_provider_adapter", subpackets["PTL-I100-111C-crm-quote-and-delivery-page-adapters"]["capability_gaps_covered"])
        self.assertEqual(
            subpackets["PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund"][
                "refund_boundary"
            ],
            "manual exception/governed review only; no automated refund execution",
        )

        for task_id in (
            "PTL-I100-111B-sales-outreach-adapter-execution",
            "PTL-I100-111C-crm-quote-and-delivery-page-adapters",
            "PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund",
            "PTL-I100-112-production-platform-infrastructure",
            "PTL-I100-113-stage1-scheduler-production-loop",
            "PTL-I100-114-stage2-real-public-source-adapters",
            "PTL-I100-115-stage3-real-parser-ocr-attachments",
            "PTL-I100-116-stage4-public-verification-adapters",
            "PTL-I100-116A-project-manager-active-conflict-vertical-slice",
            "PTL-I100-117-rule-factory-expansion-and-golden-cases",
            "PTL-I100-119A-real-challenger-identification-hardening",
            "PTL-I100-119-stage6-product-package-hardening",
            "PTL-I100-111E-provider-reliability-and-circuit-breaker",
            "PTL-I100-120-operator-customer-access-and-go-live-readiness",
            "PTL-I100-121A-sales-outreach-live-pilot",
            "PTL-I100-121B-payment-delivery-live-pilot-no-auto-refund",
            "PTL-I100-121C-production-slo-monitoring-incident-readiness",
            "PTL-I100-118-full-product-operational-acceptance",
            "PTL-I100-122-approved-sales-outreach-provider-execution",
            "PTL-I100-123-approved-payment-delivery-provider-execution-no-auto-refund",
            "PTL-I100-124-customer-visible-leadpack-delivery-approval-unlock",
            "PTL-I100-125-approved-crm-quote-provider-execution",
            "PTL-I100-126-production-live-dependency-and-drill-approval",
            "PTL-I100-118R-final-product-operational-reacceptance",
            "PTL-I100-127-owner-operator-frontend-and-customer-portal",
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
            "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
            "PTL-I100-132-owner-operator-frontend-productization-workbench",
        ):
            self.assertTrue(tasks_by_id[task_id]["capability_gaps_covered"], task_id)

    def test_source_families_and_package_types_are_explicit_subpackets(self) -> None:
        tasks_by_id = {row["task_id"]: row for row in self.task_library["tasks"]}

        source_subpackets = {
            row["subpacket_id"]: row
            for row in tasks_by_id["PTL-I100-114-stage2-real-public-source-adapters"][
                "planned_source_family_subpackets"
            ]
        }
        self.assertEqual(
            set(source_subpackets),
            {
                "PTL-I100-114A-local-public-resource-trading-centers",
                "PTL-I100-114B-provincial-bidding-platforms",
                "PTL-I100-114C-national-construction-market-platform",
                "PTL-I100-114D-credit-china-public-records",
                "PTL-I100-114E-national-enterprise-credit-publicity-system",
                "PTL-I100-114F-government-procurement-public-sites",
                "PTL-I100-114G-tender-agency-public-sites",
                "PTL-I100-114H-tenderer-public-notice-pages",
                "PTL-I100-114I-industry-authority-filing-pages",
            },
        )
        for row in source_subpackets.values():
            self.assertTrue(row["covered_capabilities"], row["subpacket_id"])

        package_subpackets = {
            row["subpacket_id"]: row
            for row in tasks_by_id["PTL-I100-111C-crm-quote-and-delivery-page-adapters"][
                "planned_package_type_subpackets"
            ]
        }
        self.assertEqual(
            set(package_subpackets),
            {
                "PTL-I100-111C1-internal-leadpack",
                "PTL-I100-111C2-customer-visible-leadpack",
                "PTL-I100-111C3-formal-objection-pack",
                "PTL-I100-111C4-sales-talk-track-pack",
            },
        )
        for row in package_subpackets.values():
            self.assertTrue(row["covered_capabilities"], row["subpacket_id"])

    def test_task_library_count_and_task_ids_stay_unique(self) -> None:
        task_ids = [row["task_id"] for row in self.task_library["tasks"]]

        self.assertEqual(self.task_library["task_count"], len(task_ids))
        self.assertEqual(len(task_ids), len(set(task_ids)))

    def test_reassessed_execution_order_prioritizes_real_data_chain_before_provider_execution(self) -> None:
        sequence = [
            row["packet_ref"]
            for row in self.matrix["recommended_execution_order_after_reassessment"]["sequence"]
        ]

        self.assertEqual(sequence[0], "PTL-I100-112-production-platform-infrastructure")
        self.assertLess(
            sequence.index("PTL-I100-116-stage4-public-verification-adapters"),
            sequence.index("PTL-I100-116A-project-manager-active-conflict-vertical-slice"),
        )
        self.assertLess(
            sequence.index("PTL-I100-116A-project-manager-active-conflict-vertical-slice"),
            sequence.index("PTL-I100-117-rule-factory-expansion-and-golden-cases"),
        )
        self.assertLess(
            sequence.index("PTL-I100-119A-real-challenger-identification-hardening"),
            sequence.index("PTL-I100-119-stage6-product-package-hardening"),
        )
        self.assertLess(
            sequence.index("PTL-I100-119-stage6-product-package-hardening"),
            sequence.index("PTL-I100-111E-provider-reliability-and-circuit-breaker"),
        )
        self.assertLess(
            sequence.index("PTL-I100-111E-provider-reliability-and-circuit-breaker"),
            sequence.index("PTL-I100-111B-sales-outreach-adapter-execution"),
        )
        self.assertLess(
            sequence.index("PTL-I100-111C-crm-quote-and-delivery-page-adapters"),
            sequence.index("PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund"),
        )
        self.assertLess(
            sequence.index("PTL-I100-120-operator-customer-access-and-go-live-readiness"),
            sequence.index("PTL-I100-121A-sales-outreach-live-pilot"),
        )
        self.assertLess(
            sequence.index("PTL-I100-121C-production-slo-monitoring-incident-readiness"),
            sequence.index("PTL-I100-118-full-product-operational-acceptance"),
        )
        self.assertEqual(sequence[-1], "PTL-I100-118-full-product-operational-acceptance")

    def test_acceptance_model_requires_three_layer_validation(self) -> None:
        acceptance_model = self.matrix["acceptance_model"]
        self.assertIn("engineering_regression", acceptance_model)
        self.assertIn("capability_state", acceptance_model)
        self.assertIn("product_closure", acceptance_model)
        self.assertIn("SANDBOX_READY", acceptance_model["capability_state"]["state_order"])
        self.assertEqual(
            acceptance_model["product_closure"]["refund_boundary"],
            "automated refund execution remains excluded; refund handling is manual exception and governed review only.",
        )

    def test_118_final_acceptance_records_operational_blockers_not_closeout(self) -> None:
        final = self.matrix["final_118_operational_acceptance"]

        self.assertEqual(final["packet_ref"], "PTL-I100-118-full-product-operational-acceptance")
        self.assertEqual(final["acceptance_result"], "BLOCKED_BY_PRODUCT_OPERATIONAL_GAPS")
        self.assertEqual(final["capability_state_result"], "VERIFIED_MIXED_READY_READBACK")
        self.assertEqual(final["product_closure_result"], "NOT_CLOSED")
        self.assertTrue(final["owner_internal_loop_operable"])
        self.assertFalse(final["owner_end_to_end_sales_delivery_operable"])
        self.assertEqual(final["closeout_recommendation"], "DO_NOT_CLOSEOUT")

        blockers = {row["blocker_id"]: row for row in final["remaining_blockers"]}
        self.assertEqual(
            set(blockers),
            {
                "B118_STAGE8_REAL_SEND_NOT_EXECUTABLE",
                "B118_STAGE9_REAL_PAYMENT_DELIVERY_NOT_EXECUTABLE",
                "B118_CUSTOMER_VISIBLE_LEADPACK_DELIVERY_LOCKED",
                "B118_EXTERNAL_CRM_QUOTE_EXECUTION_LOCKED",
                "B118_PRODUCTION_LIVE_DEPENDENCIES_READBACK_ONLY",
            },
        )
        for blocker in blockers.values():
            self.assertTrue(blocker["minimum_followup_task_id"].startswith("PTL-I100-12"))
            self.assertIn(blocker["minimum_followup_task_id"], self.task_library_task_ids())
            self.assertTrue(blocker["forbidden_in_118"])

        self.assertEqual(blockers["B118_STAGE8_REAL_SEND_NOT_EXECUTABLE"]["current_state"], "LIVE_READY")
        self.assertEqual(
            blockers["B118_STAGE9_REAL_PAYMENT_DELIVERY_NOT_EXECUTABLE"]["refund_boundary"],
            "manual exception/governed review only; no automated refund execution",
        )
        self.assertEqual(final["controlled_opening_requirements_preserved"]["automated_refund_execution"], "EXCLUDED")

    def test_118r_reacceptance_is_closed_by_131_real_world_e2e_pilot(self) -> None:
        final = self.matrix["final_118R_operational_reacceptance"]

        self.assertEqual(final["packet_ref"], "PTL-I100-118R-final-product-operational-reacceptance")
        self.assertEqual(final["previous_acceptance_ref"], "PTL-I100-118-full-product-operational-acceptance")
        self.assertEqual(final["acceptance_result"], "CONTROLLED_REAL_WORLD_E2E_ACCEPTED")
        self.assertEqual(final["capability_state_result"], "VERIFIED_CONTROLLED_OWNER_OPERABLE_PRODUCTION_READY")
        self.assertEqual(final["product_closure_result"], "CONTROLLED_REAL_WORLD_CLOSED")
        self.assertTrue(final["owner_internal_loop_operable"])
        self.assertTrue(final["owner_controlled_execution_loop_operable"])
        self.assertTrue(final["owner_end_to_end_real_world_sales_delivery_operable"])
        self.assertEqual(
            final["closeout_recommendation"],
            "PRODUCTION_CLOSEOUT_READY_FOR_OWNER_OPERATED_CONTROLLED_USE",
        )
        self.assertEqual(
            set(final["resolved_118_blockers"]),
            {
                "B118_STAGE8_REAL_SEND_NOT_EXECUTABLE",
                "B118_STAGE9_REAL_PAYMENT_DELIVERY_NOT_EXECUTABLE",
                "B118_CUSTOMER_VISIBLE_LEADPACK_DELIVERY_LOCKED",
                "B118_EXTERNAL_CRM_QUOTE_EXECUTION_LOCKED",
                "B118_PRODUCTION_LIVE_DEPENDENCIES_READBACK_ONLY",
            },
        )

        gaps = {row["gap_id"]: row for row in final["real_world_gaps"]}
        self.assertEqual(gaps, {})
        resolved_gaps = {row["gap_id"]: row for row in final["resolved_real_world_gaps"]}
        self.assertEqual(
            resolved_gaps["B118R_FRONTEND_OPERATOR_CUSTOMER_UI_MISSING"]["resolved_by_task_id"],
            "PTL-I100-127-owner-operator-frontend-and-customer-portal",
        )
        self.assertEqual(
            resolved_gaps["B118R_REAL_SOURCE_FIELD_VALIDATION_NOT_DONE"]["resolved_by_task_id"],
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
        )
        self.assertIn(
            "owner_operator_frontend_and_customer_artifact_portal",
            final["controlled_operable_now"],
        )
        self.assertIn(
            "real_public_source_field_validation_and_coverage_report",
            final["controlled_operable_now"],
        )
        self.assertIn(
            "real_provider_binding_matrix_and_sandbox_callback_readback",
            final["controlled_operable_now"],
        )
        self.assertEqual(
            resolved_gaps["B118R_REAL_PROVIDER_BINDING_NOT_DONE"]["resolved_by_task_id"],
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
        )
        self.assertEqual(
            resolved_gaps["B118R_LLM_ASSIST_NOT_PRODUCTIZED"]["resolved_by_task_id"],
            "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
        )
        self.assertEqual(
            resolved_gaps["B118R_REAL_WORLD_E2E_PILOT_NOT_DONE"]["resolved_by_task_id"],
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
        )
        self.assertIn(
            "governed_model_assist_parser_review_sales_readback",
            final["controlled_operable_now"],
        )
        self.assertIn("controlled_real_world_e2e_pilot_closeout", final["controlled_operable_now"])
        self.assertEqual(
            self.matrix["final_131_controlled_real_world_e2e_closeout"]["remaining_product_blockers"],
            [],
        )
        final_132 = self.matrix["final_132_frontend_productization_workbench"]
        self.assertEqual(
            final_132["packet_ref"],
            "PTL-I100-132-owner-operator-frontend-productization-workbench",
        )
        self.assertEqual(final_132["acceptance_result"], "OWNER_FRONTEND_PRODUCTIZED")
        self.assertTrue(final_132["owner_can_observe_product_loop_without_raw_api_calls"])
        self.assertTrue(final_132["customer_portal_handles_missing_artifact_readback"])
        self.assertFalse(final_132["live_execution_enabled_by_frontend"])
        self.assertIn(
            "stage1_to_stage9_operations_board",
            final_132["frontend_surfaces"],
        )
        self.assertNotIn("B118R_REAL_PROVIDER_BINDING_NOT_DONE", gaps)
        self.assertNotIn("B118R_LLM_ASSIST_NOT_PRODUCTIZED", gaps)
        self.assertNotIn("B118R_REAL_WORLD_E2E_PILOT_NOT_DONE", gaps)
        self.assertEqual(final["controlled_opening_requirements_preserved"]["automated_refund_execution"], "EXCLUDED")

    def task_library_task_ids(self) -> set[str]:
        return {row["task_id"] for row in self.task_library["tasks"]}


if __name__ == "__main__":
    unittest.main()
