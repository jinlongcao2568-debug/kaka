from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for search_path in (ROOT / "tests", ROOT / "src"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture, run_internal_chain_to_stage7
from shared.capability_runtime import CapabilityResolver, CapabilityRuntime
from shared.context_packet import ContextPacket
from shared.pipeline import run_internal_chain


class TestCapabilityPermissionLayer(unittest.TestCase):
    def test_model_usage_policy_remains_assist_shadow_and_not_final_decision(self) -> None:
        policy = json.loads((ROOT / "contracts/model/model_usage_policy.json").read_text(encoding="utf-8"))

        self.assertEqual(
            policy["capability_mode_vocabulary_ref"],
            "contracts/release/runtime_policy_catalog.json#capability_mode_vocabulary",
        )
        self.assertTrue(policy["default_rules"]["final_decision_prohibited_all_stages"])
        self.assertTrue(policy["default_rules"]["live_external_provider_prohibited"])
        self.assertIn("review_assist", policy["default_rules"]["allowed_usage_modes"])
        self.assertIn("structured_assist", policy["default_rules"]["allowed_usage_modes"])
        self.assertIn("shadow_evaluation", policy["default_rules"]["allowed_usage_modes"])
        self.assertEqual(set(policy["allowed_action_intents"]), {"PREVIEW_ONLY", "INTERNAL_SOURCE_READ"})
        self.assertTrue(
            {"APPROVAL_EXECUTION", "INTERNAL_WRITEBACK", "LIVE_EXECUTION"}.issubset(
                set(policy["blocked_action_intents"])
            )
        )
        for boundary in policy["stage_boundaries"]:
            with self.subTest(stage=boundary["stage"]):
                self.assertFalse(boundary["hard_dependency"])
                self.assertTrue(boundary["final_decision_prohibited"])
                forbidden = " ".join(boundary["forbidden_actions"]).lower()
                self.assertTrue("decision" in forbidden or "gate" in forbidden or "writeback" in forbidden)

    def test_tool_provider_registry_is_registered_not_bound_and_never_live_default(self) -> None:
        registry = json.loads(
            (ROOT / "contracts/model/tool_provider_registry_catalog.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            registry["capability_mode_vocabulary_ref"],
            "contracts/release/runtime_policy_catalog.json#capability_mode_vocabulary",
        )
        defaults = registry["registry_defaults"]
        self.assertFalse(defaults["direct_mutation_allowed"])
        self.assertFalse(defaults["external_action_enabled"])
        self.assertFalse(defaults["live_execution_enabled"])
        self.assertFalse(defaults["default_open"])
        self.assertFalse(defaults["long_term_default_open_allowed"])
        self.assertIn("LIVE_EXECUTION", defaults["blocked_action_intents"])

        for provider in registry["providers"]:
            with self.subTest(provider=provider["provider_id"]):
                self.assertEqual(provider["current_status"], "REGISTERED_NOT_BOUND")
                self.assertIn(provider["provider_role"], {
                    "ENTERPRISE_INFO_SUPPORT_TOOL",
                    "CONTACT_ENRICHMENT_SUPPORT_TOOL",
                    "INTERNAL_OBJECT_QUERY_TOOL",
                })
                self.assertTrue(provider["audit_capable"])
                self.assertTrue(provider["manual_review_default"])
                self.assertFalse(provider["direct_mutation_allowed"])
                self.assertFalse(provider["external_action_enabled"])
                self.assertFalse(provider["live_execution_enabled"])
                self.assertFalse(provider["default_open"])
                self.assertNotIn("REAL_RUN_READY", provider["allowed_capability_modes"])
                self.assertEqual(set(provider["allowed_action_intents"]), {"PREVIEW_ONLY", "INTERNAL_SOURCE_READ"})
                self.assertIn("LIVE_EXECUTION", provider["blocked_action_intents"])

    def test_tool_usage_policy_uses_canonical_capability_ref_and_blocks_mutation(self) -> None:
        policy = json.loads((ROOT / "contracts/model/tool_usage_policy_catalog.json").read_text(encoding="utf-8"))

        self.assertEqual(
            policy["capability_mode_vocabulary_ref"],
            "contracts/release/runtime_policy_catalog.json#capability_mode_vocabulary",
        )
        self.assertFalse(policy["policy_defaults"]["direct_mutation_allowed"])
        self.assertFalse(policy["policy_defaults"]["external_action_enabled"])
        self.assertFalse(policy["policy_defaults"]["live_execution_enabled"])
        self.assertIn("LIVE_EXECUTION", policy["blocked_action_intents"])
        for entry in policy["policies"]:
            with self.subTest(policy=entry["policy_id"]):
                self.assertTrue(entry["requires_manual_review"])
                self.assertFalse(entry["direct_mutation_allowed"])
                self.assertFalse(entry["external_action_enabled"])
                self.assertFalse(entry["live_execution_enabled"])
                self.assertFalse(entry["default_open"])
                self.assertIn("direct_mutation", entry["forbidden_actions"])
                self.assertIn("direct_external_action", entry["forbidden_actions"])

    def test_runtime_catalog_precedence_contract_is_loaded(self) -> None:
        resolver = CapabilityResolver()
        runtime_policy = json.loads(
            (ROOT / "contracts/release/runtime_policy_catalog.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            resolver.mode_priority_order,
            tuple(runtime_policy["capability_mode_priority_order"]),
        )
        self.assertEqual(
            resolver.effective_mode_source_order,
            tuple(runtime_policy["runtime_resolver_precedence"]["effective_capability_mode_sources"]),
        )
        self.assertEqual(
            resolver.protected_short_circuit_modes,
            tuple(runtime_policy["runtime_resolver_precedence"]["protected_short_circuit_modes"]),
        )
        self.assertEqual(
            resolver.external_blocked_release_level,
            runtime_policy["runtime_resolver_precedence"]["release_layer_redline"],
        )
        self.assertEqual(
            resolver.control_projection_sources_ignored_for_mode_resolution,
            tuple(
                runtime_policy["runtime_resolver_precedence"][
                    "control_projection_sources_ignored_for_mode_resolution"
                ]
            ),
        )

    def test_target_policy_mode_overrides_family_mode(self) -> None:
        resolver = CapabilityResolver()
        context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=1,
            project_id="P-1",
            records={},
            inputs={
                "release_level": "INTERNAL_OPERABLE",
                "approval_state": "NOT_REQUIRED",
            },
        )

        resolution = resolver.resolve(
            context=context,
            capability_family="contact_enrichment",
            requested_action="PREVIEW_ONLY",
            target_type="source_vendor",
            target_role="CONTACT_ENRICHMENT_SOURCE",
            release_level="INTERNAL_OPERABLE",
            approval_state="NOT_REQUIRED",
        )

        self.assertEqual(resolution.capability_mode, "PERMANENTLY_BLOCKED")
        self.assertEqual(resolution.decision, "BLOCK")
        resolved_sources = {entry["source"] for entry in resolution.trace_fields["resolved_from"]}
        self.assertIn("source_vendor_usage_policy", resolved_sources)
        self.assertIn("runtime_policy_family", resolved_sources)

    def test_runtime_policy_family_mode_is_canonical_and_control_surfaces_are_trace_only(self) -> None:
        resolver = CapabilityResolver()
        runtime_policy = json.loads(
            (ROOT / "contracts/release/runtime_policy_catalog.json").read_text(encoding="utf-8")
        )

        context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=8,
            project_id="P-1",
            records={},
            inputs={
                "release_level": "INTERNAL_OPERABLE",
                "approval_state": "APPROVED",
            },
        )

        resolution = resolver.resolve(
            context=context,
            capability_family="stage8_execution",
            requested_action="LIVE_EXECUTION",
            release_level="INTERNAL_OPERABLE",
            approval_state="APPROVED",
        )

        self.assertEqual(resolution.capability_mode, "DRY_RUN")
        self.assertEqual(resolution.decision, "BLOCK")
        control_projection = resolution.trace_fields["control_projection"]
        self.assertEqual(
            control_projection["resolution_role"],
            "TRACE_ONLY_PROJECTION",
        )
        self.assertTrue(control_projection["projection_only"])
        self.assertTrue(control_projection["trace_only_projection"])
        self.assertFalse(control_projection["mode_resolution_source"])
        self.assertFalse(control_projection["release_layer_semantics_source"])
        self.assertEqual(control_projection["capability_family"], "stage8_execution")
        self.assertEqual(
            control_projection["ignored_sources"],
            runtime_policy["runtime_resolver_precedence"]["control_projection_sources_ignored_for_mode_resolution"],
        )
        self.assertEqual(
            control_projection["canonical_runtime_policy_ref"],
            "contracts/release/runtime_policy_catalog.json#capability_families",
        )
        self.assertNotIn("runtime_inventory", control_projection)
        self.assertNotIn("model_release_manifest_provider", control_projection)
        self.assertNotIn("model_release_manifest_runtime", control_projection)
        self.assertFalse(hasattr(resolver, "runtime_inventory"))
        self.assertFalse(hasattr(resolver, "model_release_manifest"))
        resolved_sources = {entry["source"] for entry in resolution.trace_fields["resolved_from"]}
        self.assertIn("runtime_policy_family", resolved_sources)
        self.assertNotIn("runtime_inventory_family", resolved_sources)
        self.assertNotIn("model_release_manifest_runtime_execution", resolved_sources)

    def test_same_precedence_group_uses_catalog_priority_order(self) -> None:
        resolver = CapabilityResolver()
        resolved_from = [
            {
                "source": "policy-a",
                "mode": "REAL_RUN_READY",
                "precedence_group": "target_policy_current_capability_mode",
            },
            {
                "source": "policy-b",
                "mode": "DRY_RUN",
                "precedence_group": "target_policy_current_capability_mode",
            },
        ]

        self.assertEqual(resolver._resolve_effective_mode(resolved_from), "DRY_RUN")

    def test_emergency_off_and_permanently_blocked_short_circuit(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        opportunity = stage7.record("saleable_opportunity")
        runtime = CapabilityRuntime()

        emergency_context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=8,
            project_id=opportunity.get("project_id"),
            records={"saleable_opportunity": opportunity},
            inputs={
                "release_level": "INTERNAL_OPERABLE",
                "approval_state": "NOT_REQUIRED",
                "capability_mode_overrides": {
                    "stage8_execution": "EMERGENCY_OFF",
                },
            },
        )
        emergency_state = runtime.resolve_permissions(
            emergency_context,
            [
                {
                    "capability_family": "stage8_execution",
                    "requested_action": "DRY_RUN",
                    "release_level": "INTERNAL_OPERABLE",
                    "approval_state": "NOT_REQUIRED",
                }
            ],
        )
        self.assertEqual(emergency_state.permission_decision_state, "BLOCK")
        self.assertTrue(emergency_state.permission_short_circuit)
        self.assertIn("emergency off", " ".join(emergency_state.permission_blocked_reasons))

        blocked_context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=8,
            project_id=opportunity.get("project_id"),
            records={"saleable_opportunity": opportunity},
            inputs={
                "release_level": "INTERNAL_OPERABLE",
                "approval_state": "NOT_REQUIRED",
                "capability_mode_overrides": {
                    "tool_provider": "PERMANENTLY_BLOCKED",
                },
            },
        )
        blocked_state = runtime.resolve_permissions(
            blocked_context,
            [
                {
                    "capability_family": "tool_provider",
                    "requested_action": "PREVIEW_ONLY",
                    "target_id": "TOOL_PROVIDER_UNBOUND_INTERNAL_QUERY",
                    "target_type": "tool_provider",
                    "target_role": "INTERNAL_OBJECT_QUERY_TOOL",
                    "release_level": "INTERNAL_OPERABLE",
                    "approval_state": "NOT_REQUIRED",
                }
            ],
        )
        self.assertEqual(blocked_state.permission_decision_state, "BLOCK")
        self.assertTrue(blocked_state.permission_short_circuit)
        self.assertIn("permanently blocked", " ".join(blocked_state.permission_blocked_reasons))

    def test_real_run_ready_does_not_override_external_blocked(self) -> None:
        stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage7"]
        opportunity = stage7.record("saleable_opportunity")
        runtime = CapabilityRuntime()
        context = ContextPacket.from_records(
            capability_mode="stage8_outreach",
            stage=8,
            project_id=opportunity.get("project_id"),
            records={"saleable_opportunity": opportunity},
            inputs={
                "release_level": "EXTERNAL_BLOCKED",
                "approval_state": "APPROVED",
                "capability_mode_overrides": {
                    "execution_vendor": "REAL_RUN_READY",
                },
            },
        )

        state = runtime.resolve_permissions(
            context,
            [
                {
                    "capability_family": "execution_vendor",
                    "requested_action": "LIVE_EXECUTION",
                    "target_id": "EXEC-EMAIL-SERVICE",
                    "target_type": "execution_vendor",
                    "target_role": "EXECUTION_VENDOR",
                    "release_level": "EXTERNAL_BLOCKED",
                    "approval_state": "APPROVED",
                }
            ],
        )
        self.assertEqual(state.permission_decision_state, "BLOCK")
        self.assertIn("external release blocked redline", " ".join(state.permission_blocked_reasons))

    def test_stage8_permission_trace_is_emitted_before_policy_load(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        policy_trace = stage8.inputs.get("policy_trace", [])
        permission_trace = stage8.inputs.get("permission_trace", [])

        self.assertTrue(permission_trace)
        self.assertEqual(stage8.inputs.get("permission_decision_state"), "ALLOW")
        first_permission = next(index for index, entry in enumerate(policy_trace) if entry.get("event") == "capability_resolution")
        first_policy_load = next(index for index, entry in enumerate(policy_trace) if entry.get("event") == "load_policy")
        self.assertLess(first_permission, first_policy_load)

    def test_stage9_permission_trace_is_emitted_before_policy_load(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        policy_trace = stage9.inputs.get("policy_trace", [])
        permission_trace = stage9.inputs.get("permission_trace", [])

        self.assertTrue(permission_trace)
        self.assertEqual(stage9.inputs.get("permission_decision_state"), "ALLOW")
        first_permission = next(index for index, entry in enumerate(policy_trace) if entry.get("event") == "capability_resolution")
        first_policy_load = next(index for index, entry in enumerate(policy_trace) if entry.get("event") == "load_policy")
        self.assertLess(first_permission, first_policy_load)

    def test_stage8_emergency_off_short_circuits_risky_path(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["capability_mode_overrides"] = {"stage8_execution": "EMERGENCY_OFF"}

        result = run_internal_chain(payload)
        stage8 = result["stage8"]

        self.assertEqual(stage8.inputs.get("permission_decision_state"), "BLOCK")
        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "BLOCKED")
        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "BLOCKED")
        self.assertEqual(stage8.record("touch_record").get("touch_record_state"), "CANCELLED")

    def test_stage9_emergency_off_short_circuits_internal_writeback(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["capability_mode_overrides"] = {"stage9_execution": "EMERGENCY_OFF"}

        result = run_internal_chain(payload)
        stage9 = result["stage9"]

        self.assertEqual(stage9.inputs.get("permission_decision_state"), "BLOCK")
        self.assertEqual(stage9.record("order_record").get("order_status"), "ON_HOLD")
        self.assertEqual(stage9.record("delivery_record").get("delivery_status"), "RELEASE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
