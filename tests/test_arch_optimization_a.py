from __future__ import annotations

import unittest

from helpers import load_fixture, load_repo_json, run_internal_chain_to_stage7
from shared.capability_runtime import CapabilityRuntime
from shared.context_packet import ContextPacket
from shared.pipeline import run_internal_chain
from shared.runtime_validator import RuntimeValidator


class TestArchOptimizationA(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = RuntimeValidator()
        self.schema_catalog = {
            entry["object"]: entry
            for entry in load_repo_json("contracts/schemas/schema_catalog.json")["schemas"]
        }

    def test_stage7_8_9_agent_loop_trace_exists(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))

        stage7_trace = result["stage7"].inputs.get("policy_trace", [])
        stage8_trace = result["stage8"].inputs.get("policy_trace", [])
        stage9_trace = result["stage9"].inputs.get("policy_trace", [])

        self.assertTrue(any(entry.get("event") == "resolve_capability_mode" for entry in stage7_trace))
        self.assertTrue(any(entry.get("policy_key") == "sku_recommendation" for entry in stage7_trace))
        self.assertTrue(any(entry.get("event") == "load_policy" for entry in stage8_trace))
        self.assertTrue(any(entry.get("event") == "emit_decision" for entry in stage9_trace))

    def test_full_chain_happy_path_reaches_stage9(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))

        contact_target = result["stage8"].record("contact_target")
        outreach_plan = result["stage8"].record("outreach_plan")
        payment_record = result["stage9"].record("payment_record")
        delivery_record = result["stage9"].record("delivery_record")
        outcome = result["stage9"].record("opportunity_outcome_event")

        self.assertEqual(contact_target.get("contact_target_status"), "ELIGIBLE")
        self.assertEqual(outreach_plan.get("cadence_profile_id"), "CADENCE-NORMAL")
        self.assertEqual(contact_target.get("saleability_status"), "QUALIFIED")
        self.assertEqual(outreach_plan.get("projection_mode"), "INTERNAL_GOVERNED_PREVIEW")
        self.assertEqual(result["stage8"].record("touch_record").get("feedback_reason"), "NO_RESPONSE")
        self.assertEqual(payment_record.get("payment_proof_state"), "NOT_PROVIDED")
        self.assertEqual(delivery_record.get("delivery_form"), "INTERNAL_REVIEW")
        self.assertIsInstance(outcome.get("writeback_targets"), list)
        self.assertTrue(outcome.get("writeback_targets"))

    def test_runtime_validator_rejects_shape_drift(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be bool"):
            self.validator.validate_payload(
                "contact_target",
                self.schema_catalog["contact_target"],
                {
                    "contact_target_id": "CT-1",
                    "opportunity_id": "OPP-1",
                    "project_id": "P-1",
                    "saleability_status": "QUALIFIED",
                    "org_name": "ORG",
                    "org_type": "ENTERPRISE",
                    "person_name_optional": "N/A",
                    "role_cluster": "PROCUREMENT_DECISION",
                    "public_contact_source": "PUBLIC_SITE",
                    "source_family": "PROCUREMENT_NOTICE",
                    "source_auditability_state": "AUDITABLE",
                    "source_vendor_id_optional": "SRC-1",
                    "source_vendor_type_optional": "SOURCE_VENDOR",
                    "source_vendor_role": "PUBLIC_OFFICIAL_SOURCE",
                    "contact_channel": "EMAIL",
                    "channel_family": "ORG_EMAIL",
                    "contact_target_status": "ELIGIBLE",
                    "contact_validity_status": "VALID",
                    "contact_legal_basis": "PUBLIC_ROLE_CONTACT",
                    "reasonable_expectation_status": "REASONABLE",
                    "channel_policy_status": "ALLOW",
                    "frequency_policy_state": "ALLOW",
                    "opt_out_state": "ACTIVE",
                    "quiet_hours_policy_state": "ALLOW",
                    "auto_contact_allowed": "true",
                    "source_audit_ref": "AUDIT-1",
                    "query_trace_id": "TRACE-1",
                    "vendor_response_ref_optional": "RESP-1",
                    "fallback_vendor_id_optional": "FB-1",
                    "requires_manual_review": False,
                    "primary_contact_flag": True,
                    "contact_priority_score": 80,
                    "contact_priority_reason_tags": ["ROLE_PROCUREMENT_DECISION_ACTOR"],
                    "contact_candidate_rank": 1,
                    "contact_selection_reason": "role=PROCUREMENT_DECISION_ACTOR;channel=ORG_EMAIL",
                    "contact_conflict_flag": False,
                    "contact_conflict_reason": "single candidate",
                    "blocking_reasons": [],
                    "last_evaluated_at": "2026-04-15T00:00:00Z",
                },
            )

        with self.assertRaisesRegex(ValueError, "must be list"):
            self.validator.validate_payload(
                "buyer_fit",
                self.schema_catalog["buyer_fit"],
                {
                    "buyer_fit_id": "BF-1",
                    "project_id": "P-1",
                    "buyer_type": "GOVERNMENT",
                    "fit_score": 80,
                    "attack_motivation_score": 80,
                    "purchase_intent_score": 70,
                    "payment_capacity_score": 60,
                    "window_urgency_score": 90,
                    "fit_reason_tags": "WINDOW_MATCH",
                },
            )

    def test_runtime_validator_schema_guard_for_stage1_5_critical_objects(self) -> None:
        with self.assertRaisesRegex(ValueError, "contains undeclared fields"):
            self.validator.validate_payload(
                "execution_context",
                load_repo_json("contracts/schemas/execution_context.schema.json"),
                {
                    "context_id": "CTX-1",
                    "task_id": "TASK-1",
                    "project_unification_strategy": "STRICT",
                    "review_lane": "STANDARD",
                    "window_priority": "NORMAL",
                    "region_scope": "NATIONAL",
                    "source_family": "PROCUREMENT_NOTICE",
                    "platform_level": "NATIONAL",
                    "coverage_tier": "T0_CORE",
                    "carrier_type": "HTML_PAGE",
                    "default_route": "LIST_TO_DETAIL",
                    "source_registry_id": "SRC-REG-PROC-NATIONAL-HTML",
                    "route_policy_id": "ROUTE-PROC-NOTICE-001",
                    "fallback_route": "DETAIL_DIRECT",
                    "requires_manual_review": False,
                    "created_at": "2026-04-15T00:00:00Z",
                    "unexpected_flag": True,
                },
            )

        with self.assertRaisesRegex(ValueError, "must be array"):
            self.validator.validate_payload(
                "public_chain",
                load_repo_json("contracts/schemas/public_chain.schema.json"),
                {
                    "public_chain_id": "PC-1",
                    "project_id": "P-1",
                    "announcement_url": "https://example.invalid/notice",
                    "source_family": "PROCUREMENT_NOTICE",
                    "platform_level": "NATIONAL",
                    "region_scope": "NATIONAL",
                    "coverage_tier": "T0_CORE",
                    "carrier_type": "HTML_PAGE",
                    "source_registry_id": "SRC-REG-PROC-NATIONAL-HTML",
                    "route_policy_id": "ROUTE-PROC-NOTICE-001",
                    "default_route": "LIST_TO_DETAIL",
                    "fallback_route": "DETAIL_DIRECT",
                    "route_decision_state": "ALLOW",
                    "route_review_reasons": [],
                    "route_downgrade_signals": [],
                    "route_block_signals": [],
                    "collection_state": "PARSED",
                    "requires_manual_review": False,
                    "timeline_nodes": "NOTICE_PUBLISHED",
                    "required_node_set": ["NOTICE_PUBLISHED"],
                    "node_presence_matrix": {"NOTICE_PUBLISHED": True},
                    "statutory_node_completeness": True,
                    "window_clock_state": "OPEN",
                    "clock_chain_id": "CLOCK-1",
                    "version_chain_id": "VERSION-1",
                    "first_seen_at": "2026-04-15T00:00:00Z",
                    "last_retrieved_at": "2026-04-15T00:00:00Z",
                    "origin_carrier_type": "HTML_PAGE",
                    "fixation_bundle_id": "FIX-1",
                },
            )

        with self.assertRaisesRegex(ValueError, "must be boolean"):
            self.validator.validate_payload(
                "evidence_gate_decision",
                load_repo_json("contracts/schemas/evidence_gate_decision.schema.json"),
                {
                    "gate_id": "EGATE-1",
                    "project_id": "P-1",
                    "gate_scope": "PROJECT",
                    "evidence_gate_status": "PASS",
                    "minimum_external_use_grade": "E2_REVIEW_READY",
                    "blocking_evidence_refs": [],
                    "manual_confirmation_required": "false",
                    "visibility_reason_summary": "ok",
                },
            )

    def test_runtime_validator_schema_guard_for_stage1_2_7_8_9(self) -> None:
        expected_objects = {
            "execution_context",
            "public_chain",
            "clock_chain_profile",
            "notice_version_chain",
            "project_fact",
            "legal_action_recommendation",
            "review_queue_profile",
            "report_record",
            "challenger_candidate_profile",
            "legal_action_actor_profile",
            "procurement_decision_actor_profile",
            "buyer_fit",
            "challenger_buyer_fit",
            "sales_lead",
            "offer_recommendation",
            "saleable_opportunity",
            "contact_target",
            "outreach_plan",
            "touch_record",
            "order_record",
            "payment_record",
            "delivery_record",
            "opportunity_outcome_event",
            "governance_feedback_event",
        }
        self.assertEqual(set(self.validator.STRICT_PROFILES.keys()), expected_objects)
        for object_name in expected_objects:
            required = set(self.schema_catalog[object_name]["required"])
            strict = set(self.validator.STRICT_PROFILES[object_name].keys())
            self.assertTrue(required.issubset(strict), object_name)

    def test_policy_executor_consumes_expected_catalogs(self) -> None:
        stage_bundle = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        stage7 = stage_bundle["stage7"]
        stage8_inputs = {
            **dict(stage7.inputs),
            "now": load_fixture("internal_chain_happy.json")["now"],
            "response_status": "NO_RESPONSE",
        }
        runtime = CapabilityRuntime()
        state = runtime.run(
            ContextPacket.from_records(
                capability_mode="stage8_outreach",
                stage=8,
                project_id=stage7.record("saleable_opportunity").get("project_id"),
                records={
                    "saleable_opportunity": stage7.record("saleable_opportunity"),
                    "legal_action_actor_profile": stage7.record("legal_action_actor_profile"),
                    "procurement_decision_actor_profile": stage7.record("procurement_decision_actor_profile"),
                },
                inputs=stage8_inputs,
            )
        )
        self.assertEqual(
            set(state.outputs.keys()),
            {
                "contact_source_policy",
                "contact_compliance",
                "contact_priority",
                "outreach_cadence",
                "retry_policy",
                "touch_stop",
            },
        )


if __name__ == "__main__":
    unittest.main()
