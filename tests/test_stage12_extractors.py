from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestStage12Extractors(unittest.TestCase):
    def test_source_registry_declares_scoped_execution_skeleton_boundary(self) -> None:
        registry = load_json("contracts/governance/source_registry.json")
        authority = registry["canonical_authority"]

        self.assertEqual(registry["contract_scope"], "stage1_to_stage2_authoritative_source_route_clock_formal_skeleton")
        self.assertEqual(registry["execution_scope"], "scoped_execution")
        self.assertEqual(registry["implementation_boundary"]["mode"], "FORMAL_SKELETON_ONLY")
        self.assertEqual(registry["implementation_boundary"]["runtime_state"], "NOT_IMPLEMENTED_IN_PACKET")
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

        self.assertEqual(catalog["contract_scope"], "stage1_to_stage2_authoritative_source_route_clock_formal_skeleton")
        self.assertEqual(catalog["execution_scope"], "scoped_execution")
        self.assertEqual(catalog["implementation_boundary"]["mode"], "FORMAL_SKELETON_ONLY")
        self.assertEqual(catalog["implementation_boundary"]["runtime_state"], "NOT_IMPLEMENTED_IN_PACKET")
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
        self.assertEqual(contract["implementation_boundary"]["mode"], "FORMAL_SKELETON_ONLY")
        self.assertEqual(contract["implementation_boundary"]["runtime_state"], "NOT_IMPLEMENTED_IN_PACKET")
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

        self.assertEqual(interfaces["stage2_collection_clock_version_extractor"]["implementation_boundary"]["mode"], "FORMAL_SKELETON_ONLY")
        self.assertEqual(interfaces["stage2_collection_clock_version_extractor"]["implementation_boundary"]["runtime_state"], "NOT_IMPLEMENTED_IN_PACKET")

    def test_h01_contract_freezes_authoritative_fields_without_runtime_fallback(self) -> None:
        handoff = load_json("handoff/stage1_to_stage2/contract.json")

        self.assertEqual(handoff["packet_id"], "PTL-PKT-S12-source-route-clock-authority")
        self.assertEqual(handoff["execution_scope"], "scoped_execution")
        self.assertEqual(handoff["implementation_boundary"]["mode"], "FORMAL_SKELETON_ONLY")
        self.assertEqual(handoff["implementation_boundary"]["runtime_state"], "NOT_IMPLEMENTED_IN_PACKET")
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
        for field_name in handoff["required_payload_fields"]:
            self.assertIn(field_name, payload)
        for field_name in (
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, payload)


if __name__ == "__main__":
    unittest.main()
