from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from helpers import load_fixture
from shared.contract_loader import load_contract
from stage1_tasking.extractors import extract_stage1
from stage1_tasking.service import Stage1Service
from stage2_ingestion.extractors import extract_stage2
from stage2_ingestion.service import Stage2Service


class TestStage12Extractors(unittest.TestCase):
    def test_stage12_authoritative_baseline_registries_cover_minimum_scope(self) -> None:
        source_registry = load_contract("contracts/governance/source_registry.json")
        source_family_registry = load_contract("contracts/governance/source_family_registry.json")
        platform_level_registry = load_contract("contracts/governance/platform_level_registry.json")

        source_entries = source_registry["entries"]
        source_index = {entry["source_registry_id"]: entry for entry in source_entries}
        rollout_ids = set(source_registry["rollout_scope"]["rollout_registry_refs"])
        backlog_ids = set(source_registry["rollout_scope"]["backlog_registry_refs"])
        source_authority = source_registry["canonical_authority"]
        family_authority = source_family_registry["canonical_authority"]

        self.assertEqual(source_authority["producer_stage"], "stage1_tasking")
        self.assertEqual(source_authority["consumer_stages"], ["stage2_ingestion"])
        self.assertEqual(source_authority["producer_interface"], "stage1_source_route_extractor")
        self.assertEqual(source_authority["adapter_contract_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(source_authority["live_external_source_enabled"])
        for field_name in (
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
            "rollout_enabled",
            "winning_version_resolution_rule_id",
            "clock_precedence_rule_id",
        ):
            self.assertIn(field_name, source_authority["canonical_fields"])

        self.assertEqual(family_authority["producer_stage"], "governance_contract")
        self.assertIn("stage1_tasking", family_authority["runtime_consumer_stages"])
        self.assertEqual(family_authority["adapter_contract_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(family_authority["live_external_source_enabled"])

        self.assertGreaterEqual(len(source_entries), 9)
        self.assertEqual(
            {entry["source_family"] for entry in source_entries},
            {
                "PROCUREMENT_NOTICE",
                "AWARD_ANNOUNCEMENT",
                "REGULATORY_PUBLICATION",
                "ENTERPRISE_REGISTRY",
                "JUDICIAL_CREDIT_RISK",
                "ANNEX_QA_SUPPLEMENT",
                "OTHER_PUBLIC_SOURCE",
            },
        )
        self.assertEqual(
            {entry["platform_level"] for entry in source_entries},
            {
                "NATIONAL",
                "PROVINCE",
                "CITY",
                "COUNTY",
                "INDUSTRY_PLATFORM",
                "ENTERPRISE_SITE",
            },
        )
        self.assertEqual(
            {entry["carrier_type"] for entry in source_entries},
            {
                "HTML_PAGE",
                "PDF_ATTACHMENT",
                "DOC_ATTACHMENT",
                "IMAGE_ATTACHMENT",
                "TABLE_SEGMENT",
                "TEXT_SEGMENT",
            },
        )
        self.assertTrue(rollout_ids)
        self.assertTrue(backlog_ids)
        self.assertFalse(rollout_ids & backlog_ids)
        self.assertEqual(rollout_ids | backlog_ids, set(source_index))

        family_rollout_ids: set[str] = set()
        family_backlog_ids: set[str] = set()
        for entry in source_entries:
            registry_id = entry["source_registry_id"]
            self.assertEqual(entry["rollout_enabled"], registry_id in rollout_ids)
            if entry["rollout_enabled"]:
                self.assertIsNone(entry["backlog_reason_optional"])
            else:
                self.assertTrue(entry["backlog_reason_optional"])
            self.assertTrue(entry["winning_version_resolution_rule_id"])
            self.assertTrue(entry["clock_precedence_rule_id"])

        for entry in source_family_registry["entries"]:
            for registry_id in entry["baseline_registry_refs"]:
                self.assertIn(registry_id, source_index)
            family_rollout_ids.update(entry["rollout_registry_refs"])
            family_backlog_ids.update(entry["backlog_registry_refs"])
            self.assertEqual(
                set(entry["baseline_registry_refs"]),
                set(entry["rollout_registry_refs"]) | set(entry["backlog_registry_refs"]),
            )

        self.assertEqual(family_rollout_ids, rollout_ids)
        self.assertEqual(family_backlog_ids, backlog_ids)

        for entry in platform_level_registry["entries"]:
            for registry_id in entry["baseline_registry_refs"]:
                self.assertIn(registry_id, source_index)

    def test_stage12_route_policy_baseline_covers_major_routes(self) -> None:
        route_catalog = load_contract("contracts/governance/route_policy_catalog.json")
        policies = route_catalog["policies"]
        route_authority = route_catalog["canonical_authority"]

        self.assertEqual(route_authority["producer_stage"], "stage1_tasking")
        self.assertEqual(route_authority["consumer_stages"], ["stage2_ingestion"])
        self.assertEqual(route_authority["adapter_contract_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(route_authority["live_external_source_enabled"])
        self.assertIn("action_deadline_relation", route_authority["canonical_fields"])

        self.assertGreaterEqual(len(policies), 8)
        self.assertEqual(
            {policy["route_type"] for policy in policies},
            {
                "LIST_TO_DETAIL",
                "DETAIL_DIRECT",
                "ATTACHMENT_FIRST",
                "VERSION_CHAIN",
                "METADATA_ONLY",
                "SEMI_MANUAL",
                "REGISTER_ONLY",
            },
        )

        for policy in policies:
            self.assertTrue(policy["source_family_refs"], policy["route_policy_id"])
            self.assertTrue(policy["platform_level_refs"], policy["route_policy_id"])
            self.assertTrue(policy["carrier_type_refs"], policy["route_policy_id"])
            self.assertTrue(policy["source_registry_refs"], policy["route_policy_id"])
            self.assertEqual(policy["route_fallback_order"][0], policy["default_route"])
            self.assertIn("current_action_deadline_at_optional", policy["action_deadline_relation"]["required_fields"])
            self.assertIn("winning_version_resolution_rule_id", policy["version_chain_relation"])
            self.assertTrue(policy["version_chain_relation"]["precedence_order"])
            self.assertIn("clock_resolution_rule_id", policy["clock_chain_relation"])
            self.assertIn("clock_precedence_rule_id", policy["clock_chain_relation"])
            self.assertTrue(policy["clock_chain_relation"]["precedence_order"])
            self.assertIn("strategy", policy["version_chain_relation"])
            self.assertEqual(
                policy["collection_state_runtime_map"]["baseline_to_runtime"]["ELIGIBLE"],
                "PARSED",
            )
            self.assertEqual(
                policy["collection_state_runtime_map"]["baseline_to_runtime"]["DISCOVERED"],
                "REVIEW_REQUIRED",
            )
            deadline_requirement = policy["action_deadline_relation"]["deadline_provenance_requirement"]
            self.assertTrue(deadline_requirement["required"])
            self.assertEqual(deadline_requirement["source_object"], "clock_chain_profile")
            self.assertFalse(deadline_requirement["live_external_clock_lookup_enabled"])
            self.assertIn("current_action_deadline_at_optional", deadline_requirement["deadline_fields"])
            for field_name in (
                "source_registry_id",
                "route_policy_id",
                "clock_precedence_rule_id",
                "clock_resolution_rule_id",
            ):
                self.assertIn(field_name, deadline_requirement["anchor_fields"])

    def test_stage1_time_range_falls_back_to_now_year_bounds(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.pop("time_range_from", None)
        payload.pop("time_range_until", None)

        extraction = extract_stage1(payload, Stage1Service().store, now=payload["now"])

        self.assertEqual(extraction.time_range_from, "2026-01-01")
        self.assertEqual(extraction.time_range_until, "2026-12-31")
        self.assertIn("time_range_from_from_now_year", extraction.fallback_reasons)
        self.assertIn("time_range_until_from_now_year", extraction.fallback_reasons)

    def test_stage1_route_falls_back_from_registry_when_default_route_missing(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.pop("default_route", None)

        extraction = extract_stage1(payload, Stage1Service().store, now=payload["now"])

        self.assertEqual(extraction.default_route, "LIST_TO_DETAIL")
        self.assertEqual(extraction.fallback_route, "DETAIL_DIRECT")

    def test_stage1_rollout_scope_marks_backlog_entry_for_review(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "source_family": "OTHER_PUBLIC_SOURCE",
                "platform_level": "ENTERPRISE_SITE",
                "region_scope": "CITY",
                "coverage_tier": "T2_LOCAL",
                "carrier_type": "TEXT_SEGMENT",
            }
        )
        payload.pop("default_route", None)
        payload.pop("fallback_route", None)

        extraction = extract_stage1(payload, Stage1Service().store, now=payload["now"])

        self.assertFalse(extraction.rollout_enabled)
        self.assertEqual(extraction.baseline_collection_state, "DISCOVERED")
        self.assertEqual(extraction.clock_precedence_rule_id, "CLOCK-REGISTER-ONLY-001")
        self.assertTrue(extraction.requires_manual_review)
        self.assertIn("rollout_scope_requires_review", extraction.fallback_reasons)

    def test_stage1_service_projects_h01_optional_authority_fields(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "current_action_start_at_optional": "2026-04-01T00:00:00Z",
                "current_action_deadline_at_optional": "2026-04-12T23:59:59Z",
            }
        )

        stage1 = Stage1Service().run(payload)

        self.assertEqual(stage1.handoff.get("baseline_collection_state"), "ELIGIBLE")
        self.assertTrue(stage1.handoff.get("rollout_enabled"))
        self.assertIsNone(stage1.handoff.get("backlog_reason_optional"))
        self.assertEqual(stage1.handoff.get("clock_resolution_rule_id"), "CLOCK-DEFAULT")
        self.assertEqual(stage1.handoff.get("clock_precedence_rule_id"), "CLOCK-PROC-NOTICE-001")
        self.assertEqual(
            stage1.handoff.get("current_action_start_at_optional"),
            "2026-04-01T00:00:00Z",
        )
        self.assertEqual(
            stage1.handoff.get("current_action_deadline_at_optional"),
            "2026-04-12T23:59:59Z",
        )
        self.assertEqual(stage1.inputs.get("baseline_collection_state"), "ELIGIBLE")
        self.assertTrue(stage1.inputs.get("rollout_enabled"))
        self.assertEqual(stage1.inputs.get("clock_precedence_rule_id"), "CLOCK-PROC-NOTICE-001")

    def test_stage2_consumes_h01_authority_instead_of_raw_input_override(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "current_action_start_at_optional": "2026-04-01T00:00:00Z",
                "current_action_deadline_at_optional": "2026-04-12T23:59:59Z",
            }
        )
        stage1 = Stage1Service().run(payload)
        conflicted = copy.deepcopy(stage1.inputs)
        conflicted["default_route"] = "DETAIL_DIRECT"
        conflicted["source_registry_id"] = "SRC-REG-PROC-CITY-PDF"
        conflicted["carrier_type"] = "IMAGE_ATTACHMENT"
        conflicted_bundle = type(stage1)(
            stage=stage1.stage,
            records=dict(stage1.records),
            handoff=dict(stage1.handoff),
            trace_rules=list(stage1.trace_rules),
            inputs=conflicted,
        )

        stage2 = Stage2Service().run(conflicted_bundle)

        self.assertEqual(stage2.record("public_chain").get("default_route"), "LIST_TO_DETAIL")
        self.assertEqual(stage2.handoff.get("source_registry_id"), "SRC-REG-PROC-NATIONAL-HTML")
        self.assertEqual(stage2.record("public_chain").get("carrier_type"), "HTML_PAGE")
        self.assertEqual(stage2.record("public_chain").get("route_policy_id"), "ROUTE-PROC-NOTICE-001")
        self.assertEqual(stage2.record("public_chain").get("fallback_route"), "DETAIL_DIRECT")
        self.assertEqual(stage2.record("clock_chain_profile").get("clock_resolution_rule_id"), "CLOCK-DEFAULT")
        self.assertEqual(
            stage2.record("clock_chain_profile").get("current_action_start_at_optional"),
            "2026-04-01T00:00:00Z",
        )
        self.assertEqual(
            stage2.record("clock_chain_profile").get("current_action_deadline_at_optional"),
            "2026-04-12T23:59:59Z",
        )
        self.assertEqual(stage2.inputs["stage12_extractor_trace"]["stage2"]["default_route_source"], "h01_authority")

    def test_stage2_precedence_resolves_from_contracts_before_compatibility_default(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "current_action_start_at_optional": "2026-04-01T00:00:00Z",
                "current_action_deadline_at_optional": "2026-04-12T23:59:59Z",
            }
        )
        stage1 = Stage1Service().run(payload)

        extraction = extract_stage2(stage1, Stage2Service().store, now=payload["now"])

        self.assertEqual(extraction.baseline_collection_state, "ELIGIBLE")
        self.assertTrue(extraction.rollout_enabled)
        self.assertEqual(extraction.version_precedence_rule_id, "VERSION-PROC-NOTICE-001")
        self.assertEqual(extraction.version_precedence_source, "source_registry")
        self.assertEqual(extraction.clock_precedence_rule_id, "CLOCK-PROC-NOTICE-001")
        self.assertEqual(extraction.clock_precedence_source, "source_registry")
        self.assertEqual(extraction.winning_version_resolution_rule_id, "VERSION-PROC-NOTICE-001")

    def test_stage2_collection_state_runtime_mapping_projects_backlog_to_review(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "source_family": "OTHER_PUBLIC_SOURCE",
                "platform_level": "ENTERPRISE_SITE",
                "region_scope": "CITY",
                "coverage_tier": "T2_LOCAL",
                "carrier_type": "TEXT_SEGMENT",
            }
        )
        stage1 = Stage1Service().run(payload)

        extraction = extract_stage2(stage1, Stage2Service().store, now=payload["now"])

        self.assertEqual(extraction.baseline_collection_state, "DISCOVERED")
        self.assertFalse(extraction.rollout_enabled)
        self.assertEqual(extraction.collection_state, "REVIEW_REQUIRED")
        self.assertIn("rollout_scope_requires_review", extraction.route_review_reasons)

    def test_stage12_authoritative_baseline_runtime_cases(self) -> None:
        cases = [
            {
                "source_family": "AWARD_ANNOUNCEMENT",
                "platform_level": "CITY",
                "region_scope": "CITY",
                "coverage_tier": "T2_LOCAL",
                "carrier_type": "HTML_PAGE",
                "expected_registry": "SRC-REG-AWARD-CITY-HTML",
                "expected_policy": "ROUTE-AWARD-ANNOUNCEMENT-001",
                "expected_route": "LIST_TO_DETAIL",
                "expected_fallback": "DETAIL_DIRECT",
                "expected_decision": "REVIEW",
                "expected_version_strategy": "ANNOUNCEMENT_REPLACEMENT_CHAIN",
                "expected_version_rule": "VERSION-AWARD-ANNOUNCEMENT-001",
            },
            {
                "source_family": "REGULATORY_PUBLICATION",
                "platform_level": "NATIONAL",
                "region_scope": "NATIONAL",
                "coverage_tier": "T0_CORE",
                "carrier_type": "HTML_PAGE",
                "expected_registry": "SRC-REG-REG-NATIONAL-HTML",
                "expected_policy": "ROUTE-REG-PUBLICATION-001",
                "expected_route": "DETAIL_DIRECT",
                "expected_fallback": "METADATA_ONLY",
                "expected_decision": "ALLOW",
                "expected_version_strategy": "LATEST_ONLY",
                "expected_version_rule": "VERSION-REGULATORY-LATEST-001",
            },
            {
                "source_family": "ENTERPRISE_REGISTRY",
                "platform_level": "INDUSTRY_PLATFORM",
                "region_scope": "NATIONAL",
                "coverage_tier": "T1_REGIONAL",
                "carrier_type": "TABLE_SEGMENT",
                "expected_registry": "SRC-REG-ENTERPRISE-INDUSTRY-TABLE",
                "expected_policy": "ROUTE-ENTERPRISE-REGISTRY-001",
                "expected_route": "METADATA_ONLY",
                "expected_fallback": "SEMI_MANUAL",
                "expected_decision": "REVIEW",
                "expected_version_strategy": "METADATA_REFRESH_CHAIN",
                "expected_version_rule": "VERSION-ENTERPRISE-REGISTRY-001",
            },
            {
                "source_family": "JUDICIAL_CREDIT_RISK",
                "platform_level": "COUNTY",
                "region_scope": "COUNTY",
                "coverage_tier": "T2_LOCAL",
                "carrier_type": "IMAGE_ATTACHMENT",
                "expected_registry": "SRC-REG-JUDICIAL-COUNTY-IMAGE",
                "expected_policy": "ROUTE-JUDICIAL-SEMI-MANUAL-001",
                "expected_route": "SEMI_MANUAL",
                "expected_fallback": "REGISTER_ONLY",
                "expected_decision": "REVIEW",
                "expected_version_strategy": "ATTACHMENT_WITH_VERSION_TRACE",
                "expected_version_rule": "VERSION-JUDICIAL-ATTACHMENT-001",
            },
            {
                "source_family": "ANNEX_QA_SUPPLEMENT",
                "platform_level": "PROVINCE",
                "region_scope": "PROVINCE",
                "coverage_tier": "T1_REGIONAL",
                "carrier_type": "DOC_ATTACHMENT",
                "expected_registry": "SRC-REG-ANNEX-PROVINCE-DOC",
                "expected_policy": "ROUTE-ANNEX-VERSION-001",
                "expected_route": "VERSION_CHAIN",
                "expected_fallback": "ATTACHMENT_FIRST",
                "expected_decision": "REVIEW",
                "expected_version_strategy": "ANNEX_VERSION_CHAIN",
                "expected_version_rule": "VERSION-ANNEX-CHAIN-001",
            },
            {
                "source_family": "OTHER_PUBLIC_SOURCE",
                "platform_level": "ENTERPRISE_SITE",
                "region_scope": "CITY",
                "coverage_tier": "T2_LOCAL",
                "carrier_type": "TEXT_SEGMENT",
                "expected_registry": "SRC-REG-OTHER-ENTERPRISE-TEXT",
                "expected_policy": "ROUTE-OTHER-REGISTER-001",
                "expected_route": "REGISTER_ONLY",
                "expected_fallback": "SEMI_MANUAL",
                "expected_decision": "REVIEW",
                "expected_version_strategy": "REGISTER_ONLY",
                "expected_version_rule": "VERSION-REGISTER-ONLY-001",
            },
        ]

        for case in cases:
            with self.subTest(source_family=case["source_family"], platform_level=case["platform_level"]):
                payload = load_fixture("internal_chain_happy.json")
                payload.update(
                    {
                        "source_family": case["source_family"],
                        "platform_level": case["platform_level"],
                        "region_scope": case["region_scope"],
                        "coverage_tier": case["coverage_tier"],
                        "carrier_type": case["carrier_type"],
                        "current_action_start_at_optional": "2026-04-01T00:00:00Z",
                        "current_action_deadline_at_optional": "2026-04-12T23:59:59Z",
                    }
                )
                payload.pop("default_route", None)
                payload.pop("fallback_route", None)

                stage1 = Stage1Service().run(payload)
                stage2 = Stage2Service().run(stage1)

                self.assertEqual(stage1.handoff.get("source_registry_id"), case["expected_registry"])
                self.assertEqual(stage1.handoff.get("route_policy_id"), case["expected_policy"])
                self.assertEqual(stage1.handoff.get("carrier_type"), case["carrier_type"])
                self.assertEqual(stage1.handoff.get("default_route"), case["expected_route"])
                self.assertEqual(stage1.handoff.get("fallback_route"), case["expected_fallback"])

                public_chain = stage2.record("public_chain")
                notice_version_chain = stage2.record("notice_version_chain")
                clock_chain = stage2.record("clock_chain_profile")

                self.assertEqual(public_chain.get("source_registry_id"), case["expected_registry"])
                self.assertEqual(public_chain.get("route_policy_id"), case["expected_policy"])
                self.assertEqual(public_chain.get("carrier_type"), case["carrier_type"])
                self.assertEqual(public_chain.get("default_route"), case["expected_route"])
                self.assertEqual(public_chain.get("fallback_route"), case["expected_fallback"])
                self.assertEqual(public_chain.get("route_decision_state"), case["expected_decision"])
                self.assertEqual(notice_version_chain.get("version_chain_strategy"), case["expected_version_strategy"])
                self.assertEqual(
                    notice_version_chain.get("winning_version_resolution_rule_id"),
                    case["expected_version_rule"],
                )
                self.assertEqual(clock_chain.get("clock_resolution_rule_id"), "CLOCK-DEFAULT")
                self.assertEqual(
                    clock_chain.get("current_action_deadline_at_optional"),
                    "2026-04-12T23:59:59Z",
                )

    def test_stage12_extractor_contract_declares_owned_fields(self) -> None:
        contract = load_contract("contracts/governance/stage12_extractor_contract.json")
        interfaces = {entry["interface_id"]: entry for entry in contract["interfaces"]}

        self.assertEqual(
            interfaces["stage1_source_route_extractor"]["owned_fields"],
            ["source_registry_id", "route_policy_id", "default_route", "fallback_route"],
        )
        self.assertIn(
            "winning_version_resolution_rule_id",
            interfaces["stage2_collection_clock_version_extractor"]["owned_fields"],
        )


if __name__ == "__main__":
    unittest.main()
