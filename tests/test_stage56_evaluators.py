from __future__ import annotations

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
from shared.context_packet import ContextPacket
from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from shared.policy_executor import PolicyExecutor
from shared.state_packet import StatePacket
from stage5_rules_evidence.engine import RuleEvidenceEngine
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.fact_aggregator import ProjectFactAggregator
from stage6_fact_review.service import Stage6Service


class TestStage56Evaluators(unittest.TestCase):
    def test_stage5_engine_matches_service_outputs(self) -> None:
        stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
        service_result = Stage5Service().run(stage4)
        engine_result = RuleEvidenceEngine(Stage5Service().store).execute(stage4)

        self.assertEqual(service_result.handoff, engine_result.handoff)
        self.assertEqual(service_result.trace_rules, engine_result.trace_rules)
        self.assertEqual(set(service_result.records.keys()), set(engine_result.records.keys()))
        self.assertEqual(
            service_result.record("evidence_gate_decision").get("evidence_gate_status"),
            engine_result.record("evidence_gate_decision").get("evidence_gate_status"),
        )
        self.assertEqual(
            service_result.record("rule_gate_decision").get("rule_gate_status"),
            engine_result.record("rule_gate_decision").get("rule_gate_status"),
        )

    def test_stage6_aggregator_matches_service_outputs(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage5 = Stage5Service().run(result["stage4"])
        service_result = Stage6Service().run(stage5)
        aggregated = ProjectFactAggregator(Stage6Service().store).aggregate(
            stage5,
            now=stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
        )

        self.assertEqual(service_result.handoff, aggregated.handoff)
        self.assertEqual(set(service_result.records.keys()), set(aggregated.records.keys()))
        self.assertEqual(
            service_result.record("report_record").get("report_status"),
            aggregated.record("report_record").get("report_status"),
        )
        self.assertEqual(
            service_result.record("challenger_candidate_profile").get("challenge_actionability_score"),
            aggregated.record("challenger_candidate_profile").get("challenge_actionability_score"),
        )
        self.assertEqual(
            service_result.record("review_queue_profile").get("review_priority_score"),
            aggregated.record("review_queue_profile").get("review_priority_score"),
        )
        self.assertEqual(
            service_result.record("review_queue_profile").get("review_queue_bucket"),
            aggregated.record("review_queue_profile").get("review_queue_bucket"),
        )
        self.assertEqual(
            service_result.record("review_queue_profile").get("review_lane"),
            aggregated.record("review_queue_profile").get("review_lane"),
        )

    def test_stage6_aggregator_preserves_superseded_report_path(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload["flags"]["report_superseded"] = True
        result = run_internal_chain(payload)
        stage5 = Stage5Service().run(result["stage4"])

        aggregated = ProjectFactAggregator(Stage6Service().store).aggregate(
            stage5,
            now=stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
        )

        self.assertEqual(aggregated.record("report_record").get("report_status"), "REVOKED")
        self.assertEqual(aggregated.record("report_record").get("review_task_status"), "SUPERSEDED")

    def test_stage6_review_queue_defaults_follow_formal_policy(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage5 = Stage5Service().run(result["stage4"])
        aggregated = ProjectFactAggregator(Stage6Service().store).aggregate(
            stage5,
            now=stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
        )

        queue_profile = aggregated.record("review_queue_profile")
        self.assertEqual(queue_profile.get("commercial_urgency_level"), "NORMAL")
        self.assertEqual(queue_profile.get("review_lane"), "STANDARD")
        self.assertEqual(queue_profile.get("review_priority_score"), 46)
        self.assertEqual(queue_profile.get("review_queue_bucket"), "NORMAL")
        self.assertEqual(aggregated.record("legal_action_recommendation").get("window_status"), "ACTIONABLE")

    def test_stage6_competitor_grade_uses_formal_policy_not_heuristic_mapping(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage5 = Stage5Service().run(result["stage4"])
        aggregated = ProjectFactAggregator(Stage6Service().store).aggregate(
            stage5,
            now=stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
        )

        challenger_profile = aggregated.record("challenger_candidate_profile")
        context = ContextPacket.from_records(
            capability_mode="stage6_fact_review",
            stage=6,
            project_id=aggregated.record("project_fact").get("project_id"),
            records={"challenger_candidate_profile": challenger_profile},
            inputs={
                **stage5.inputs,
                "confidence_band": stage5.inputs.get("confidence_band", "MEDIUM"),
                "external_use_grade": stage5.inputs.get("external_use_grade"),
                "evidence_ref_count_optional": 2,
                "now": stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
            },
        )
        state = StatePacket(capability_mode="stage6_fact_review")
        decision = PolicyExecutor().execute("competitor_confidence", context, state)
        state.add_decision(decision)

        old_heuristic = {
            ("OPEN", "HIGH"): "A",
            ("OPEN", "MEDIUM"): "B",
            ("OPEN", "LOW"): "C",
            ("HOLD", "HIGH"): "B",
            ("HOLD", "MEDIUM"): "C",
            ("HOLD", "LOW"): "D",
            ("REVIEW", "HIGH"): "B",
            ("REVIEW", "MEDIUM"): "C",
            ("REVIEW", "LOW"): "D",
        }.get(
            (
                aggregated.record("project_fact").get("sale_gate_status"),
                stage5.inputs.get("confidence_band", "MEDIUM"),
            ),
            "D",
        )

        self.assertEqual(
            aggregated.record("project_fact").get("competitor_quality_grade"),
            state.resolve("competitor_quality_grade"),
        )
        self.assertNotEqual(
            aggregated.record("project_fact").get("competitor_quality_grade"),
            old_heuristic,
        )
        self.assertEqual(
            aggregated.handoff.get("confidence_score_optional"),
            state.resolve("competitor_confidence_score"),
        )

    def test_stage6_project_fact_summaries_do_not_emit_placeholder_defaults(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage5 = Stage5Service().run(result["stage4"])
        aggregated = ProjectFactAggregator(Stage6Service().store).aggregate(
            stage5,
            now=stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
        )

        project_fact = aggregated.record("project_fact")
        self.assertEqual(project_fact.get("clue_summary"), [])
        self.assertEqual(project_fact.get("risk_summary"), [])
        self.assertNotIn("DEFAULT_CLUE", project_fact.get("clue_summary"))
        self.assertNotIn("DEFAULT_RISK", project_fact.get("risk_summary"))

    def test_stage6_missing_authoritative_action_inputs_fall_back_to_review_path(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload["flags"] = {}
        result = run_internal_chain(payload)
        stage6 = result["stage6"]

        self.assertEqual(stage6.record("project_fact").get("sale_gate_status"), "HOLD")
        self.assertEqual(stage6.record("report_record").get("report_status"), "READY")
        self.assertEqual(stage6.record("legal_action_recommendation").get("action_family"), "REVIEW_ONLY")
        self.assertEqual(
            stage6.record("legal_action_recommendation").get("recommended_next_step"),
            "hold_until_report_issued",
        )
        self.assertIn(
            "report_status=READY",
            stage6.record("legal_action_recommendation").get("blocking_reasons"),
        )

    def test_stage6_prefers_h05_authoritative_review_fields(self) -> None:
        payload = load_fixture("internal_chain_block.json")
        result = run_internal_chain(payload)
        stage5 = Stage5Service().run(result["stage4"])
        conflicted_stage5 = StageBundle(
            stage=5,
            records=dict(stage5.records),
            handoff=dict(stage5.handoff),
            trace_rules=list(stage5.trace_rules),
            inputs={
                **stage5.inputs,
                "review_lane": "HIGH_PRIORITY",
                "missing_condition_family": "MISSING_CLOCK",
            },
        )

        aggregated = Stage6Service().run(conflicted_stage5)

        self.assertEqual(
            aggregated.record("review_queue_profile").get("review_lane"),
            stage5.handoff.get("review_lane"),
        )
        self.assertEqual(
            aggregated.inputs.get("linked_review_request_id_optional"),
            stage5.handoff.get("review_request_id"),
        )
        self.assertEqual(
            aggregated.inputs.get("missing_condition_family_optional"),
            stage5.handoff.get("missing_condition_family"),
        )

    def test_stage6_supplement_trace_is_machine_readable_and_isolated(self) -> None:
        payload = load_fixture("internal_chain_block.json")
        payload.update(
            {
                "supplement_material_family": "MISSING_ATTACHMENT_BACKFILL",
                "supplement_source_owner": "MANUAL_REVIEW",
                "supplement_lawful_basis": "REVIEW_CHAIN_AUTHORIZED",
                "supplement_visible_roles": "review_user,governance_owner",
                "supplement_written_back_policy": "GOVERNANCE_SINK_ONLY",
            }
        )

        result = run_internal_chain(payload)
        stage6 = result["stage6"]
        supplement = stage6.inputs.get("private_supplement_record_optional")

        self.assertIsNotNone(supplement)
        self.assertEqual(
            supplement.get("linked_review_request_id"),
            result["stage5"].record("review_request").get("review_request_id"),
        )
        self.assertEqual(supplement.get("release_state"), "REVIEW_ELIGIBLE")
        self.assertEqual(supplement.get("usable_scope"), "REVIEW_ONLY")
        self.assertEqual(supplement.get("written_back_policy"), "GOVERNANCE_SINK_ONLY")
        self.assertNotIn("private_supplement_record", stage6.records)
        self.assertEqual(
            stage6.handoff.get("private_supplement_record_id_optional"),
            supplement.get("supplement_id"),
        )
        self.assertNotIn("private_supplement_record_id_optional", result["stage7"].handoff)

    def test_stage5_prefers_stage4_formal_outputs_over_conflicting_inputs(self) -> None:
        stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
        conflicted_stage4 = StageBundle(
            stage=4,
            records=dict(stage4.records),
            handoff=dict(stage4.handoff),
            trace_rules=list(stage4.trace_rules),
            inputs={
                **stage4.inputs,
                "flags": {
                    "evidence_blocked": True,
                    "verification_blocked": True,
                },
                "lineage_status": "UNVERIFIED",
                "conflict_state": "UNRESOLVED",
            },
        )

        stage5 = Stage5Service().run(conflicted_stage4)

        self.assertEqual(stage4.record("focus_bidder_verification_profile").get("verification_state"), "PASS")
        self.assertEqual(stage4.record("evidence_grade_profile").get("cross_check_state"), "PASS")
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "PASS")
        self.assertNotIn("review_request", stage5.records)

    def test_stage5_handoff_exports_authoritative_gate_fields(self) -> None:
        stage4 = run_internal_chain(load_fixture("internal_chain_block.json"))["stage4"]
        stage5 = Stage5Service().run(stage4)

        self.assertEqual(
            stage5.handoff.get("rule_gate_decision_id"),
            stage5.record("rule_gate_decision").get("gate_id"),
        )
        self.assertEqual(
            stage5.handoff.get("evidence_gate_decision_id"),
            stage5.record("evidence_gate_decision").get("gate_id"),
        )
        self.assertEqual(stage5.handoff.get("rule_hit_id"), stage5.record("rule_hit").get("rule_hit_id"))
        self.assertEqual(stage5.handoff.get("evidence_id"), stage5.record("evidence").get("evidence_id"))
        self.assertEqual(
            stage5.handoff.get("review_request_id"),
            stage5.record("review_request").get("review_request_id"),
        )
        self.assertEqual(
            stage5.handoff.get("missing_condition_family"),
            stage5.record("review_request").get("missing_condition_family"),
        )


if __name__ == "__main__":
    unittest.main()
