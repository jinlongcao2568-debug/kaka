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
from shared.pipeline import run_internal_chain, run_internal_chain_until_stage6
from shared.policy_executor import PolicyExecutor
from shared.state_packet import StatePacket
from stage5_rules_evidence.engine import RuleEvidenceEngine
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.fact_aggregator import ProjectFactAggregator
from stage6_fact_review.service import Stage6Service


class TestStage56Evaluators(unittest.TestCase):
    def _execute_window_value_policy(
        self,
        *,
        deadline: str | None = None,
        now: str = "2026-04-14T00:00:00Z",
        window_status: str | None = None,
        sale_gate_status: str = "OPEN",
        commercial_urgency_level: str | None = None,
    ) -> tuple[object, dict[str, object]]:
        inputs: dict[str, object] = {
            "now": now,
            "sale_gate_status": sale_gate_status,
        }
        if deadline is not None:
            inputs["current_action_deadline_at_optional"] = deadline
        if window_status is not None:
            inputs["window_status"] = window_status
        if commercial_urgency_level is not None:
            inputs["commercial_urgency_level"] = commercial_urgency_level

        context = ContextPacket.from_records(
            capability_mode="stage6_fact_review",
            stage=6,
            project_id="PRJ-WINDOW",
            records={
                "project_fact": {"sale_gate_status": sale_gate_status},
                "clock_chain_profile": {},
                "legal_action_recommendation": (
                    {"window_status": window_status} if window_status is not None else {}
                ),
            },
            inputs=inputs,
        )
        state = StatePacket(capability_mode="stage6_fact_review")
        decision = PolicyExecutor().execute("window_value", context, state)
        state.add_decision(decision)
        return decision, state.merged_outputs()

    def test_stage5_engine_matches_service_outputs(self) -> None:
        stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
        service_result = Stage5Service().run(stage4)
        engine_result = RuleEvidenceEngine(Stage5Service().store).execute(stage4)

        for field_name, value in engine_result.handoff.items():
            self.assertEqual(service_result.handoff.get(field_name), value, field_name)
        for field_name in ("lineage_status", "conflict_state"):
            self.assertIn(field_name, service_result.handoff)
            self.assertEqual(service_result.handoff.get(field_name), service_result.inputs.get(field_name))
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
        self.assertEqual(
            service_result.inputs.get("stage5_rule_codes"),
            ["PROC-001", "PROC-002", "DOC-001"],
        )
        self.assertEqual(
            service_result.inputs.get("stage5_rule_codes"),
            engine_result.inputs.get("stage5_rule_codes"),
        )
        selection_trace = service_result.inputs.get("stage5_rule_selection_trace", [])
        self.assertEqual(
            selection_trace,
            engine_result.inputs.get("stage5_rule_selection_trace"),
        )
        self.assertGreater(len(selection_trace), len(service_result.inputs.get("stage5_rule_codes", [])))
        self.assertEqual(
            {
                entry.get("rule_code")
                for entry in selection_trace
                if entry.get("selected")
            },
            {"PROC-001", "PROC-002", "DOC-001"},
        )
        self.assertTrue(
            all(
                entry.get("reason") == "selected_first_slice_priority"
                or entry.get("reason") == "selected_catalog_priority"
                for entry in selection_trace
                if entry.get("selected")
            )
        )
        self.assertEqual(
            next(
                entry
                for entry in selection_trace
                if entry.get("rule_code") == "WIN-001"
            ).get("reason"),
            "skipped_by_priority_limit",
        )
        self.assertEqual(
            next(
                entry
                for entry in selection_trace
                if entry.get("rule_code") == "PROC-003"
            ).get("reason"),
            "unsupported_upstream_objects",
        )
        execution_trace = service_result.inputs.get("stage5_rule_execution_trace", [])
        self.assertEqual(
            execution_trace,
            engine_result.inputs.get("stage5_rule_execution_trace"),
        )
        self.assertEqual(
            [entry.get("rule_code") for entry in execution_trace],
            ["PROC-001", "PROC-002", "DOC-001"],
        )
        for entry in execution_trace:
            self.assertIn("rule_name", entry)
            self.assertTrue(entry.get("upstream_objects"))
            self.assertIn("version", entry)
            self.assertTrue(entry.get("dependency_fields"))
            self.assertTrue(entry.get("dependency_evidence"))
            self.assertEqual(entry.get("evidence_refs"), [service_result.record("evidence").get("evidence_id")])
            self.assertGreaterEqual(entry.get("confidence"), 0.6)
            self.assertEqual(entry.get("rule_gate_status"), "PASS")
            self.assertEqual(entry.get("rule_hit_state"), "CONFIRMED")
            self.assertEqual(entry.get("blocking_reasons"), [])
            self.assertEqual(entry.get("selected_reason"), "selected_catalog_priority")
            self.assertIsNone(entry.get("review_request_target_object_type"))
            self.assertIsNone(entry.get("review_request_target_object_id"))
            self.assertFalse(entry.get("review_request_target_selected"))
        coverage = service_result.inputs.get("stage5_rule_coverage_summary", {})
        self.assertEqual(coverage.get("selected_count"), 3)
        self.assertEqual(coverage.get("pass_count"), 3)
        self.assertEqual(coverage.get("review_count"), 0)
        self.assertEqual(coverage.get("block_count"), 0)
        self.assertTrue(coverage.get("golden_case_refs"))
        self.assertGreaterEqual(len(service_result.inputs.get("stage5_rule_hits", [])), 2)
        self.assertEqual(
            service_result.record("rule_gate_decision").get("passed_rule_hits"),
            [
                rule_hit.get("rule_hit_id")
                for rule_hit in service_result.inputs.get("stage5_rule_hits", [])
            ],
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

    def test_stage6_stage16_report_profile_summarizes_mainline_risk_without_formal_review_request(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "task_id": "TASK-B6-REPORT-PROFILE-001",
                "project_id": "PROJ-B6-REPORT-PROFILE-001",
                "source_title": "公共资源交易中心工程建设招标公告",
                "source_text": (
                    "依法必须招标工程建设项目。评标办法采用综合评分法，"
                    "价格分30分，技术分40分，商务分30分。"
                    "投标人须提供制造商授权、ISO9001、CMA检验检测机构资质认定、"
                    "本地服务网点证明和现场踏勘回执。"
                    "投标文件须签字盖章，提交投标保证金，投标有效期90日。"
                ),
                "document_completeness_state": "COMPLETE_WITH_ATTACHMENTS",
                "project_manager_name": "张建明",
            }
        )

        result = run_internal_chain_until_stage6(payload)
        stage5 = result["stage5"]
        report_profile = result["stage6"].inputs["stage6_review_report_trace"][
            "stage16_file_analysis_trace"
        ]["stage16_file_analysis_report_profile"]

        self.assertNotIn("review_request", stage5.records)
        self.assertEqual(report_profile["rule_gate_status"], "PASS")
        self.assertEqual(report_profile["evidence_gate_status"], "PASS")
        self.assertEqual(report_profile["review_request_state"], "NOT_CREATED")
        self.assertEqual(report_profile["report_profile_state"], "INTERNAL_REVIEW_RECOMMENDED")
        self.assertEqual(report_profile["tailored_bid_risk_level"], "HIGH_CLUE_REVIEW")
        self.assertGreaterEqual(report_profile["qualification_clause_count"], 4)
        self.assertGreaterEqual(report_profile["fatal_rejection_count"], 3)
        self.assertIn("MAINLINE_RISK_REVIEW", report_profile["recommended_review_lanes"])
        self.assertFalse(report_profile["customer_visible"])
        self.assertTrue(report_profile["no_illegality_or_reserved_winner_conclusion"])

    def test_stage6_stage16_report_profile_links_stage5_review_request(self) -> None:
        result = run_internal_chain_until_stage6(load_fixture("internal_chain_block.json"))
        stage5 = result["stage5"]
        report_profile = result["stage6"].inputs["stage6_review_report_trace"][
            "stage16_file_analysis_trace"
        ]["stage16_file_analysis_report_profile"]

        self.assertIn("review_request", stage5.records)
        self.assertEqual(report_profile["report_profile_state"], "REVIEW_REQUIRED")
        self.assertEqual(report_profile["review_request_state"], "LINKED_REVIEW_REQUEST")
        self.assertEqual(
            report_profile["linked_review_request_id_optional"],
            stage5.record("review_request").get("review_request_id"),
        )
        self.assertEqual(
            report_profile["missing_condition_family_optional"],
            stage5.record("review_request").get("missing_condition_family"),
        )
        self.assertIn("DUAL_GATE_REVIEW", report_profile["recommended_review_lanes"])
        self.assertIn("linked_review_request_id_present", report_profile["review_reasons"])

    def test_stage6_stage16_report_profile_partials_when_mainline_profile_missing(self) -> None:
        stage5 = Stage5Service().run(run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"])
        inputs = dict(stage5.inputs)
        for field_name in (
            "mainline_risk_profile",
            "bid_selection_score",
            "bid_selection_state",
            "blind_bid_pipeline_stage",
            "evaluation_method_profile",
            "tailored_bid_risk_level",
            "qualification_clause_hits",
            "fatal_rejection_risk_hits",
            "self_score_forecast",
        ):
            inputs.pop(field_name, None)
        stage5_without_profile = StageBundle(
            stage=5,
            records=dict(stage5.records),
            handoff=dict(stage5.handoff),
            trace_rules=list(stage5.trace_rules),
            inputs=inputs,
        )

        stage6 = Stage6Service().run(stage5_without_profile)
        report_profile = stage6.inputs["stage6_review_report_trace"]["stage16_file_analysis_trace"][
            "stage16_file_analysis_report_profile"
        ]

        self.assertEqual(report_profile["rule_gate_status"], "PASS")
        self.assertEqual(report_profile["evidence_gate_status"], "PASS")
        self.assertEqual(report_profile["report_profile_state"], "PARTIAL_REVIEW_REQUIRED")
        self.assertEqual(report_profile["mainline_risk_state"], "MISSING")
        self.assertIn("mainline_risk_profile_missing", report_profile["review_reasons"])
        self.assertNotIn("review_request", stage5.records)

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

    def test_stage6_window_policy_scores_bucket_boundaries_from_catalog(self) -> None:
        cases = [
            (
                "critical_window",
                "2026-04-16T00:00:00Z",
                "CRITICAL",
                "ACTIONABLE",
                "CRITICAL",
                95,
                "FAST_WINDOW",
                97,
                "CRITICAL_WINDOW",
                "ALLOW",
            ),
            (
                "high_window",
                "2026-04-19T00:00:00Z",
                "HIGH",
                "ACTIONABLE",
                "HIGH",
                80,
                "HIGH_PRIORITY",
                73,
                "HIGH",
                "ALLOW",
            ),
            (
                "normal_window",
                "2026-04-24T00:00:00Z",
                "NORMAL",
                "ACTIONABLE",
                "MEDIUM",
                60,
                "STANDARD",
                46,
                "NORMAL",
                "ALLOW",
            ),
            (
                "low_window",
                "2026-05-05T00:00:00Z",
                "LOW",
                "ACTIONABLE",
                "LOW",
                40,
                "STANDARD",
                24,
                "LOW",
                "ALLOW",
            ),
            (
                "missed_window",
                "2026-04-13T00:00:00Z",
                "HIGH",
                "MISSED",
                "CRITICAL",
                0,
                "FAST_WINDOW",
                100,
                "CRITICAL_WINDOW",
                "BLOCK",
            ),
        ]

        for (
            case_name,
            deadline,
            commercial_urgency,
            expected_window_status,
            expected_risk_level,
            expected_urgency_score,
            expected_lane,
            expected_priority,
            expected_bucket,
            expected_decision_state,
        ) in cases:
            with self.subTest(case_name=case_name):
                decision, outputs = self._execute_window_value_policy(
                    deadline=deadline,
                    commercial_urgency_level=commercial_urgency,
                )

                self.assertEqual(outputs.get("window_status"), expected_window_status)
                self.assertEqual(outputs.get("window_risk_level"), expected_risk_level)
                self.assertEqual(outputs.get("window_urgency_score"), expected_urgency_score)
                self.assertEqual(outputs.get("review_lane"), expected_lane)
                self.assertEqual(outputs.get("review_priority_score"), expected_priority)
                self.assertEqual(outputs.get("review_queue_bucket"), expected_bucket)
                self.assertEqual(outputs.get("commercial_urgency_level"), commercial_urgency)
                self.assertEqual(decision.decision_state, expected_decision_state)

    def test_stage6_review_required_queue_floors_and_default_urgency(self) -> None:
        decision, outputs = self._execute_window_value_policy(window_status="REVIEW_REQUIRED")

        self.assertEqual(decision.decision_state, "REVIEW")
        self.assertTrue(decision.fallback_used)
        self.assertEqual(outputs.get("window_status"), "REVIEW_REQUIRED")
        self.assertEqual(outputs.get("commercial_urgency_level"), "NORMAL")
        self.assertEqual(outputs.get("review_priority_score"), 40)
        self.assertEqual(outputs.get("review_queue_bucket"), "NORMAL")

        high_decision, high_outputs = self._execute_window_value_policy(
            window_status="REVIEW_REQUIRED",
            commercial_urgency_level="HIGH",
        )

        self.assertEqual(high_decision.decision_state, "REVIEW")
        self.assertTrue(high_decision.fallback_used)
        self.assertEqual(high_outputs.get("commercial_urgency_level"), "HIGH")
        self.assertEqual(high_outputs.get("review_priority_score"), 65)
        self.assertEqual(high_outputs.get("review_queue_bucket"), "HIGH")

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

    def test_stage6_legal_action_outputs_are_resolved_from_policy_contract(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage5 = Stage5Service().run(result["stage4"])
        aggregated = ProjectFactAggregator(Stage6Service().store).aggregate(
            stage5,
            now=stage5.inputs.get("now", "2026-04-14T00:00:00Z"),
        )

        resolution_trace = aggregated.inputs.get("stage6_legal_action_resolution_trace", [])
        decision = next(
            (
                entry
                for entry in resolution_trace
                if isinstance(entry, dict)
                and entry.get("policy_key") == "stage6_legal_action"
            ),
            None,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(
            aggregated.record("legal_action_recommendation").get("action_family"),
            "OBJECTION_PREP",
        )
        self.assertEqual(
            aggregated.record("legal_action_recommendation").get("recommended_next_step"),
            "prepare_stage7_commercial_objects",
        )

    def test_stage6_semantic_review_preserves_action_chain_next_step_via_policy_override(self) -> None:
        context = ContextPacket.from_records(
            capability_mode="stage6_fact_review",
            stage=6,
            project_id="PRJ-SEMANTIC",
            records={
                "project_fact": {
                    "sale_gate_status": "OPEN",
                    "rule_gate_status": "PASS",
                    "evidence_gate_status": "PASS",
                },
                "report_record": {
                    "report_status": "ISSUED",
                },
                "legal_action_recommendation": {
                    "window_status": "ACTIONABLE",
                },
            },
            inputs={
                "sale_gate_status": "OPEN",
                "report_status": "ISSUED",
                "rule_gate_status": "PASS",
                "evidence_gate_status": "PASS",
                "window_status": "ACTIONABLE",
                "semantic_decision_state_optional": "BLOCK",
            },
        )
        state = StatePacket(capability_mode="stage6_fact_review")
        decision = PolicyExecutor().execute("stage6_legal_action", context, state)
        state.add_decision(decision)

        self.assertEqual(state.resolve("action_family"), "REVIEW_ONLY")
        self.assertEqual(
            state.resolve("recommended_next_step"),
            "prepare_stage7_commercial_objects",
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

    def test_stage6_requires_h05_handoff_authority_not_scattered_inputs(self) -> None:
        stage5 = Stage5Service().run(run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"])
        broken_handoff = dict(stage5.handoff)
        broken_handoff.pop("lineage_status")
        broken_stage5 = StageBundle(
            stage=5,
            records=dict(stage5.records),
            handoff=broken_handoff,
            trace_rules=list(stage5.trace_rules),
            inputs={**stage5.inputs, "lineage_status": "NORMALIZED"},
        )

        with self.assertRaisesRegex(ValueError, "missing_h05_handoff_field:lineage_status"):
            Stage6Service().run(broken_stage5)

    def test_stage6_blocks_conflicting_gate_inputs_against_h05_authority(self) -> None:
        stage5 = Stage5Service().run(run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"])
        conflicted_stage5 = StageBundle(
            stage=5,
            records=dict(stage5.records),
            handoff=dict(stage5.handoff),
            trace_rules=list(stage5.trace_rules),
            inputs={
                **stage5.inputs,
                "rule_gate_status": "BLOCK",
                "evidence_gate_status": "BLOCK",
                "review_request_id": "RR-RAW-INPUT",
                "missing_condition_family": "MISSING_CLOCK",
                "review_lane": "FAST_WINDOW",
            },
        )

        with self.assertRaisesRegex(ValueError, "must-not-recompute conflicts"):
            Stage6Service().run(conflicted_stage5)

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
        supplement = stage6.inputs.get("governed_supplement_record_optional")
        supplement_summary = stage6.inputs.get("governed_supplement_carrier_summary")
        supplement_trace = stage6.inputs.get("stage6_review_report_trace", {}).get("supplement_trace", {})

        self.assertIsNotNone(supplement)
        self.assertIsNotNone(supplement_summary)
        self.assertEqual(
            supplement.get("linked_review_request_id"),
            result["stage5"].record("review_request").get("review_request_id"),
        )
        self.assertEqual(supplement.get("release_state"), "REVIEW_ELIGIBLE")
        self.assertEqual(supplement.get("usable_scope"), "REVIEW_ONLY")
        self.assertEqual(supplement.get("written_back_policy"), "GOVERNANCE_SINK_ONLY")
        self.assertEqual(supplement_summary.get("supplement_id"), supplement.get("supplement_id"))
        self.assertEqual(supplement_summary.get("project_id"), supplement.get("project_id"))
        self.assertEqual(
            supplement_summary.get("linked_review_request_id"),
            supplement.get("linked_review_request_id"),
        )
        self.assertEqual(supplement_summary.get("release_state"), "REVIEW_ELIGIBLE")
        self.assertEqual(supplement_summary.get("usable_scope"), "REVIEW_ONLY")
        self.assertEqual(supplement_summary.get("written_back_policy"), "GOVERNANCE_SINK_ONLY")
        self.assertEqual(supplement_summary.get("supplement_loop_state"), "REQUESTED")
        self.assertEqual(supplement_summary.get("impact_readiness_state"), "REVIEW_ELIGIBLE")
        self.assertEqual(
            supplement_summary.get("impact_decision_trace", {}).get("stage6_internal_runtime_allowed"),
            True,
        )
        self.assertEqual(
            supplement_summary.get("impact_decision_trace", {}).get("stage7_formal_surface_allowed"),
            False,
        )
        self.assertEqual(
            supplement_trace.get("governed_supplement_carrier_summary"),
            supplement_summary,
        )
        self.assertNotIn("governed_supplement_record", stage6.records)
        self.assertEqual(
            stage6.handoff.get("governed_supplement_record_id_optional"),
            supplement.get("supplement_id"),
        )
        self.assertEqual(
            stage6.handoff.get("governed_supplement_carrier_summary"),
            supplement_summary,
        )
        self.assertNotIn("governed_supplement_record_id_optional", result["stage7"].handoff)

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
                "public_attack_surface_id": "RAW-PAS-OVERRIDE",
                "verification_profile_id": "RAW-VFP-OVERRIDE",
                "evidence_grade_profile_id": "RAW-EGP-OVERRIDE",
                "verification_state": "BLOCK",
                "cross_check_state": "BLOCK",
                "fixation_status": "NOT_FIXED",
                "provenance_chain_status": "BROKEN",
                "retrieval_readiness_status": "BLOCKED",
                "lineage_status": "UNVERIFIED",
                "conflict_state": "UNRESOLVED",
                "winning_version_resolution_rule_id": "VERSION-RAW-OVERRIDE",
                "version_conflict_state": "CONFLICTING",
                "clock_resolution_rule_id": "CLOCK-RAW-OVERRIDE",
                "clock_precedence_rule_id": "CLOCK-PREC-RAW-OVERRIDE",
                "clock_conflict_state": "CONFLICTING",
                "collection_state": "BLOCKED",
                "fallback_route": "SEMI_MANUAL",
                "route_decision_state": "BLOCK",
                "route_review_reasons": ["raw_override"],
                "lineage": {
                    "lineage_status": "UNVERIFIED",
                    "conflict_state": "UNRESOLVED",
                },
            },
        )

        stage5 = Stage5Service().run(conflicted_stage4)

        self.assertEqual(stage4.record("focus_bidder_verification_profile").get("verification_state"), "PASS")
        self.assertEqual(stage4.record("evidence_grade_profile").get("cross_check_state"), "PASS")
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "PASS")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "PASS")
        self.assertNotIn("review_request", stage5.records)
        self.assertEqual(
            stage5.inputs.get("verification_profile_id"),
            stage4.handoff.get("verification_profile_id"),
        )
        self.assertEqual(stage5.inputs.get("verification_state"), "PASS")
        self.assertEqual(stage5.inputs.get("cross_check_state"), "PASS")
        self.assertEqual(stage5.inputs.get("lineage_status"), "NORMALIZED")
        self.assertEqual(stage5.inputs.get("conflict_state"), "CONSISTENT")
        for field_name in (
            "winning_version_resolution_rule_id",
            "version_conflict_state",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
            "clock_conflict_state",
            "collection_state",
            "fallback_route",
            "route_decision_state",
            "route_review_reasons",
        ):
            self.assertEqual(stage5.inputs.get(field_name), stage4.handoff.get(field_name), field_name)
        self.assertEqual(stage5.handoff.get("lineage_status"), "NORMALIZED")
        self.assertEqual(stage5.handoff.get("conflict_state"), "CONSISTENT")

    def test_stage5_blocks_when_required_h04_handoff_fields_are_missing(self) -> None:
        stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]

        for missing_field in (
            "verification_profile_id",
            "evidence_grade_profile_id",
            "clock_precedence_rule_id",
        ):
            with self.subTest(missing_field=missing_field):
                broken_stage4 = StageBundle(
                    stage=4,
                    records=dict(stage4.records),
                    handoff={
                        key: value
                        for key, value in stage4.handoff.items()
                        if key != missing_field
                    },
                    trace_rules=list(stage4.trace_rules),
                    inputs=dict(stage4.inputs),
                )

                with self.assertRaisesRegex(ValueError, f"missing_h04_handoff_field:{missing_field}"):
                    Stage5Service().run(broken_stage4)

                with self.assertRaisesRegex(ValueError, f"missing_h04_handoff_field:{missing_field}"):
                    RuleEvidenceEngine(Stage5Service().store).execute(broken_stage4)

        broken_clock_stage4 = StageBundle(
            stage=4,
            records=dict(stage4.records),
            handoff={
                **stage4.handoff,
                "clock_conflict_state": "CONFLICTING",
                "collection_state": "REVIEW_REQUIRED",
            },
            trace_rules=list(stage4.trace_rules),
            inputs=dict(stage4.inputs),
        )
        stage5 = Stage5Service().run(broken_clock_stage4)

        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertEqual(stage5.record("review_request").get("missing_condition_family"), "MISSING_CLOCK")
        self.assertEqual(stage5.record("review_request").get("target_object_type"), "rule_hit")
        self.assertEqual(stage5.record("rule_gate_decision").get("passed_rule_hits"), [])
        self.assertEqual(stage5.record("rule_gate_decision").get("blocked_rule_hits"), [])
        self.assertIn("review_request", stage5.records)
        self.assertIn("h04_clock_conflict_state_not_consistent", stage5.inputs.get("h04_authority_review_reasons"))
        self.assertGreaterEqual(len(stage5.inputs.get("stage5_rule_hits", [])), 2)
        execution_trace = stage5.inputs.get("stage5_rule_execution_trace", [])
        self.assertEqual(len(execution_trace), 3)
        self.assertTrue(
            all(entry.get("rule_gate_status") == "REVIEW" for entry in execution_trace)
        )
        self.assertTrue(
            all(entry.get("review_request_target_object_type") == "rule_hit" for entry in execution_trace)
        )
        self.assertTrue(
            all(
                entry.get("review_request_target_object_id")
                == stage5.record("review_request").get("target_object_id")
                for entry in execution_trace
            )
        )
        self.assertEqual(
            [
                entry.get("rule_hit_id")
                for entry in execution_trace
                if entry.get("review_request_target_selected")
            ],
            [stage5.record("rule_hit").get("rule_hit_id")],
        )
        self.assertTrue(
            any(
                rule_hit.get("rule_hit_state") == "REVIEW_REQUIRED"
                for rule_hit in stage5.inputs.get("stage5_rule_hits", [])
            )
        )

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
        self.assertEqual(stage5.handoff.get("lineage_status"), stage5.inputs.get("lineage_status"))
        self.assertEqual(stage5.handoff.get("conflict_state"), stage5.inputs.get("conflict_state"))
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
