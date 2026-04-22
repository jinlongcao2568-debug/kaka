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
        self.assertIsInstance(active_packet["runtime_change_in_packet"], str)
        self.assertTrue(active_packet["runtime_change_in_packet"])
        for required_field in (
            "packet_id",
            "backlog_packet_ref",
            "source_blueprint_batch_id",
            "declared_changed_paths",
            "allowed_modification_paths",
        ):
            self.assertIn(required_field, active_packet)
            self.assertTrue(active_packet[required_field])

        scoped_execution_scope = active_packet["scoped_execution_scope"]
        self.assertFalse(scoped_execution_scope["product_task_library_change"])
        self.assertFalse(scoped_execution_scope["external_release_change"])
        self.assertFalse(scoped_execution_scope["stage8_real_execution_change"])
        self.assertFalse(scoped_execution_scope["stage9_real_payment_delivery_refund_change"])
        self.assertFalse(scoped_execution_scope["new_formal_object_enum_gate_exception_semantics"])
        self.assertFalse(scoped_execution_scope["commit_allowed"])
        if scoped_execution_scope["runtime_change"]:
            self.assertNotEqual(active_packet["runtime_change_in_packet"], "OUT_OF_SCOPE")
        else:
            self.assertEqual(active_packet["runtime_change_in_packet"], "OUT_OF_SCOPE")
        self.assertEqual(
            scoped_execution_scope["product_module_registry_change"],
            "control/product_module_registry.yaml" in active_packet["allowed_modification_paths"],
        )
        self.assertIn("control/current_task.yaml remains the only active execution source.", task_library_text)
        self.assertIn(
            "current_mainline_next_candidate is a candidate-pool pointer only; it does not auto-activate",
            task_library_text,
        )
        self.assertEqual(task_library["formal_active_task_source"], "control/current_task.yaml")

        candidate = task_library["current_mainline_next_candidate"]
        self.assertEqual(candidate["runtime_change_in_packet"], "OUT_OF_SCOPE")
        if candidate["planning_state"] == "MAINLINE_COMPLETE":
            self.assertIsNone(candidate["task_id"])
            self.assertIsNone(candidate["packet_id"])
        else:
            self.assertTrue(candidate["task_id"])
            self.assertEqual(candidate["planning_state"], "REALITY_ALIGNMENT_QUEUED")
        self.assertIn("planning_state: MAINLINE_COMPLETE", task_library_text)
        self.assertIn("当前 product mainline pool 内 S12/S23/S34/S45/S56/S67/S7/S78/S89/INT 均已 completed", task_library_text)
        self.assertIn("现在没有自动 next candidate", task_library_text)
        self.assertIn("后续进入新主线、模块拆分、强化包或外发 unlock，都必须另开 task packet 并人工确认", task_library_text)
        self.assertIn("external release / Stage8 / Stage9 红线不变", task_library_text)

        completed_mainline_task_ids = (
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
        )
        task_index = {task["task_id"]: task for task in task_library["tasks"]}
        for task_id in completed_mainline_task_ids:
            task_entry = task_index[task_id]
            self.assertEqual(task_entry["status"], "COMPLETED")
            self.assertEqual(task_entry["planning_state"], "COMPLETED")
            self.assertFalse(task_entry["is_current_mainline_next_candidate"])
        if candidate["planning_state"] == "MAINLINE_COMPLETE":
            self.assertFalse(
                any(task.get("is_current_mainline_next_candidate") is True for task in task_library["tasks"])
            )

        self.assertIn("本文件是**纯导航图**", route_map_text)
        self.assertIn("非当前任务源", route_map_text)
        self.assertIn("只作导航提示，不决定执行顺序", route_map_text)
        self.assertIn("非状态源", route_map_text)
        self.assertIn("非完整 backlog", route_map_text)
        self.assertIn("不是状态源、执行顺序源", route_map_text)
        self.assertIn("Stage1-9 + INT 当前产品主线闭合完成", route_map_text)
        self.assertIn("当前没有自动 next candidate", route_map_text)
        self.assertIn("post-mainline 方向选择当前只作导航提示", route_map_text)
        self.assertIn("当前推荐方向仅作导航建议，不是已激活任务", route_map_text)
        self.assertIn("Stage7 模块边界重构", route_map_text)
        self.assertIn("Stage1-5 当前代码现状统一按 `PARTIAL_RUNTIME` 理解", route_map_text)
        self.assertIn("Stage6-9 当前代码现状统一按 `HEAVY_RUNTIME` 理解", route_map_text)
        self.assertIn("不是 live execution", route_map_text)
        self.assertIn("PTL-GOV-116-mainline-candidate-shift-to-INT", route_map_text)
        self.assertIn("PTL-INT-internal-preview-surface-envelope", route_map_text)
        self.assertIn("已完成 scoped-execution 并提交 `cfc5265`", route_map_text)
        self.assertIn("本文件仍只提供近端导航提示", route_map_text)
        self.assertIn("不提供状态源、执行顺序源、完整 backlog 或 release 放行", route_map_text)
        self.assertIn("209c4cd", route_map_text)
        self.assertIn("PTL-S89-outreach-writeback-delivery-governance", route_map_text)
        self.assertIn("c36dd9d", route_map_text)
        self.assertIn("PTL-S78-contact-candidate-compliance-preview` scoped-execution 已完成并提交", route_map_text)
        redline_surface = "\n".join(
            (repo_status_text, route_map_text, json.dumps(active_packet, ensure_ascii=False))
        )
        for redline_token in (
            "external release",
            "Stage 8 real execution",
            "Stage 9 real payment",
            "blocked",
        ):
            self.assertIn(redline_token, redline_surface)


if __name__ == "__main__":
    unittest.main()
