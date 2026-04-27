from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CHANGE_IN_PACKET = "CONTROLLED_STAGE1_2_RUNTIME_CLOSURE"


def load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def load_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_yaml(relative_path: str) -> dict:
    return yaml.safe_load(load_text(relative_path))


class TestStage12Extractors(unittest.TestCase):
    def test_source_registry_declares_scoped_execution_partial_runtime_boundary(self) -> None:
        registry = load_json("contracts/governance/source_registry.json")
        authority = registry["canonical_authority"]

        self.assertEqual(registry["contract_scope"], "stage1_to_stage2_authoritative_source_route_clock_partial_runtime_alignment")
        self.assertEqual(registry["execution_scope"], "scoped_execution")
        self.assertEqual(registry["implementation_boundary"]["mode"], "PARTIAL_RUNTIME_ALIGNMENT_ONLY")
        self.assertEqual(registry["implementation_boundary"]["existing_runtime_state"], "PARTIAL_RUNTIME")
        self.assertEqual(registry["implementation_boundary"]["runtime_change_in_packet"], RUNTIME_CHANGE_IN_PACKET)
        self.assertNotIn("NOT_IMPLEMENTED_IN_PACKET", json.dumps(registry, ensure_ascii=False))
        self.assertEqual(authority["producer_stage"], "stage1_tasking")
        self.assertEqual(authority["consumer_stages"], ["stage2_ingestion"])
        self.assertEqual(authority["producer_interface"], "stage1_source_route_extractor")
        self.assertFalse(authority["live_external_source_enabled"])
        self.assertEqual(authority["adapter_contract_state"], "RESERVED_NOT_LIVE")
        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ):
            self.assertIn(field_name, authority["canonical_fields"])
        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ):
            self.assertIn(field_name, authority["consumer_must_not_recompute_fields"])

    def test_route_policy_catalog_aligns_with_source_registry_for_source_route_clock(self) -> None:
        registry = load_json("contracts/governance/source_registry.json")
        catalog = load_json("contracts/governance/route_policy_catalog.json")
        policy_index = {entry["route_policy_id"]: entry for entry in catalog["policies"]}
        authority = catalog["canonical_authority"]

        self.assertEqual(catalog["contract_scope"], "stage1_to_stage2_authoritative_source_route_clock_partial_runtime_alignment")
        self.assertEqual(catalog["execution_scope"], "scoped_execution")
        self.assertEqual(catalog["implementation_boundary"]["mode"], "PARTIAL_RUNTIME_ALIGNMENT_ONLY")
        self.assertEqual(catalog["implementation_boundary"]["existing_runtime_state"], "PARTIAL_RUNTIME")
        self.assertEqual(catalog["implementation_boundary"]["runtime_change_in_packet"], RUNTIME_CHANGE_IN_PACKET)
        self.assertNotIn("NOT_IMPLEMENTED_IN_PACKET", json.dumps(catalog, ensure_ascii=False))
        self.assertEqual(authority["producer_stage"], "stage1_tasking")
        self.assertEqual(authority["consumer_stages"], ["stage2_ingestion"])
        self.assertEqual(authority["producer_interface"], "stage1_source_route_extractor")
        self.assertFalse(authority["live_external_source_enabled"])
        self.assertEqual(authority["adapter_contract_state"], "RESERVED_NOT_LIVE")
        for field_name in (
            "route_policy_id",
            "default_route",
            "fallback_route",
            "clock_chain_relation",
            "action_deadline_relation",
        ):
            self.assertIn(field_name, authority["canonical_fields"])

        for entry in registry["entries"]:
            policy = policy_index[entry["route_policy_id"]]
            self.assertIn(entry["source_registry_id"], policy["source_registry_refs"])
            self.assertEqual(policy["default_route"], entry["default_route"])
            self.assertEqual(policy["fallback_route"], entry["fallback_route"])
            self.assertEqual(
                policy["clock_chain_relation"]["clock_precedence_rule_id"],
                entry["clock_precedence_rule_id"],
            )

    def test_stage12_extractor_contract_freezes_h01_authority_boundary(self) -> None:
        contract = load_json("contracts/governance/stage12_extractor_contract.json")
        authority = contract["authoritative_contract"]
        interfaces = {entry["interface_id"]: entry for entry in contract["interfaces"]}

        self.assertEqual(contract["packet_id"], "PTL-PKT-S12-source-route-clock-authority")
        self.assertEqual(contract["execution_scope"], "scoped_execution")
        self.assertEqual(contract["implementation_boundary"]["mode"], "PARTIAL_RUNTIME_ALIGNMENT_ONLY")
        self.assertEqual(contract["implementation_boundary"]["existing_runtime_state"], "PARTIAL_RUNTIME")
        self.assertEqual(contract["implementation_boundary"]["runtime_change_in_packet"], RUNTIME_CHANGE_IN_PACKET)
        self.assertNotIn("NOT_IMPLEMENTED_IN_PACKET", json.dumps(contract, ensure_ascii=False))
        self.assertEqual(authority["handoff_id"], "H-01-STAGE1-TO-STAGE2")
        self.assertEqual(authority["producer_stage"], "stage1_tasking")
        self.assertEqual(authority["consumer_stage"], "stage2_ingestion")
        self.assertEqual(authority["authoritative_dimensions"], ["source", "route", "clock"])
        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ):
            self.assertIn(field_name, authority["consumer_must_not_recompute_fields"])

        self.assertEqual(interfaces["stage1_source_route_extractor"]["consumer_stage"], 2)
        self.assertTrue(interfaces["stage1_source_route_extractor"]["consumer_must_not_recompute"])
        self.assertIn("route_policy_id", interfaces["stage1_source_route_extractor"]["owned_fields"])

        self.assertEqual(interfaces["stage1_time_window_extractor"]["consumer_stage"], 2)
        self.assertTrue(interfaces["stage1_time_window_extractor"]["consumer_must_not_recompute"])
        self.assertIn("clock_precedence_rule_id", interfaces["stage1_time_window_extractor"]["owned_fields"])
        self.assertIn("current_action_deadline_at_optional", interfaces["stage1_time_window_extractor"]["owned_fields"])
        self.assertNotIn(
            "payload.window_priority_policy/clock_resolution_rule_id",
            interfaces["stage1_time_window_extractor"]["input_priority"],
        )

        self.assertEqual(
            interfaces["stage2_collection_clock_version_extractor"]["implementation_boundary"]["mode"],
            "PARTIAL_RUNTIME_ALIGNMENT_ONLY",
        )
        self.assertEqual(
            interfaces["stage2_collection_clock_version_extractor"]["implementation_boundary"]["existing_runtime_state"],
            "PARTIAL_RUNTIME",
        )
        self.assertEqual(
            interfaces["stage2_collection_clock_version_extractor"]["implementation_boundary"]["runtime_change_in_packet"],
            RUNTIME_CHANGE_IN_PACKET,
        )
        self.assertTrue(interfaces["stage2_collection_clock_version_extractor"]["consumer_must_not_recompute"])
        self.assertIn(
            "clock_precedence_rule_id_source=h01_authority",
            interfaces["stage2_collection_clock_version_extractor"]["fallback_taxonomy"],
        )

    def test_h01_contract_freezes_authoritative_fields_without_runtime_rewrite(self) -> None:
        handoff = load_json("handoff/stage1_to_stage2/contract.json")

        self.assertEqual(handoff["packet_id"], "PTL-PKT-S12-source-route-clock-authority")
        self.assertEqual(handoff["execution_scope"], "scoped_execution")
        self.assertEqual(handoff["implementation_boundary"]["mode"], "PARTIAL_RUNTIME_ALIGNMENT_ONLY")
        self.assertEqual(handoff["implementation_boundary"]["existing_runtime_state"], "PARTIAL_RUNTIME")
        self.assertEqual(handoff["implementation_boundary"]["runtime_change_in_packet"], RUNTIME_CHANGE_IN_PACKET)
        self.assertNotIn("NOT_IMPLEMENTED_IN_PACKET", json.dumps(handoff, ensure_ascii=False))
        self.assertEqual(handoff["handoff_id"], "H-01-STAGE1-TO-STAGE2")
        self.assertEqual(handoff["from_stage"], 1)
        self.assertEqual(handoff["to_stage"], 2)
        self.assertEqual(handoff["authoritative_dimensions"], ["source", "route", "clock"])
        self.assertEqual(
            handoff["producer_interface_refs"],
            ["stage1_source_route_extractor", "stage1_time_window_extractor"],
        )
        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ):
            self.assertIn(field_name, handoff["required_payload_fields"])
            self.assertIn(field_name, handoff["consumer_runtime_required_fields"])
            self.assertIn(field_name, handoff["consumer_must_not_recompute_fields"])

    def test_h01_example_matches_contract_required_payload_shape(self) -> None:
        handoff = load_json("handoff/stage1_to_stage2/contract.json")
        example = load_json("handoff/stage1_to_stage2/example.json")
        payload = example["payload"]

        self.assertEqual(example["packet_id"], "PTL-PKT-S12-source-route-clock-authority")
        self.assertEqual(example["execution_scope"], "scoped_execution")
        self.assertEqual(example["implementation_boundary"]["mode"], "PARTIAL_RUNTIME_ALIGNMENT_ONLY")
        self.assertEqual(example["implementation_boundary"]["existing_runtime_state"], "PARTIAL_RUNTIME")
        self.assertEqual(example["implementation_boundary"]["runtime_change_in_packet"], RUNTIME_CHANGE_IN_PACKET)
        for field_name in handoff["required_payload_fields"]:
            self.assertIn(field_name, payload)
        for field_name in (
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, payload)

    def test_planning_surfaces_keep_transition_safe_active_source_relationship(self) -> None:
        task_library = load_yaml("control/product_task_library.yaml")
        current_task = load_yaml("control/current_task.yaml")
        task_library_text = load_text("control/product_task_library.yaml")
        current_task_text = load_text("control/current_task.yaml")
        repo_status_text = load_text("control/repo_status.md")
        route_map_text = load_text("docs/AX9S_开发执行路由图.md")

        self.assertIn("current_task -> product_task_library -> repo_status", current_task_text)
        self.assertIn("current_task -> product_task_library -> repo_status", repo_status_text)

        active_task = current_task["currentTask"]
        self.assertTrue(active_task["task_id"])
        self.assertIn("task_packet", active_task)

        active_packet = active_task["task_packet"]
        self.assertIsInstance(active_packet, dict)
        self.assertEqual(active_packet["packet_kind"], "EXECUTABLE_SCOPED_SUBPACKET")
        self.assertIn(active_packet["execution_mode"], {"ACTIVATION_ONLY", "SCOPED_EXECUTION"})
        self.assertEqual(active_packet["status"], "ACTIVE")
        self.assertTrue(active_packet["packet_id"])
        self.assertTrue(active_packet["backlog_packet_ref"])
        self.assertTrue(active_packet["source_blueprint_batch_id"])

        declared_paths = set(active_packet["declared_changed_paths"])
        allowed_paths = set(active_packet["allowed_modification_paths"])
        self.assertTrue(declared_paths.issubset(allowed_paths))

        impacted_assets = active_packet["impacted_assets"]
        for key in ("docs", "control", "contracts", "handoff", "scripts", "tests", "runtime"):
            self.assertIn(key, impacted_assets)

        scoped_execution_scope = active_packet["scoped_execution_scope"]
        self.assertEqual(
            scoped_execution_scope["product_task_library_change"],
            "control/product_task_library.yaml" in allowed_paths,
        )
        self.assertEqual(
            scoped_execution_scope["product_module_registry_change"],
            "control/product_module_registry.yaml" in allowed_paths,
        )
        if scoped_execution_scope["runtime_change"]:
            self.assertNotEqual(active_packet["runtime_change_in_packet"], "OUT_OF_SCOPE")
        else:
            self.assertEqual(active_packet["runtime_change_in_packet"], "OUT_OF_SCOPE")

        self.assertIn("control/current_task.yaml remains the only active execution source.", task_library_text)
        self.assertIn(
            "current_mainline_next_candidate is a candidate-pool pointer only; it does not auto-activate",
            task_library_text,
        )
        self.assertEqual(task_library["formal_active_task_source"], "control/current_task.yaml")

        candidate = task_library["current_mainline_next_candidate"]
        self.assertEqual(candidate["planning_state"], "CANDIDATE_NOT_ACTIVATED")
        self.assertEqual(candidate["task_id"], "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout")
        self.assertEqual(candidate["packet_id"], "PTL-I100-131-controlled-real-world-e2e-pilot-and-closeout")

        self.assertIn("planning_state: CANDIDATE_NOT_ACTIVATED", task_library_text)
        self.assertIn("PTL-I100-128-real-public-source-field-validation-and-coverage", task_library_text)
        self.assertIn("COMPLETED_CONTROLLED_MANUAL_PUBLIC_SOURCE_FIELD_VALIDATION_AND_COVERAGE_REPORT", task_library_text)
        self.assertIn("PTL-I100-129 已补真实 provider binding readback", task_library_text)
        self.assertIn("PTL-I100-130 已补受治理 model-assist readback", task_library_text)
        self.assertIn("current_mainline_next_candidate 指向 131 仅作候选提示", task_library_text)
        self.assertIn("仅作候选提示，不自动激活", task_library_text)
        self.assertIn("进入 131 仍必须另开 dedicated current_task packet", task_library_text)
        self.assertIn("Execution-level management and reporting should use the P1 -> P8 ladder plus task_ids", task_library_text)
        self.assertIn("external release / Stage8 / Stage9 红线不变", task_library_text)

        completed_task_ids = (
            "PTL-S12-source-route-clock-authority",
            "PTL-S23-public-chain-to-parser-contract",
            "PTL-S34-object-lineage-verification-handoff",
            "PTL-S45-rule-evidence-dual-gate",
            "PTL-S56-project-fact-review-report",
            "PTL-S67-saleable-opportunity-derivation",
            "PTL-S7-price-competitor-offer-resolution",
            "PTL-S78-contact-candidate-compliance-preview",
            "PTL-S89-outreach-writeback-delivery-governance",
            "PTL-INT-internal-preview-surface-envelope",
            "PTL-S8-101-p1-candidate-compliance-boundary-refactor",
            "PTL-S8-102-p2-plan-touch-productization",
            "PTL-INT-101-p3-policy-validator-boundary-split",
            "PTL-INT-102-p4-repository-boundary-hardening",
            "PTL-S9-101-p5-typed-lifecycle-deepening",
            "PTL-S9-102-p6-feedback-writeback-productization",
            "PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion",
            "PTL-INT-104-p8-observability-operator-workbench",
        )
        task_index = {task["task_id"]: task for task in task_library["tasks"]}
        for task_id in completed_task_ids:
            task_entry = task_index[task_id]
            self.assertEqual(task_entry["status"], "COMPLETED")
            self.assertEqual(task_entry["planning_state"], "COMPLETED")
            self.assertFalse(task_entry["is_current_mainline_next_candidate"])
        self.assertEqual(
            task_index["PTL-S8-101-p1-candidate-compliance-boundary-refactor"]["completed_commit"],
            "632c6ae",
        )
        self.assertEqual(
            task_index["PTL-S8-102-p2-plan-touch-productization"]["completed_commit"],
            "9d4662a",
        )
        self.assertEqual(
            task_index["PTL-INT-101-p3-policy-validator-boundary-split"]["completed_commit"],
            "8c7eea3",
        )
        self.assertEqual(
            task_index["PTL-INT-102-p4-repository-boundary-hardening"]["completed_commit"],
            "b8288a7",
        )
        self.assertEqual(
            task_index["PTL-S9-101-p5-typed-lifecycle-deepening"]["completed_commit"],
            "3d9fc74",
        )
        self.assertEqual(
            task_index["PTL-S9-102-p6-feedback-writeback-productization"]["completed_commit"],
            "edff5af",
        )
        self.assertEqual(
            task_index["PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion"]["completed_commit"],
            "2dbfb12",
        )
        self.assertEqual(
            task_index["PTL-INT-104-p8-observability-operator-workbench"]["completed_commit"],
            "b8a2762",
        )
        product_only_manual_selection_ids = [
            task["task_id"]
            for task in task_library["tasks"]
            if task["status"] == "OPEN_FOR_MANUAL_SELECTION"
        ]
        self.assertEqual(product_only_manual_selection_ids, [])

        self.assertNotIn("PTL-GOV-126-p0-current-governance-closeout", task_index)
        self.assertNotIn("PTL-GOV-127-p0b-ax9s-navigation-sync", task_index)
        self.assertNotIn("PTL-GOV-128-p9-future-unlock-prep-only", task_index)
        self.assertNotIn("PTL-S8-governed-touch-deepening", task_index)
        self.assertNotIn("PTL-S9-governed-delivery-deepening", task_index)

        ladder = task_library["post_mainline_execution_ladder"]
        self.assertEqual(ladder["status"], "EFFECTIVE")
        self.assertEqual(ladder["mode"], "MANUAL_SELECTION_ONLY")
        self.assertFalse(ladder["auto_activate_next_candidate"])
        self.assertEqual(ladder["scope"], "PRODUCT_ONLY")
        self.assertEqual(
            ladder["excludes_non_product_tasks"],
            [
                "PTL-GOV-126-p0-current-governance-closeout",
                "PTL-GOV-127-p0b-ax9s-navigation-sync",
                "PTL-GOV-128-p9-future-unlock-prep-only",
            ],
        )
        self.assertEqual(
            ladder["priority_bands"][0]["task_ids"],
            [
                "PTL-S8-101-p1-candidate-compliance-boundary-refactor",
                "PTL-S8-102-p2-plan-touch-productization",
            ],
        )
        self.assertEqual(
            ladder["priority_bands"][1]["task_ids"],
            [
                "PTL-INT-101-p3-policy-validator-boundary-split",
                "PTL-INT-102-p4-repository-boundary-hardening",
                "PTL-S9-101-p5-typed-lifecycle-deepening",
                "PTL-S9-102-p6-feedback-writeback-productization",
            ],
        )
        self.assertEqual(
            ladder["priority_bands"][2]["task_ids"],
            [
                "PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion",
                "PTL-INT-104-p8-observability-operator-workbench",
            ],
        )
        self.assertEqual(task_library["task_count"], len(task_library["tasks"]))
        self.assertIn("P1 -> P2 -> P3 -> P4 -> P5 -> P6 -> P7 -> P8", task_library_text)
        self.assertIn(
            "Execution-level management and reporting should use the P1 -> P8 ladder plus task_ids defined here.",
            task_library_text,
        )
        self.assertIn(
            "Direction-level labels in control/product_module_registry.yaml remain navigation-only and must not replace P1-P8 task_ids in execution-level communication.",
            task_library_text,
        )
        self.assertIn(
            "Execution-level management and reporting should use the P1 -> P8 ladder in control/product_task_library.yaml rather than direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化.",
            repo_status_text,
        )

        self.assertIn("纯导航图", route_map_text)
        self.assertIn("非当前任务源", route_map_text)
        self.assertIn("只作导航提示，不决定执行顺序", route_map_text)
        self.assertIn("不是状态源", route_map_text)
        self.assertIn("执行顺序源", route_map_text)
        self.assertIn("完整 backlog", route_map_text)
        self.assertIn("PTL-I100-128-real-public-source-field-validation-and-coverage", route_map_text)
        self.assertIn("PTL-I100-118R-final-product-operational-reacceptance", route_map_text)
        self.assertIn("PTL-I100-127-owner-operator-frontend-and-customer-portal", route_map_text)
        self.assertIn("PTL-I100-128", route_map_text)
        self.assertIn("PTL-I100-129", route_map_text)
        self.assertIn("PTL-I100-130", route_map_text)
        self.assertIn("PTL-I100-131", route_map_text)
        self.assertIn("130 -> 131", route_map_text)
        self.assertNotIn("当前 active packet：`PTL-I100-112A-production-platform-storage-seam`", route_map_text)
        self.assertNotIn("当前 112A 已激活", route_map_text)

        redline_surface = "\n".join(
            (current_task_text, repo_status_text, route_map_text, json.dumps(active_packet, ensure_ascii=False))
        )
        for redline_token in (
            "external release",
            "Stage 8 real execution",
            "Stage 9 real payment / delivery / refund",
            "blocked",
        ):
            self.assertIn(redline_token, redline_surface)


if __name__ == "__main__":
    unittest.main()
