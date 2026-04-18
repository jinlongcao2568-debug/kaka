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

from helpers import load_fixture, load_repo_json
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


class TestStage8ResolutionClosure(unittest.TestCase):
    @staticmethod
    def _policy_decisions(stage8_bundle) -> dict[str, dict]:
        return {
            entry["policy_key"]: entry
            for entry in stage8_bundle.inputs.get("policy_trace", [])
            if isinstance(entry, dict) and entry.get("catalog_id")
        }

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
        self.assertEqual(outreach_plan.get("execution_vendor_id_optional"), "EXEC-EMAIL-SERVICE")
        self.assertEqual(trace["source_vendor_resolution"]["resolved_from"], "POLICY_DEFAULT")
        self.assertEqual(trace["execution_vendor_resolution"]["resolved_from"], "POLICY_DEFAULT")

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


if __name__ == "__main__":
    unittest.main()
