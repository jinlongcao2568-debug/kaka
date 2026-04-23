from __future__ import annotations

import ast
import copy
import json
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import (
    extract_service_record_dependencies,
    extract_service_optional_record_dependencies,
    load_fixture,
    run_internal_chain_to_stage7,
)
from shared.pipeline import run_internal_chain
from shared.runtime_validator import RuntimeValidator
from stage1_tasking.service import Stage1Service


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_json(relative_path: str) -> dict:
    return json.loads(read(relative_path))


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read(relative_path))


def extract_typed_dict_fields(relative_path: str, class_name: str) -> set[str]:
    tree = ast.parse(read(relative_path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    raise AssertionError(f"{relative_path} missing class {class_name}")


def assert_subsequence(testcase: unittest.TestCase, text: str, tokens: list[str], label: str) -> None:
    positions: list[int] = []
    for token in tokens:
        position = text.find(token)
        testcase.assertNotEqual(position, -1, f"{label} missing token {token}")
        positions.append(position)
    testcase.assertEqual(positions, sorted(positions), f"{label} sequence drift: {tokens}")


VERTICAL_SLICE_FIXTURE = "stage1_to_stage5_real_source_vertical_slice_proc_national_html.json"


CATALOG_CONSUMPTION_SPECS = [
    {
        "path": "contracts/governance/source_registry.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/contracts_runtime.py": [
                'self.source_registry = self._load_json("contracts/governance/source_registry.json")',
                "source_registry_index",
                "def resolve_source_entry(",
            ],
            "src/stage1_tasking/extractors.py": [
                "store.resolve_source_entry(",
                'source_registry_id=str(source_entry["source_registry_id"])',
            ],
            "src/stage2_ingestion/extractors.py": [
                "store.resolve_source_entry(",
                "source_registry_id=source_registry_id",
            ],
        },
    },
    {
        "path": "contracts/governance/route_policy_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/contracts_runtime.py": [
                'self.route_policy_catalog = self._load_json("contracts/governance/route_policy_catalog.json")',
                "route_policy_index",
                "def resolve_route_policy(",
            ],
            "src/stage1_tasking/extractors.py": [
                "store.resolve_route_policy(",
                'route_policy_id=str(route_policy["route_policy_id"])',
            ],
            "src/stage2_ingestion/extractors.py": [
                "store.resolve_route_policy(",
                "route_decision_state, route_downgrade_signals, route_block_signals = _route_decision(",
            ],
        },
    },
    {
        "path": "control/runtime_inventory.yaml",
        "mode": "INTENTIONAL_PARTIAL",
        "reason": "Capability runtime must not consume control projections for mode resolution; this file remains projection-only evidence.",
        "required_signals": {
            "control/runtime_inventory.yaml": [
                "control_projection_consumption_boundary:",
                "projection_only: true",
                "capability_family_state_projection:",
            ],
            "src/shared/capability_runtime.py": [
                "_collect_control_projection(",
                "control_projection_sources_ignored_for_mode_resolution",
                "canonical_runtime_policy_ref",
            ],
            "tests/test_architecture_anti_drift.py": [
                "test_capability_runtime_projections_follow_runtime_policy_catalog",
                "test_capability_runtime_resolver_does_not_load_control_projection_sources",
            ],
        },
    },
    {
        "path": "contracts/release/runtime_policy_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/capability_runtime.py": [
                'self.runtime_policy = self._load_json("contracts/release/runtime_policy_catalog.json")',
                "family_policy_index",
                "decision_matrix",
            ],
            "src/stage8_outreach/service.py": ["resolve_permissions("],
            "src/stage9_delivery/service.py": ["resolve_permissions("],
        },
    },
    {
        "path": "contracts/sales/vendor_registry_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/capability_runtime.py": [
                'self.vendor_registry = self._load_json("contracts/sales/vendor_registry_catalog.json")',
                "vendor_index",
                "_resolve_source_vendor(",
                "_resolve_execution_vendor(",
            ],
            "src/stage8_outreach/service.py": [
                '"target_type": "source_vendor"',
                '"target_type": "execution_vendor"',
                "resolve_permissions(",
            ],
        },
    },
    {
        "path": "contracts/sales/source_vendor_usage_policy.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/capability_runtime.py": [
                'self.source_vendor_usage_policy = self._load_json("contracts/sales/source_vendor_usage_policy.json")',
                "_resolve_source_vendor(",
                "source_vendor_usage_policy",
            ],
            "src/stage8_outreach/service.py": ['"target_type": "source_vendor"', "resolve_permissions("],
        },
    },
    {
        "path": "contracts/sales/channel_vendor_execution_policy.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/capability_runtime.py": [
                'self.channel_vendor_execution_policy = self._load_json("contracts/sales/channel_vendor_execution_policy.json")',
                "_resolve_execution_vendor(",
                "channel_vendor_execution_policy",
            ],
            "src/stage8_outreach/service.py": ['"target_type": "execution_vendor"', "resolve_permissions("],
        },
    },
    {
        "path": "contracts/sales/stage7_resolution_policy.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "contracts/sales/stage7_resolution_policy.json": [
                '"actorSeedPolicies"',
                '"priceCandidateResolution"',
            ],
            "src/stage7_sales/resolution.py": [
                'load_contract("contracts/sales/stage7_resolution_policy.json", settings)',
                '"actorSeedPolicies"',
            ],
            "src/stage7_sales/service.py": [
                "resolve_actor_seed(",
                "stage7_resolution_trace",
                "multi_competitor_collection",
            ],
        },
    },
    {
        "path": "contracts/model/model_usage_policy.json",
        "mode": "INTENTIONAL_PARTIAL",
        "reason": "Provider usage is input-gated today; only preview permission resolution is expected until a later bound-provider batch.",
        "required_signals": {
            "src/shared/capability_runtime.py": [
                'self.model_usage_policy = self._load_json("contracts/model/model_usage_policy.json")',
                'self.model_usage_policy.get("allowed_action_intents", [])',
                "_resolve_model_provider(",
            ],
            "src/stage8_outreach/service.py": ['"target_type": "model_provider"'],
            "src/stage9_delivery/service.py": ['"target_type": "model_provider"'],
        },
    },
    {
        "path": "contracts/model/tool_usage_policy_catalog.json",
        "mode": "INTENTIONAL_PARTIAL",
        "reason": "Tool provider resolution is input-gated today; runtime spine must exist without claiming live provider execution coverage.",
        "required_signals": {
            "src/shared/capability_runtime.py": [
                'self.tool_usage_policy = self._load_json("contracts/model/tool_usage_policy_catalog.json")',
                "_resolve_tool_provider(",
                "tool_usage_policy_catalog",
            ],
            "src/stage8_outreach/service.py": ['"target_type": "tool_provider"'],
            "src/stage9_delivery/service.py": ['"target_type": "tool_provider"'],
        },
    },
    {
        "path": "contracts/governance/field_policy_dictionary.json",
        "mode": "INTENTIONAL_PARTIAL",
        "reason": "The dictionary is broader than the current runtime surface; Stage8/9 must still consume touched fields through RuntimeValidator.",
        "required_signals": {
            "src/shared/runtime_validator.py": [
                'self.field_policy = self._load_json("contracts/governance/field_policy_dictionary.json")',
                "_evaluate_field_policy(",
                "field_policy_index",
            ],
            "src/stage8_outreach/service.py": ["evaluate_runtime_guards("],
            "src/stage9_delivery/service.py": ["evaluate_runtime_guards("],
        },
    },
    {
        "path": "contracts/release/delivery_matrix.json",
        "mode": "INTENTIONAL_PARTIAL",
        "reason": "The delivery matrix is object and surface broad; runtime must consume the governed objects it actually emits.",
        "required_signals": {
            "src/shared/runtime_validator.py": [
                'self.delivery_matrix = self._load_json("contracts/release/delivery_matrix.json")',
                "_evaluate_delivery_matrix(",
                "delivery_index",
            ],
            "src/stage8_outreach/service.py": ["evaluate_runtime_guards("],
            "src/stage9_delivery/service.py": ["evaluate_runtime_guards("],
        },
    },
    {
        "path": "contracts/release/release_gates.json",
        "mode": "INTENTIONAL_PARTIAL",
        "reason": "Release gates are larger than current Stage8/9 governed execution; runtime must still consume touched gates and keep traces.",
        "required_signals": {
            "src/shared/runtime_validator.py": [
                'self.release_gates = self._load_json("contracts/release/release_gates.json")',
                "_evaluate_release_gates(",
                "release_gate_index",
            ],
            "src/shared/capability_runtime.py": [
                'self.release_gates = self._load_json("contracts/release/release_gates.json")',
            ],
            "src/stage8_outreach/service.py": ["evaluate_runtime_guards("],
            "src/stage9_delivery/service.py": ["evaluate_runtime_guards("],
        },
    },
    {
        "path": "contracts/sales/payment_exception_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/policy_executor.py": [
                '"payment_exception": "contracts/sales/payment_exception_catalog.json"',
                "_evaluate_payment_exception(",
            ],
            "src/shared/capability_runtime.py": ['"payment_exception"', '"stage9_delivery"'],
        },
    },
    {
        "path": "contracts/sales/delivery_exception_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/policy_executor.py": [
                '"delivery_exception": "contracts/sales/delivery_exception_catalog.json"',
                "_evaluate_delivery_exception(",
            ],
            "src/shared/capability_runtime.py": ['"delivery_exception"', '"stage9_delivery"'],
        },
    },
    {
        "path": "contracts/sales/outcome_taxonomy_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/policy_executor.py": [
                '"outcome_taxonomy": "contracts/sales/outcome_taxonomy_catalog.json"',
                "_evaluate_outcome_taxonomy(",
            ],
            "src/shared/capability_runtime.py": ['"outcome_taxonomy"', '"stage9_delivery"'],
        },
    },
    {
        "path": "contracts/sales/governance_feedback_policy_catalog.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/shared/policy_executor.py": [
                '"governance_taxonomy": "contracts/sales/governance_feedback_policy_catalog.json"',
                "_evaluate_governance_taxonomy(",
            ],
            "src/shared/capability_runtime.py": ['"governance_taxonomy"', '"stage9_delivery"'],
        },
    },
    {
        "path": "contracts/governance/writeback_impact_policy.json",
        "mode": "FULL_RUNTIME",
        "required_signals": {
            "src/stage9_delivery/impact_executor.py": [
                'load_contract("contracts/governance/writeback_impact_policy.json"',
                "describe_targets(",
            ],
            "src/stage9_delivery/service.py": [
                "self.impact_executor.execute(",
                "writeback_target_contracts",
            ],
        },
    },
]


class TestArchitectureAntiDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = RuntimeValidator()
        self.schema_catalog = {
            entry["object"]: entry
            for entry in read_json("contracts/schemas/schema_catalog.json")["schemas"]
        }
        self.enum_names = {
            entry["enum_name"]
            for entry in read_json("contracts/enums/enum_catalog.json")["enums"]
        }

    def _assert_type_matches_schema(self, object_name: str, field_name: str, type_spec: object, schema_field: dict) -> None:
        schema_type = schema_field.get("type")
        if isinstance(schema_type, list):
            schema_types = set(schema_type)
        else:
            schema_types = {schema_type}

        expected_type = type_spec.expected_type
        if expected_type == "str":
            self.assertIn("string", schema_types, f"{object_name}.{field_name}")
        elif expected_type == "int":
            self.assertIn("integer", schema_types, f"{object_name}.{field_name}")
        elif expected_type == "number":
            self.assertTrue(schema_types.intersection({"number", "integer"}), f"{object_name}.{field_name}")
        elif expected_type == "bool":
            self.assertIn("boolean", schema_types, f"{object_name}.{field_name}")
        elif expected_type == "list":
            self.assertIn("array", schema_types, f"{object_name}.{field_name}")
            if type_spec.item_type:
                self.assertEqual(
                    schema_field.get("items", {}).get("type"),
                    "string" if type_spec.item_type == "str" else type_spec.item_type,
                    f"{object_name}.{field_name}",
                )
        elif expected_type == "object":
            self.assertIn("object", schema_types, f"{object_name}.{field_name}")
        else:
            raise AssertionError(f"Unsupported validator type {expected_type} for {object_name}.{field_name}")

    def test_critical_catalogs_are_declared_full_or_intentionally_partial(self) -> None:
        accidental_modes = {"UNDECLARED_PARTIAL", "ACCIDENTAL_PARTIAL", "UNINTENTIONAL_PARTIAL", "UNUSED"}
        for spec in CATALOG_CONSUMPTION_SPECS:
            with self.subTest(catalog=spec["path"]):
                self.assertTrue((ROOT / spec["path"]).exists(), spec["path"])
                self.assertIn(spec["mode"], {"FULL_RUNTIME", "INTENTIONAL_PARTIAL"})
                self.assertNotIn(spec["mode"], accidental_modes)
                if spec["mode"] == "INTENTIONAL_PARTIAL":
                    self.assertTrue(spec.get("reason"), spec["path"])
                for relative_path, tokens in spec["required_signals"].items():
                    text = read(relative_path)
                    for token in tokens:
                        self.assertIn(token, text, f"{spec['path']} -> {relative_path}")

    def test_stage8_and_stage9_runtime_behavior_consumes_governance_and_provider_assets(self) -> None:
        stage1 = Stage1Service().run(load_fixture("internal_chain_happy.json"))
        stage2 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))["stage2"]

        self.assertEqual(stage1.handoff.get("source_registry_id"), "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(stage1.handoff.get("route_policy_id"), "ROUTE-PROC-NOTICE-001")
        self.assertEqual(stage1.handoff.get("default_route"), "LIST_TO_DETAIL")
        self.assertEqual(stage1.handoff.get("fallback_route"), "DETAIL_DIRECT")

        public_chain = stage2.record("public_chain")
        version_chain = stage2.record("notice_version_chain")
        clock_chain = stage2.record("clock_chain_profile")
        stage2_trace = stage2.inputs.get("stage12_extractor_trace", {}).get("stage2", {})
        self.assertEqual(public_chain.get("source_registry_id"), stage1.handoff.get("source_registry_id"))
        self.assertEqual(public_chain.get("route_policy_id"), stage1.handoff.get("route_policy_id"))
        self.assertEqual(public_chain.get("default_route"), stage1.handoff.get("default_route"))
        self.assertEqual(public_chain.get("fallback_route"), stage1.handoff.get("fallback_route"))
        self.assertEqual(stage2_trace.get("default_route_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("fallback_route_source"), "h01_authority")
        self.assertEqual(stage2_trace.get("clock_precedence_rule_id_source"), "h01_authority")
        self.assertEqual(version_chain.get("version_chain_strategy"), "NOTICE_REPLACEMENT_CHAIN")
        self.assertEqual(clock_chain.get("clock_resolution_rule_id"), "CLOCK-DEFAULT")

        stage8_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        stage8_payload.update(
            {
                "source_vendor_role": "CONTACT_ENRICHMENT_SOURCE",
                "channel_family": "ORG_EMAIL",
                "contact_channel": "EMAIL",
                "model_provider_id_optional": "MODEL_PROVIDER_UNBOUND_GENERIC",
                "tool_provider_id_optional": "TOOL_PROVIDER_UNBOUND_CONTACT_ENRICHMENT",
            }
        )
        stage8 = run_internal_chain(stage8_payload)["stage8"]
        stage8_permission = {
            entry["capability_family"]: entry
            for entry in stage8.inputs.get("permission_trace", [])
            if entry.get("event") == "capability_resolution"
        }
        self.assertTrue(
            {"contact_enrichment", "execution_vendor", "stage8_execution", "model_provider", "tool_provider"}.issubset(
                set(stage8_permission)
            )
        )
        self.assertIn(
            "source_vendor_usage_policy",
            {item["source"] for item in stage8_permission["contact_enrichment"]["resolved_from"]},
        )
        self.assertIn(
            "channel_vendor_execution_policy",
            {item["source"] for item in stage8_permission["execution_vendor"]["resolved_from"]},
        )
        self.assertIn(
            "tool_usage_policy_catalog",
            {item["source"] for item in stage8_permission["tool_provider"]["resolved_from"]},
        )

        stage8_trace = stage8.inputs.get("governance_trace", [])
        self.assertEqual(
            {entry.get("object_type") for entry in stage8_trace},
            {"contact_target", "outreach_plan", "touch_record"},
        )
        for entry in stage8_trace:
            for token in ("field_policy", "delivery_matrix", "release_gates"):
                self.assertIn(token, entry)

        stage9_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        stage9_payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
                "model_provider_id_optional": "MODEL_PROVIDER_UNBOUND_GENERIC",
                "tool_provider_id_optional": "TOOL_PROVIDER_UNBOUND_INTERNAL_QUERY",
            }
        )
        stage9 = run_internal_chain(stage9_payload)["stage9"]
        stage9_permission = {
            entry["capability_family"]: entry
            for entry in stage9.inputs.get("permission_trace", [])
            if entry.get("event") == "capability_resolution"
        }
        self.assertTrue({"stage9_execution", "model_provider", "tool_provider"}.issubset(set(stage9_permission)))
        self.assertIn(
            "tool_usage_policy_catalog",
            {item["source"] for item in stage9_permission["tool_provider"]["resolved_from"]},
        )

        stage9_policy_keys = {
            entry["policy_key"]
            for entry in stage9.inputs.get("policy_trace", [])
            if entry.get("policy_key")
        }
        self.assertEqual(
            stage9_policy_keys,
            {"payment_exception", "delivery_exception", "outcome_taxonomy", "governance_taxonomy"},
        )
        self.assertEqual(stage9.inputs.get("impact_executor_state"), "INTERNAL_V0_ACTIVE")
        self.assertTrue(stage9.inputs.get("writeback_target_contracts"))

        stage9_trace = stage9.inputs.get("governance_trace", [])
        self.assertEqual(
            {entry.get("object_type") for entry in stage9_trace},
            {
                "order_record",
                "payment_record",
                "delivery_record",
                "opportunity_outcome_event",
                "governance_feedback_event",
            },
        )
        for entry in stage9_trace:
            for token in ("field_policy", "delivery_matrix", "release_gates"):
                self.assertIn(token, entry)

    def test_stage9_taxonomy_and_writeback_contract_boundaries_are_single_source(self) -> None:
        payment_catalog = read_json("contracts/sales/payment_exception_catalog.json")
        delivery_catalog = read_json("contracts/sales/delivery_exception_catalog.json")
        outcome_catalog = read_json("contracts/sales/outcome_taxonomy_catalog.json")
        governance_catalog = read_json("contracts/sales/governance_feedback_policy_catalog.json")
        writeback_policy = read_json("contracts/governance/writeback_impact_policy.json")
        opportunity_policy = read_json("contracts/sales/opportunity_policy_catalog.json")

        payment_policy = payment_catalog["policies"][0]
        delivery_policy = delivery_catalog["policies"][0]
        outcome_entries = {entry["outcome_family"]: entry for entry in outcome_catalog["entries"]}
        governance_entries = {
            entry["trigger_type"]: entry for entry in governance_catalog["entries"]
        }
        outcome_feedback_policy = next(
            policy
            for policy in opportunity_policy["policies"]
            if policy["policyId"] == "opportunity_outcome_writeback_v1"
        )

        self.assertEqual(
            payment_policy["family_semantics"]["PARTIAL_PAYMENT"]["additive_writeback_targets"],
            ["saleable_opportunity", "project_fact"],
        )
        self.assertEqual(
            payment_policy["family_semantics"]["REFUND_REQUESTED"]["coarse_outcome_reason_tags"],
            ["SIGNED"],
        )
        self.assertEqual(
            delivery_policy["family_semantics"]["PARTIAL_DELIVERY"]["additive_writeback_targets"],
            ["saleable_opportunity"],
        )
        self.assertEqual(
            delivery_policy["family_semantics"]["REDELIVERY_REQUIRED"]["additive_writeback_targets"],
            ["delivery_record"],
        )
        self.assertNotIn("buyer_fit", outcome_entries["LOST"]["writeback_targets"])
        self.assertNotIn(
            "challenger_candidate_profile",
            outcome_entries["FALSE_POSITIVE"]["writeback_targets"],
        )
        self.assertIn(
            "governance_feedback_event",
            outcome_entries["DELIVERY_ABANDONED"]["writeback_targets"],
        )
        self.assertIn("SIGNED", outcome_entries["DELIVERY_ABANDONED"]["allowed_reason_tags"])
        self.assertEqual(
            governance_entries["DELIVERY_BLOCK"]["writeback_targets"],
            ["delivery_record", "release_gates"],
        )
        self.assertEqual(
            governance_entries["APPROVAL_MISSING"]["writeback_targets"],
            ["order_record", "payment_record"],
        )
        self.assertEqual(
            governance_entries["EXCEPTION_TRIGGERED"]["writeback_targets"],
            ["controlled_exception_record", "release_gates"],
        )
        self.assertEqual(
            outcome_feedback_policy["mustWriteBackTo"],
            ["sales_lead", "report_record"],
        )
        self.assertEqual(
            outcome_feedback_policy["mustAdvisoryWriteBackTo"],
            ["buyer_fit", "challenger_candidate_profile"],
        )
        self.assertEqual(
            writeback_policy["target_source_resolution_order"],
            [
                "outcome_taxonomy",
                "upstream_feedback_loop",
                "governance_taxonomy",
                "payment_exception",
                "delivery_exception",
            ],
        )
        self.assertEqual(
            writeback_policy["upstream_feedback_loop_contract"]["merge_semantics"],
            "PROJECTED_FEEDBACK_ONLY",
        )
        self.assertEqual(
            writeback_policy["writeback_source_contracts"]["governance_taxonomy"]["contract_ref"],
            "contracts/sales/governance_feedback_policy_catalog.json",
        )
        self.assertEqual(
            writeback_policy["additive_sources_allowed_targets"]["upstream_feedback_loop"],
            ["sales_lead", "report_record", "buyer_fit", "challenger_candidate_profile"],
        )
        self.assertTrue(
            writeback_policy["contract_semantics"]["service_local_target_semantics_forbidden"]
        )

    def test_runtime_spine_traces_remain_behaviorally_visible(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))

        stage7 = result["stage7"]
        self.assertTrue(stage7.inputs.get("policy_trace"))
        self.assertTrue(stage7.inputs.get("semantic_trace"))
        self.assertEqual(stage7.inputs.get("semantic_decision_state"), "ALLOW")

        for stage_key in ("stage8", "stage9"):
            stage = result[stage_key]
            with self.subTest(stage=stage_key):
                self.assertTrue(stage.inputs.get("permission_trace"))
                self.assertTrue(stage.inputs.get("policy_trace"))
                self.assertTrue(stage.inputs.get("governance_trace"))
                self.assertTrue(stage.inputs.get("semantic_trace"))
                self.assertIn(stage.inputs.get("permission_decision_state"), {"ALLOW", "REVIEW", "BLOCK"})
                self.assertIn(stage.inputs.get("governance_decision_state"), {"ALLOW", "REVIEW", "BLOCK"})
                self.assertIn(stage.inputs.get("semantic_decision_state"), {"ALLOW", "REVIEW", "BLOCK"})

    def test_stage_services_must_use_shared_runtime_chain(self) -> None:
        stage6 = read("src/stage6_fact_review/service.py")
        stage7 = read("src/stage7_sales/service.py")
        stage8 = read("src/stage8_outreach/service.py")
        stage9 = read("src/stage9_delivery/service.py")

        self.assertIn("evaluate_handoff_consumer(", stage6)
        self.assertIn("evaluate_object_semantics(", stage6)
        self.assertIn("missing_h05_handoff_field:", stage6)
        self.assertIn("stage6_h05_authority_source", stage6)

        self.assertIn("runtime.run(", stage7)
        self.assertIn("evaluate_handoff_consumer(", stage7)
        self.assertIn("evaluate_object_semantics(", stage7)
        self.assertIn("stage6_formal_carriers", stage7)
        self.assertNotIn('get_flag(flags, "sale_blocked")', stage7)
        self.assertNotIn('get_flag(flags, "sale_review")', stage7)
        self.assertNotIn('get_flag(flags, "offer_review")', stage7)

        self.assertIn("resolve_permissions(", stage8)
        self.assertIn("evaluate_runtime_guards(", stage8)
        self.assertIn("evaluate_object_semantics(", stage8)

        self.assertIn("resolve_permissions(", stage9)
        self.assertIn("evaluate_runtime_guards(", stage9)
        self.assertIn("evaluate_object_semantics(", stage9)

    def test_services_must_not_bypass_unified_runtime_spine(self) -> None:
        stage7 = read("src/stage7_sales/service.py")
        stage8 = read("src/stage8_outreach/service.py")
        stage9 = read("src/stage9_delivery/service.py")

        for relative_path, text in (
            ("src/stage7_sales/service.py", stage7),
            ("src/stage8_outreach/service.py", stage8),
            ("src/stage9_delivery/service.py", stage9),
        ):
            for token in (
                "PolicyExecutor(",
                "CapabilityResolver(",
                "RuntimeValidator(",
                'load_contract("contracts/governance',
                'load_contract("contracts/release',
                "json.loads(",
                "yaml.safe_load(",
                "_load_json(",
                "Path(__file__)",
            ):
                self.assertNotIn(token, text, relative_path)

        assert_subsequence(
            self,
            stage7,
            ["evaluate_handoff_consumer(", "self.runtime.run(", "evaluate_object_semantics("],
            "stage7 runtime spine",
        )
        assert_subsequence(
            self,
            stage8,
            ["resolve_permissions(", "self.runtime.run(", "evaluate_runtime_guards(", "evaluate_object_semantics("],
            "stage8 runtime spine",
        )
        assert_subsequence(
            self,
            stage9,
            ["resolve_permissions(", "self.runtime.run(", "evaluate_runtime_guards(", "evaluate_object_semantics("],
            "stage9 runtime spine",
        )

    def test_stage9_must_not_regrow_private_policy_loop(self) -> None:
        stage9 = read("src/stage9_delivery/service.py")
        self.assertNotIn("def _run_policy_chain", stage9)
        self.assertNotIn("runtime.executor.execute(", stage9)

    def test_stage9_consumes_h08_authority_and_keeps_writeback_policy_bound(self) -> None:
        stage9 = read("src/stage9_delivery/service.py")
        impact_executor = read("src/stage9_delivery/impact_executor.py")

        for token in (
            "REQUIRED_H08_FIELDS",
            "payload = dict(stage8_bundle.handoff or {})",
            "response_status = h08_payload[\"response_status\"]",
            "saleability_status = h08_payload[\"saleability_status\"]",
            "crm_owner_state = h08_payload[\"crm_owner_state\"]",
            "writeback_target_resolution = self.impact_executor.resolve_effective_targets(",
            "impact_result = self.impact_executor.execute(",
            "\"live_execution_enabled\": False",
            "\"governed_execution_mode\": \"INTERNAL_GOVERNED\"",
        ):
            self.assertIn(token, stage9)

        for token in (
            'inputs.get("opportunity_id"',
            'inputs.get("touch_record_id"',
            'inputs.get("response_status"',
            'inputs.get("saleability_status"',
            'inputs.get("crm_owner_state"',
        ):
            self.assertNotIn(token, stage9)

        for token in (
            'load_contract("contracts/governance/writeback_impact_policy.json"',
            "REQUIRED_TARGET_SEMANTIC_GROUPS",
            "PROJECTED_MUTATION_ONLY",
            "PERSISTED_STAGE9_RECORD",
            "TRACE_ONLY_CONTRACT",
            "runtime_executor_enabled",
        ):
            self.assertIn(token, impact_executor)

    def test_services_must_not_load_governance_assets_directly(self) -> None:
        for relative_path in (
            "src/stage6_fact_review/service.py",
            "src/stage7_sales/service.py",
            "src/stage8_outreach/service.py",
            "src/stage9_delivery/service.py",
        ):
            text = read(relative_path)
            self.assertNotIn("json.loads(", text, relative_path)
            self.assertNotIn("yaml.safe_load(", text, relative_path)
            self.assertNotIn("_load_json(", text, relative_path)
            self.assertNotIn("Path(__file__)", text, relative_path)

    def test_stage7_module_boundary_split_uses_helper_modules(self) -> None:
        expected_modules = (
            "src/stage7_sales/runtime.py",
            "src/stage7_sales/scorecard.py",
            "src/stage7_sales/pricing.py",
            "src/stage7_sales/recommendation.py",
        )
        for relative_path in expected_modules:
            self.assertTrue((ROOT / relative_path).exists(), relative_path)

        stage7 = read("src/stage7_sales/service.py")
        for token in (
            "from stage7_sales.runtime import",
            "from stage7_sales.pricing import",
            "from stage7_sales.scorecard import",
            "from stage7_sales.recommendation import",
            "build_stage7_runtime_context(",
            "resolve_price_projection(runtime_state)",
            "resolve_scorecard_projection(runtime_state)",
            "build_buyer_fit_scorecard_trace(",
            "build_value_derivation_trace(",
            "build_price_resolution_trace(",
            "build_opportunity_policy_trace(",
        ):
            self.assertIn(token, stage7)
        for token in (
            "def required_runtime_value(",
            "def resolved_policy_output(",
            "price_policy_outputs =",
            '"selected_candidate_trace": runtime_state.resolve("selected_candidate_trace"',
            '"buyer_fit_derivation_trace": runtime_state.resolve("buyer_fit_derivation_trace")',
        ):
            self.assertNotIn(token, stage7)

    def test_stage7_service_does_not_use_direct_input_fallback_for_price_authority_outputs(self) -> None:
        stage7 = read("src/stage7_sales/service.py")
        pricing = read("src/stage7_sales/pricing.py")
        recommendation = read("src/stage7_sales/recommendation.py")

        self.assertIn(
            'resolved_policy_output(',
            pricing,
        )
        self.assertIn(
            '"price_normalization"',
            pricing,
        )
        self.assertIn(
            "resolve_price_projection(runtime_state)",
            stage7,
        )
        self.assertNotIn(
            'runtime_state.resolve("price_band", inputs.get("price_band_optional"))',
            stage7,
        )
        self.assertNotIn(
            'runtime_state.resolve("recommended_quote_band", inputs.get("recommended_quote_band"))',
            stage7,
        )
        self.assertNotIn('inputs.get("recommended_quote_band")', stage7 + pricing)
        self.assertNotIn('inputs.get("why_recommended")', stage7 + recommendation)

    def test_stage8_service_uses_h07_authority_for_contact_fields_and_conflict_preview(self) -> None:
        stage8 = read("src/stage8_outreach/service.py")

        for token in (
            "H07_AUTHORITATIVE_FIELDS",
            "_stage7_authoritative_inputs(",
            "inputs=authoritative_inputs,",
            'inputs_out["winning_competitor_candidate_id_optional"] = winning_competitor_candidate_id',
            'inputs_out["winning_challenger_profile_id_optional"] = str(winning_challenger_profile_id)',
            'inputs_out["multi_competitor_collection_id_optional"] = str(multi_competitor_collection_id)',
            'source_conflict_present = bool(selected_candidate.get("source_conflict_flag", False))',
            '"source_conflict_requires_manual_review"',
        ):
            self.assertIn(token, stage8)

    def test_schema_catalog_runtime_validator_and_enum_refs_align_for_critical_objects(self) -> None:
        critical_objects = [
            "execution_context",
            "public_chain",
            "clock_chain_profile",
            "notice_version_chain",
            "saleable_opportunity",
            "contact_target",
            "outreach_plan",
            "touch_record",
            "order_record",
            "payment_record",
            "delivery_record",
            "opportunity_outcome_event",
            "governance_feedback_event",
        ]
        for object_name in critical_objects:
            with self.subTest(object_name=object_name):
                concrete = read_json(f"contracts/schemas/{object_name}.schema.json")
                catalog = self.schema_catalog[object_name]
                self.assertEqual(set(catalog["required"]), set(concrete.get("required", [])), object_name)
                for enum_name in catalog.get("enum_refs", []):
                    self.assertIn(enum_name, self.enum_names, f"{object_name} -> {enum_name}")
                strict_profile = self.validator.STRICT_PROFILES[object_name]
                self.assertTrue(set(catalog["required"]).issubset(set(strict_profile.keys())), object_name)
                for field_name, type_spec in strict_profile.items():
                    self.assertIn(field_name, concrete.get("properties", {}), f"{object_name}.{field_name}")
                    self._assert_type_matches_schema(
                        object_name,
                        field_name,
                        type_spec,
                        concrete["properties"][field_name],
                    )

    def test_stage3_truth_layer_schema_catalog_declares_carrier_fields(self) -> None:
        expected_optional_fields = {
            "project_base": {
                "stage3_truth_layer_ref_optional",
                "field_lineage_collection_ref_optional",
                "bidder_candidate_collection_ref_optional",
                "stage3_review_path_ref_optional",
            },
            "field_lineage_record": {
                "normalized_value_ref_optional",
                "lineage_conflict_group_id_optional",
                "unresolved_reason_optional",
                "review_path_optional",
                "candidate_collection_ref_optional",
            },
            "bidder_candidate": {
                "candidate_collection_ref_optional",
                "candidate_collection_role_optional",
                "candidate_source_lineage_ids_optional",
                "candidate_conflict_group_id_optional",
                "candidate_review_path_optional",
            },
        }
        for object_name, field_names in expected_optional_fields.items():
            with self.subTest(object_name=object_name):
                concrete = read_json(f"contracts/schemas/{object_name}.schema.json")
                catalog = self.schema_catalog[object_name]
                self.assertTrue(field_names.issubset(set(concrete["properties"])), object_name)
                self.assertTrue(field_names.issubset(set(catalog.get("optional", []))), object_name)
                constraints = " ".join(catalog.get("hard_constraints", [])).lower()
                self.assertIn("stage", constraints)
                self.assertIn("truth", constraints)

        h02 = read_json("handoff/stage2_to_stage3/contract.json")
        self.assertIn("stage3_truth_layer_output_obligations", h02)
        self.assertIn("unresolved_or_conflicting_lineage_paths", h02)
        self.assertIn("consumer_obligations", h02)
        self.assertIn("consumer_must_not_recompute_fields", h02)
        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "route_decision_state",
            "route_review_reasons",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_conflict_state",
            "collection_state",
        ):
            self.assertIn(field_name, h02["required_payload_fields"])
            self.assertIn(field_name, h02["consumer_runtime_required_fields"])

        h03 = read_json("handoff/stage3_to_stage4/contract.json")
        for field_name in (
            "lineage_status",
            "conflict_state",
            "fixation_bundle_id",
            "source_registry_id",
            "route_policy_id",
            "fallback_route",
            "route_decision_state",
            "route_review_reasons",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
            "stage3_review_path_ref_optional",
        ):
            self.assertIn(field_name, h03["required_payload_fields"])
            self.assertIn(field_name, h03["consumer_runtime_required_fields"])
        for field_name in (
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h03["optional_payload_fields"])
        for field_name in (
            "lineage_status",
            "conflict_state",
            "candidate_collection_ref_optional",
            "stage3_review_path_ref_optional",
            "source_registry_id",
            "route_policy_id",
            "fallback_route",
            "route_decision_state",
            "route_review_reasons",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h03["consumer_must_not_recompute_fields"])
        self.assertIn("consumer_obligations", h03)
        self.assertIn("optional_payload_fields", h03)

        h04 = read_json("handoff/stage4_to_stage5/contract.json")
        for field_name in (
            "project_id",
            "focus_bidder_id",
            "public_attack_surface_id",
            "verification_profile_id",
            "evidence_grade_profile_id",
            "public_capability_tier",
            "verification_state",
            "external_use_grade",
            "cross_check_state",
            "fixation_status",
            "provenance_chain_status",
            "retrieval_readiness_status",
            "lineage_status",
            "conflict_state",
            "pseudo_competitor_signal_set_id",
            "confidence_band",
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
        ):
            self.assertIn(field_name, h04["required_payload_fields"])
            self.assertIn(field_name, h04["consumer_runtime_required_fields"])
            self.assertIn(field_name, h04["consumer_must_not_recompute_fields"])
        for field_name in (
            "fallback_route",
            "route_decision_state",
            "route_review_reasons",
            "current_action_start_at_optional",
            "current_action_deadline_at_optional",
        ):
            self.assertIn(field_name, h04["optional_payload_fields"])
            self.assertIn(field_name, h04["consumer_must_not_recompute_fields"])
        self.assertIn("consumer_obligations", h04)

        h05 = read_json("handoff/stage5_to_stage6/contract.json")
        for field_name in (
            "rule_hit_id",
            "evidence_id",
            "rule_gate_decision_id",
            "evidence_gate_decision_id",
            "rule_gate_status",
            "evidence_gate_status",
            "lineage_status",
            "conflict_state",
        ):
            self.assertIn(field_name, h05["required_payload_fields"])
            self.assertIn(field_name, h05["consumer_runtime_required_fields"])
        for field_name in (
            "rule_hit_state",
            "rule_gate_status",
            "evidence_gate_status",
            "lineage_status",
            "conflict_state",
            "coverage_sellable_state",
            "delivery_risk_state",
        ):
            self.assertIn(field_name, h05["consumer_must_not_recompute_fields"])
        self.assertIn("review_request_id", h05["optional_payload_fields"])
        self.assertIn("missing_condition_family", h05["optional_payload_fields"])
        self.assertIn("review_lane", h05["optional_payload_fields"])

        h06 = read_json("handoff/stage6_to_stage7/contract.json")
        for object_name in (
            "project_fact",
            "legal_action_recommendation",
            "review_queue_profile",
            "challenger_candidate_profile",
            "report_record",
        ):
            self.assertIn(object_name, h06["producer_objects"])
        for field_name in (
            "project_fact_id",
            "review_queue_profile_id",
            "report_record_id",
            "challenger_candidate_profile_id",
            "report_status",
            "sale_gate_status",
            "saleability_status",
            "review_lane",
            "linked_review_request_id_optional",
            "missing_condition_family_optional",
        ):
            self.assertIn(field_name, h06["consumer_must_not_recompute_fields"])

    def test_stage3_runtime_materializes_truth_layer_and_handoff_trace(self) -> None:
        result = run_internal_chain_to_stage7(load_fixture(VERTICAL_SLICE_FIXTURE))
        stage2 = result["stage2"]
        stage3 = result["stage3"]
        project_id = stage3.record("project_base").get("project_id")

        self.assertEqual(stage3.record("project_base").get("stage3_truth_layer_ref_optional"), f"ST3TL-{project_id}")
        self.assertEqual(stage3.record("project_base").get("field_lineage_collection_ref_optional"), f"LINEAGE-{project_id}")
        self.assertEqual(stage3.record("project_base").get("bidder_candidate_collection_ref_optional"), f"CSET-{project_id}")
        self.assertEqual(stage3.record("field_lineage_record").get("review_path_optional"), "STAGE3_READY_FOR_STAGE4")
        self.assertEqual(stage3.record("bidder_candidate").get("candidate_collection_ref_optional"), f"CSET-{project_id}")
        self.assertEqual(stage3.handoff.get("source_registry_id"), stage2.handoff.get("source_registry_id"))
        self.assertEqual(stage3.handoff.get("route_policy_id"), stage2.handoff.get("route_policy_id"))
        self.assertEqual(
            stage3.handoff.get("winning_version_resolution_rule_id"),
            stage2.handoff.get("winning_version_resolution_rule_id"),
        )
        self.assertEqual(stage3.handoff.get("version_conflict_state"), stage2.handoff.get("version_conflict_state"))
        self.assertEqual(
            stage3.handoff.get("clock_resolution_rule_id"),
            stage2.handoff.get("clock_resolution_rule_id"),
        )
        self.assertEqual(
            stage3.handoff.get("clock_precedence_rule_id"),
            stage2.handoff.get("clock_precedence_rule_id"),
        )
        self.assertEqual(stage3.handoff.get("fallback_route"), stage2.handoff.get("fallback_route"))
        self.assertEqual(
            stage3.handoff.get("current_action_start_at_optional"),
            stage2.handoff.get("current_action_start_at_optional"),
        )
        self.assertEqual(
            stage3.handoff.get("current_action_deadline_at_optional"),
            stage2.handoff.get("current_action_deadline_at_optional"),
        )
        self.assertEqual(stage3.handoff.get("fixation_bundle_id"), stage2.handoff.get("fixation_bundle_id"))
        self.assertIn("source_registry_id", stage3.inputs)
        self.assertIn("collection_state", stage3.inputs)
        self.assertIn("clock_precedence_rule_id", stage3.inputs)
        self.assertIn("fallback_route", stage3.inputs)
        self.assertIn("stage3_truth_layer_ref_optional", stage3.inputs)
        self.assertEqual(stage3.handoff.get("stage3_review_path_ref_optional"), "STAGE3_READY_FOR_STAGE4")

    def test_stage3_service_consumes_h02_authority_from_formal_carriers_only(self) -> None:
        text = read("src/stage3_parsing/service.py")
        for token in (
            "resolve_h02_authority(",
            "resolve_optional_h02_authority(",
            '("handoff", handoff_map)',
            '("public_chain", public_chain_map)',
            '("notice_version_chain", notice_version_map)',
            '("clock_chain_profile", clock_chain_map)',
            "missing_h02_handoff_field:",
            "h02_authority_conflict:",
        ):
            self.assertIn(token, text)
        for token in (
            'inputs.get("source_registry_id")',
            'inputs.get("route_policy_id")',
            'inputs.get("fallback_route")',
            'inputs.get("route_decision_state")',
            'inputs.get("route_review_reasons")',
            'inputs.get("winning_version_resolution_rule_id")',
            'inputs.get("clock_precedence_rule_id")',
            'inputs.get("clock_resolution_rule_id")',
            'inputs.get("current_action_start_at_optional")',
            'inputs.get("current_action_deadline_at_optional")',
        ):
            self.assertNotIn(token, text)

    def test_stage4_service_consumes_h03_formal_carriers_only(self) -> None:
        text = read("src/stage4_verification/service.py")
        for token in (
            "resolve_h03_field(",
            "handoff_map = stage3_bundle.handoff",
            'stage3_bundle.records.get("project_manager")',
            "stage3_handoff_then_formal_producer_objects",
            "candidate_collection_ref_missing",
            "stage3_review_path_requires_review",
            "STAGE3_CLOCK_PRECEDENCE",
            "formal_carrier_fields",
        ):
            self.assertIn(token, text)
        for token in (
            'inputs.get("project_root_id")',
            'inputs.get("notice_version_id")',
            'inputs.get("candidate_order_mode")',
            'inputs.get("award_determination_mode")',
            'inputs.get("lineage_status")',
            'inputs.get("conflict_state")',
            'inputs.get("fallback_route")',
            'inputs.get("clock_precedence_rule_id")',
            'inputs.get("collection_state")',
            'inputs.get("current_action_start_at_optional")',
            'inputs.get("current_action_deadline_at_optional")',
            'inputs.get("candidate_set_ids")',
            'inputs.get("ranked_candidate_ids_optional")',
            'inputs.get("candidate_ids")',
        ):
            self.assertNotIn(token, text)

    def test_stage5_runtime_consumes_h04_authority_from_formal_handoff_only(self) -> None:
        engine_text = read("src/stage5_rules_evidence/engine.py")
        rule_runner_text = read("src/stage5_rules_evidence/rule_runner.py")
        for token in (
            "def _build_stage4_authority_inputs(",
            "stage4_handoff_authority_required_fields",
            '"lineage",',
            "missing_h04_handoff_field:",
            "_apply_h04_clock_authority_guard(",
            "clock_precedence_rule_id",
            '"stage5_rule_selection_trace"',
            '"stage5_rule_execution_trace"',
        ):
            self.assertIn(token, engine_text)
        for token in (
            "FIRST_SLICE_SUPPORTED_UPSTREAM_OBJECTS",
            "def _selection_reason(",
            "selected_first_slice_priority",
            "not_in_first_slice_priority",
            "unsupported_upstream_objects",
        ):
            self.assertIn(token, rule_runner_text)
        self.assertNotIn('inputs.get("lineage")', rule_runner_text)

    def test_placeholder_models_remain_minimal_and_do_not_silently_drift(self) -> None:
        placeholder_files = [
            "src/stage7_sales/models.py",
            "src/stage8_outreach/models.py",
            "src/stage9_delivery/models.py",
        ]
        for relative_path in placeholder_files:
            text = read(relative_path)
            self.assertIn("TODO: align with contracts/schemas/schema_catalog.json", text, relative_path)
            tree = ast.parse(text)
            dataclasses = [node for node in tree.body if isinstance(node, ast.ClassDef)]
            self.assertTrue(dataclasses, relative_path)
            for class_node in dataclasses:
                annotations = [
                    stmt.target.id
                    for stmt in class_node.body
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                ]
                self.assertEqual(len(annotations), 1, f"{relative_path}:{class_node.name}")
                self.assertTrue(annotations[0].endswith("_id") or annotations[0].endswith("_context_id"))

    def test_api_skeletons_do_not_silently_drift_from_stage_scope(self) -> None:
        expected_route_tokens = {
            "src/api/routes/stage6.py": ["project_fact", "review_report_workbench", "preview-only", "live_execution_enabled"],
            "src/api/routes/stage7.py": ["saleable_opportunity", "preview-only", "live_execution_enabled"],
            "src/api/routes/stage8.py": ["contact_target", "draft-only", "blocked_by_default"],
            "src/api/routes/stage9.py": ["order_record", "draft-only", "blocked_by_default"],
        }
        for relative_path, tokens in expected_route_tokens.items():
            text = read(relative_path)
            for token in tokens:
                self.assertIn(token, text, relative_path)

        stage_schema_expected = {
            "src/api/schemas/stage6.py": (
                "Stage6Request",
                {
                    "project_id",
                    "project_fact_id",
                    "report_record_id",
                    "review_queue_profile_id",
                    "challenger_candidate_profile_id",
                    "action_id",
                    "requested_surface_state",
                    "include_formal_objects",
                },
            ),
            "src/api/schemas/stage7.py": (
                "Stage7Request",
                {"opportunity_id", "saleability_status", "requested_surface_state", "include_formal_objects"},
            ),
            "src/api/schemas/stage8.py": (
                "Stage8Request",
                {"opportunity_id", "touch_record_id", "requested_surface_state", "include_formal_objects"},
            ),
            "src/api/schemas/stage9.py": (
                "Stage9Request",
                {"opportunity_id", "crm_owner_state", "requested_surface_state", "include_formal_objects"},
            ),
        }
        for relative_path, (request_class_name, expected_fields) in stage_schema_expected.items():
            self.assertEqual(
                extract_typed_dict_fields(relative_path, request_class_name),
                expected_fields,
                relative_path,
            )
            text = read(relative_path)
            self.assertIn("formal_object_refs", text, relative_path)
            self.assertIn("preview_projection", text, relative_path)

    def test_h01_h06_h07_h08_producer_consumer_sets_stay_aligned(self) -> None:
        stage1 = Stage1Service().run(load_fixture("internal_chain_happy.json"))
        chain_to_stage7 = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        full_chain = run_internal_chain(load_fixture("internal_chain_happy.json"))
        integration_rows = {
            row["contractId"]: row
            for row in read_json("handoff/integration_matrix.json")["rows"]
        }
        targeted = {
            "H-01-STAGE1-TO-STAGE2": (
                read_json("handoff/stage1_to_stage2/contract.json"),
                stage1,
                "src/stage2_ingestion/service.py",
            ),
            "H-06-STAGE6-TO-STAGE7": (
                read_json("handoff/stage6_to_stage7/contract.json"),
                chain_to_stage7["stage6"],
                "src/stage7_sales/service.py",
            ),
            "H-07-STAGE7-TO-STAGE8": (
                read_json("handoff/stage7_to_stage8/contract.json"),
                chain_to_stage7["stage7"],
                "src/stage8_outreach/service.py",
            ),
            "H-08-STAGE8-TO-STAGE9": (
                read_json("handoff/stage8_to_stage9/contract.json"),
                full_chain["stage8"],
                "src/stage9_delivery/service.py",
            ),
        }
        for contract_id, (contract, bundle, consumer_path) in targeted.items():
            with self.subTest(contract_id=contract_id):
                self.assertEqual(set(bundle.records.keys()), set(contract["producer_objects"]), contract_id)
                self.assertEqual(
                    extract_service_record_dependencies(consumer_path),
                    sorted(integration_rows[contract_id]["criticalObjects"]),
                    contract_id,
                )
                combined_payload = dict(bundle.inputs)
                combined_payload.update(bundle.handoff)
                for field_name in contract["required_payload_fields"]:
                    self.assertIn(field_name, combined_payload, f"{contract_id}:{field_name}")
                if contract_id == "H-08-STAGE8-TO-STAGE9":
                    for field_name in contract["required_payload_fields"]:
                        self.assertIn(field_name, bundle.inputs, f"{contract_id}:inputs:{field_name}")

    def test_h07_and_h08_optional_runtime_consumers_are_explicit(self) -> None:
        optional_expectations = {
            "H-07-STAGE7-TO-STAGE8": (
                "handoff/stage7_to_stage8/contract.json",
                "src/stage8_outreach/service.py",
                ["legal_action_actor_profile", "multi_competitor_collection"],
                [
                    'records.get("legal_action_actor_profile")',
                    'records.get("multi_competitor_collection")',
                    "must be present before Stage8 contact resolution",
                ],
            ),
            "H-08-STAGE8-TO-STAGE9": (
                "handoff/stage8_to_stage9/contract.json",
                "src/stage9_delivery/service.py",
                ["outreach_plan"],
                ['records.get("outreach_plan")', "if outreach_plan else None"],
            ),
        }
        for contract_id, (contract_path, consumer_path, expected_optional, tokens) in optional_expectations.items():
            with self.subTest(contract_id=contract_id):
                contract = read_json(contract_path)
                self.assertEqual(
                    extract_service_optional_record_dependencies(consumer_path),
                    expected_optional,
                    contract_id,
                )
                self.assertTrue(set(expected_optional).issubset(set(contract["producer_objects"])), contract_id)
                consumer_text = read(consumer_path)
                for token in tokens:
                    self.assertIn(token, consumer_text, f"{contract_id}:{token}")

    def test_d11_declares_architecture_closeout_assertions(self) -> None:
        d11 = read("docs/D11_测试验收与金标回归清单.md")
        for token in (
            "ARCH-006",
            "ARCH-007",
            "ARCH-008",
            "ARCH-009",
            "ARCH-010",
            "UNDECLARED_PARTIAL",
            "Stage 1 / 2 baseline",
            "unused catalog / partial consumption",
            "unified runtime spine",
            "H-01 / H-06 / H-07 / H-08",
        ):
            self.assertIn(token, d11)

    def test_release_checklist_and_regression_manifest_cover_architecture_guards(self) -> None:
        release = read_json("contracts/testing/release_checklist.json")
        release_item_ids = {
            item["itemId"]
            for section in release["sections"]
            for item in section["items"]
        }
        for item_id in ("REL-100", "REL-101", "REL-102", "REL-103", "REL-104", "REL-105", "REL-106", "REL-107", "REL-108", "REL-109"):
            self.assertIn(item_id, release_item_ids)

        regression = read_json("contracts/testing/regression_manifest.json")
        suite_ids = {suite["suite_id"] for suite in regression["suites"]}
        for suite_id in (
            "REG-ARCH-SERVICE-HARDCODE-ANTI-REGRESSION",
            "REG-ARCH-UNUSED-CATALOG-PARTIAL-CONSUMPTION",
            "REG-ARCH-GOVERNANCE-RUNTIME-CONSUMPTION-CLOSURE",
            "REG-ARCH-SCHEMA-VALIDATOR-MODEL-DRIFT",
            "REG-ARCH-HANDOFF-PRODUCER-CONSUMER-DRIFT",
            "REG-ARCH-UNIFIED-RUNTIME-SPINE",
        ):
            self.assertIn(suite_id, suite_ids)

        release_script = read("scripts/check-final-gate.ps1")
        for token in (
            "REL-104",
            "REL-109",
            "REG-ARCH-UNUSED-CATALOG-PARTIAL-CONSUMPTION",
            "REG-ARCH-HANDOFF-PRODUCER-CONSUMER-DRIFT",
            "REG-ARCH-UNIFIED-RUNTIME-SPINE",
        ):
            self.assertIn(token, release_script)

    def test_capability_runtime_projections_follow_runtime_policy_catalog(self) -> None:
        runtime_policy = read_json("contracts/release/runtime_policy_catalog.json")
        runtime_inventory = read_yaml("control/runtime_inventory.yaml")
        model_release_manifest = read_yaml("control/model_release_manifest.yaml")
        release_manifest = read_yaml("control/release_manifest.yaml")

        family_index = {
            entry["family_id"]: entry
            for entry in runtime_policy["capability_families"]
        }
        self.assertIn("runtime_resolver_precedence", runtime_policy["canonical_source_for"])
        self.assertIn("capability_families", runtime_policy["canonical_source_for"])
        self.assertEqual(
            runtime_policy["runtime_resolver_precedence"]["within_precedence_group_resolution"],
            "MOST_RESTRICTIVE_BY_PRIORITY_ORDER",
        )
        self.assertEqual(
            runtime_policy["runtime_resolver_precedence"]["release_layer_redline"],
            "EXTERNAL_BLOCKED",
        )

        projection_boundary = runtime_inventory["control_projection_consumption_boundary"]
        self.assertTrue(projection_boundary["projection_only"])
        self.assertTrue(projection_boundary["trace_only_projection"])
        self.assertFalse(projection_boundary["mode_resolution_source"])
        self.assertFalse(projection_boundary["release_layer_semantics_source"])
        self.assertEqual(
            runtime_inventory["runtime_resolver_precedence"]["projected_from"],
            "contracts/release/runtime_policy_catalog.json#runtime_resolver_precedence",
        )

        for family_id, projection in runtime_inventory["capability_family_state_projection"].items():
            with self.subTest(family_id=family_id):
                self.assertEqual(
                    projection["projected_current_mode"],
                    family_index[family_id]["current_capability_mode"],
                )
                self.assertEqual(
                    projection["projected_release_layer_ceiling"],
                    family_index[family_id]["release_layer_ceiling"],
                )
                self.assertTrue(projection["projection_only"])

        model_boundary = model_release_manifest["control_projection_consumption_boundary"]
        self.assertTrue(model_boundary["projection_only"])
        self.assertTrue(model_boundary["trace_only_projection"])
        self.assertFalse(model_boundary["mode_resolution_source"])
        self.assertFalse(model_boundary["release_layer_semantics_source"])
        self.assertEqual(
            model_release_manifest["runtime_resolver_precedence_ref"],
            "contracts/release/runtime_policy_catalog.json#runtime_resolver_precedence",
        )
        for family_id, projection in model_release_manifest["provider_family_projection"].items():
            with self.subTest(provider_family=family_id):
                self.assertEqual(
                    projection["projected_current_capability_mode"],
                    family_index[family_id]["current_capability_mode"],
                )
                self.assertEqual(
                    projection["projected_release_layer_ceiling"],
                    family_index[family_id]["release_layer_ceiling"],
                )
                self.assertTrue(projection["projection_only"])
        for family_id, projection in model_release_manifest["runtime_execution_projection"].items():
            with self.subTest(runtime_family=family_id):
                self.assertEqual(
                    projection["projected_current_capability_mode"],
                    family_index[family_id]["current_capability_mode"],
                )
                self.assertEqual(
                    projection["projected_release_layer_ceiling"],
                    family_index[family_id]["release_layer_ceiling"],
                )
                self.assertTrue(projection["projection_only"])

        release_projection = release_manifest["capability_runtime_projection"]
        self.assertTrue(release_projection["projection_only"])
        self.assertFalse(release_projection["mode_resolution_source"])
        self.assertFalse(release_projection["release_layer_semantics_source"])
        self.assertTrue(release_projection["external_blocked_redline_retained"])
        self.assertEqual(
            release_projection["runtime_policy_ref"],
            "contracts/release/runtime_policy_catalog.json#capability_families",
        )
        self.assertEqual(
            release_projection["runtime_inventory_ref"],
            "control/runtime_inventory.yaml#capability_family_state_projection",
        )
        self.assertEqual(
            release_projection["runtime_resolver_precedence_ref"],
            "contracts/release/runtime_policy_catalog.json#runtime_resolver_precedence",
        )

    def test_capability_runtime_resolver_does_not_load_control_projection_sources(self) -> None:
        runtime_text = read("src/shared/capability_runtime.py")
        runtime_tree = ast.parse(runtime_text)

        self.assertIn(
            'self.runtime_policy = self._load_json("contracts/release/runtime_policy_catalog.json")',
            runtime_text,
        )
        self.assertIn("canonical_runtime_policy_ref", runtime_text)

        assigned_self_attrs = set()
        yaml_loader_calls = 0
        for node in ast.walk(runtime_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        assigned_self_attrs.add(target.attr)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr == "_load_yaml"
            ):
                yaml_loader_calls += 1

        self.assertEqual(yaml_loader_calls, 0)
        self.assertNotIn("runtime_inventory", assigned_self_attrs)
        self.assertNotIn("model_release_manifest", assigned_self_attrs)
        self.assertNotIn("family_inventory_index", assigned_self_attrs)
        self.assertNotIn("provider_family_projection_index", assigned_self_attrs)
        self.assertNotIn("runtime_execution_projection_index", assigned_self_attrs)

    def test_b9_provider_vendor_projection_does_not_become_capability_source(self) -> None:
        runtime_inventory = read_yaml("control/runtime_inventory.yaml")
        model_release_manifest = read_yaml("control/model_release_manifest.yaml")
        tool_usage_policy = read_json("contracts/model/tool_usage_policy_catalog.json")

        self.assertEqual(
            tool_usage_policy["capability_mode_vocabulary_ref"],
            "contracts/release/runtime_policy_catalog.json#capability_mode_vocabulary",
        )

        runtime_projection = runtime_inventory["provider_vendor_policy_projection"]
        self.assertTrue(runtime_projection["projection_only"])
        self.assertTrue(runtime_projection["trace_only_projection"])
        self.assertFalse(runtime_projection["mode_resolution_source"])
        self.assertFalse(runtime_projection["release_layer_semantics_source"])
        self.assertFalse(runtime_projection["live_provider_binding_source"])
        for forbidden_role in (
            "capability_mode_decision_source",
            "release_layer_decision_source",
            "live_provider_binding_source",
            "external_action_authority",
        ):
            self.assertIn(forbidden_role, runtime_projection["forbidden_projection_roles"])

        release_projection = model_release_manifest["provider_vendor_release_projection"]
        self.assertTrue(release_projection["projection_only"])
        self.assertTrue(release_projection["trace_only_projection"])
        self.assertFalse(release_projection["mode_resolution_source"])
        self.assertFalse(release_projection["release_layer_semantics_source"])
        self.assertFalse(release_projection["live_provider_binding_source"])
        self.assertFalse(release_projection["current_externalization_authority"])
        self.assertFalse(release_projection["current_live_provider_authority"])

        expected_refs = {
            "model_usage_policy": "contracts/model/model_usage_policy.json",
            "tool_provider_registry_catalog": "contracts/model/tool_provider_registry_catalog.json",
            "tool_usage_policy_catalog": "contracts/model/tool_usage_policy_catalog.json",
            "vendor_registry_catalog": "contracts/sales/vendor_registry_catalog.json",
            "source_vendor_usage_policy": "contracts/sales/source_vendor_usage_policy.json",
            "channel_vendor_execution_policy": "contracts/sales/channel_vendor_execution_policy.json",
        }
        self.assertEqual(runtime_projection["registry_policy_refs"], expected_refs)
        self.assertEqual(release_projection["registry_policy_refs"], expected_refs)


if __name__ == "__main__":
    unittest.main()
