from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from helpers import load_fixture, load_repo_json
from shared.provider_adapter_config import PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY
from shared.pipeline import run_internal_chain


def _outreach_cadence_policy() -> dict:
    return load_repo_json("contracts/sales/outreach_cadence_catalog.json")["policies"][0]


def _select_cadence_profile(policy: dict, *, urgency: str, window_urgency: int) -> dict:
    normalized_urgency = (urgency or "NORMAL").upper()
    if normalized_urgency == "CRITICAL" or window_urgency >= 90:
        profile_id = "CADENCE-CRITICAL"
    elif normalized_urgency == "HIGH" or window_urgency >= 80:
        profile_id = "CADENCE-HIGH"
    elif normalized_urgency == "LOW":
        profile_id = "CADENCE-LOW"
    else:
        profile_id = "CADENCE-NORMAL"
    return next(item for item in policy["cadence_profiles"] if item["profile_id"] == profile_id)


def _select_channel_ladder(policy: dict, channel_family: str) -> dict:
    return next(item for item in policy["channel_ladders"] if item["entry_channel_family"] == channel_family)


def _feedback_mapping(response_status: str) -> dict:
    entry = load_repo_json("contracts/sales/feedback_reason_catalog.json")["entries"][0]
    return next(item for item in entry["mappings"] if item["response_status"] == response_status)


class TestStage8ResolutionClosure(unittest.TestCase):
    @staticmethod
    def _policy_decisions(stage8_bundle) -> dict[str, dict]:
        return {
            entry["policy_key"]: entry
            for entry in stage8_bundle.inputs.get("policy_trace", [])
            if isinstance(entry, dict) and entry.get("catalog_id")
        }

    @staticmethod
    def _stage8_with_outbox(payload_updates: dict | None = None):
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        if payload_updates:
            payload.update(payload_updates)
        stage8 = run_internal_chain(payload)["stage8"]
        return stage8, stage8.inputs["outreach_execution_outbox_snapshot"]

    def test_source_vendor_usage_policy_requires_carriers_and_blocks_live_override(self) -> None:
        policy = load_repo_json("contracts/sales/source_vendor_usage_policy.json")

        defaults = policy["policyDefaults"]
        self.assertFalse(defaults["default_main_source"])
        self.assertFalse(defaults["formal_main_source_override_allowed"])
        self.assertFalse(defaults["direct_contact_projection_allowed"])
        self.assertIn("LIVE_EXECUTION", defaults["blocked_action_intents"])

        third_party_or_enrichment = [
            item
            for item in policy["stagePolicies"]
            if item["vendor_role"] in {"THIRD_PARTY_SUPPORT_SOURCE", "CONTACT_ENRICHMENT_SOURCE"}
        ]
        self.assertTrue(third_party_or_enrichment)
        for item in third_party_or_enrichment:
            with self.subTest(stage=item["stage_range"], role=item["vendor_role"]):
                self.assertFalse(item.get("default_main_source", False))
                self.assertIn("formal_main_source_override", item["forbidden_actions"])
                self.assertNotIn("LIVE_EXECUTION", item.get("allowed_action_intents", defaults["allowed_action_intents"]))
                self.assertIn("LIVE_EXECUTION", item.get("blocked_action_intents", defaults["blocked_action_intents"]))
                if item["stage_range"] in {"7", "7-8", "8"}:
                    self.assertIn("contact_candidate_collection", item["carrier_path_required"])
                    self.assertIn("contact_selection_trace", item["carrier_path_required"])
                if item["vendor_role"] == "THIRD_PARTY_SUPPORT_SOURCE" or item["stage_range"] in {"7-8", "8"}:
                    self.assertTrue(item.get("formal_merge_required"))

    def test_channel_vendor_execution_policy_keeps_all_channels_non_live(self) -> None:
        policy = load_repo_json("contracts/sales/channel_vendor_execution_policy.json")

        self.assertFalse(policy["policyDefaults"]["live_execution_enabled"])
        self.assertTrue(policy["policyDefaults"]["live_execution_requires_separate_release_gate"])
        for entry in policy["entries"]:
            with self.subTest(vendor=entry["vendor_id"], stage=entry["stage"]):
                self.assertTrue(entry["approval_required"])
                self.assertFalse(entry["live_execution_enabled"])
                self.assertFalse(entry["external_action_enabled"])
                self.assertFalse(entry["direct_mutation_allowed"])
                self.assertFalse(entry["default_open"])
                self.assertIn("LIVE_EXECUTION", entry["blocked_action_intents"])
                self.assertNotEqual(entry["writeback_scope"], "live_execution")

    def test_stage8_candidate_pool_prefers_organization_path(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-personal",
                "org_name": "Personal Candidate",
                "org_type": "INDIVIDUAL",
                "person_name_optional": "张三",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "PHONE",
                "channel_family": "PERSONAL_PHONE",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "CUSTOMER_AUTHORIZED_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T10:00:00Z"
            },
            {
                "candidate_id": "cand-org",
                "org_name": "Org Candidate",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T09:00:00Z"
            }
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        trace = stage8.inputs["stage8_resolution_trace"]["candidate_resolution"]

        self.assertEqual(contact_target.get("org_name"), "Org Candidate")
        self.assertTrue(contact_target.get("primary_contact_flag"))
        self.assertEqual(trace["selected_candidate_id"], "cand-org")
        self.assertEqual(trace["selected_candidate_source"], "candidate_pool")
        self.assertEqual(
            stage8.inputs["contact_candidate_collection_snapshot"]["winning_contact_candidate_id"],
            "cand-org",
        )
        self.assertEqual(
            stage8.inputs["contact_selection_trace_snapshot"]["winning_contact_candidate_id"],
            "cand-org",
        )

    def test_stage8_priority_tiebreaker_prefers_higher_legal_basis_before_recency(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-public-newer",
                "org_name": "Org Public",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T10:00:00Z",
            },
            {
                "candidate_id": "cand-authorized-older",
                "org_name": "Org Authorized",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "CUSTOMER_AUTHORIZED_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T09:00:00Z",
            },
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        collection = stage8.inputs["contact_candidate_collection_snapshot"]
        selection_trace = stage8.inputs["contact_selection_trace_snapshot"]
        contact_target = stage8.record("contact_target")

        self.assertEqual(collection.get("winning_contact_candidate_id"), "cand-authorized-older")
        self.assertEqual(selection_trace.get("winning_contact_candidate_id"), "cand-authorized-older")
        self.assertEqual(contact_target.get("org_name"), "Org Authorized")
        self.assertEqual(contact_target.get("contact_legal_basis"), "CUSTOMER_AUTHORIZED_CONTACT")

    def test_stage8_candidate_pool_conflict_trace_is_emitted(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-proc",
                "org_name": "Proc Candidate",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T10:00:00Z"
            },
            {
                "candidate_id": "cand-legal",
                "org_name": "Legal Candidate",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "LEGAL_ACTION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T09:00:00Z"
            }
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        trace = stage8.inputs["stage8_resolution_trace"]["candidate_resolution"]

        self.assertTrue(contact_target.get("contact_conflict_flag"))
        self.assertEqual(contact_target.get("contact_conflict_reason"), "role_cluster_diff_within_5")
        self.assertTrue(trace["conflict_flag"])
        self.assertEqual(trace["conflict_reason"], "role_cluster_diff_within_5")

    def test_stage8_restricted_channel_review_persists_conflict_and_review_path(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-personal-only",
                "org_name": "Personal Candidate",
                "org_type": "INDIVIDUAL",
                "person_name_optional": "李四",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "PHONE",
                "channel_family": "PERSONAL_PHONE",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "CUSTOMER_AUTHORIZED_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T10:00:00Z",
            }
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        outreach_plan = stage8.record("outreach_plan")
        trace = self._policy_decisions(stage8)

        self.assertEqual(contact_target.get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertEqual(outreach_plan.get("plan_status"), "REVIEW_REQUIRED")
        self.assertTrue(contact_target.get("contact_conflict_flag"))
        self.assertTrue(contact_target.get("requires_manual_review"))
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["candidate_compliance_decision"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["execution_compliance_decision"],
            "REVIEW_REQUIRED",
        )

    def test_stage8_formal_contact_candidate_collection_and_trace_are_emitted(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-primary",
                "org_name": "Primary Org",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T09:30:00Z"
            },
            {
                "candidate_id": "cand-backup",
                "org_name": "Backup Org",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "LEGAL_ACTION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T08:30:00Z"
            }
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        collection = stage8.inputs["contact_candidate_collection_snapshot"]
        selection_trace = stage8.inputs["contact_selection_trace_snapshot"]
        contact_target = stage8.record("contact_target")

        self.assertEqual(collection.get("winning_contact_candidate_id"), "cand-primary")
        self.assertEqual(selection_trace.get("contact_candidate_collection_id"), collection.get("contact_candidate_collection_id"))
        self.assertEqual(selection_trace.get("winning_contact_candidate_id"), collection.get("winning_contact_candidate_id"))
        self.assertEqual(contact_target.get("org_name"), "Primary Org")
        self.assertEqual(contact_target.get("contact_selection_reason"), selection_trace.get("winning_selection_reason"))
        self.assertEqual(stage8.inputs["contact_candidate_collection_id_optional"], collection.get("contact_candidate_collection_id"))
        self.assertEqual(stage8.inputs["contact_selection_trace_id_optional"], selection_trace.get("contact_selection_trace_id"))

    def test_stage8_reselect_history_is_formally_persisted(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["response_status"] = "WRONG_ROLE"
        payload["previous_contact_candidate_id_optional"] = "cand-old"
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-new",
                "org_name": "New Org",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T11:00:00Z"
            }
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        collection = stage8.inputs["contact_candidate_collection_snapshot"]
        selection_trace = stage8.inputs["contact_selection_trace_snapshot"]
        reselect_history = collection.get("reselect_history")

        self.assertEqual(collection.get("reselect_reason_optional"), "wrong_role_reselect_required")
        self.assertEqual(selection_trace.get("reselect_reason_optional"), "wrong_role_reselect_required")
        self.assertEqual(reselect_history[0]["reselect_from_candidate_id"], "cand-old")
        self.assertEqual(reselect_history[0]["reselect_to_candidate_id"], collection.get("winning_contact_candidate_id"))
        self.assertEqual(selection_trace.get("reselect_history")[0]["trigger_response_status"], "WRONG_ROLE")

    def test_stage8_multi_source_merge_dedupe_and_source_conflict_are_materialized(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload["contact_candidate_pool"] = [
            {
                "candidate_id": "cand-official",
                "org_name": "Merged Org",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "source_vendor_id_optional": "SOURCE-OFFICIAL-WEBSITE",
                "public_contact_source": "OFFICIAL_SITE",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T10:00:00Z",
            },
            {
                "candidate_id": "cand-third-party",
                "org_name": "Merged Org",
                "org_type": "ENTERPRISE",
                "person_name_optional": "UNKNOWN",
                "role_cluster": "PROCUREMENT_DECISION",
                "source_vendor_role": "THIRD_PARTY_SUPPORT_SOURCE",
                "source_vendor_id_optional": "SOURCE-TIANYANCHA",
                "public_contact_source": "TIANYANCHA",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
                "contact_validity_status": "VALID",
                "contact_legal_basis": "REVIEW_REQUIRED",
                "reasonable_expectation_status": "REASONABLE",
                "channel_policy_status": "ALLOW",
                "frequency_policy_state": "ALLOW",
                "opt_out_state": "ACTIVE",
                "quiet_hours_policy_state": "ALLOW",
                "source_auditability_state": "AUDITABLE",
                "last_evaluated_at": "2026-04-17T09:00:00Z",
            },
        ]

        stage8 = run_internal_chain(payload)["stage8"]
        collection = stage8.inputs["contact_candidate_collection_snapshot"]
        selection_trace = stage8.inputs["contact_selection_trace_snapshot"]
        merged_candidate = collection["candidate_list"][0]
        trace_entry = selection_trace["trace_entries"][0]

        self.assertEqual(len(collection["candidate_list"]), 1)
        self.assertTrue(collection["dedupe_applied"])
        self.assertEqual(collection["merge_policy_id"], "contact_candidate_formal_merge_v1")
        self.assertEqual(merged_candidate["formal_merge_state"], "FORMAL_MERGED_MULTI_SOURCE")
        self.assertEqual(
            merged_candidate["merged_candidate_ids"],
            ["cand-official", "cand-third-party"],
        )
        self.assertTrue(merged_candidate["source_conflict_flag"])
        self.assertIn("contact_legal_basis", merged_candidate["source_conflict_fields"])
        self.assertTrue(merged_candidate["source_merge_review_required"])
        self.assertTrue(trace_entry["source_conflict_flag"])
        self.assertEqual(
            stage8.inputs["stage8_resolution_trace"]["candidate_resolution"]["selected_candidate_source"],
            "formal_merge",
        )
        self.assertEqual(stage8.record("contact_target").get("source_vendor_role"), "PUBLIC_OFFICIAL_SOURCE")
        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "REVIEW_REQUIRED")

    def test_stage8_third_party_single_source_requires_formal_merge_review(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "source_vendor_role": "THIRD_PARTY_SUPPORT_SOURCE",
                "source_vendor_id_optional": "SOURCE-TIANYANCHA",
                "public_contact_source": "TIANYANCHA",
                "contact_channel": "EMAIL",
                "channel_family": "ORG_EMAIL",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        collection = stage8.inputs["contact_candidate_collection_snapshot"]
        selection_trace = stage8.inputs["contact_selection_trace_snapshot"]
        candidate = collection["candidate_list"][0]

        self.assertEqual(candidate["formal_merge_state"], "REVIEW_REQUIRED_SINGLE_THIRD_PARTY")
        self.assertTrue(candidate["source_merge_review_required"])
        self.assertEqual(collection["source_merge_review_required_count"], 1)
        self.assertEqual(selection_trace["source_merge_review_required_count"], 1)
        self.assertEqual(
            stage8.inputs["stage8_resolution_trace"]["candidate_resolution"]["selected_candidate_source"],
            "formal_merge",
        )
        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertTrue(stage8.record("contact_target").get("requires_manual_review"))

    def test_stage8_vendor_resolution_uses_registry_and_policy(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "source_vendor_role": "CONTACT_ENRICHMENT_SOURCE",
                "channel_family": "ORG_EMAIL",
                "contact_channel": "EMAIL"
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        outreach_plan = stage8.record("outreach_plan")
        trace = stage8.inputs["stage8_resolution_trace"]

        self.assertEqual(contact_target.get("source_vendor_id_optional"), "SOURCE-AUTHORIZED-CRM")
        self.assertEqual(contact_target.get("source_vendor_role"), "CONTACT_ENRICHMENT_SOURCE")
        self.assertEqual(contact_target.get("fallback_vendor_id_optional"), "SOURCE-AUTHORIZED-CRM")
        self.assertEqual(outreach_plan.get("execution_vendor_id_optional"), "EXEC-EMAIL-SERVICE")
        self.assertEqual(outreach_plan.get("fallback_vendor_id_optional"), "EXEC-EMAIL-SERVICE")
        self.assertNotEqual(
            contact_target.get("source_vendor_id_optional"),
            outreach_plan.get("execution_vendor_id_optional"),
        )
        self.assertEqual(trace["source_vendor_resolution"]["resolved_from"], "POLICY_DEFAULT")
        self.assertEqual(trace["source_vendor_resolution"]["decision_state"], "ALLOW")
        self.assertEqual(trace["execution_vendor_resolution"]["resolved_from"], "POLICY_DEFAULT")
        self.assertEqual(trace["execution_vendor_resolution"]["decision_state"], "ALLOW")

    def test_stage8_unknown_source_vendor_blocks_without_project_fallback(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "source_vendor_id_optional": "SOURCE-UNKNOWN-REGISTRY",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        trace = stage8.inputs["stage8_resolution_trace"]["source_vendor_resolution"]

        self.assertEqual(trace["resolved_from"], "EXPLICIT_UNKNOWN_VENDOR")
        self.assertEqual(trace["decision_state"], "BLOCK")
        self.assertEqual(contact_target.get("source_vendor_id_optional"), "SOURCE-UNKNOWN-REGISTRY")
        self.assertEqual(contact_target.get("fallback_vendor_id_optional"), "SOURCE-OFFICIAL-WEBSITE")
        self.assertEqual(contact_target.get("contact_target_status"), "BLOCKED")
        self.assertTrue(contact_target.get("requires_manual_review"))
        self.assertFalse(contact_target.get("auto_contact_allowed"))
        self.assertNotIn("PROJECT_FALLBACK", trace["resolved_from"])
        self.assertFalse(contact_target.get("fallback_vendor_id_optional", "").startswith("NO-FALLBACK-"))

    def test_stage8_unknown_source_vendor_keeps_execution_owner_separate(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                "source_vendor_id_optional": "SOURCE-UNKNOWN-REGISTRY",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        contact_target = stage8.record("contact_target")
        outreach_plan = stage8.record("outreach_plan")
        source_trace = stage8.inputs["stage8_resolution_trace"]["source_vendor_resolution"]
        execution_trace = stage8.inputs["stage8_resolution_trace"]["execution_vendor_resolution"]

        self.assertEqual(contact_target.get("source_vendor_id_optional"), "SOURCE-UNKNOWN-REGISTRY")
        self.assertEqual(contact_target.get("fallback_vendor_id_optional"), "SOURCE-OFFICIAL-WEBSITE")
        self.assertEqual(outreach_plan.get("execution_vendor_id_optional"), "EXEC-EMAIL-SERVICE")
        self.assertEqual(outreach_plan.get("fallback_vendor_id_optional"), "EXEC-EMAIL-SERVICE")
        self.assertNotEqual(
            contact_target.get("source_vendor_id_optional"),
            outreach_plan.get("execution_vendor_id_optional"),
        )
        self.assertEqual(source_trace["resolved_from"], "EXPLICIT_UNKNOWN_VENDOR")
        self.assertEqual(source_trace["decision_state"], "BLOCK")
        self.assertEqual(execution_trace["resolved_from"], "POLICY_DEFAULT")
        self.assertEqual(execution_trace["decision_state"], "ALLOW")

    def test_stage8_unknown_execution_vendor_blocks_without_project_fallback(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "channel_family": "ORG_EMAIL",
                "contact_channel": "EMAIL",
                "execution_vendor_id_optional": "EXEC-UNKNOWN-SERVICE",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        outreach_plan = stage8.record("outreach_plan")
        touch_record = stage8.record("touch_record")
        trace = stage8.inputs["stage8_resolution_trace"]["execution_vendor_resolution"]

        self.assertEqual(trace["resolved_from"], "EXPLICIT_UNKNOWN_VENDOR")
        self.assertEqual(trace["decision_state"], "BLOCK")
        self.assertEqual(outreach_plan.get("execution_vendor_id_optional"), "EXEC-UNKNOWN-SERVICE")
        self.assertEqual(outreach_plan.get("fallback_vendor_id_optional"), "EXEC-EMAIL-SERVICE")
        self.assertEqual(outreach_plan.get("plan_status"), "BLOCKED")
        self.assertTrue(outreach_plan.get("requires_manual_review"))
        self.assertEqual(touch_record.get("touch_record_state"), "CANCELLED")
        self.assertNotIn("PROJECT_FALLBACK", trace["resolved_from"])
        self.assertFalse(outreach_plan.get("fallback_vendor_id_optional", "").startswith("NO-FALLBACK-"))

    def test_stage8_service_consumes_formal_winner_snapshot_instead_of_selected_projection(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "source_vendor_role": "CONTACT_ENRICHMENT_SOURCE",
                "source_vendor_id_optional": "SOURCE-AUTHORIZED-CRM",
            }
        )
        selected_candidate = {
            "candidate_id": "cand-formal",
            "org_name": "Formal Winner Org",
            "org_type": "ENTERPRISE",
            "person_name_optional": "UNKNOWN",
            "role_cluster": "PROCUREMENT_DECISION",
            "public_contact_source": "AUTHORIZED_CRM",
            "source_family": "PROCUREMENT_NOTICE",
            "source_auditability_state": "AUDITABLE",
            "source_vendor_role": "CONTACT_ENRICHMENT_SOURCE",
            "source_vendor_id_optional": "SOURCE-AUTHORIZED-CRM",
            "source_vendor_type_optional": "SOURCE_VENDOR",
            "source_audit_ref": "AUDIT-CRM",
            "query_trace_id": "TRACE-CRM",
            "vendor_response_ref_optional": "RESP-CRM",
            "fallback_vendor_id_optional": "SOURCE-AUTHORIZED-CRM",
            "contact_channel": "EMAIL",
            "channel_family": "ORG_EMAIL",
            "contact_validity_status": "VALID",
            "contact_legal_basis": "CUSTOMER_AUTHORIZED_CONTACT",
            "reasonable_expectation_status": "REASONABLE",
            "channel_policy_status": "ALLOW",
            "frequency_policy_state": "ALLOW",
            "opt_out_state": "ACTIVE",
            "quiet_hours_policy_state": "ALLOW",
            "last_evaluated_at": "2026-04-17T10:00:00Z",
            "contact_priority_score": 95,
            "contact_priority_reason_tags": ["selected_projection"],
            "contact_candidate_rank": 1,
            "primary_contact_flag": True,
            "contact_selection_reason": "selected_projection_should_not_win",
            "contact_conflict_flag": False,
            "contact_conflict_reason": "no_conflict",
            "merge_key": "candidate_identity::cand-formal",
            "merged_candidate_ids": ["cand-formal"],
            "merged_source_roles": ["CONTACT_ENRICHMENT_SOURCE"],
            "merged_source_vendor_ids_optional": ["SOURCE-AUTHORIZED-CRM"],
            "formal_merge_state": "NOT_REQUIRED_SINGLE_SOURCE",
            "source_conflict_flag": False,
            "source_conflict_reason": "no_source_conflict",
            "source_conflict_fields": [],
            "source_merge_review_required": False,
        }
        candidate_trace = {
            "candidate_pool_mode": "CONTACT_TARGET_EQUIVALENT_COLLECTION",
            "candidate_pool_count": 1,
            "input_candidate_count": 1,
            "merge_policy_id": "contact_candidate_formal_merge_v1",
            "dedupe_applied": False,
            "source_conflict_candidate_count": 0,
            "source_merge_review_required_count": 0,
            "eligible_candidate_count": 1,
            "selected_candidate_id": "cand-formal",
            "selected_candidate_source": "formal_merge",
            "merged_candidates": [
                {
                    "candidate_id": "cand-formal",
                    "org_name": "Formal Winner Org",
                    "org_type": "ENTERPRISE",
                    "person_name_optional": "UNKNOWN",
                    "role_cluster": "PROCUREMENT_DECISION",
                    "public_contact_source": "OFFICIAL_SITE",
                    "source_family": "PROCUREMENT_NOTICE",
                    "source_auditability_state": "AUDITABLE",
                    "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                    "source_vendor_id_optional": "SOURCE-OFFICIAL-WEBSITE",
                    "source_vendor_type_optional": "SOURCE_VENDOR",
                    "source_audit_ref": "AUDIT-OFFICIAL",
                    "query_trace_id": "TRACE-OFFICIAL",
                    "vendor_response_ref_optional": "RESP-OFFICIAL",
                    "fallback_vendor_id_optional": "SOURCE-OFFICIAL-WEBSITE",
                    "contact_channel": "EMAIL",
                    "channel_family": "ORG_EMAIL",
                    "contact_validity_status": "VALID",
                    "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                    "reasonable_expectation_status": "REASONABLE",
                    "channel_policy_status": "ALLOW",
                    "frequency_policy_state": "ALLOW",
                    "opt_out_state": "ACTIVE",
                    "quiet_hours_policy_state": "ALLOW",
                    "last_evaluated_at": "2026-04-17T10:00:00Z",
                    "contact_selection_reason": "formal_winner_snapshot",
                    "contact_priority_reason_tags": ["formal_trace"],
                    "merge_key": "candidate_identity::cand-formal",
                    "merged_candidate_ids": ["cand-formal"],
                    "merged_source_roles": ["PUBLIC_OFFICIAL_SOURCE"],
                    "merged_source_vendor_ids_optional": ["SOURCE-OFFICIAL-WEBSITE"],
                    "formal_merge_state": "NOT_REQUIRED_SINGLE_SOURCE",
                    "source_conflict_flag": False,
                    "source_conflict_reason": "no_source_conflict",
                    "source_conflict_fields": [],
                    "source_merge_review_required": False,
                }
            ],
            "ranked_candidates": [
                {
                    "candidate_id": "cand-formal",
                    "score": 88,
                    "role_cluster": "PROCUREMENT_DECISION",
                    "channel_family": "ORG_EMAIL",
                    "merge_key": "candidate_identity::cand-formal",
                    "merged_candidate_ids": ["cand-formal"],
                    "merged_source_roles": ["PUBLIC_OFFICIAL_SOURCE"],
                    "source_conflict_flag": False,
                    "source_conflict_reason_optional": None,
                    "source_merge_review_required": False,
                    "organization_channel": True,
                    "blocked": False,
                }
            ],
            "conflict_flag": False,
            "conflict_reason": "single candidate",
        }

        with patch(
            "stage8_outreach.service.select_stage8_contact_candidate",
            return_value=(selected_candidate, candidate_trace),
        ):
            stage8 = run_internal_chain(payload)["stage8"]

        contact_target = stage8.record("contact_target")

        self.assertEqual(contact_target.get("source_vendor_role"), "PUBLIC_OFFICIAL_SOURCE")
        self.assertEqual(contact_target.get("source_vendor_id_optional"), "SOURCE-OFFICIAL-WEBSITE")
        self.assertEqual(contact_target.get("public_contact_source"), "OFFICIAL_SITE")
        self.assertNotEqual(contact_target.get("source_vendor_id_optional"), "SOURCE-AUTHORIZED-CRM")

    def test_stage8_source_conflict_without_merge_review_still_forces_governed_review(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        selected_candidate = {
            "candidate_id": "cand-conflict",
            "org_name": "Conflict Org",
            "org_type": "ENTERPRISE",
            "person_name_optional": "UNKNOWN",
            "role_cluster": "PROCUREMENT_DECISION",
            "public_contact_source": "OFFICIAL_SITE",
            "source_family": "PROCUREMENT_NOTICE",
            "source_auditability_state": "AUDITABLE",
            "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
            "source_vendor_id_optional": "SOURCE-OFFICIAL-WEBSITE",
            "source_vendor_type_optional": "SOURCE_VENDOR",
            "source_audit_ref": "AUDIT-OFFICIAL",
            "query_trace_id": "TRACE-OFFICIAL",
            "vendor_response_ref_optional": "RESP-OFFICIAL",
            "fallback_vendor_id_optional": "SOURCE-OFFICIAL-WEBSITE",
            "contact_channel": "EMAIL",
            "channel_family": "ORG_EMAIL",
            "contact_validity_status": "VALID",
            "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
            "reasonable_expectation_status": "REASONABLE",
            "channel_policy_status": "ALLOW",
            "frequency_policy_state": "ALLOW",
            "opt_out_state": "ACTIVE",
            "quiet_hours_policy_state": "ALLOW",
            "last_evaluated_at": "2026-04-17T10:00:00Z",
            "contact_priority_score": 88,
            "contact_priority_reason_tags": ["formal_trace"],
            "contact_candidate_rank": 1,
            "primary_contact_flag": True,
            "contact_selection_reason": "formal_winner_snapshot",
            "contact_conflict_flag": False,
            "contact_conflict_reason": "no_conflict",
            "merge_key": "candidate_identity::cand-conflict",
            "merged_candidate_ids": ["cand-conflict"],
            "merged_source_roles": ["PUBLIC_OFFICIAL_SOURCE"],
            "merged_source_vendor_ids_optional": ["SOURCE-OFFICIAL-WEBSITE"],
            "formal_merge_state": "NOT_REQUIRED_SINGLE_SOURCE",
            "source_conflict_flag": True,
            "source_conflict_reason": "source_conflict:public_contact_source",
            "source_conflict_fields": ["public_contact_source"],
            "source_merge_review_required": False,
        }
        candidate_trace = {
            "candidate_pool_mode": "CONTACT_TARGET_EQUIVALENT_COLLECTION",
            "candidate_pool_count": 1,
            "input_candidate_count": 1,
            "merge_policy_id": "contact_candidate_formal_merge_v1",
            "dedupe_applied": False,
            "source_conflict_candidate_count": 1,
            "source_merge_review_required_count": 0,
            "eligible_candidate_count": 1,
            "selected_candidate_id": "cand-conflict",
            "selected_candidate_source": "formal_merge",
            "merged_candidates": [dict(selected_candidate)],
            "ranked_candidates": [
                {
                    "candidate_id": "cand-conflict",
                    "score": 88,
                    "role_cluster": "PROCUREMENT_DECISION",
                    "channel_family": "ORG_EMAIL",
                    "merge_key": "candidate_identity::cand-conflict",
                    "merged_candidate_ids": ["cand-conflict"],
                    "merged_source_roles": ["PUBLIC_OFFICIAL_SOURCE"],
                    "source_conflict_flag": True,
                    "source_conflict_reason_optional": "source_conflict:public_contact_source",
                    "source_merge_review_required": False,
                    "organization_channel": True,
                    "blocked": False,
                }
            ],
            "conflict_flag": False,
            "conflict_reason": "single candidate",
        }

        with patch(
            "stage8_outreach.service.select_stage8_contact_candidate",
            return_value=(selected_candidate, candidate_trace),
        ):
            stage8 = run_internal_chain(payload)["stage8"]

        governed = stage8.record("outreach_plan").get("governed_metadata", {})
        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "REVIEW_REQUIRED")
        self.assertEqual(stage8.record("touch_record").get("touch_record_state"), "CREATED")
        self.assertEqual(governed.get("projection_mode"), "INTERNAL_GOVERNED_PREVIEW")
        self.assertEqual(governed.get("requested_delivery_surface"), "INTERNAL_OPERATIONS")

    def test_stage8_governed_metadata_carries_compliance_lattice(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"run_mode": "APPROVAL_RUN", "approval_state": "PENDING"})

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8)
        governed = stage8.record("outreach_plan").get("governed_metadata", {})

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "ELIGIBLE")
        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "REVIEW_REQUIRED")
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["candidate_compliance_decision"],
            "ALLOW_PREVIEW",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["execution_compliance_decision"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(governed.get("candidate_compliance_decision"), "ALLOW_PREVIEW")
        self.assertEqual(governed.get("execution_compliance_decision"), "REVIEW_REQUIRED")
        self.assertEqual(governed.get("stop_semantics"), "EXECUTION_REVIEW_REQUIRED")

    def test_stage8_contact_priority_reason_tags_include_formal_stage7_dimensions(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))

        result = run_internal_chain(payload)
        stage8 = result["stage8"]
        stage7 = result["stage7"]
        contact_target = stage8.record("contact_target")
        reason_tags = set(contact_target.get("contact_priority_reason_tags", []))

        self.assertIn(
            f"OPPORTUNITY_{stage7.record('saleable_opportunity').get('opportunity_grade')}",
            reason_tags,
        )
        self.assertIn(
            f"URGENCY_{stage8.inputs.get('commercial_urgency_level_optional')}",
            reason_tags,
        )
        self.assertIn(
            f"ACTIONABILITY_{stage7.record('legal_action_actor_profile').get('actionability_state')}",
            reason_tags,
        )
        self.assertIn(
            f"REACHABILITY_{stage7.record('procurement_decision_actor_profile').get('reachable_state')}",
            reason_tags,
        )

    def test_stage8_quiet_hours_only_schedules_execution_and_keeps_candidate_eligible(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"quiet_hours_policy_state": "BLOCK"})

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8)
        governed = stage8.record("outreach_plan").get("governed_metadata", {})

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "ELIGIBLE")
        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "SCHEDULED")
        self.assertEqual(stage8.record("touch_record").get("touch_record_state"), "CREATED")
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["candidate_compliance_decision"],
            "ALLOW_PREVIEW",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["execution_compliance_decision"],
            "SCHEDULED",
        )
        self.assertEqual(governed.get("candidate_compliance_decision"), "ALLOW_PREVIEW")
        self.assertEqual(governed.get("execution_compliance_decision"), "SCHEDULED")
        self.assertEqual(governed.get("stop_semantics"), "QUIET_HOURS_SCHEDULE")

    def test_stage8_outreach_cadence_trace_exposes_single_sourced_channel_ladder(self) -> None:
        cadence_policy = _outreach_cadence_policy()
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "channel_family": "ORG_PHONE",
                "contact_channel": "PHONE",
                "commercial_urgency_level_optional": "HIGH",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8)
        cadence_outputs = trace["outreach_cadence"]["outputs"]
        expected_profile = _select_cadence_profile(cadence_policy, urgency="HIGH", window_urgency=50)
        expected_ladder = _select_channel_ladder(cadence_policy, "ORG_PHONE")

        self.assertEqual(cadence_outputs.get("cadence_profile_id"), expected_profile["profile_id"])
        self.assertEqual(cadence_outputs.get("retry_policy_id"), cadence_policy["retry_policy_id"])
        self.assertEqual(cadence_outputs.get("stop_policy_id"), cadence_policy["stop_policy_id"])
        self.assertEqual(cadence_outputs.get("channel_ladder_id"), expected_ladder["ladder_id"])
        self.assertEqual(cadence_outputs.get("ladder_sequence"), expected_ladder["step_sequence"])
        self.assertEqual(cadence_outputs.get("channel_fallback_sequence"), expected_ladder["fallback_sequence"])
        self.assertEqual(
            cadence_outputs.get("fallback_channel_family_optional"),
            expected_ladder["fallback_sequence"][0],
        )
        self.assertEqual(cadence_outputs.get("ladder_sequence_mode"), expected_ladder["sequence_mode"])
        self.assertFalse(cadence_outputs.get("live_execution_enabled"))
        self.assertEqual(
            stage8.record("outreach_plan").get("cadence_profile_id"),
            cadence_outputs.get("cadence_profile_id"),
        )
        self.assertEqual(
            stage8.record("outreach_plan").get("retry_policy_id"),
            cadence_outputs.get("retry_policy_id"),
        )
        self.assertEqual(
            stage8.record("outreach_plan").get("stop_policy_id"),
            cadence_outputs.get("stop_policy_id"),
        )
        self.assertEqual(
            stage8.record("outreach_plan").get("next_touch_due_at_optional"),
            trace["retry_policy"]["outputs"].get("next_touch_due_at_optional"),
        )
        self.assertNotEqual(
            stage8.record("outreach_plan").get("next_touch_due_at_optional"),
            stage8.inputs.get("now"),
        )

    def test_stage8_retry_trace_projects_feedback_writeback_from_single_contract(self) -> None:
        feedback = _feedback_mapping("WRONG_ROLE")
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"response_status": "WRONG_ROLE"})

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8)
        retry_outputs = trace["retry_policy"]["outputs"]
        touch_record = stage8.record("touch_record")

        self.assertEqual(retry_outputs.get("next_action"), "RESELECT_CONTACT")
        self.assertEqual(retry_outputs.get("feedback_reason"), feedback["feedback_reason"])
        self.assertEqual(retry_outputs.get("next_step_optional"), feedback["next_step_optional"])
        self.assertEqual(
            retry_outputs.get("failure_reason_tag_optional"),
            feedback["failure_reason_tag_optional"],
        )
        self.assertEqual(
            retry_outputs.get("stop_reason_optional"),
            feedback["stop_reason_optional"],
        )
        self.assertEqual(retry_outputs.get("writeback_targets"), feedback["writeback_targets"])
        self.assertEqual(
            retry_outputs.get("writeback_target_optional"),
            feedback["writeback_targets"][0],
        )
        self.assertEqual(
            retry_outputs.get("written_back_at_optional"),
            touch_record.get("written_back_at_optional"),
        )
        self.assertTrue(retry_outputs.get("writeback_required"))
        self.assertEqual(touch_record.get("feedback_reason"), feedback["feedback_reason"])
        self.assertEqual(touch_record.get("next_step_optional"), feedback["next_step_optional"])
        self.assertEqual(touch_record.get("writeback_targets"), feedback["writeback_targets"])
        self.assertTrue(stage8.record("outreach_plan").get("writeback_required"))

    def test_stage8_governed_execution_outbox_blocks_live_and_explains_prerequisites(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "run_mode": "REAL_RUN",
                "approval_state": "PENDING",
                "live_execution_enabled": True,
                "audit_trail_present": False,
                "vendor_direct_connection_requested": True,
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        outbox = stage8.inputs["outreach_execution_outbox_snapshot"]
        readiness = stage8.inputs["outbox_readiness_summary"]

        self.assertEqual(outbox["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertEqual(outbox["approval_state"], "PENDING")
        self.assertEqual(outbox["audit_state"], "MISSING")
        self.assertEqual(outbox["vendor_adapter_state"]["state"], "BLOCKED")
        self.assertEqual(outbox["channel_vendor_boundary"]["allowed_adapter_scope"], "INTERNAL_OUTBOX_CARRIER_ONLY")
        self.assertFalse(outbox["live_execution_enabled"])
        self.assertFalse(outbox["real_send_attempted"])
        self.assertFalse(outbox["channel_vendor_boundary"]["real_provider_receipt_allowed"])
        provider_summary = stage8.inputs[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]
        self.assertEqual(provider_summary["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertEqual(provider_summary["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(provider_summary["provider_circuit_breaker_state"], "CLOSED")
        self.assertFalse(provider_summary["provider_reliability_summary"]["live_fallback_allowed"])
        self.assertEqual(outbox["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(outbox["provider_circuit_breaker_state"], "CLOSED")
        self.assertFalse(outbox["provider_adapter_suspended"])
        self.assertFalse(outbox["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertIn("live_execution_requested_but_blocked", outbox["blocked_reasons"])
        self.assertIn("approval_state=PENDING", outbox["blocked_reasons"])
        self.assertIn("audit_ref_missing", outbox["blocked_reasons"])
        self.assertIn("vendor_connection_enabled=false", outbox["blocked_reasons"])
        self.assertIn("external_vendor_connection_disabled", outbox["blocked_reasons"])
        self.assertFalse(readiness["ready_for_real_send"])
        self.assertFalse(readiness["real_send_attempted"])
        self.assertEqual(readiness["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(readiness["provider_circuit_breaker_state"], "CLOSED")
        self.assertTrue(readiness["provider_status_replayable"])

    def test_stage8_governed_execution_outbox_carries_quiet_retry_stop_and_unknown_vendor(self) -> None:
        feedback = _feedback_mapping("WRONG_ROLE")
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "quiet_hours_policy_state": "BLOCK",
                "response_status": "WRONG_ROLE",
                "execution_vendor_id_optional": "EXEC-UNKNOWN-SERVICE",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        outbox = stage8.inputs["outreach_execution_outbox_snapshot"]

        self.assertEqual(outbox["quiet_hours_state"], "SCHEDULED")
        self.assertEqual(outbox["retry_policy"]["retry_policy_id"], stage8.record("outreach_plan").get("retry_policy_id"))
        self.assertEqual(outbox["retry_state"]["state"], "SCHEDULED")
        self.assertEqual(outbox["stop_policy"]["stop_policy_id"], stage8.record("outreach_plan").get("stop_policy_id"))
        self.assertEqual(outbox["stop_state"]["stop_reason_optional"], feedback["stop_reason_optional"])
        self.assertEqual(outbox["vendor_adapter_state"]["resolution_decision_state"], "BLOCK")
        self.assertEqual(outbox["vendor_adapter_state"]["resolved_from"], "EXPLICIT_UNKNOWN_VENDOR")
        self.assertIn("quiet_hours_schedule", outbox["blocked_reasons"])
        self.assertIn("execution_vendor_not_in_registry", outbox["blocked_reasons"])

    def test_stage8_sandbox_execution_record_supports_four_adapter_families(self) -> None:
        scenarios = [
            (
                "email",
                {
                    "channel_family": "ORG_EMAIL",
                    "contact_channel": "EMAIL",
                },
            ),
            (
                "sms",
                {
                    "channel_family": "CRM_APPROVED_DIRECT",
                    "contact_channel": "SMS",
                },
            ),
            (
                "phone_call",
                {
                    "channel_family": "ORG_PHONE",
                    "contact_channel": "PHONE",
                },
            ),
            (
                "wecom_im",
                {
                    "channel_family": "CRM_APPROVED_DIRECT",
                    "contact_channel": "WECOM_IM",
                },
            ),
        ]

        required_fields = {
            "execution_id",
            "outbox_id",
            "outreach_plan_id",
            "touch_record_id",
            "contact_target_id",
            "opportunity_id",
            "channel",
            "adapter_family",
            "sandbox_execution_state",
            "provider_family",
            PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
            "template_approval_state",
            "contact_source_audit_state",
            "frequency_control_state",
            "quiet_hours_state",
            "opt_out_state",
            "unsubscribe_state",
            "bounce_state",
            "failure_state",
            "retry_policy",
            "retry_state",
            "stop_policy",
            "stop_state",
            "execution_timeline",
            "approval_state",
            "audit_state",
            "live_execution_enabled",
            "real_send_attempted",
            "external_delivery_enabled",
            "governed_execution_mode",
            "blocked_reasons",
            "replay_state",
        }

        for expected_family, updates in scenarios:
            with self.subTest(adapter_family=expected_family):
                stage8, outbox = self._stage8_with_outbox(updates)
                readiness = stage8.inputs["outbox_readiness_summary"]

                self.assertTrue(required_fields.issubset(outbox.keys()))
                self.assertEqual(outbox["adapter_family"], expected_family)
                self.assertEqual(outbox["provider_family"], "sales_outreach")
                self.assertIn(
                    outbox["sandbox_execution_state"],
                    {"SANDBOX_RECORDED", "HELD", "BLOCKED", "STOPPED", "SUSPENDED"},
                )
                self.assertFalse(outbox["live_execution_enabled"])
                self.assertFalse(outbox["real_send_attempted"])
                self.assertFalse(outbox["external_delivery_enabled"])
                self.assertEqual(outbox["governed_execution_mode"], "INTERNAL_GOVERNED")
                self.assertEqual(readiness["execution_id"], outbox["execution_id"])
                self.assertEqual(readiness["adapter_family"], expected_family)
                self.assertTrue(outbox["replay_state"]["sandbox_record_replayable"])
                self.assertEqual(
                    outbox["execution_timeline"][-1]["event"],
                    "sandbox_execution_readiness_decided",
                )

    def test_stage8_sandbox_execution_governance_states_explain_blocks_and_holds(self) -> None:
        scenarios = [
            (
                "missing_template",
                {"template_approval_state": "MISSING"},
                "template_approval_state",
                "MISSING",
                "template_approval_missing",
                "BLOCKED",
            ),
            (
                "missing_contact_source_audit",
                {"audit_trail_present": False},
                "contact_source_audit_state",
                "MISSING",
                "contact_source_audit_missing",
                "BLOCKED",
            ),
            (
                "frequency_held",
                {"frequency_policy_state": "BLOCK"},
                "frequency_control_state",
                "HELD",
                "frequency_control_held",
                "HELD",
            ),
            (
                "quiet_hours_held",
                {"quiet_hours_policy_state": "BLOCK"},
                "quiet_hours_state",
                "SCHEDULED",
                "quiet_hours_schedule",
                "HELD",
            ),
            (
                "opt_out_blocked",
                {"opt_out_state": "OPTED_OUT"},
                "opt_out_state",
                "OPTED_OUT",
                "opt_out_blocked",
                "STOPPED",
            ),
            (
                "unsubscribe_blocked",
                {"unsubscribe_state": "UNSUBSCRIBED"},
                "unsubscribe_state",
                "UNSUBSCRIBED",
                "unsubscribe_blocked",
                "STOPPED",
            ),
        ]

        for name, updates, state_field, expected_state, reason, execution_state in scenarios:
            with self.subTest(name=name):
                _, outbox = self._stage8_with_outbox(updates)

                self.assertEqual(outbox[state_field], expected_state)
                self.assertIn(reason, outbox["blocked_reasons"])
                self.assertEqual(outbox["sandbox_execution_state"], execution_state)
                self.assertFalse(outbox["live_execution_enabled"])
                self.assertFalse(outbox["real_send_attempted"])

    def test_stage8_sandbox_execution_bounce_failure_retry_and_stop_readback(self) -> None:
        feedback = _feedback_mapping("INVALID_CONTACT")
        _, outbox = self._stage8_with_outbox(
            {
                "response_status": "INVALID_CONTACT",
                "bounce_state": "HARD_BOUNCE",
            }
        )

        self.assertEqual(outbox["bounce_state"], "HARD_BOUNCE")
        self.assertEqual(outbox["failure_state"]["state"], "FAILED")
        self.assertEqual(outbox["failure_state"]["failure_class"], "BOUNCE")
        self.assertFalse(outbox["failure_state"]["retryable"])
        self.assertEqual(outbox["retry_state"]["state"], "SCHEDULED")
        self.assertTrue(outbox["retry_state"]["sandbox_retry_plan_only"])
        self.assertFalse(outbox["retry_state"]["sandbox_retry_execution_enabled"])
        self.assertFalse(outbox["retry_state"]["real_retry_execution_enabled"])
        self.assertEqual(outbox["stop_state"]["state"], "STOPPED")
        self.assertEqual(outbox["stop_state"]["stop_reason_optional"], feedback["stop_reason_optional"])
        self.assertFalse(outbox["stop_state"]["live_send_readiness_enabled"])
        self.assertEqual(outbox["sandbox_execution_state"], "STOPPED")
        self.assertIn("bounce_state:HARD_BOUNCE", outbox["blocked_reasons"])
        self.assertIn("failure_taxonomy:BOUNCE", outbox["blocked_reasons"])

    def test_stage8_provider_reliability_blocks_sandbox_execution_readiness(self) -> None:
        scenarios = [
            (
                "unhealthy",
                {"KAKA_SALES_OUTREACH_PROVIDER_HEALTH": "unhealthy"},
                "provider_health_unhealthy_fail_closed",
            ),
            (
                "rate_limited",
                {"KAKA_SALES_OUTREACH_PROVIDER_RATE_LIMITED": "true"},
                "provider_rate_limited_fail_closed",
            ),
            (
                "timeout",
                {"KAKA_SALES_OUTREACH_PROVIDER_TIMEOUT": "true"},
                "provider_timeout_fail_closed",
            ),
            (
                "circuit_open",
                {"KAKA_SALES_OUTREACH_PROVIDER_CIRCUIT_OPEN": "true"},
                "provider_circuit_open_fail_closed",
            ),
            (
                "suspended_failure",
                {"KAKA_SALES_OUTREACH_PROVIDER_FAILURE_CLASS": "SUSPENDED"},
                "provider_failure_taxonomy_fail_closed",
            ),
        ]

        for name, env, expected_reason in scenarios:
            with self.subTest(name=name):
                with patch.dict("os.environ", env, clear=False):
                    stage8, outbox = self._stage8_with_outbox()
                readiness = stage8.inputs["outbox_readiness_summary"]

                self.assertEqual(outbox["provider_adapter_readiness"]["readiness_state"], "SUSPENDED")
                self.assertTrue(outbox["provider_adapter_suspended"])
                self.assertEqual(outbox["sandbox_execution_state"], "SUSPENDED")
                self.assertEqual(readiness["sandbox_execution_readiness"], "SUSPENDED")
                self.assertFalse(readiness["dry_run_ready"])
                self.assertIn(expected_reason, outbox["blocked_reasons"])
                self.assertIn("provider_adapter_suspended_fail_closed", outbox["blocked_reasons"])
                self.assertFalse(outbox["live_execution_enabled"])
                self.assertFalse(outbox["real_send_attempted"])

    def test_stage8_live_send_request_still_only_records_sandbox_block(self) -> None:
        stage8, outbox = self._stage8_with_outbox(
            {
                "run_mode": "REAL_RUN",
                "approval_state": "PENDING",
                "live_execution_enabled": True,
                "vendor_connection_enabled": True,
            }
        )
        readiness = stage8.inputs["outbox_readiness_summary"]

        self.assertEqual(outbox["sandbox_execution_state"], "BLOCKED")
        self.assertIn("live_execution_requested_but_blocked", outbox["blocked_reasons"])
        self.assertIn("vendor_connection_enabled=false", outbox["blocked_reasons"])
        self.assertFalse(outbox["live_execution_enabled"])
        self.assertFalse(outbox["real_send_attempted"])
        self.assertFalse(outbox["external_delivery_enabled"])
        self.assertFalse(readiness["ready_for_real_send"])
        self.assertFalse(readiness["real_provider_call_enabled"])


if __name__ == "__main__":
    unittest.main()
