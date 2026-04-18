from __future__ import annotations

import copy
import unittest
from pathlib import Path

from helpers import load_fixture, load_repo_json
from shared.pipeline import run_internal_chain


def _stage8_policy(relative_path: str) -> dict:
    return load_repo_json(relative_path)["policies"][0]


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


def _select_channel_override(policy: dict, channel_family: str) -> dict:
    return next(
        (item for item in policy["channel_overrides"] if item["channel_family"] == channel_family),
        {},
    )


def _select_channel_ladder(policy: dict, channel_family: str) -> dict:
    return next(
        (item for item in policy["channel_ladders"] if item["entry_channel_family"] == channel_family),
        {
            "ladder_id": f"LADDER-{channel_family}",
            "step_sequence": [channel_family],
            "fallback_sequence": [],
            "fallback_trigger_response_statuses": [],
            "sequence_mode": "GOVERNED_PREVIEW_ONLY",
            "live_execution_enabled": False,
            "advance_requires_manual_review": False,
        },
    )


def _retry_rule(policy: dict, response_status: str) -> dict:
    return next(item for item in policy["retry_rules"] if item["response_status"] == response_status)


def _feedback_mapping(response_status: str) -> dict:
    entry = load_repo_json("contracts/sales/feedback_reason_catalog.json")["entries"][0]
    return next(item for item in entry["mappings"] if item["response_status"] == response_status)


def _policy_actions(actions: list[str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for action in actions:
        field_name, raw_value = action.split("=", 1)
        if raw_value == "true":
            parsed[field_name] = True
        elif raw_value == "false":
            parsed[field_name] = False
        else:
            parsed[field_name] = raw_value
    return parsed


def _stop_rule(policy: dict, *, section: str, reason: str) -> dict:
    if section == "stop_after_retry":
        rule = dict(policy["stop_after_retry"])
        rule["actions_map"] = _policy_actions(rule["actions"])
        return rule
    rule = next(item for item in policy[section] if item["reason"] == reason)
    enriched = dict(rule)
    enriched["actions_map"] = _policy_actions(rule["actions"])
    return enriched


class TestPreRouteBehavior(unittest.TestCase):
    @staticmethod
    def _policy_decisions(trace: list[dict]) -> dict[str, dict]:
        return {
            entry["policy_key"]: entry
            for entry in trace
            if isinstance(entry, dict) and entry.get("policy_key") and entry.get("catalog_id")
        }

    def test_stage7_window_value_trace_exposes_formal_queue_outputs(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "commercial_urgency_level": "HIGH",
                "current_action_deadline_at_optional": "2026-04-20T00:00:00Z",
            }
        )

        result = run_internal_chain(payload)
        stage7 = result["stage7"]
        trace = self._policy_decisions(stage7.handoff.get("policy_trace", []))

        window_value = trace["window_value"]
        self.assertEqual(window_value["outputs"]["window_status"], "ACTIONABLE")
        self.assertEqual(window_value["outputs"]["review_lane"], "HIGH_PRIORITY")
        self.assertEqual(window_value["outputs"]["review_priority_score"], 73)
        self.assertEqual(window_value["outputs"]["review_queue_bucket"], "HIGH")
        self.assertEqual(window_value["outputs"]["commercial_urgency_level"], "HIGH")

    def test_stage8_conflict_cadence_retry_behavior(self) -> None:
        cadence_policy = _stage8_policy("contracts/sales/outreach_cadence_catalog.json")
        retry_policy = _stage8_policy("contracts/sales/retry_policy_catalog.json")
        feedback_mapping = _feedback_mapping("NO_RESPONSE")
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "channel_family": "PERSONAL_PHONE",
                "contact_channel": "PHONE",
                "response_status": "NO_RESPONSE",
            }
        )

        result = run_internal_chain(payload)
        stage8 = result["stage8"]
        trace = self._policy_decisions(stage8.handoff.get("policy_trace", []))

        self.assertEqual(
            set(trace.keys()),
            {
                "contact_source_policy",
                "contact_compliance",
                "contact_priority",
                "outreach_cadence",
                "retry_policy",
                "touch_stop",
            },
        )
        for key, entry in trace.items():
            self.assertIn("catalog_id", entry, key)
            self.assertIn("decision_state", entry, key)
            self.assertIn("outputs", entry, key)
            self.assertIn("reasons", entry, key)

        contact_target = stage8.record("contact_target")
        outreach_plan = stage8.record("outreach_plan")
        touch_record = stage8.record("touch_record")
        cadence_outputs = trace["outreach_cadence"]["outputs"]
        retry_outputs = trace["retry_policy"]["outputs"]
        expected_profile = _select_cadence_profile(cadence_policy, urgency="NORMAL", window_urgency=50)
        expected_channel_override = _select_channel_override(cadence_policy, "PERSONAL_PHONE")
        expected_ladder = _select_channel_ladder(cadence_policy, "PERSONAL_PHONE")
        expected_retry_rule = _retry_rule(retry_policy, "NO_RESPONSE")

        self.assertTrue(contact_target.get("contact_conflict_flag"))
        self.assertFalse(contact_target.get("primary_contact_flag"))
        self.assertEqual(contact_target.get("contact_target_status"), "REVIEW_REQUIRED")
        self.assertGreaterEqual(contact_target.get("contact_priority_score"), 0)
        self.assertEqual(outreach_plan.get("cadence_profile_id"), expected_profile["profile_id"])
        self.assertEqual(outreach_plan.get("retry_policy_id"), cadence_policy["retry_policy_id"])
        self.assertEqual(outreach_plan.get("stop_policy_id"), cadence_policy["stop_policy_id"])
        self.assertEqual(
            outreach_plan.get("max_retry_count"),
            expected_channel_override.get("max_attempts_7d", expected_profile["max_attempts_7d"]),
        )
        self.assertEqual(outreach_plan.get("retry_count"), 1 if expected_retry_rule["next_action"] == "RETRY" else 0)
        self.assertEqual(touch_record.get("attempt_index"), 2 if expected_retry_rule["next_action"] == "RETRY" else 1)
        self.assertEqual(cadence_outputs.get("channel_ladder_id"), expected_ladder["ladder_id"])
        self.assertEqual(cadence_outputs.get("ladder_sequence"), expected_ladder["step_sequence"])
        self.assertEqual(cadence_outputs.get("channel_fallback_sequence"), expected_ladder["fallback_sequence"])
        self.assertEqual(
            cadence_outputs.get("fallback_channel_family_optional"),
            next(iter(expected_ladder["fallback_sequence"]), None),
        )
        self.assertEqual(cadence_outputs.get("ladder_sequence_mode"), expected_ladder["sequence_mode"])
        self.assertFalse(cadence_outputs.get("live_execution_enabled"))
        self.assertEqual(retry_outputs.get("next_action"), expected_retry_rule["next_action"])
        self.assertEqual(retry_outputs.get("backoff_hours_optional"), expected_retry_rule["backoff_hours"][0])
        self.assertEqual(retry_outputs.get("feedback_reason"), feedback_mapping["feedback_reason"])
        self.assertEqual(retry_outputs.get("next_step_optional"), feedback_mapping["next_step_optional"])
        self.assertEqual(retry_outputs.get("writeback_targets"), feedback_mapping["writeback_targets"])
        self.assertEqual(touch_record.get("feedback_reason"), feedback_mapping["feedback_reason"])
        self.assertEqual(touch_record.get("next_step_optional"), feedback_mapping["next_step_optional"])
        self.assertEqual(touch_record.get("writeback_targets"), feedback_mapping["writeback_targets"])
        self.assertEqual(touch_record.get("writeback_target_optional"), feedback_mapping["writeback_targets"][0])
        self.assertEqual(stage8.inputs.get("feedback_reason"), touch_record.get("feedback_reason"))
        self.assertEqual(stage8.inputs.get("next_step_optional"), touch_record.get("next_step_optional"))
        self.assertEqual(stage8.inputs.get("writeback_targets"), touch_record.get("writeback_targets"))
        self.assertEqual(
            stage8.inputs.get("writeback_target_optional"),
            touch_record.get("writeback_target_optional"),
        )
        self.assertEqual(
            stage8.inputs.get("failure_reason_tag_optional"),
            touch_record.get("failure_reason_tag_optional"),
        )
        self.assertEqual(stage8.inputs.get("retry_count"), outreach_plan.get("retry_count"))
        self.assertEqual(stage8.inputs.get("max_retry_count"), outreach_plan.get("max_retry_count"))
        self.assertEqual(stage8.inputs.get("attempt_index"), touch_record.get("attempt_index"))
        self.assertEqual(stage8.inputs.get("cadence_profile_id"), outreach_plan.get("cadence_profile_id"))
        self.assertEqual(stage8.inputs.get("retry_policy_id"), outreach_plan.get("retry_policy_id"))
        self.assertEqual(stage8.inputs.get("stop_policy_id"), outreach_plan.get("stop_policy_id"))
        self.assertEqual(stage8.handoff.get("plan_status"), "REVIEW_REQUIRED")
        self.assertEqual(
            outreach_plan.get("next_touch_due_at_optional"),
            "2026-04-16T00:00:00+00:00",
        )
        self.assertEqual(
            stage8.inputs.get("next_touch_due_at_optional"),
            "2026-04-16T00:00:00+00:00",
        )

    def test_stage8_opt_out_stop_behavior(self) -> None:
        stop_policy = _stage8_policy("contracts/sales/touch_stop_condition_catalog.json")
        opt_out_stop = _stop_rule(
            stop_policy,
            section="permanent_block_conditions",
            reason="opt_out_blocked",
        )
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "opt_out_state": "OPTED_OUT",
                "response_status": "OPTED_OUT",
            }
        )

        result = run_internal_chain(payload)
        stage8 = result["stage8"]

        self.assertEqual(
            stage8.record("contact_target").get("contact_target_status"),
            opt_out_stop["actions_map"]["contact_target_status"],
        )
        self.assertEqual(
            stage8.record("outreach_plan").get("plan_status"),
            opt_out_stop["actions_map"]["plan_status"],
        )
        self.assertEqual(stage8.record("touch_record").get("touch_record_state"), "CANCELLED")
        self.assertEqual(stage8.record("touch_record").get("feedback_reason"), "OPTED_OUT")
        self.assertEqual(stage8.handoff.get("policy_decision_state"), "BLOCK")

    def test_stage8_quiet_hours_only_schedules_execution(self) -> None:
        stop_policy = _stage8_policy("contracts/sales/touch_stop_condition_catalog.json")
        quiet_hours_stop = _stop_rule(
            stop_policy,
            section="review_conditions",
            reason="quiet_hours_block",
        )
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"quiet_hours_policy_state": "BLOCK"})

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8.handoff.get("policy_trace", []))

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "ELIGIBLE")
        self.assertFalse(stage8.record("contact_target").get("requires_manual_review"))
        self.assertEqual(
            stage8.record("outreach_plan").get("plan_status"),
            quiet_hours_stop["actions_map"]["plan_status"],
        )
        self.assertFalse(stage8.record("outreach_plan").get("requires_manual_review"))
        self.assertEqual(stage8.record("touch_record").get("touch_record_state"), "CREATED")
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["candidate_compliance_decision"],
            "ALLOW_PREVIEW",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["execution_compliance_decision"],
            "SCHEDULED",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["stop_semantics"],
            "QUIET_HOURS_SCHEDULE",
        )
        self.assertEqual(
            trace["touch_stop"]["outputs"]["plan_status"],
            quiet_hours_stop["actions_map"]["plan_status"],
        )
        self.assertFalse(trace["touch_stop"]["outputs"]["requires_manual_review"])

    def test_stage8_frequency_block_reviews_execution_without_blocking_candidate(self) -> None:
        stop_policy = _stage8_policy("contracts/sales/touch_stop_condition_catalog.json")
        frequency_review = _stop_rule(
            stop_policy,
            section="review_conditions",
            reason="frequency_review_required",
        )
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"frequency_policy_state": "BLOCK"})

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8.handoff.get("policy_trace", []))

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "ELIGIBLE")
        self.assertFalse(stage8.record("contact_target").get("requires_manual_review"))
        self.assertEqual(
            stage8.record("outreach_plan").get("plan_status"),
            frequency_review["actions_map"]["plan_status"],
        )
        self.assertTrue(stage8.record("outreach_plan").get("requires_manual_review"))
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["candidate_compliance_decision"],
            "ALLOW_PREVIEW",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["execution_compliance_decision"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(trace["touch_stop"]["outputs"]["contact_target_status"], "ELIGIBLE")
        self.assertEqual(
            trace["touch_stop"]["outputs"]["plan_status"],
            frequency_review["actions_map"]["plan_status"],
        )

    def test_stage8_retry_exhaustion_stop_behavior_is_single_sourced(self) -> None:
        cadence_policy = _stage8_policy("contracts/sales/outreach_cadence_catalog.json")
        stop_policy = _stage8_policy("contracts/sales/touch_stop_condition_catalog.json")
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "channel_family": "ORG_EMAIL",
                "contact_channel": "EMAIL",
                "response_status": "NO_RESPONSE",
                "retry_count": 2,
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        stop_after_retry = _stop_rule(
            stop_policy,
            section="stop_after_retry",
            reason="retry_exhausted",
        )
        expected_ladder = _select_channel_ladder(cadence_policy, "ORG_EMAIL")
        trace = self._policy_decisions(stage8.handoff.get("policy_trace", []))

        self.assertEqual(
            stage8.record("contact_target").get("contact_target_status"),
            stop_after_retry["actions_map"]["contact_target_status"],
        )
        self.assertEqual(
            stage8.record("outreach_plan").get("plan_status"),
            stop_after_retry["actions_map"]["plan_status"],
        )
        self.assertEqual(stage8.record("touch_record").get("touch_record_state"), "CANCELLED")
        self.assertEqual(stage8.record("outreach_plan").get("stop_reason_optional"), stop_after_retry["reason"])
        self.assertEqual(trace["outreach_cadence"]["outputs"]["channel_ladder_id"], expected_ladder["ladder_id"])
        self.assertEqual(trace["touch_stop"]["outputs"]["stop_reason_optional"], stop_after_retry["reason"])

    def test_stage8_approval_gap_reviews_execution_without_downgrading_candidate(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update({"run_mode": "APPROVAL_RUN", "approval_state": "PENDING"})

        stage8 = run_internal_chain(payload)["stage8"]
        trace = self._policy_decisions(stage8.handoff.get("policy_trace", []))

        self.assertEqual(stage8.record("contact_target").get("contact_target_status"), "ELIGIBLE")
        self.assertFalse(stage8.record("contact_target").get("requires_manual_review"))
        self.assertEqual(stage8.record("outreach_plan").get("plan_status"), "REVIEW_REQUIRED")
        self.assertTrue(stage8.record("outreach_plan").get("requires_manual_review"))
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["candidate_compliance_decision"],
            "ALLOW_PREVIEW",
        )
        self.assertEqual(
            trace["contact_compliance"]["outputs"]["execution_compliance_decision"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(
            trace["contact_compliance"]["reasons"][0],
            "approval_missing_for_execution_vendor",
        )
        self.assertEqual(
            stage8.record("outreach_plan").get("governed_metadata", {}).get("execution_compliance_decision"),
            "REVIEW_REQUIRED",
        )

    def test_stage8_connected_human_handoff_owner_and_sla(self) -> None:
        feedback_mapping = _feedback_mapping("CONNECTED")
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "run_mode": "APPROVAL_RUN",
                "approval_state": "APPROVED",
                "response_status": "CONNECTED",
                "commercial_urgency_level": "HIGH",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        human_handoff = stage8.record("touch_record").get("governed_metadata", {}).get("human_handoff", {})

        self.assertEqual(stage8.handoff.get("human_handoff_next_owner_role_optional"), "sales_user")
        self.assertEqual(stage8.handoff.get("human_handoff_sla_hours_optional"), 8)
        self.assertEqual(stage8.handoff.get("human_handoff_sla_due_at_optional"), "2026-04-14T08:00:00Z")
        self.assertEqual(stage8.inputs.get("human_handoff_policy_id_optional"), "stage8_human_handoff_v1")
        self.assertEqual(stage8.inputs.get("human_handoff_next_owner_role_optional"), "sales_user")
        self.assertEqual(stage8.inputs.get("human_handoff_sla_hours_optional"), 8)
        self.assertEqual(stage8.inputs.get("human_handoff_reason_optional"), "human_followup_required_after_connected")
        self.assertEqual(stage8.record("touch_record").get("next_step_optional"), feedback_mapping["next_step_optional"])
        self.assertEqual(stage8.record("touch_record").get("writeback_targets"), feedback_mapping["writeback_targets"])
        self.assertEqual(human_handoff.get("next_step_optional"), "HANDOFF_TO_SALES")
        self.assertEqual(human_handoff.get("reason_optional"), "human_followup_required_after_connected")

    def test_stage8_org_routed_human_handoff_owner_and_sla(self) -> None:
        feedback_mapping = _feedback_mapping("ORG_ROUTED")
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "run_mode": "APPROVAL_RUN",
                "approval_state": "APPROVED",
                "response_status": "ORG_ROUTED",
                "commercial_urgency_level": "HIGH",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        human_handoff = stage8.inputs.get("stage8_resolution_trace", {}).get("human_handoff", {})

        self.assertEqual(stage8.handoff.get("human_handoff_next_owner_role_optional"), "sales_user")
        self.assertEqual(stage8.handoff.get("human_handoff_sla_hours_optional"), 24)
        self.assertEqual(stage8.handoff.get("human_handoff_sla_due_at_optional"), "2026-04-15T00:00:00Z")
        self.assertEqual(stage8.inputs.get("human_handoff_next_owner_role_optional"), "sales_user")
        self.assertEqual(stage8.inputs.get("human_handoff_sla_hours_optional"), 24)
        self.assertEqual(stage8.inputs.get("human_handoff_reason_optional"), "organization_route_followup_required")
        self.assertEqual(stage8.record("touch_record").get("next_step_optional"), feedback_mapping["next_step_optional"])
        self.assertEqual(stage8.record("touch_record").get("writeback_targets"), feedback_mapping["writeback_targets"])
        self.assertEqual(human_handoff.get("next_step_optional"), "WAIT_ORG_RESPONSE")
        self.assertEqual(human_handoff.get("reason_optional"), "organization_route_followup_required")

    def test_stage8_h08_payload_and_writeback_projection_stay_authoritative_on_connected_handoff(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "run_mode": "APPROVAL_RUN",
                "approval_state": "APPROVED",
                "response_status": "CONNECTED",
                "commercial_urgency_level": "HIGH",
            }
        )

        stage8 = run_internal_chain(payload)["stage8"]
        touch_record = stage8.record("touch_record")
        human_handoff = touch_record.get("governed_metadata", {}).get("human_handoff", {})
        expected_h08_projection = {
            "opportunity_id": stage8.record("saleable_opportunity").get("opportunity_id"),
            "touch_record_id": touch_record.get("touch_record_id"),
            "response_status": touch_record.get("response_status"),
            "saleability_status": stage8.record("saleable_opportunity").get("saleability_status"),
            "crm_owner_state": stage8.record("saleable_opportunity").get("crm_owner_state"),
        }

        for field_name, expected_value in expected_h08_projection.items():
            self.assertEqual(stage8.handoff.get(field_name), expected_value)
            self.assertEqual(stage8.inputs.get(field_name), expected_value)

        self.assertEqual(stage8.handoff.get("feedback_reason"), touch_record.get("feedback_reason"))
        self.assertEqual(
            stage8.handoff.get("written_back_at_optional"),
            touch_record.get("written_back_at_optional"),
        )
        self.assertEqual(stage8.inputs.get("writeback_targets"), touch_record.get("writeback_targets"))
        self.assertEqual(
            stage8.inputs.get("writeback_target_optional"),
            touch_record.get("writeback_target_optional"),
        )
        self.assertEqual(stage8.inputs.get("next_step_optional"), touch_record.get("next_step_optional"))
        self.assertEqual(
            stage8.inputs.get("written_back_at_optional"),
            touch_record.get("written_back_at_optional"),
        )
        self.assertEqual(stage8.handoff.get("human_handoff_next_owner_role_optional"), "sales_user")
        self.assertEqual(stage8.handoff.get("human_handoff_sla_hours_optional"), 8)
        self.assertEqual(
            stage8.handoff.get("human_handoff_reason_optional"),
            "human_followup_required_after_connected",
        )
        self.assertEqual(
            stage8.inputs.get("human_handoff_next_owner_role_optional"),
            stage8.handoff.get("human_handoff_next_owner_role_optional"),
        )
        self.assertEqual(
            stage8.inputs.get("human_handoff_sla_hours_optional"),
            stage8.handoff.get("human_handoff_sla_hours_optional"),
        )
        self.assertEqual(
            stage8.inputs.get("human_handoff_reason_optional"),
            stage8.handoff.get("human_handoff_reason_optional"),
        )
        self.assertEqual(human_handoff.get("next_owner_role_optional"), "sales_user")
        self.assertEqual(human_handoff.get("sla_hours_optional"), 8)
        self.assertEqual(
            human_handoff.get("reason_optional"),
            "human_followup_required_after_connected",
        )

    def test_stage9_outcome_governance_taxonomy_trace_behavior(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "refund_state": "COMPLETED",
                "outcome_family": "DELIVERY_ABANDONED",
                "outcome_reason_tags": ["REFUND_COMPLETED"],
                "trigger_type": "EXCEPTION_TRIGGERED",
            }
        )

        result = run_internal_chain(payload)
        stage9 = result["stage9"]
        trace = self._policy_decisions(stage9.inputs.get("policy_trace", []))

        self.assertEqual(
            set(trace.keys()),
            {
                "payment_exception",
                "delivery_exception",
                "outcome_taxonomy",
                "governance_taxonomy",
            },
        )
        for key, entry in trace.items():
            self.assertIn("catalog_id", entry, key)
            self.assertIn("decision_state", entry, key)
            self.assertIn("outputs", entry, key)
            self.assertIn("reasons", entry, key)

        outcome = stage9.record("opportunity_outcome_event")
        governance = stage9.record("governance_feedback_event")

        self.assertEqual(outcome.get("outcome_family"), "DELIVERY_ABANDONED")
        self.assertEqual(outcome.get("outcome_reason_tags"), ["REFUND_COMPLETED"])
        self.assertEqual(
            outcome.get("writeback_targets"),
            ["delivery_record", "project_fact", "governance_feedback_event"],
        )
        self.assertEqual(governance.get("trigger_type"), "EXCEPTION_TRIGGERED")
        self.assertIn("register controlled_exception_record", governance.get("action_taken"))
        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "REFUND_COMPLETED",
        )
        self.assertEqual(
            stage9.record("delivery_record").get("archival_status"),
            "ARCHIVE_EXCEPTION",
        )
        self.assertEqual(
            stage9.inputs.get("outcome_writeback_targets"),
            ["delivery_record", "project_fact", "governance_feedback_event"],
        )
        self.assertEqual(
            stage9.inputs.get("upstream_feedback_projected_targets"),
            ["sales_lead", "report_record"],
        )
        self.assertEqual(
            stage9.inputs.get("upstream_feedback_advisory_targets"),
            [],
        )
        self.assertEqual(
            stage9.inputs.get("governance_writeback_targets_optional"),
            ["controlled_exception_record", "release_gates"],
        )
        self.assertEqual(
            stage9.inputs.get("payment_exception_writeback_targets_optional"),
            ["saleable_opportunity", "project_fact"],
        )
        self.assertEqual(
            stage9.inputs.get("delivery_exception_writeback_targets_optional"),
            ["delivery_record"],
        )
        self.assertEqual(
            stage9.inputs.get("effective_writeback_targets"),
            [
                "delivery_record",
                "project_fact",
                "governance_feedback_event",
                "controlled_exception_record",
                "release_gates",
                "saleable_opportunity",
            ],
        )
        self.assertEqual(
            stage9.inputs.get("resolved_effective_writeback_targets"),
            [
                "delivery_record",
                "project_fact",
                "governance_feedback_event",
                "sales_lead",
                "report_record",
                "controlled_exception_record",
                "release_gates",
                "saleable_opportunity",
            ],
        )
        self.assertEqual(
            stage9.inputs.get("writeback_advisory_targets"),
            [],
        )
        self.assertEqual(
            set(stage9.inputs.get("impact_targets_projected_contract_only", [])),
            {"sales_lead", "report_record"},
        )
        self.assertEqual(
            stage9.inputs.get("writeback_source_contracts", {})
            .get("outcome_taxonomy", {})
            .get("merge_semantics"),
            "AUTHORITATIVE_BASE",
        )
        self.assertEqual(
            stage9.inputs.get("writeback_source_contracts", {})
            .get("payment_exception", {})
            .get("merge_semantics"),
            "ADDITIVE_ONLY",
        )
        self.assertEqual(
            stage9.inputs.get("writeback_target_sources", {}).get("project_fact"),
            ["outcome_taxonomy", "payment_exception"],
        )
        self.assertEqual(
            stage9.inputs.get("writeback_target_contracts", {})
            .get("delivery_record", {})
            .get("resolved_from_sources"),
            ["outcome_taxonomy", "delivery_exception"],
        )

    def test_stage9_governance_targets_are_additive_not_override(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "response_status": "NO_RESPONSE",
                "crm_owner_state": "UNASSIGNED",
            }
        )

        result = run_internal_chain(payload)
        stage9 = result["stage9"]
        outcome = stage9.record("opportunity_outcome_event")

        self.assertEqual(
            stage9.inputs.get("outcome_writeback_targets"),
            ["contact_target", "saleable_opportunity"],
        )
        self.assertEqual(
            stage9.inputs.get("upstream_feedback_projected_targets"),
            ["sales_lead", "report_record"],
        )
        self.assertEqual(
            stage9.inputs.get("governance_writeback_targets_optional"),
            ["order_record", "payment_record"],
        )
        self.assertEqual(
            stage9.inputs.get("effective_writeback_targets"),
            ["contact_target", "saleable_opportunity", "order_record", "payment_record"],
        )
        self.assertEqual(
            stage9.inputs.get("resolved_effective_writeback_targets"),
            ["contact_target", "saleable_opportunity", "sales_lead", "report_record", "order_record", "payment_record"],
        )
        self.assertEqual(
            outcome.get("writeback_targets"),
            ["contact_target", "saleable_opportunity"],
        )
        self.assertEqual(
            set(stage9.inputs.get("impact_targets_projected_contract_only", [])),
            {"sales_lead", "report_record"},
        )

    def test_stage9_payment_and_delivery_exception_enter_executor_chain(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
                "payment_status": "PARTIALLY_PAID",
                "delivery_status": "REDELIVERY_REQUIRED",
            }
        )

        result = run_internal_chain(payload)
        stage9 = result["stage9"]
        trace = self._policy_decisions(stage9.inputs.get("policy_trace", []))

        self.assertIn("payment_exception", trace)
        self.assertIn("delivery_exception", trace)
        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "PARTIAL_PAYMENT",
        )
        self.assertEqual(
            stage9.record("delivery_record").get("delivery_exception_family_optional"),
            "REDELIVERY_REQUIRED",
        )
        self.assertTrue(stage9.record("delivery_record").get("redeliver_required_optional"))
        self.assertEqual(
            stage9.record("opportunity_outcome_event").get("outcome_family"),
            "DELIVERY_ABANDONED",
        )
        self.assertEqual(
            stage9.record("governance_feedback_event").get("trigger_type"),
            "DELIVERY_BLOCK",
        )

    def test_stage9_chargeback_review_runtime_coverage(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
                "payment_status": "PAYMENT_EXCEPTION",
                "payment_exception_family_optional": "CHARGEBACK_REVIEW",
            }
        )

        stage9 = run_internal_chain(payload)["stage9"]
        trace = self._policy_decisions(stage9.inputs.get("policy_trace", []))
        contracts = stage9.inputs.get("writeback_target_contracts", {})

        self.assertEqual(
            trace["payment_exception"]["outputs"]["payment_exception_family_optional"],
            "CHARGEBACK_REVIEW",
        )
        self.assertEqual(
            stage9.record("payment_record").get("payment_exception_family_optional"),
            "CHARGEBACK_REVIEW",
        )
        self.assertEqual(
            stage9.record("governance_feedback_event").get("trigger_type"),
            "EXCEPTION_TRIGGERED",
        )
        self.assertEqual(
            stage9.inputs.get("payment_exception_writeback_targets_optional"),
            ["order_record", "project_fact"],
        )
        self.assertEqual(
            stage9.inputs.get("upstream_feedback_projected_targets"),
            [],
        )
        self.assertEqual(
            contracts["order_record"]["persistence_semantics"],
            "PERSISTED_IN_STAGE9_RUNTIME",
        )
        self.assertEqual(
            contracts["project_fact"]["mutation_semantics"],
            "PROJECTED_MUTATION_ONLY",
        )
        self.assertIn("order_record", stage9.inputs.get("effective_writeback_targets"))

    def test_stage9_delivery_exception_family_runtime_coverage(self) -> None:
        cases = [
            {
                "family": "DELIVERY_REJECTED",
                "expected_targets": ["saleable_opportunity", "project_fact"],
                "expected_ack": "REJECTED",
                "expected_partial": "NOT_PARTIAL",
                "expected_target": "saleable_opportunity",
                "expected_persistence": "NOT_PERSISTED_IN_STAGE9_RUNTIME",
            },
            {
                "family": "PARTIAL_DELIVERY",
                "expected_targets": ["saleable_opportunity"],
                "expected_ack": "PENDING",
                "expected_partial": "PARTIAL",
                "expected_target": "saleable_opportunity",
                "expected_persistence": "NOT_PERSISTED_IN_STAGE9_RUNTIME",
            },
            {
                "family": "ACK_TIMEOUT",
                "expected_targets": ["delivery_record"],
                "expected_ack": "TIMEOUT",
                "expected_partial": "NOT_PARTIAL",
                "expected_target": "delivery_record",
                "expected_persistence": "PERSISTED_IN_STAGE9_RUNTIME",
            },
        ]

        for case in cases:
            with self.subTest(exception_family=case["family"]):
                payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
                payload.update(
                    {
                        "crm_owner_state": "ASSIGNED",
                        "response_status": "CONNECTED",
                        "delivery_exception_family_optional": case["family"],
                    }
                )

                stage9 = run_internal_chain(payload)["stage9"]
                trace = self._policy_decisions(stage9.inputs.get("policy_trace", []))
                delivery_record = stage9.record("delivery_record")
                outcome = stage9.record("opportunity_outcome_event")
                governance = stage9.record("governance_feedback_event")
                contracts = stage9.inputs.get("writeback_target_contracts", {})

                self.assertEqual(
                    trace["delivery_exception"]["outputs"]["delivery_exception_family_optional"],
                    case["family"],
                )
                self.assertEqual(
                    delivery_record.get("delivery_exception_family_optional"),
                    case["family"],
                )
                self.assertEqual(
                    delivery_record.get("customer_ack_state_optional"),
                    case["expected_ack"],
                )
                self.assertEqual(
                    delivery_record.get("partial_delivery_state_optional"),
                    case["expected_partial"],
                )
                self.assertEqual(outcome.get("outcome_family"), "DELIVERY_ABANDONED")
                self.assertEqual(governance.get("trigger_type"), "DELIVERY_BLOCK")
                self.assertEqual(
                    stage9.inputs.get("delivery_exception_writeback_targets_optional"),
                    case["expected_targets"],
                )
                self.assertEqual(
                    stage9.inputs.get("upstream_feedback_projected_targets"),
                    ["sales_lead", "report_record"],
                )
                self.assertEqual(
                    contracts[case["expected_target"]]["persistence_semantics"],
                    case["expected_persistence"],
                )
                self.assertEqual(
                    set(stage9.inputs.get("impact_targets_projected_contract_only", [])),
                    {"sales_lead", "report_record"},
                )

    def test_stage9_payment_delivery_control_fields_present(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        payment_record = result["stage9"].record("payment_record")
        delivery_record = result["stage9"].record("delivery_record")
        outcome = result["stage9"].record("opportunity_outcome_event")
        governance = result["stage9"].record("governance_feedback_event")

        self.assertEqual(payment_record.get("payment_proof_state"), "NOT_PROVIDED")
        self.assertEqual(payment_record.get("refund_state"), "NOT_REQUESTED")
        self.assertEqual(payment_record.get("payer_match_state"), "MATCHED")
        self.assertEqual(payment_record.get("amount_match_state"), "MATCHED")
        self.assertEqual(delivery_record.get("delivery_form"), "INTERNAL_REVIEW")
        self.assertEqual(delivery_record.get("customer_ack_state_optional"), "NOT_REQUESTED")
        self.assertIsInstance(outcome.get("writeback_targets"), list)
        self.assertTrue(outcome.get("writeback_targets"))
        for record in (payment_record, delivery_record, outcome, governance):
            self.assertEqual(record.get("governed_execution_mode"), "INTERNAL_GOVERNED")
            self.assertFalse(record.get("governed_metadata").get("live_execution_enabled"))

    def test_stage9_amount_mismatch_blocks_delivery_and_consumes_writeback_timestamp(self) -> None:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "crm_owner_state": "ASSIGNED",
                "response_status": "CONNECTED",
                "payment_status": "PAID",
                "payment_proof_state": "UPLOADED",
                "amount_mismatch_state_optional": "CONFIRMED",
            }
        )

        result = run_internal_chain(payload)
        stage8 = result["stage8"]
        stage9 = result["stage9"]
        payment_record = stage9.record("payment_record")
        delivery_record = stage9.record("delivery_record")
        outcome = stage9.record("opportunity_outcome_event")
        governance = stage9.record("governance_feedback_event")

        self.assertEqual(payment_record.get("payment_exception_family_optional"), "AMOUNT_MISMATCH")
        self.assertEqual(payment_record.get("amount_match_state"), "MISMATCHED")
        self.assertEqual(delivery_record.get("delivery_status"), "RELEASE_BLOCKED")
        self.assertEqual(outcome.get("outcome_family"), "LOST")
        self.assertEqual(governance.get("trigger_type"), "APPROVAL_MISSING")
        self.assertEqual(
            payment_record.get("written_back_at_optional"),
            stage8.record("touch_record").get("written_back_at_optional"),
        )
        self.assertEqual(
            delivery_record.get("written_back_at_optional"),
            stage8.record("touch_record").get("written_back_at_optional"),
        )

    def test_writeback_impact_executor_is_formally_active_internal_v0(self) -> None:
        policy = load_repo_json("contracts/governance/writeback_impact_policy.json")
        self.assertEqual(policy["current_state"], "INTERNAL_V0_ACTIVE")
        self.assertTrue(policy["runtime_executor_enabled"])
        self.assertTrue(policy["typed_writeback_supported"])
        self.assertEqual(policy["mutation_mode"], "ADDITIVE_INTERNAL_ONLY")
        self.assertEqual(
            policy["formal_targets"],
            ["project_fact", "saleable_opportunity", "contact_target", "review_queue_profile"],
        )

        runtime_inventory = Path(__file__).resolve().parents[1] / "control" / "runtime_inventory.yaml"
        inventory_text = runtime_inventory.read_text(encoding="utf-8")
        self.assertIn("writeback_impact_executor:", inventory_text)
        self.assertIn('current_state: "INTERNAL_V0_ACTIVE"', inventory_text)

        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]
        self.assertEqual(
            set(stage9.records.keys()),
            {
                "order_record",
                "payment_record",
                "delivery_record",
                "governance_feedback_event",
                "opportunity_outcome_event",
            },
        )
        self.assertEqual(stage9.inputs.get("impact_executor_state"), "INTERNAL_V0_ACTIVE")
        self.assertEqual(stage9.inputs.get("impact_mutation_mode"), "ADDITIVE_INTERNAL_ONLY")
        self.assertIn("saleable_opportunity", stage9.inputs.get("impact_mutations"))


if __name__ == "__main__":
    unittest.main()
