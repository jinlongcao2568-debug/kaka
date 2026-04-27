from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


class ProductAcceptanceChecklistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = read_yaml("control/product_task_library.yaml")
        self.checklist = read_yaml("control/product_acceptance_checklist.yaml")
        self.tasks_by_id = {row["task_id"]: row for row in self.library["tasks"]}

    def test_checklist_is_registered_from_task_library(self) -> None:
        self.assertEqual(
            self.library["acceptance_checklist_ref"],
            "control/product_acceptance_checklist.yaml",
        )
        self.assertEqual(
            self.library["acceptance_checklist_policy"]["mandatory_layers"],
            ["engineering_regression", "capability_state", "product_closure"],
        )
        self.assertEqual(
            self.checklist["policy_ref"],
            "control/product_task_library.yaml#open_capability_policy",
        )
        self.assertEqual(
            self.checklist["final_product_closure_gate"],
            "PTL-I100-118-full-product-operational-acceptance",
        )

    def test_every_non_completed_task_has_checklist_entry_and_ref(self) -> None:
        checklist_tasks = self.checklist["tasks"]
        non_completed = [
            task for task in self.library["tasks"]
            if task.get("status") != "COMPLETED"
        ]

        self.assertEqual(
            {task["task_id"] for task in non_completed},
            {
                "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
            },
        )
        for task in non_completed:
            task_id = task["task_id"]
            self.assertIn(task_id, checklist_tasks)
            self.assertEqual(
                task["acceptance_checklist_ref"],
                f"control/product_acceptance_checklist.yaml#tasks.{task_id}",
            )
            self.assertTrue(task["acceptance_checks"], task_id)
            self.assertEqual(
                checklist_tasks[task_id]["required_acceptance_layers"],
                ["engineering_regression", "capability_state", "product_closure"],
                task_id,
            )

    def test_task_target_states_are_from_open_capability_state_order(self) -> None:
        allowed_states = set(self.library["open_capability_policy"]["state_order"])
        checklist_tasks = self.checklist["tasks"]

        for task_id, entry in checklist_tasks.items():
            self.assertIn(entry["target_capability_state"], allowed_states, task_id)

        for task_id in (
            "PTL-I100-121A-sales-outreach-live-pilot",
            "PTL-I100-121B-payment-delivery-live-pilot-no-auto-refund",
        ):
            task = self.tasks_by_id[task_id]
            self.assertIn("capability_state_LIVE_READY", task["acceptance_checks"])
            self.assertNotIn("capability_state_LIVE_READY_PILOT", task["acceptance_checks"])
            self.assertTrue(checklist_tasks[task_id]["pilot_scope"])

        for task_id in (
            "PTL-I100-122-approved-sales-outreach-provider-execution",
            "PTL-I100-123-approved-payment-delivery-provider-execution-no-auto-refund",
            "PTL-I100-124-customer-visible-leadpack-delivery-approval-unlock",
            "PTL-I100-125-approved-crm-quote-provider-execution",
        ):
            task = self.tasks_by_id[task_id]
            self.assertIn("capability_state_LIVE_READY", task["acceptance_checks"])
            self.assertNotIn("capability_state_LIVE_READY_PILOT", task["acceptance_checks"])

        task_126 = self.tasks_by_id["PTL-I100-126-production-live-dependency-and-drill-approval"]
        self.assertIn("capability_state_PRODUCTION_READY", task_126["acceptance_checks"])

        task_118r = self.tasks_by_id["PTL-I100-118R-final-product-operational-reacceptance"]
        self.assertIn("capability_states_reverified", task_118r["acceptance_checks"])
        self.assertIn("fake_provider_not_misclassified_as_real_provider", task_118r["acceptance_checks"])

        production_task = self.tasks_by_id["PTL-I100-121C-production-slo-monitoring-incident-readiness"]
        self.assertIn("capability_state_PRODUCTION_READY", production_task["acceptance_checks"])
        self.assertNotIn("capability_state_PRODUCTION_READY_CANDIDATE", production_task["acceptance_checks"])

    def test_live_and_external_tasks_keep_gate_and_redline_acceptance(self) -> None:
        required_gate_tokens = {
            "provider_config",
            "sandbox_pass",
            "approval_chain",
            "audit_chain",
            "operator_action_record",
            "field_allowlist_and_masking",
            "suspension_and_rollback_path",
        }
        self.assertTrue(required_gate_tokens.issubset(set(self.checklist["live_or_external_gate_requirements"])))

        live_task_ids = {
            "PTL-I100-111B-sales-outreach-adapter-execution",
            "PTL-I100-111C-crm-quote-and-delivery-page-adapters",
            "PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund",
            "PTL-I100-120-operator-customer-access-and-go-live-readiness",
            "PTL-I100-121A-sales-outreach-live-pilot",
            "PTL-I100-121B-payment-delivery-live-pilot-no-auto-refund",
        }
        for task_id in live_task_ids:
            entry = self.checklist["tasks"][task_id]
            serialized = yaml.safe_dump(entry, allow_unicode=True)
            self.assertRegex(serialized, r"approval|audit|gated|blocked|no_unapproved", task_id)
            self.assertTrue(entry["redline_checks"], task_id)

    def test_refund_boundary_is_manual_exception_only_everywhere_it_matters(self) -> None:
        self.assertIn("automated refund execution is excluded", self.checklist["refund_boundary"])
        self.assertIn("automated refund execution remains excluded", self.library["acceptance_checklist_policy"]["refund_boundary"])

        refund_sensitive_ids = {
            "PTL-I100-111-live-provider-adapters-no-auto-refund",
            "PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund",
            "PTL-I100-121B-payment-delivery-live-pilot-no-auto-refund",
            "PTL-I100-118-full-product-operational-acceptance",
            "PTL-I100-123-approved-payment-delivery-provider-execution-no-auto-refund",
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
        }
        for task_id in refund_sensitive_ids:
            serialized = yaml.safe_dump(self.checklist["tasks"][task_id], allow_unicode=True)
            self.assertRegex(serialized, r"automated_refund|manual refund|refund handling", task_id)

        self.assertIn(
            "automated_refund_absent",
            self.tasks_by_id["PTL-I100-118-full-product-operational-acceptance"]["acceptance_checks"],
        )

    def test_public_data_tasks_keep_public_boundary_acceptance(self) -> None:
        required_public_tokens = {
            "public_visible_source_only",
            "no_private_or_gray_source",
            "no_login_or_captcha_bypass",
            "source_url_snapshot_hash_and_lineage",
            "weak_public_or_uncertain_data_degrades_to_review",
        }
        self.assertTrue(required_public_tokens.issubset(set(self.checklist["public_data_boundary_requirements"])))

        for task_id in (
            "PTL-I100-114-stage2-real-public-source-adapters",
            "PTL-I100-116-stage4-public-verification-adapters",
            "PTL-I100-116A-project-manager-active-conflict-vertical-slice",
        ):
            serialized = yaml.safe_dump(self.checklist["tasks"][task_id], allow_unicode=True)
            self.assertIn("public", serialized, task_id)
            self.assertRegex(serialized, r"no_private|public_only|public_boundary", task_id)

    def test_required_subpackets_have_dedicated_acceptance_entries(self) -> None:
        subpacket_acceptance = self.checklist["subpacket_acceptance"]
        task_111c = self.tasks_by_id["PTL-I100-111C-crm-quote-and-delivery-page-adapters"]
        task_114 = self.tasks_by_id["PTL-I100-114-stage2-real-public-source-adapters"]

        package_subpacket_ids = {
            row["subpacket_id"]
            for row in task_111c["planned_package_type_subpackets"]
        }
        source_subpacket_ids = {
            row["subpacket_id"]
            for row in task_114["planned_source_family_subpackets"]
        }

        self.assertEqual(
            package_subpacket_ids,
            {
                "PTL-I100-111C1-internal-leadpack",
                "PTL-I100-111C2-customer-visible-leadpack",
                "PTL-I100-111C3-formal-objection-pack",
                "PTL-I100-111C4-sales-talk-track-pack",
            },
        )
        self.assertEqual(len(source_subpacket_ids), 9)
        self.assertIn(
            "coverage report",
            " ".join(
                subpacket_acceptance[
                    "PTL-I100-114I-industry-authority-filing-pages"
                ]["completion_must_prove"]
            ),
        )
        for subpacket_id in package_subpacket_ids | source_subpacket_ids:
            self.assertIn(subpacket_id, subpacket_acceptance)
            self.assertTrue(subpacket_acceptance[subpacket_id]["completion_must_prove"], subpacket_id)
            self.assertTrue(subpacket_acceptance[subpacket_id]["redline_checks"], subpacket_id)

    def test_completed_packets_and_current_active_packet_are_aligned(self) -> None:
        task_112 = self.tasks_by_id["PTL-I100-112-production-platform-infrastructure"]
        task_113 = self.tasks_by_id["PTL-I100-113-stage1-scheduler-production-loop"]
        task_114 = self.tasks_by_id["PTL-I100-114-stage2-real-public-source-adapters"]
        task_115 = self.tasks_by_id["PTL-I100-115-stage3-real-parser-ocr-attachments"]
        task_116 = self.tasks_by_id["PTL-I100-116-stage4-public-verification-adapters"]
        task_116a = self.tasks_by_id["PTL-I100-116A-project-manager-active-conflict-vertical-slice"]
        task_117 = self.tasks_by_id["PTL-I100-117-rule-factory-expansion-and-golden-cases"]
        task_119a = self.tasks_by_id["PTL-I100-119A-real-challenger-identification-hardening"]
        task_119 = self.tasks_by_id["PTL-I100-119-stage6-product-package-hardening"]
        task_111b = self.tasks_by_id["PTL-I100-111B-sales-outreach-adapter-execution"]
        task_111c = self.tasks_by_id["PTL-I100-111C-crm-quote-and-delivery-page-adapters"]
        task_111d = self.tasks_by_id[
            "PTL-I100-111D-payment-collection-and-delivery-fulfillment-adapters-no-refund"
        ]
        task_111e = self.tasks_by_id["PTL-I100-111E-provider-reliability-and-circuit-breaker"]
        task_120 = self.tasks_by_id["PTL-I100-120-operator-customer-access-and-go-live-readiness"]
        task_121a = self.tasks_by_id["PTL-I100-121A-sales-outreach-live-pilot"]
        task_121b = self.tasks_by_id["PTL-I100-121B-payment-delivery-live-pilot-no-auto-refund"]
        task_121c = self.tasks_by_id["PTL-I100-121C-production-slo-monitoring-incident-readiness"]
        task_118 = self.tasks_by_id["PTL-I100-118-full-product-operational-acceptance"]
        task_118r = self.tasks_by_id["PTL-I100-118R-final-product-operational-reacceptance"]
        task_122 = self.tasks_by_id["PTL-I100-122-approved-sales-outreach-provider-execution"]
        task_123 = self.tasks_by_id[
            "PTL-I100-123-approved-payment-delivery-provider-execution-no-auto-refund"
        ]
        task_124 = self.tasks_by_id["PTL-I100-124-customer-visible-leadpack-delivery-approval-unlock"]
        task_125 = self.tasks_by_id["PTL-I100-125-approved-crm-quote-provider-execution"]

        self.assertEqual(task_112["status"], "COMPLETED")
        self.assertEqual(task_112["planning_state"], "COMPLETED")
        completed_by_id = {
            row["subpacket_id"]: row for row in task_112["completed_subpackets"]
        }
        self.assertEqual(
            completed_by_id["PTL-I100-112A-production-platform-storage-seam"][
                "completed_commit"
            ],
            "e3870ab",
        )
        self.assertEqual(
            completed_by_id["PTL-I100-112B-production-queue-worker-durability"][
                "completed_commit"
            ],
            "1f2471d",
        )
        self.assertEqual(
            completed_by_id["PTL-I100-112C-object-storage-snapshot-durability"][
                "completed_commit"
            ],
            "52d2ad3",
        )
        self.assertEqual(
            completed_by_id["PTL-I100-112D-docker-compose-health-readiness"][
                "completed_commit"
            ],
            "c8ace6f",
        )
        self.assertEqual(
            completed_by_id["PTL-I100-112E-backup-restore-rollback-readiness"][
                "completed_commit"
            ],
            "bea524b",
        )
        self.assertEqual(
            completed_by_id["PTL-I100-112F-monitoring-alerting-readiness"][
                "completed_commit"
            ],
            "0fe9212",
        )
        self.assertIsNone(task_112["active_subpacket"])
        self.assertEqual(task_112["completed_commit"], "0fe9212")
        self.assertEqual(task_112["capability_state_after"], "INTERNAL_READY")
        self.assertEqual(task_113["status"], "COMPLETED")
        self.assertEqual(task_113["planning_state"], "COMPLETED")
        self.assertEqual(task_113["completed_commit"], "ce733ba")
        self.assertEqual(task_113["capability_state_after"], "INTERNAL_READY")
        self.assertEqual(
            task_113["runtime_change_in_packet"],
            "COMPLETED_113_STAGE1_SCHEDULER_PRODUCTION_LOOP",
        )
        self.assertEqual(task_114["status"], "COMPLETED")
        self.assertEqual(task_114["planning_state"], "COMPLETED")
        self.assertIsNone(task_114["active_subpacket"])
        self.assertEqual(task_114["completed_commit"], "af13a96")
        self.assertEqual(task_114["capability_state_after"], "SANDBOX_READY")
        self.assertEqual(
            task_114["runtime_change_in_packet"],
            "COMPLETED_114_STAGE2_REAL_PUBLIC_SOURCE_ADAPTERS",
        )
        self.assertEqual(task_115["status"], "COMPLETED")
        self.assertEqual(task_115["planning_state"], "COMPLETED")
        self.assertEqual(task_115["completed_commit"], "4eca3f3")
        self.assertEqual(task_115["capability_state_after"], "INTERNAL_READY")
        self.assertEqual(
            task_115["runtime_change_in_packet"],
            "COMPLETED_115_STAGE3_REAL_PARSER_OCR_ATTACHMENTS",
        )
        self.assertEqual(task_116["status"], "COMPLETED")
        self.assertEqual(task_116["planning_state"], "COMPLETED")
        self.assertEqual(task_116["completed_commit"], "511cd30")
        self.assertEqual(task_116["capability_state_after"], "SANDBOX_READY")
        self.assertEqual(
            task_116["runtime_change_in_packet"],
            "COMPLETED_116_STAGE4_PUBLIC_VERIFICATION_ADAPTERS",
        )
        self.assertEqual(task_116a["status"], "COMPLETED")
        self.assertEqual(task_116a["planning_state"], "COMPLETED")
        self.assertEqual(task_116a["completed_commit"], "7fba84a")
        self.assertEqual(task_116a["capability_state_after"], "SANDBOX_READY")
        self.assertEqual(
            task_116a["runtime_change_in_packet"],
            "COMPLETED_116A_PROJECT_MANAGER_ACTIVE_CONFLICT_VERTICAL_SLICE",
        )
        self.assertEqual(task_117["status"], "COMPLETED")
        self.assertEqual(task_117["planning_state"], "COMPLETED")
        self.assertEqual(task_117["completed_commit"], "c073440")
        self.assertEqual(task_117["capability_state_after"], "INTERNAL_READY")
        self.assertEqual(
            task_117["runtime_change_in_packet"],
            "COMPLETED_117_STAGE5_RULE_FACTORY_EXPANSION_AND_GOLDEN_CASES",
        )
        self.assertEqual(task_119a["status"], "COMPLETED")
        self.assertEqual(task_119a["planning_state"], "COMPLETED")
        self.assertEqual(task_119a["completed_commit"], "56cd04e")
        self.assertEqual(task_119a["capability_state_after"], "INTERNAL_READY")
        self.assertEqual(
            task_119a["runtime_change_in_packet"],
            "COMPLETED_119A_REAL_CHALLENGER_IDENTIFICATION_HARDENING",
        )
        self.assertEqual(task_119["status"], "COMPLETED")
        self.assertEqual(task_119["planning_state"], "COMPLETED")
        self.assertEqual(task_119["completed_commit"], "54112c8")
        self.assertEqual(task_119["capability_state_after"], "INTERNAL_READY")
        self.assertEqual(
            task_119["runtime_change_in_packet"],
            "COMPLETED_119_STAGE6_PRODUCT_PACKAGE_HARDENING",
        )
        self.assertEqual(task_111e["status"], "COMPLETED")
        self.assertEqual(task_111e["planning_state"], "COMPLETED")
        self.assertEqual(task_111e["completed_commit"], "1a1233c")
        self.assertEqual(task_111e["capability_state_after"], "APPROVAL_READY")
        self.assertEqual(
            task_111e["runtime_change_in_packet"],
            "COMPLETED_111E_PROVIDER_RELIABILITY_AND_CIRCUIT_BREAKER",
        )
        self.assertEqual(task_111b["status"], "COMPLETED")
        self.assertEqual(task_111b["planning_state"], "COMPLETED")
        self.assertEqual(task_111b["completed_commit"], "5642cb4")
        self.assertEqual(task_111b["capability_state_after"], "SANDBOX_READY")
        self.assertEqual(
            task_111b["runtime_change_in_packet"],
            "COMPLETED_111B_SALES_OUTREACH_ADAPTER_EXECUTION",
        )
        self.assertEqual(task_111c["status"], "COMPLETED")
        self.assertEqual(task_111c["planning_state"], "COMPLETED")
        self.assertEqual(task_111c["completed_commit"], "7af8966")
        self.assertEqual(task_111c["capability_state_after"], "SANDBOX_READY")
        self.assertEqual(
            task_111c["runtime_change_in_packet"],
            "COMPLETED_111C_CRM_QUOTE_AND_DELIVERY_PAGE_ADAPTERS",
        )
        self.assertEqual(task_111d["status"], "COMPLETED")
        self.assertEqual(task_111d["planning_state"], "COMPLETED")
        self.assertEqual(task_111d["completed_commit"], "0ab2dba")
        self.assertEqual(task_111d["capability_state_after"], "SANDBOX_READY")
        self.assertEqual(
            task_111d["runtime_change_in_packet"],
            "COMPLETED_111D_PAYMENT_COLLECTION_AND_DELIVERY_FULFILLMENT_ADAPTERS_NO_REFUND",
        )
        self.assertEqual(task_120["status"], "COMPLETED")
        self.assertEqual(task_120["planning_state"], "COMPLETED")
        self.assertEqual(task_120["completed_commit"], "5bd558d")
        self.assertEqual(task_120["capability_state_after"], "APPROVAL_READY")
        self.assertEqual(
            task_120["runtime_change_in_packet"],
            "COMPLETED_120_OPERATOR_CUSTOMER_ACCESS_AND_GO_LIVE_READINESS",
        )
        self.assertEqual(task_121a["status"], "COMPLETED")
        self.assertEqual(task_121a["planning_state"], "COMPLETED")
        self.assertEqual(task_121a["completed_commit"], "4fc8020")
        self.assertEqual(task_121a["capability_state_after"], "LIVE_READY")
        self.assertEqual(
            task_121a["runtime_change_in_packet"],
            "COMPLETED_121A_SALES_OUTREACH_LIVE_PILOT",
        )
        self.assertEqual(task_121b["status"], "COMPLETED")
        self.assertEqual(task_121b["planning_state"], "COMPLETED")
        self.assertEqual(task_121b["completed_commit"], "c1515f5")
        self.assertEqual(task_121b["capability_state_after"], "LIVE_READY")
        self.assertEqual(
            task_121b["runtime_change_in_packet"],
            "COMPLETED_121B_PAYMENT_DELIVERY_LIVE_PILOT_NO_AUTO_REFUND",
        )
        self.assertEqual(task_121c["status"], "COMPLETED")
        self.assertEqual(task_121c["planning_state"], "COMPLETED")
        self.assertEqual(task_121c["completed_commit"], "aaf903c")
        self.assertEqual(task_121c["capability_state_after"], "PRODUCTION_READY")
        self.assertEqual(
            task_121c["runtime_change_in_packet"],
            "COMPLETED_121C_PRODUCTION_SLO_MONITORING_INCIDENT_READINESS",
        )
        self.assertEqual(task_118["status"], "COMPLETED")
        self.assertEqual(task_118["planning_state"], "COMPLETED")
        self.assertEqual(task_118["runtime_change_in_packet"], "OUT_OF_SCOPE")
        self.assertEqual(task_118["completion_result"], "BLOCKED_BY_PRODUCT_OPERATIONAL_GAPS")
        self.assertEqual(task_118["closeout_recommendation"], "DO_NOT_CLOSEOUT")
        self.assertEqual(task_118r["status"], "COMPLETED")
        self.assertEqual(task_118r["planning_state"], "COMPLETED")
        self.assertEqual(task_118r["runtime_change_in_packet"], "OUT_OF_SCOPE")
        self.assertEqual(task_118r["completion_result"], "BLOCKED_BY_REAL_WORLD_OPERATIONAL_GAPS")
        self.assertEqual(task_118r["closeout_recommendation"], "DO_NOT_PRODUCTION_CLOSEOUT")
        self.assertEqual(
            task_118r["followup_tasks_registered"],
            [
                "PTL-I100-127-owner-operator-frontend-and-customer-portal",
                "PTL-I100-128-real-public-source-field-validation-and-coverage",
                "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
                "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
                "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
            ],
        )
        self.assertEqual(task_122["status"], "COMPLETED")
        self.assertEqual(task_122["planning_state"], "COMPLETED")
        self.assertEqual(task_122["completed_commit"], "f3cf7e5")
        self.assertEqual(
            task_122["completion_result"],
            "COMPLETED_APPROVED_STAGE8_PROVIDER_EXECUTION_READBACK",
        )
        self.assertEqual(task_125["status"], "COMPLETED")
        self.assertEqual(task_125["planning_state"], "COMPLETED")
        self.assertEqual(task_125["completed_commit"], "0809322")
        self.assertEqual(
            task_125["completion_result"],
            "COMPLETED_APPROVED_STAGE7_CRM_QUOTE_PROVIDER_EXECUTION_READBACK",
        )
        self.assertEqual(task_124["status"], "COMPLETED")
        self.assertEqual(task_124["planning_state"], "COMPLETED")
        self.assertEqual(task_124["completed_commit"], "f8c1182")
        self.assertEqual(
            task_124["completion_result"],
            "COMPLETED_APPROVED_CUSTOMER_VISIBLE_LEADPACK_DELIVERY_UNLOCK_READBACK",
        )
        self.assertEqual(task_123["status"], "COMPLETED")
        self.assertEqual(task_123["planning_state"], "COMPLETED")
        self.assertEqual(task_123["completed_commit"], "7fb9e13")
        self.assertEqual(
            task_123["completion_result"],
            "COMPLETED_APPROVED_STAGE9_PAYMENT_DELIVERY_PROVIDER_EXECUTION_READBACK_NO_AUTO_REFUND",
        )
        self.assertEqual(
            task_123["runtime_change_in_packet"],
            "IN_SCOPE_WHEN_ACTIVATED",
        )
        task_126 = self.tasks_by_id["PTL-I100-126-production-live-dependency-and-drill-approval"]
        self.assertEqual(task_126["status"], "COMPLETED")
        self.assertEqual(task_126["planning_state"], "COMPLETED")
        self.assertEqual(task_126["completed_commit"], "fc52e19")
        self.assertEqual(
            task_126["completion_result"],
            "COMPLETED_APPROVED_PRODUCTION_LIVE_DEPENDENCY_AND_DRILL_READBACK",
        )
        completed_114 = {
            row["subpacket_id"]: row for row in task_114["completed_subpackets"]
        }
        self.assertEqual(
            completed_114["PTL-I100-114A-local-public-resource-trading-centers"][
                "completed_commit"
            ],
            "7de630d",
        )
        self.assertEqual(
            completed_114["PTL-I100-114B-provincial-bidding-platforms"][
                "completed_commit"
            ],
            "6b4f91b",
        )
        self.assertEqual(
            completed_114["PTL-I100-114C-national-construction-market-platform"][
                "completed_commit"
            ],
            "2c403d6",
        )
        self.assertEqual(
            completed_114["PTL-I100-114D-credit-china-public-records"][
                "completed_commit"
            ],
            "e75a461",
        )
        self.assertEqual(
            completed_114["PTL-I100-114E-national-enterprise-credit-publicity-system"][
                "completed_commit"
            ],
            "e93b503",
        )
        self.assertEqual(
            completed_114["PTL-I100-114F-government-procurement-public-sites"][
                "completed_commit"
            ],
            "3f6bf5f",
        )
        self.assertEqual(
            completed_114["PTL-I100-114G-tender-agency-public-sites"][
                "completed_commit"
            ],
            "a4f71bb",
        )
        self.assertEqual(
            completed_114["PTL-I100-114H-tenderer-public-notice-pages"][
                "completed_commit"
            ],
            "9e9c033",
        )
        self.assertEqual(
            completed_114["PTL-I100-114I-industry-authority-filing-pages"][
                "completed_commit"
            ],
            "af13a96",
        )
        self.assertIn("docker_compose_local_stack", task_112["capability_gaps_covered"])
        self.assertIn("health_and_readiness_checks", task_112["capability_gaps_covered"])
        serialized_acceptance = yaml.safe_dump(
            self.checklist["tasks"]["PTL-I100-112-production-platform-infrastructure"],
            allow_unicode=True,
        )
        self.assertIn("object storage", serialized_acceptance)
        self.assertIn("explicitly reserved seams", serialized_acceptance)
        self.assertIn("no_live_execution_unlocked", serialized_acceptance)
        self.assertEqual(
            self.checklist["tasks"]["PTL-I100-112-production-platform-infrastructure"][
                "completed_reference_subpackets"
            ],
            [
                "PTL-I100-112A-production-platform-storage-seam",
                "PTL-I100-112B-production-queue-worker-durability",
                "PTL-I100-112C-object-storage-snapshot-durability",
                "PTL-I100-112D-docker-compose-health-readiness",
                "PTL-I100-112E-backup-restore-rollback-readiness",
                "PTL-I100-112F-monitoring-alerting-readiness",
            ],
        )

    def test_final_gate_requires_product_closure_not_just_tests(self) -> None:
        final_entry = self.checklist["tasks"]["PTL-I100-118-full-product-operational-acceptance"]
        reacceptance_entry = self.checklist["tasks"]["PTL-I100-118R-final-product-operational-reacceptance"]

        self.assertTrue(final_entry["final_closure_gate"])
        serialized = yaml.safe_dump(final_entry, allow_unicode=True)
        self.assertIn("real public notice sample", serialized)
        self.assertIn("evidence-pack business closure", serialized)
        self.assertIn("automated refund", serialized)
        result = final_entry["current_118_acceptance_result"]
        self.assertEqual(result["acceptance_result"], "BLOCKED_BY_PRODUCT_OPERATIONAL_GAPS")
        self.assertEqual(result["product_closure_result"], "NOT_CLOSED")
        self.assertTrue(result["owner_internal_loop_operable"])
        self.assertFalse(result["owner_end_to_end_sales_delivery_operable"])
        self.assertEqual(result["closeout_recommendation"], "DO_NOT_CLOSEOUT")
        self.assertEqual(len(result["minimum_followup_task_refs"]), 5)
        self.assertIn(
            "PTL-I100-123-approved-payment-delivery-provider-execution-no-auto-refund",
            result["minimum_followup_task_refs"],
        )
        self.assertTrue(reacceptance_entry["final_reacceptance_gate"])
        serialized_reacceptance = yaml.safe_dump(reacceptance_entry, allow_unicode=True)
        self.assertIn("LOCAL_CONTROLLED_FAKE_PROVIDER", serialized_reacceptance)
        self.assertIn("自动退款", serialized_reacceptance)

    def test_118r_registers_remaining_real_world_product_tasks(self) -> None:
        expected = {
            "PTL-I100-127-owner-operator-frontend-and-customer-portal",
            "PTL-I100-128-real-public-source-field-validation-and-coverage",
            "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
            "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
            "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout",
        }
        self.assertTrue(expected.issubset(self.tasks_by_id))
        self.assertEqual(
            self.tasks_by_id["PTL-I100-127-owner-operator-frontend-and-customer-portal"]["status"],
            "COMPLETED",
        )
        self.assertEqual(
            self.tasks_by_id["PTL-I100-128-real-public-source-field-validation-and-coverage"]["status"],
            "COMPLETED",
        )
        self.assertEqual(
            self.tasks_by_id["PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund"]["status"],
            "COMPLETED",
        )
        self.assertEqual(
            self.tasks_by_id["PTL-I100-130-llm-assisted-parsing-review-and-sales-governance"]["status"],
            "COMPLETED",
        )
        self.assertFalse(
            self.tasks_by_id["PTL-I100-127-owner-operator-frontend-and-customer-portal"][
                "is_current_mainline_next_candidate"
            ]
        )
        self.assertFalse(
            self.tasks_by_id["PTL-I100-128-real-public-source-field-validation-and-coverage"][
                "is_current_mainline_next_candidate"
            ]
        )
        self.assertFalse(
            self.tasks_by_id["PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund"][
                "is_current_mainline_next_candidate"
            ]
        )
        self.assertFalse(
            self.tasks_by_id["PTL-I100-130-llm-assisted-parsing-review-and-sales-governance"][
                "is_current_mainline_next_candidate"
            ]
        )
        self.assertTrue(
            self.tasks_by_id["PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout"][
                "is_current_mainline_next_candidate"
            ]
        )
        for task_id in expected:
            with self.subTest(task_id=task_id):
                if task_id not in {
                    "PTL-I100-127-owner-operator-frontend-and-customer-portal",
                    "PTL-I100-128-real-public-source-field-validation-and-coverage",
                    "PTL-I100-129-real-provider-binding-wecom-email-crm-payment-delivery-no-auto-refund",
                    "PTL-I100-130-llm-assisted-parsing-review-and-sales-governance",
                }:
                    self.assertEqual(self.tasks_by_id[task_id]["status"], "PLANNED")
                self.assertEqual(
                    self.tasks_by_id[task_id]["acceptance_checklist_ref"],
                    f"control/product_acceptance_checklist.yaml#tasks.{task_id}",
                )
                self.assertIn(task_id, self.checklist["tasks"])
                self.assertTrue(self.checklist["tasks"][task_id]["completion_must_prove"])
                self.assertTrue(self.checklist["tasks"][task_id]["redline_checks"])


if __name__ == "__main__":
    unittest.main()
