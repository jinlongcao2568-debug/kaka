from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_json(relative_path: str) -> dict:
    return json.loads(read_text(relative_path))


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read_text(relative_path))


class TestExternalUnlockPrerequisites(unittest.TestCase):
    def test_future_unlock_decision_matrix_covers_required_domains_and_fields(self) -> None:
        decision = read_json("contracts/release/future_unlock_decision_matrix.json")
        domains = {entry["capability_domain_id"]: entry for entry in decision["capability_domains"]}

        required_domains = {
            "external_software_release",
            "leadpack_external_delivery",
            "stage8_live_execution",
            "stage9_live_payment_execution",
            "stage9_live_delivery_execution",
            "model_provider_externalized_usage",
            "tool_provider_externalized_usage",
            "source_vendor_externalized_usage",
            "external_export_surface",
        }
        self.assertEqual(set(domains.keys()), required_domains)
        self.assertEqual(
            set(decision["decision_buckets"]["FUTURE_UNLOCK_CANDIDATE"]),
            {"leadpack_external_delivery", "source_vendor_externalized_usage", "external_export_surface"},
        )
        self.assertEqual(
            set(decision["decision_buckets"]["DENY_BY_DEFAULT_CONTINUE"]),
            {
                "external_software_release",
                "stage8_live_execution",
                "stage9_live_payment_execution",
                "stage9_live_delivery_execution",
                "model_provider_externalized_usage",
            },
        )
        self.assertEqual(
            set(decision["decision_buckets"]["LONG_TERM_BLOCKED_OR_NEVER_DEFAULT_OPEN"]),
            {"tool_provider_externalized_usage"},
        )

        required_fields = {
            "decision_status",
            "decision_rationale",
            "recommended_next_phase",
            "minimum_next_batch_type",
            "required_preconditions_already_met",
            "remaining_blockers",
            "future_unlock_sequence_order",
            "default_position_after_decision",
            "why_not_now",
            "never_default_open",
        }
        for domain_id, entry in domains.items():
            self.assertTrue(required_fields.issubset(entry.keys()), domain_id)
            self.assertTrue(entry["required_preconditions_already_met"], domain_id)
            self.assertTrue(entry["remaining_blockers"], domain_id)

        self.assertEqual(decision["recommended_sequence"][0]["capability_domain_id"], "leadpack_external_delivery")

    def test_prerequisite_matrix_covers_required_domains_and_fields(self) -> None:
        matrix = read_json("contracts/release/external_unlock_prerequisite_matrix.json")
        domains = {entry["capability_domain_id"]: entry for entry in matrix["capability_domains"]}

        required_domains = {
            "external_software_release",
            "leadpack_external_delivery",
            "stage8_live_execution",
            "stage9_live_payment_execution",
            "stage9_live_delivery_execution",
            "model_provider_externalized_usage",
            "tool_provider_externalized_usage",
            "source_vendor_externalized_usage",
            "external_export_surface",
        }
        self.assertEqual(set(domains.keys()), required_domains)
        self.assertIn("PERMANENTLY_BLOCKED", matrix["unlock_tier_vocabulary"])
        self.assertIn("EXTERNAL_CONTROLLED_OPENING_UNTIL_PREREQS_MET", matrix["unlock_tier_vocabulary"])

        required_fields = {
            "current_default_status",
            "future_unlock_allowed",
            "unlock_tier",
            "minimum_prerequisite_level",
            "required_gates",
            "evidence_pack_required",
            "required_test_suites",
            "required_release_checks",
            "required_owner_signoffs",
            "required_control_assets",
            "required_runtime_modes",
            "required_shadow_or_canary_state",
            "unlock_denial_conditions",
        }
        for domain_id, entry in domains.items():
            self.assertTrue(required_fields.issubset(entry.keys()), domain_id)
            self.assertTrue(entry["evidence_pack_required"], domain_id)
            self.assertTrue(entry["required_owner_signoffs"], domain_id)
            self.assertTrue(entry["unlock_denial_conditions"], domain_id)

        self.assertEqual(
            domains["leadpack_external_delivery"]["candidate_matrix_ref"],
            "contracts/release/leadpack_external_delivery_candidate_matrix.json",
        )
        self.assertEqual(
            domains["leadpack_external_delivery"]["activation_prep_evidence_pack_ref"],
            "contracts/release/leadpack_activation_prep_evidence_pack.json",
        )
        self.assertEqual(
            domains["leadpack_external_delivery"]["activation_prep_transition_ref"],
            "contracts/release/leadpack_activation_prep_transition_matrix.json",
        )

    def test_external_export_surface_remains_future_unlock_candidate_not_live(self) -> None:
        decision = read_json("contracts/release/future_unlock_decision_matrix.json")
        matrix = read_json("contracts/release/external_unlock_prerequisite_matrix.json")
        ledger = read_yaml("control/product_doc_runtime_coverage_ledger.yaml")

        decision_domains = {
            entry["capability_domain_id"]: entry
            for entry in decision["capability_domains"]
        }
        prerequisite_domains = {
            entry["capability_domain_id"]: entry
            for entry in matrix["capability_domains"]
        }
        capability = next(
            item
            for item in ledger["capabilities"]
            if item["capability_id"] == "FORMAL_CLIENT_EXPORT_AND_PAGE_LAYER"
        )

        self.assertEqual(
            decision_domains["external_export_surface"]["decision_status"],
            "FUTURE_UNLOCK_CANDIDATE",
        )
        self.assertEqual(
            prerequisite_domains["external_export_surface"]["current_default_status"],
            "BLOCKED",
        )
        self.assertEqual(
            prerequisite_domains["external_export_surface"]["unlock_tier"],
            "EXTERNAL_CONTROLLED_OPENING_UNTIL_PREREQS_MET",
        )
        self.assertTrue(capability["external_or_live_capability"])
        self.assertIn("RESERVED_NOT_LIVE", capability["classification"])
        self.assertIn("BLOCKED_BY_GOVERNANCE", capability["classification"])
        self.assertNotIn("INTERNAL_IMPLEMENTED", capability["classification"])

    def test_prerequisite_state_and_manifests_reference_baseline(self) -> None:
        state = read_yaml("control/external_unlock_prerequisite_state.yaml")
        decision_state = read_yaml("control/future_unlock_decision_state.yaml")
        release_manifest = read_yaml("control/release_manifest.yaml")
        model_release_manifest = read_yaml("control/model_release_manifest.yaml")
        runtime_inventory = read_yaml("control/runtime_inventory.yaml")

        self.assertEqual(state["future_unlock_decision_batch_readiness"], "READY_FOR_FUTURE_UNLOCK_DECISION_BATCH")
        self.assertEqual(state["external_release_status"], "BLOCKED")
        self.assertFalse(state["unlock_batch_executed"])
        self.assertTrue(state["decision_batch_executed"])
        self.assertEqual(state["repo_readiness_at_decision_time"], "READY_FOR_POST-R6_CANDIDATE_GAP_BATCH")
        self.assertEqual(decision_state["repo_readiness_at_decision_time"], "READY_FOR_POST-R6_CANDIDATE_GAP_BATCH")
        self.assertFalse(decision_state["approved_for_unlock_implementation"])
        self.assertEqual(
            state["leadpack_candidate_matrix_ref"],
            "contracts/release/leadpack_external_delivery_candidate_matrix.json",
        )
        self.assertEqual(
            state["leadpack_activation_prep_evidence_pack_ref"],
            "contracts/release/leadpack_activation_prep_evidence_pack.json",
        )
        self.assertEqual(
            decision_state["leadpack_candidate_matrix_ref"],
            "contracts/release/leadpack_external_delivery_candidate_matrix.json",
        )
        self.assertEqual(
            decision_state["leadpack_activation_prep_evidence_pack_ref"],
            "contracts/release/leadpack_activation_prep_evidence_pack.json",
        )
        self.assertEqual(
            state["domain_states"]["leadpack_external_delivery"]["activation_prep_status"],
            "ACTIVATION_PREP_READY_FOR_REVIEW",
        )
        self.assertEqual(
            state["domain_states"]["leadpack_external_delivery"]["implementation_prep_readiness_gate_status"],
            "FORMAL_HOLD_SOURCES_DEFINED_NOT_IMPLEMENTATION_APPROVED",
        )
        self.assertEqual(
            state["domain_states"]["leadpack_external_delivery"]["implementation_decision_readiness_packet_status"],
            "PACKET_HELD",
        )
        self.assertTrue(
            state["domain_states"]["leadpack_external_delivery"]["implementation_decision_readiness_packet_review_only"]
        )
        self.assertFalse(state["domain_states"]["leadpack_external_delivery"]["implementation_decision_ready"])
        self.assertIn(
            "review_gate",
            state["domain_states"]["leadpack_external_delivery"]["implementation_decision_hold_sources"],
        )
        self.assertEqual(
            decision_state["followup_states"]["leadpack_external_delivery"]["activation_prep_status"],
            "ACTIVATION_PREP_READY_FOR_REVIEW",
        )
        self.assertIn("future_external_unlock_prerequisites", release_manifest)
        self.assertIn("future_external_unlock_decision", release_manifest)
        self.assertIn("capability_runtime_projection", release_manifest)
        self.assertIn("future_externalization_prerequisites", model_release_manifest)
        self.assertIn("future_externalization_decision", model_release_manifest)
        self.assertIn("control_projection_consumption_boundary", model_release_manifest)
        self.assertIn("future_unlock_tier_vocabulary", runtime_inventory)
        self.assertIn("future_unlock_domain_map", runtime_inventory)
        self.assertIn("future_unlock_decision_matrix_ref", runtime_inventory)
        self.assertIn("control_projection_consumption_boundary", runtime_inventory)

    def test_release_and_model_assets_expose_prerequisite_rules(self) -> None:
        release_gates = read_json("contracts/release/release_gates.json")
        runtime_policy = read_json("contracts/release/runtime_policy_catalog.json")
        model_gates = read_json("contracts/model/model_release_gates.json")
        eval_suites = read_json("contracts/model/eval_suite_catalog.json")
        output_targets = read_json("contracts/model/output_target_matrix.json")

        future_gate_ids = {entry["gateId"] for entry in release_gates["future_unlock_prerequisite_gates"]}
        self.assertTrue(
            {
                "external_unlock_evidence_pack_ready",
                "external_unlock_owner_signoff_ready",
                "external_unlock_shadow_canary_ready",
                "external_unlock_rollback_ready",
                "model_externalization_eval_ready",
                "provider_externalization_boundary_ready",
            }.issubset(future_gate_ids)
        )
        self.assertIn("future_unlock_decision_matrix_ref", release_gates)
        self.assertIn("future_unlock_decision_rules", release_gates)
        self.assertIn("future_unlock_domains", runtime_policy)
        runtime_domains = {entry["capability_domain_id"] for entry in runtime_policy["future_unlock_domains"]}
        self.assertIn("leadpack_external_delivery", runtime_domains)
        self.assertIn("future_externalization_prerequisites", model_gates)
        self.assertIn("future_externalization_decision_policy", model_gates)
        self.assertIn("future_externalization_prerequisites", model_gates)

        suite_ids = {suite["suite_id"] for suite in eval_suites["suites"]}
        self.assertTrue(
            {"EVAL-EXTERNAL-SHADOW", "EVAL-EXTERNAL-BOUNDARY", "EVAL-EXTERNAL-CANARY"}.issubset(suite_ids)
        )
        self.assertIn("future_external_unlock_constraints", output_targets)
        self.assertIn("decision_matrix_ref", output_targets["future_external_unlock_constraints"])

    def test_boundary_and_coverage_keep_deny_by_default_rules(self) -> None:
        boundary = read_json("contracts/governance/public_boundary_registry.json")
        coverage = read_json("contracts/governance/coverage_registry.json")
        never_default_open = set(boundary["future_unlock_guardrails"]["never_default_open_capabilities"])

        self.assertTrue(boundary["future_unlock_guardrails"]["external_release_controlled_opening_required_until_prereqs_met"])
        self.assertTrue(coverage["future_unlock_constraints"]["coverage_never_sufficient_alone"])
        self.assertEqual(
            boundary["future_unlock_guardrails"]["leadpack_candidate_matrix_ref"],
            "contracts/release/leadpack_external_delivery_candidate_matrix.json",
        )
        self.assertEqual(
            coverage["future_unlock_constraints"]["leadpack_candidate_matrix_ref"],
            "contracts/release/leadpack_external_delivery_candidate_matrix.json",
        )
        self.assertEqual(
            boundary["future_unlock_guardrails"]["decision_matrix_ref"],
            "contracts/release/future_unlock_decision_matrix.json",
        )
        self.assertEqual(
            coverage["future_unlock_constraints"]["decision_matrix_ref"],
            "contracts/release/future_unlock_decision_matrix.json",
        )
        self.assertEqual(
            never_default_open,
            {
                "personal_contact_channels",
                "d_tier_or_governed_inputs_to_external_surfaces",
                "direct_stage8_stage9_object_export",
            },
        )

    def test_review_gate_keeps_r6_assets_classified_after_post_r6_batches(self) -> None:
        review_gate = read_yaml("control/review_gate_matrix.yaml")
        current_task = read_yaml("control/current_task.yaml")
        source_registry = read_yaml("control/source_blueprint_registry.yaml")

        domain_ids = {entry["domain_id"] for entry in review_gate["domains"]}
        self.assertIn("future_external_unlock_prereq_core", domain_ids)
        self.assertIn("future_external_unlock_decision", domain_ids)
        self.assertIn("future_external_unlock_activation", domain_ids)

        decision_domain = next(
            entry for entry in review_gate["domains"] if entry["domain_id"] == "future_external_unlock_decision"
        )
        activation_domain = next(
            entry for entry in review_gate["domains"] if entry["domain_id"] == "future_external_unlock_activation"
        )
        self.assertEqual(decision_domain["change_class"], "MANDATORY_HUMAN_REVIEW")
        self.assertEqual(activation_domain["change_class"], "STOP_AND_ESCALATE")

        task_packet = current_task["currentTask"]["task_packet"]
        self.assertTrue(task_packet["packet_id"])
        self.assertTrue(task_packet["subpacket_id"])
        self.assertTrue(task_packet["backlog_packet_ref"])
        self.assertEqual(task_packet["packet_kind"], "EXECUTABLE_SCOPED_SUBPACKET")
        registry = source_registry["registered_blueprints"]
        registered_blueprints = {entry["blueprint_id"] for entry in registry}
        self.assertIn(task_packet["source_blueprint_batch_id"], registered_blueprints)
        self.assertTrue({f"B{i}" for i in range(0, 11)}.issubset(registered_blueprints))
        self.assertTrue({f"FF-{i:02d}" for i in range(1, 19)}.issubset(registered_blueprints))
        self.assertTrue(
            {
                "POST-FF-CONTROL-01",
                "POST-FF-REPORT-01",
                "POST-FF-GIT-01",
            }.issubset(registered_blueprints)
        )

        class_rank = {entry["id"]: entry["rank"] for entry in review_gate["change_classes"]}
        domain_by_id = {entry["domain_id"]: entry for entry in review_gate["domains"]}
        declared_domains = set(task_packet["change_domains"])
        required_class_rank = max(
            class_rank[domain_by_id[domain_id]["change_class"]]
            for domain_id in declared_domains
            if domain_id in domain_by_id
        )
        self.assertGreaterEqual(class_rank[task_packet["change_class"]], required_class_rank)
        self.assertIn("automation_control_core", declared_domains)
        self.assertTrue(task_packet["human_review_required"])

        owner_reviews = set(task_packet["owner_reviews_required"])
        self.assertIn("automation_owner", owner_reviews)
        guarded_domains = {
            "future_external_unlock_prereq_core",
            "future_external_unlock_decision",
            "provider_vendor_source_policy_core",
            "governance_release_core",
        }
        if declared_domains & guarded_domains:
            required_owner_reviews = {
                owner
                for domain_id in declared_domains & guarded_domains
                for owner in domain_by_id[domain_id]["required_owner_reviews"]
            }
            self.assertTrue(required_owner_reviews.issubset(owner_reviews))
        self.assertTrue(
            {
                "not an external unlock implementation",
                "不改变 canonical readiness",
                "不执行 public software release",
                "不无审批/无审计发送",
                "不绕过 provider config / sandbox / approval / audit / operator action",
                "不新增业务对象、枚举、gate、exception 语义",
            }.issubset(set(task_packet["non_goals"]))
        )
        self.assertEqual(current_task["currentStatus"], "READY_FOR_POST-REPAIR_MAINLINE_SELECTION")

    def test_release_and_regression_assets_cover_future_unlock_prereqs(self) -> None:
        release = read_json("contracts/testing/release_checklist.json")
        regression = read_json("contracts/testing/regression_manifest.json")

        release_item_ids = {
            item["itemId"]
            for section in release["sections"]
            for item in section["items"]
        }
        for item_id in (
            "REL-120",
            "REL-121",
            "REL-122",
            "REL-123",
            "REL-124",
            "REL-125",
            "REL-126",
            "REL-127",
            "REL-128",
            "REL-129",
            "REL-130",
            "REL-131",
            "REL-132",
            "REL-133",
            "REL-134",
            "REL-135",
            "REL-136",
            "REL-137",
            "REL-138",
            "REL-139",
            "REL-140",
            "REL-141",
            "REL-142",
            "REL-154",
            "REL-155",
            "REL-156",
            "REL-157",
            "REL-158",
            "REL-159",
            "REL-173",
            "REL-174",
            "REL-175",
            "REL-176",
            "REL-177",
            "REL-178",
            "REL-179",
            "REL-180",
            "REL-181",
            "REL-182",
            "REL-183",
            "REL-184",
            "REL-185",
        ):
            self.assertIn(item_id, release_item_ids)

        suite_ids = {suite["suite_id"] for suite in regression["suites"]}
        for suite_id in (
            "REG-FUTURE-UNLOCK-PREREQUISITES",
            "REG-FUTURE-UNLOCK-EVIDENCE-PACK",
            "REG-FUTURE-UNLOCK-REVIEW-GATE",
            "REG-FUTURE-UNLOCK-DECISION-MATRIX",
            "REG-FUTURE-UNLOCK-STATE-SYNC",
            "REG-LEADPACK-CANDIDATE-GAP",
            "REG-LEADPACK-ACTIVATION-PREP",
            "REG-LEADPACK-ACTIVATION-DESIGN-PREP",
            "REG-LEADPACK-IMPLEMENTATION-DECISION-READINESS-PACKET",
        ):
            self.assertIn(suite_id, suite_ids)

    def test_historical_r5_r6_assertions_live_in_history_assets_not_route_map_body(self) -> None:
        decision_matrix = read_json("contracts/release/future_unlock_decision_matrix.json")
        prerequisite_state = read_yaml("control/external_unlock_prerequisite_state.yaml")
        decision_state = read_yaml("control/future_unlock_decision_state.yaml")
        route_map = read_text("docs/AX9S_开发执行路由图.md")
        launch_page = read_text("docs/正式业务代码开发开工裁决页.md")
        status_board = read_text("docs/文档与资产状态板.md")
        repo_status = read_text("control/repo_status.md")

        self.assertNotIn("R5 external unlock prerequisites", route_map)
        self.assertNotIn("R6 future unlock decision", route_map)
        self.assertNotIn("Post-R6 candidate gap", route_map)

        self.assertIn("Formal R6 future unlock decision matrix", decision_matrix["metadata"]["purpose"])
        self.assertEqual(decision_state["state_type"], "FUTURE_UNLOCK_DECISION")
        self.assertEqual(decision_state["decision_scope"], "DECISION_ONLY_NOT_IMPLEMENTATION")
        self.assertFalse(decision_state["approved_for_unlock_implementation"])
        self.assertEqual(prerequisite_state["state_type"], "EXTERNAL_UNLOCK_PREREQUISITE_BASELINE")
        self.assertEqual(prerequisite_state["decision_state_ref"], "control/future_unlock_decision_state.yaml")
        self.assertTrue(prerequisite_state["decision_batch_executed"])

        self.assertIn("R6 结论补充", launch_page)
        self.assertIn("candidate / deny / blocked", launch_page)
        self.assertIn("不构成任何 unlock implementation 批准，也不是当前 repo readiness", launch_page)
        self.assertIn("`control/external_unlock_prerequisite_state.yaml`", status_board)
        self.assertIn("`control/future_unlock_decision_state.yaml`", status_board)
        self.assertIn("R6 决策时点快照，不是当前 repo readiness 状态源", status_board)
        self.assertIn("READY_FOR_POST-REPAIR_MAINLINE_SELECTION", status_board)
        self.assertIn("READY_FOR_POST-REPAIR_MAINLINE_SELECTION", repo_status)
        self.assertIn("READY_FOR_INTERNAL_LEADOPS_DEVELOPMENT", repo_status)
        self.assertIn("Mainline Selection Ready: true", repo_status)


if __name__ == "__main__":
    unittest.main()
