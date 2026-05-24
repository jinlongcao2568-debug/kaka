from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage6_review_loop_runner import run_stage6_review_loop_runner  # noqa: E402
from storage.stage6_review_loop_operator_projection import load_stage6_review_loop_operator_projection  # noqa: E402


class Stage6ReviewLoopRunnerTests(unittest.TestCase):
    def test_dry_run_one_pass_keeps_waiting_tasks_without_external_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "DRY_RUN_ONE_PASS_NOT_EXECUTED")
            self.assertEqual(summary["dispatch_dry_run_ready_group_count"], 1)
            self.assertEqual(summary["readback_waiting_for_controlled_execution_count"], 1)
            self.assertEqual(summary["closeout_ready_to_feed_back_count"], 0)
            self.assertEqual(summary["result_runner_dry_run_ready_count"], 0)
            self.assertEqual(summary["next_cycle_skip_reason"], "batch_closeout_rebuild_output_missing_or_results_not_executed")
            self.assertEqual(summary["project_status_record_count"], 1)
            self.assertEqual(summary["loop_terminal_state_counts"], {"WAITING_FOR_DISPATCH_EXECUTION": 1})
            records = result["manifest"]["project_status_table"]["records"]
            self.assertEqual(records[0]["project_id"], "PROJ-D")
            self.assertEqual(records[0]["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")
            self.assertEqual(
                records[0]["next_recommended_action"],
                "run_controlled_dispatch_task_or_record_operator_skip",
            )
            self.assertTrue((root / "out" / "stage6-review-loop-runner-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-loop-project-status-table.json").exists())

    def test_execute_one_pass_rebuilds_batch_closeout_and_next_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                script = argv[argv.index("-File") + 1]
                output_root = Path(_arg(argv, "-OutputRoot"))
                if script == "scripts/run-evidence-orchestration-continuation-v1.ps1":
                    state_after_root = output_root / "after"
                    _write_evidence_state(state_after_root)
                    _write_json(
                        output_root / "evidence-orchestration-continuation-run-v1.json",
                        {
                            "safe_to_execute": True,
                            "blocking_reasons": [],
                            "manifest": {
                                "manifest_id": "CONTINUATION-RUN-1",
                                "state_after_root": str(state_after_root),
                            },
                            "summary": {},
                        },
                    )
                elif script == "scripts/build-evidence-batch-closeout-v1.ps1":
                    evidence_state_root = Path(_arg(argv, "-EvidenceStateRoot"))
                    _write_batch_closeout(
                        output_root,
                        evidence_state_json=evidence_state_root / "evidence-orchestration-state-v1.json",
                    )
                else:
                    raise AssertionError(f"unexpected script: {script}")
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
                execute_dispatch=True,
                execute_results=True,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 2)
            summary = result["summary"]
            self.assertEqual(summary["dispatch_executed_success_group_count"], 1)
            self.assertEqual(summary["readback_execution_output_ready_count"], 1)
            self.assertEqual(summary["closeout_ready_to_feed_back_count"], 1)
            self.assertEqual(summary["routing_batch_closeout_rebuild_ready_count"], 1)
            self.assertEqual(summary["result_runner_executed_success_count"], 1)
            self.assertEqual(summary["next_cycle_stage6_project_fact_count"], 1)
            self.assertEqual(summary["next_cycle_dispatch_task_count"], 1)
            self.assertEqual(summary["project_status_record_count"], 1)
            self.assertEqual(summary["loop_terminal_state_counts"], {"NEXT_CYCLE_DISPATCH_READY": 1})
            records = result["manifest"]["project_status_table"]["records"]
            self.assertEqual(records[0]["project_id"], "PROJ-D")
            self.assertEqual(records[0]["loop_terminal_state"], "NEXT_CYCLE_DISPATCH_READY")
            self.assertEqual(
                records[0]["next_recommended_action"],
                "run_next_cycle_dispatch_or_keep_internal_review_dry_run",
            )

    def test_terminal_next_cycle_manual_only_status_is_visible_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                script = argv[argv.index("-File") + 1]
                output_root = Path(_arg(argv, "-OutputRoot"))
                if script == "scripts/run-evidence-orchestration-continuation-v1.ps1":
                    state_after_root = output_root / "after"
                    _write_evidence_state(state_after_root)
                    _write_json(
                        output_root / "evidence-orchestration-continuation-run-v1.json",
                        {
                            "safe_to_execute": True,
                            "blocking_reasons": [],
                            "manifest": {
                                "manifest_id": "CONTINUATION-RUN-TERMINAL",
                                "state_after_root": str(state_after_root),
                            },
                            "summary": {},
                        },
                    )
                elif script == "scripts/build-evidence-batch-closeout-v1.ps1":
                    evidence_state_root = Path(_arg(argv, "-EvidenceStateRoot"))
                    _write_terminal_batch_closeout(
                        output_root,
                        evidence_state_json=evidence_state_root / "evidence-orchestration-state-v1.json",
                    )
                else:
                    raise AssertionError(f"unexpected script: {script}")
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
                execute_dispatch=True,
                execute_results=True,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["next_cycle_dispatch_task_count"], 0)
            self.assertEqual(summary["loop_terminal_state_counts"], {"MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH": 1})
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertEqual(record["next_cycle_dispatch_block_reason"], "terminal_source_gap_no_delta_manual_review_only")
            self.assertEqual(
                record["next_recommended_action"],
                "manual_review_or_new_source_override_required_before_retry",
            )

    def test_release_evidence_field_query_result_is_visible_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_release_dispatch(root / "dispatch", evidence_state_json=state_json)
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                script = argv[argv.index("-File") + 1]
                output_root = Path(_arg(argv, "-OutputRoot"))
                if script == "scripts/build-release-evidence-adapter-plan-v1.ps1":
                    _write_release_adapter_plan(output_root)
                elif script == "scripts/run-guangdong-local-field-query-probe-v1.ps1":
                    self.assertIn("-ReleaseEvidenceAdapterPlanJson", argv)
                    _write_release_field_query_result(output_root)
                else:
                    raise AssertionError(f"unexpected script: {script}")
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
                execute_dispatch=True,
                execute_results=True,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 2)
            summary = result["summary"]
            self.assertEqual(summary["dispatch_executed_success_group_count"], 1)
            self.assertEqual(summary["result_runner_executed_success_count"], 1)
            self.assertEqual(summary["release_field_query_project_count"], 1)
            self.assertEqual(summary["release_field_query_state_counts"], {"RELEASE_FIELD_QUERY_REVIEW_READY": 1})
            records = result["manifest"]["project_status_table"]["records"]
            self.assertEqual(records[0]["project_id"], "PROJ-REL")
            self.assertEqual(records[0]["loop_terminal_state"], "RELEASE_FIELD_QUERY_REVIEW_READY")
            self.assertEqual(records[0]["release_field_query_adapter_result_state_counts"], {"MATCHED": 1})
            self.assertEqual(
                records[0]["release_field_query_downstream_abcd_grade_counts"],
                {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(
                records[0]["release_field_query_authorization_state_counts"],
                {"FIELD_SURFACE_REACHED_REVIEW_REQUIRED": 1},
            )
            self.assertEqual(
                records[0]["release_field_query_authorized_session_input_state_counts"],
                {"INJECTED_BROWSER_RUNNER": 1},
            )
            self.assertEqual(
                records[0]["release_field_query_operator_next_actions"],
                ["review_gdcic_authorized_query_terms_or_capture_more_precise_field_page"],
            )
            self.assertEqual(
                records[0]["release_field_query_source_hit_summary_labels"],
                ["广东建设信息网三库一平台匿名公开源；样例人员：王先耀；证书：粤1332006200810171；施工许可：441900202206061001"],
            )
            self.assertEqual(
                records[0]["release_field_query_source_hit_summaries"][0]["pii_redaction_state"],
                "ID_CARD_HASH_OR_REDACTED_ONLY",
            )
            self.assertEqual(
                summary["release_field_query_authorization_state_counts"],
                {"FIELD_SURFACE_REACHED_REVIEW_REQUIRED": 1},
            )
            self.assertEqual(
                summary["release_field_query_authorized_session_input_state_counts"],
                {"INJECTED_BROWSER_RUNNER": 1},
            )
            self.assertEqual(
                records[0]["next_recommended_action"],
                "manual_review_release_evidence_b_or_c_readback_before_stage7_preview",
            )

    def test_standalone_release_field_query_result_can_be_imported_into_status_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            _write_release_field_query_result(root / "field-query")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "closeout",
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["manifest"]["standalone_release_field_query_imported_project_count"], 1)
            self.assertTrue(
                result["manifest"]["source_standalone_release_field_query_json"].endswith(
                    "guangdong-local-field-query-probe-v1.json"
                )
            )
            self.assertEqual(result["summary"]["release_field_query_project_count"], 1)
            records = {
                record["project_id"]: record
                for record in result["manifest"]["project_status_table"]["records"]
            }
            self.assertEqual(records["PROJ-REL"]["loop_terminal_state"], "RELEASE_FIELD_QUERY_REVIEW_READY")
            self.assertEqual(records["PROJ-REL"]["release_field_query_task_count"], 1)
            self.assertEqual(
                records["PROJ-REL"]["release_field_query_downstream_abcd_grade_counts"],
                {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(
                records["PROJ-REL"]["release_field_query_source_hit_summary_labels"],
                ["广东建设信息网三库一平台匿名公开源；样例人员：王先耀；证书：粤1332006200810171；施工许可：441900202206061001"],
            )
            self.assertEqual(
                records["PROJ-REL"]["next_recommended_action"],
                "manual_review_release_evidence_b_or_c_readback_before_stage7_preview",
            )

    def test_standalone_release_field_query_only_builds_status_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_release_field_query_result(root / "field-query")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["loop_input_state"], "STANDALONE_RELEASE_FIELD_QUERY_STATUS_ONLY")
            self.assertEqual(result["summary"]["next_cycle_skip_reason"], "standalone_release_field_query_status_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["summary"]["project_status_record_count"], 1)
            self.assertEqual(
                result["summary"]["owner_assignment_state_counts"],
                {"UNASSIGNED_OWNER_REVIEW_REQUIRED": 1},
            )
            self.assertEqual(result["summary"]["unassigned_owner_count"], 1)
            self.assertEqual(
                result["summary"]["owner_assignment_next_action_counts"],
                {"assign_project_owner_before_next_runtime_cycle": 1},
            )
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-REL")
            self.assertEqual(record["loop_terminal_state"], "RELEASE_FIELD_QUERY_REVIEW_READY")
            self.assertEqual(record["release_field_query_result_json"], str(root / "field-query" / "guangdong-local-field-query-probe-v1.json"))
            self.assertEqual(record["release_field_query_source_hit_summaries"][0]["source_label"], "广东建设信息网三库一平台匿名公开源")

    def test_standalone_stage5_calibration_samples_feed_status_and_owner_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_stage5_calibration_sample_table(root / "stage5")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                stage5_calibration_sample_root=root / "stage5",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["loop_input_state"], "STANDALONE_STAGE5_CALIBRATION_STATUS_ONLY")
            self.assertEqual(result["summary"]["next_cycle_skip_reason"], "standalone_stage5_calibration_status_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["standalone_stage5_calibration_imported_project_count"], 1)
            self.assertEqual(result["summary"]["stage5_calibration_sample_count"], 1)
            self.assertEqual(result["summary"]["stage5_calibration_truth_label_required_count"], 1)
            self.assertEqual(
                result["summary"]["stage5_calibration_review_bucket_counts"],
                {"POTENTIAL_FALSE_POSITIVE_REVIEW": 1},
            )
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-STAGE5-CAL")
            self.assertEqual(record["loop_terminal_state"], "STAGE5_CALIBRATION_REVIEW_READY")
            self.assertEqual(
                record["next_recommended_action"],
                "review_stage5_calibration_samples_before_rule_change",
            )

            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json",
                created_at="2026-05-19T00:00:00+08:00",
            )
            projected = projection["project_status_rows"][0]
            self.assertEqual(projected["current_stage"], "Stage5_RULE_GATE_CALIBRATION")
            self.assertIn("潜在误放", projected["stage5_calibration_review_bucket_label"])
            self.assertIn(
                "review_stage5_calibration_samples_before_rule_change",
                projection["operator_decision"]["next_actions"],
            )

    def test_standalone_release_evidence_plan_terminal_suppression_builds_status_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_terminal_suppressed_release_adapter_plan(root / "release-plan")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                release_evidence_adapter_plan_root=root / "release-plan",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["loop_input_state"], "STANDALONE_RELEASE_EVIDENCE_PLAN_STATUS_ONLY")
            self.assertEqual(result["summary"]["next_cycle_skip_reason"], "standalone_release_evidence_plan_status_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["standalone_release_evidence_adapter_plan_imported_project_count"], 1)
            self.assertTrue(
                result["manifest"]["source_standalone_release_evidence_adapter_plan_json"].endswith(
                    "release-evidence-adapter-plan-v1.json"
                )
            )
            self.assertEqual(result["summary"]["project_status_record_count"], 1)
            self.assertEqual(result["summary"]["runtime_blocker_ledger_count"], 0)
            self.assertEqual(result["summary"]["runtime_blocker_ledger_state_counts"], {})
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-REL-SUPPRESS")
            self.assertEqual(record["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertTrue(record["closeout_precedence_suppressed"])
            self.assertEqual(record["closeout_precedence_state"], "SUPPRESS_TERMINAL_CLOSEOUT")
            self.assertEqual(record["next_cycle_dispatch_block_reason"], "terminal_closeout_or_backfill_marker_present")
            self.assertEqual(
                record["next_recommended_action"],
                "project_to_review_ready_status_projection_without_duplicate_dispatch",
            )
            self.assertEqual(record["runtime_blocker_ledger_state_counts"], {})
            self.assertEqual(record["runtime_blocker_ledger_records"], [])
            self.assertEqual(record["runtime_blocker_subqueue_routes"], [])
            self.assertEqual(
                record["closeout_precedence_marker_source_refs"][0]["artifact_ref"],
                "tmp/field-query/guangdong-local-field-query-probe-v1.json",
            )

    def test_standalone_original_readback_continuation_builds_status_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_standalone_original_backtrace_continuation(root / "original-readback")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                original_backtrace_continuation_root=root / "original-readback",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["loop_input_state"], "STANDALONE_ORIGINAL_READBACK_STATUS_ONLY")
            self.assertEqual(result["summary"]["next_cycle_skip_reason"], "standalone_original_readback_status_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["standalone_original_backtrace_continuation_imported_project_count"], 2)
            self.assertTrue(
                result["manifest"]["source_standalone_original_backtrace_continuation_json"].endswith(
                    "p13b-original-backtrace-continuation-controller-v2.json"
                )
            )
            self.assertEqual(result["summary"]["project_status_record_count"], 2)
            self.assertEqual(
                result["summary"]["runtime_blocker_ledger_state_counts"],
                {"ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED": 1},
            )
            records = {
                record["project_id"]: record
                for record in result["manifest"]["project_status_table"]["records"]
            }
            ready = records["PROJ-ORIG-READY"]
            self.assertEqual(ready["loop_terminal_state"], "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK")
            self.assertTrue(ready["closeout_precedence_suppressed"])
            self.assertEqual(
                ready["next_recommended_action"],
                "build_release_evidence_regional_adapter_plan",
            )
            self.assertEqual(ready["runtime_blocker_ledger_state_counts"], {})
            self.assertEqual(ready["runtime_blocker_ledger_records"], [])
            retry = records["PROJ-ORIG-RETRY"]
            self.assertEqual(retry["loop_terminal_state"], "NEXT_ORIGINAL_READBACK_SUBQUEUE_READY")
            self.assertFalse(retry["closeout_precedence_suppressed"])
            self.assertEqual(
                retry["next_recommended_action"],
                "run_next_live_original_notice_backtrace_batch",
            )
            self.assertEqual(
                retry["runtime_blocker_ledger_state_counts"],
                {"ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED": 1},
            )
            self.assertEqual(
                retry["runtime_blocker_subqueue_routes"],
                ["retry", "suspend_dead_letter", "operator_action"],
            )

    def test_standalone_original_readback_park_state_is_projection_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(
                root / "original-readback" / "p13b-original-backtrace-continuation-controller-v2.json",
                {
                    "safe_to_execute": True,
                    "blocking_reasons": [],
                    "manifest": {
                        "manifest_id": "ORIG-PARK-STANDALONE-1",
                        "continuation_plan_records": [
                            {
                                "original_notice_task_id": "TASK-ORIG-PARK",
                                "project_id": "PROJ-ORIG-PARK",
                                "project_name": "Original park project",
                                "continuation_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                "recommended_next_action": "park_or_manual_review_without_release_probe",
                                "next_queue": "manual_hold",
                                "closeout_precedence": {
                                    "closeout_precedence_state": "SUPPRESS_DUPLICATE_WORKER_DISPATCH",
                                    "task_scope": "original_readback",
                                    "task_type": "p13b_original_notice_backtrace",
                                    "suppressed_dispatch": True,
                                    "should_suppress_dispatch": True,
                                    "suppression_reason": "terminal_closeout_or_backfill_marker_present",
                                    "runtime_layer": "controller decision:p13b_original_backtrace_continuation",
                                    "terminal_marker": {
                                        "task_family": "original_readback",
                                        "terminal_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                        "marker_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                    },
                                },
                                "closeout_precedence_state": "SUPPRESS_DUPLICATE_WORKER_DISPATCH",
                                "closeout_precedence_suppressed": True,
                                "runtime_blocker_ledger_record": {
                                    "blocker_ledger_id": "BLK-ORIG-PARK-STALE-1",
                                    "ledger_scope": "p13b_original_readback",
                                    "project_id": "PROJ-ORIG-PARK",
                                    "project_name": "Original park project",
                                    "task_id": "TASK-ORIG-PARK",
                                    "task_scope": "original_readback",
                                    "task_type": "p13b_original_notice_backtrace",
                                    "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                                    "blocker_reason": "terminal_closeout_or_backfill_marker_present",
                                    "runtime_layer": "controller decision:p13b_original_backtrace_continuation",
                                    "operator_next_action": "park_or_manual_review_without_release_probe",
                                    "next_action": "park_or_manual_review_without_release_probe",
                                    "terminal_marker": {
                                        "task_family": "original_readback",
                                        "terminal_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                        "marker_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                    },
                                },
                                "runtime_blocker_ledger_records": [
                                    {
                                        "blocker_ledger_id": "BLK-ORIG-PARK-STALE-1",
                                        "ledger_scope": "p13b_original_readback",
                                        "project_id": "PROJ-ORIG-PARK",
                                        "project_name": "Original park project",
                                        "task_id": "TASK-ORIG-PARK",
                                        "task_scope": "original_readback",
                                        "task_type": "p13b_original_notice_backtrace",
                                        "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                                        "blocker_reason": "terminal_closeout_or_backfill_marker_present",
                                        "runtime_layer": "controller decision:p13b_original_backtrace_continuation",
                                        "operator_next_action": "park_or_manual_review_without_release_probe",
                                        "next_action": "park_or_manual_review_without_release_probe",
                                        "terminal_marker": {
                                            "task_family": "original_readback",
                                            "terminal_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                            "marker_state": "PARK_DIFFERENT_PERSON_WITH_PERIOD",
                                        },
                                    }
                                ],
                                "operator_projection": {
                                    "projection_state": "ORIGINAL_READBACK_MANUAL_HOLD",
                                    "next_action": "park_or_manual_review_without_release_probe",
                                    "raw_json_required_for_next_step": False,
                                },
                            }
                        ],
                    },
                },
            )

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                original_backtrace_continuation_root=root / "original-readback",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["runtime_blocker_ledger_count"], 0)
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-ORIG-PARK")
            self.assertEqual(record["loop_terminal_state"], "ORIGINAL_READBACK_MANUAL_HOLD")
            self.assertEqual(record["runtime_blocker_ledger_records"], [])
            self.assertEqual(record["runtime_blocker_subqueue_routes"], [])

    def test_standalone_stage16_p13b_continuation_builds_status_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_standalone_stage16_p13b_continuation(root / "p13b-continuation")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                stage16_p13b_continuation_root=root / "p13b-continuation",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["loop_input_state"], "STANDALONE_P13B_CONTINUATION_STATUS_ONLY")
            self.assertEqual(result["summary"]["next_cycle_skip_reason"], "standalone_p13b_continuation_status_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["standalone_stage16_p13b_continuation_imported_project_count"], 2)
            self.assertTrue(
                result["manifest"]["source_standalone_stage16_p13b_continuation_json"].endswith(
                    "stage16-p13b-continuation-controller-v1.json"
                )
            )
            self.assertEqual(result["summary"]["project_status_record_count"], 2)
            self.assertEqual(
                result["summary"]["runtime_blocker_ledger_state_counts"],
                {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
            )
            records = {
                record["project_id"]: record
                for record in result["manifest"]["project_status_table"]["records"]
            }
            ready = records["PROJ-P13B-READY"]
            self.assertEqual(ready["loop_terminal_state"], "P13B_CONTINUATION_READY")
            self.assertFalse(ready["closeout_precedence_suppressed"])
            self.assertEqual(
                ready["next_recommended_action"],
                "run_data_ggzy_company_history_overlap_triage",
            )
            hold = records["PROJ-P13B-HOLD"]
            self.assertEqual(hold["loop_terminal_state"], "P13B_CONTINUATION_OPERATOR_HOLD")
            self.assertTrue(hold["closeout_precedence_suppressed"])
            self.assertEqual(
                hold["next_recommended_action"],
                "operator_confirms_higher_budget_before_retry",
            )
            self.assertEqual(
                hold["runtime_blocker_ledger_state_counts"],
                {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
            )
            self.assertEqual(
                hold["runtime_blocker_ledger_records"][0]["source_ledger_scopes"],
                ["p13b_continuation", "stage6_review_loop"],
            )

    def test_standalone_public_source_matched_without_abcd_grade_is_review_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_matched_field_query_without_downstream_grade(root / "field-query")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-20T00:00:00+08:00",
            )

            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["release_field_query_adapter_result_state_counts"], {"MATCHED": 1})
            self.assertEqual(record["release_field_query_state"], "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY")
            self.assertEqual(record["loop_terminal_state"], "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY")
            self.assertEqual(
                record["next_recommended_action"],
                "manual_review_public_field_readback_before_stage7_preview",
            )
            self.assertEqual(
                record["release_field_query_source_hit_summary_labels"],
                ["广东建设信息网三库一平台匿名公开源；样例人员：王先耀；证书：粤1332006200810171；施工许可：441900202206061001"],
            )

    def test_standalone_browser_authorized_project_manager_change_projects_c_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_browser_authorized_project_manager_change_field_query(root / "field-query")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-20T00:00:00+08:00",
            )

            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["release_field_query_adapter_result_state_counts"], {"MATCHED": 1})
            self.assertEqual(record["release_field_query_state"], "RELEASE_FIELD_QUERY_REVIEW_READY")
            self.assertEqual(
                record["release_field_query_downstream_abcd_grade_counts"],
                {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(
                record["release_field_query_source_hit_summary_labels"],
                [
                    (
                        "广东建设信息网三库一平台授权浏览器读回；"
                        "原项目经理：张三；新项目经理：李四；变更日期：2026-01-15；"
                        "窗口解释：ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"
                    )
                ],
            )
            summary = record["release_field_query_source_hit_summaries"][0]
            self.assertEqual(summary["match_state"], "MATCHED_BROWSER_AUTHORIZED_READBACK")
            self.assertEqual(summary["project_manager_change_interpretations"], ["ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"])
            self.assertEqual(result["summary"]["release_field_query_project_manager_change_ready_count"], 1)
            self.assertEqual(
                result["summary"]["release_field_query_project_manager_change_interpretation_counts"],
                {"ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1},
            )

    def test_standalone_release_field_query_imports_live_style_authorization_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_live_style_release_field_query_result(root / "field-query")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-19T00:00:00+08:00",
            )

            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(
                record["release_field_query_authorization_state_counts"],
                {"LOGIN_OR_SSO_REQUIRED": 1},
            )
            self.assertEqual(
                record["release_field_query_authorized_session_input_state_counts"],
                {"NO_AUTHORIZED_SESSION_INPUT": 1},
            )
            self.assertEqual(
                result["summary"]["release_field_query_authorization_state_counts"],
                {"LOGIN_OR_SSO_REQUIRED": 1},
            )
            self.assertEqual(
                result["summary"]["release_field_query_authorized_session_input_state_counts"],
                {"NO_AUTHORIZED_SESSION_INPUT": 1},
            )
            self.assertEqual(
                record["release_field_query_operator_next_actions"],
                [
                    "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                    "do_not_treat_http_dynamic_stealthy_as_login_state_replacement",
                ],
            )

    def test_bootstraps_dispatch_from_batch_closeout_when_dispatch_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["loop_input_state"], "BOOTSTRAPPED_DISPATCH_FROM_BATCH_CLOSEOUT")
            self.assertEqual(summary["bootstrap_from_batch_closeout_count"], 1)
            self.assertEqual(summary["dispatch_dry_run_ready_group_count"], 1)
            self.assertEqual(summary["project_status_record_count"], 1)
            self.assertTrue((root / "out" / "0-bootstrap" / "2-stage6-dispatch" / "stage6-review-action-dispatch-v1.json").exists())
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-D")
            self.assertEqual(record["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")

    def test_bootstrap_no_automated_tasks_surfaces_manual_only_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_terminal_batch_closeout(root / "closeout", evidence_state_json=state_json)

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["loop_input_state"], "BOOTSTRAPPED_DISPATCH_NO_AUTOMATED_TASKS")
            self.assertEqual(summary["bootstrap_dispatch_task_count"], 0)
            self.assertEqual(summary["bootstrap_manual_only_action_plan_count"], 1)
            self.assertEqual(summary["project_status_record_count"], 1)
            self.assertEqual(summary["next_cycle_skip_reason"], "bootstrap_dispatch_has_no_automated_tasks")
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-D")
            self.assertEqual(record["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertEqual(record["next_cycle_dispatch_block_reason"], "terminal_source_gap_no_delta_manual_review_only")

    def test_bootstrap_terminal_closeout_marker_suppresses_duplicate_release_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_release_terminal_marker_batch_closeout(root / "closeout", evidence_state_json=state_json)

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["loop_input_state"], "BOOTSTRAPPED_DISPATCH_NO_AUTOMATED_TASKS")
            self.assertEqual(result["summary"]["bootstrap_dispatch_task_count"], 0)
            record = result["manifest"]["project_status_table"]["records"][0]
            self.assertEqual(record["project_id"], "PROJ-REL-TERM")
            self.assertEqual(record["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertTrue(record["closeout_precedence_suppressed"])
            self.assertEqual(record["closeout_precedence_state"], "SUPPRESS_TERMINAL_CLOSEOUT")
            self.assertEqual(record["next_cycle_dispatch_block_reason"], "terminal_closeout_or_backfill_marker_present")
            self.assertEqual(
                record["next_recommended_action"],
                "project_to_review_ready_status_projection_without_duplicate_dispatch",
            )

    def test_artifact_backed_combo_routes_closed_and_unfinished_stage4_subqueues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_combo_batch_closeout(root / "closeout", evidence_state_json=state_json)
            _write_combo_release_field_query_result(root / "field-query")

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "closeout",
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["loop_input_state"], "BOOTSTRAPPED_DISPATCH_FROM_BATCH_CLOSEOUT")
            self.assertEqual(summary["bootstrap_dispatch_task_count"], 2)
            self.assertEqual(summary["bootstrap_manual_only_action_plan_count"], 3)
            self.assertEqual(summary["readback_waiting_for_controlled_execution_count"], 2)
            self.assertEqual(summary["release_field_query_project_count"], 3)
            self.assertEqual(
                summary["release_field_query_state_counts"],
                {
                    "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW": 2,
                    "RELEASE_FIELD_QUERY_REVIEW_READY": 1,
                },
            )
            self.assertEqual(
                summary["release_field_query_authorization_state_counts"],
                {"LOGIN_OR_SSO_REQUIRED": 1},
            )
            self.assertEqual(
                summary["release_field_query_authorized_session_input_state_counts"],
                {"NO_AUTHORIZED_SESSION_INPUT": 1},
            )
            self.assertEqual(summary["runtime_blocker_ledger_count"], 4)
            self.assertEqual(
                summary["runtime_blocker_ledger_state_counts"],
                {
                    "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION": 1,
                    "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED": 1,
                    "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 2,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_ledger_scope_counts"],
                {
                    "stage4_release_evidence_query": 2,
                    "stage6_review_action_plan": 2,
                    "stage6_review_loop": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_ledger_required_input_counts"],
                {
                    "authorized_browser_storage_state_or_user_data_dir": 1,
                    "continuation_budget_reason": 1,
                    "fallback_source_or_project_local_authority_path": 1,
                    "new_official_original_notice_source_or_snapshot": 1,
                    "operator_retry_budget": 1,
                    "operator_retry_scope": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_ledger_retry_policy_counts"],
                {
                    "manual_reopen_requires_new_official_source_or_operator_budget": 1,
                    "retry_only_after_authorized_session_available": 1,
                    "retry_only_after_budget_increase_or_new_source": 1,
                    "retry_only_with_fallback_source_or_more_precise_identifiers": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_ledger_operator_next_action_counts"],
                {
                    "operator_adds_new_official_original_source_or_confirms_manual_retry_scope": 1,
                    "operator_confirms_higher_budget_before_retry": 1,
                    "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1,
                    "record_not_found_without_clearance_claim_or_try_project_local_authority": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_ledger_reopen_condition_counts"],
                {
                    "authorized_browser_storage_state_available": 1,
                    "fallback_public_source_available": 1,
                    "more_precise_project_identifier_available": 1,
                    "new_machine_readable_input_artifact_available": 2,
                    "operator_approves_same_session_retry": 1,
                    "operator_override_records_scope_budget_and_reason": 2,
                    "prior_blocker_resolved_without_clearance_claim": 2,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_subqueue_counts"],
                {
                    "browser_worker": 1,
                    "fallback_source": 1,
                    "manual_hold": 2,
                    "operator_action": 4,
                    "retry": 3,
                    "suspend_dead_letter": 2,
                },
            )
            self.assertEqual(summary["runtime_blocker_next_subqueue_record_count"], 13)
            self.assertEqual(
                summary["runtime_blocker_next_subqueue_route_counts"],
                summary["runtime_blocker_subqueue_counts"],
            )
            self.assertEqual(
                summary["runtime_blocker_next_subqueue_state_counts"],
                {
                    "BROWSER_WORKER_WAITING_FOR_AUTHORIZED_SESSION": 1,
                    "FALLBACK_SOURCE_REQUIRED": 1,
                    "MANUAL_HOLD_PENDING_OPERATOR_REVIEW": 2,
                    "OPERATOR_ACTION_REQUIRED": 4,
                    "RETRY_WAITING_FOR_REOPEN_INPUT": 3,
                    "SUSPEND_OR_DEAD_LETTER_PENDING_REOPEN_INPUT": 2,
                },
            )
            self.assertEqual(summary["owner_assignment_state_counts"], {"ASSIGNED_OWNER_READY": 8})
            self.assertEqual(summary["assigned_owner_counts"], {"卡卡罗特": 8})
            self.assertEqual(summary["unassigned_owner_count"], 0)
            self.assertEqual(
                summary["owner_assignment_source_ref_counts"],
                {"control/operator_assignment_roster_defaults.yaml#defaults": 8},
            )
            self.assertEqual(
                summary["owner_assignment_next_action_counts"],
                {"owner_reviews_project_status_and_records_decision": 8},
            )

            records = {
                record["project_id"]: record
                for record in result["manifest"]["project_status_table"]["records"]
            }
            self.assertEqual(records["PROJ-P13B-DISPATCH"]["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")
            self.assertEqual(
                records["PROJ-P13B-DISPATCH"]["next_recommended_action"],
                "run_controlled_dispatch_task_or_record_operator_skip",
            )
            self.assertEqual(records["PROJ-P13B-HOLD"]["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertTrue(records["PROJ-P13B-HOLD"]["closeout_precedence_suppressed"])
            self.assertEqual(
                records["PROJ-P13B-HOLD"]["runtime_blocker_ledger_state_counts"],
                {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
            )
            p13b_hold_blocker = records["PROJ-P13B-HOLD"]["runtime_blocker_ledger_records"][0]
            self.assertEqual(p13b_hold_blocker["task_scope"], "p13b_follow_up")
            self.assertEqual(
                p13b_hold_blocker["source_ledger_scopes"],
                ["stage6_review_action_plan", "stage6_review_loop"],
            )
            self.assertEqual(
                records["PROJ-P13B-HOLD"]["runtime_blocker_subqueue_routes"],
                ["retry", "manual_hold", "suspend_dead_letter", "operator_action"],
            )
            self.assertEqual(p13b_hold_blocker["required_input"], ["operator_retry_budget", "continuation_budget_reason"])
            self.assertEqual(p13b_hold_blocker["retry_policy"], "retry_only_after_budget_increase_or_new_source")
            self.assertEqual(p13b_hold_blocker["operator_next_action"], "operator_confirms_higher_budget_before_retry")
            self.assertEqual(records["PROJ-ORIG-RETRY"]["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")
            self.assertEqual(records["PROJ-ORIG-SUSPEND"]["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertEqual(
                records["PROJ-ORIG-SUSPEND"]["next_cycle_dispatch_block_reason"],
                "terminal_source_gap_no_delta_manual_review_only",
            )
            self.assertEqual(
                records["PROJ-ORIG-SUSPEND"]["runtime_blocker_ledger_state_counts"],
                {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
            )
            self.assertEqual(
                records["PROJ-ORIG-SUSPEND"]["runtime_blocker_ledger_records"][0]["required_input"],
                ["new_official_original_notice_source_or_snapshot", "operator_retry_scope"],
            )
            self.assertEqual(records["PROJ-REL-TERM"]["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertTrue(records["PROJ-REL-TERM"]["closeout_precedence_suppressed"])
            self.assertEqual(records["PROJ-REL-TERM"]["runtime_blocker_ledger_state_counts"], {})
            self.assertEqual(records["PROJ-REL-TERM"]["runtime_blocker_ledger_records"], [])
            self.assertEqual(records["PROJ-FIELD-READY"]["loop_terminal_state"], "RELEASE_FIELD_QUERY_REVIEW_READY")
            self.assertEqual(
                records["PROJ-FIELD-READY"]["release_field_query_downstream_abcd_grade_counts"],
                {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(records["PROJ-FIELD-AUTH"]["loop_terminal_state"], "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW")
            self.assertEqual(
                records["PROJ-FIELD-AUTH"]["release_field_query_authorization_state_counts"],
                {"LOGIN_OR_SSO_REQUIRED": 1},
            )
            self.assertEqual(
                records["PROJ-FIELD-AUTH"]["runtime_blocker_ledger_state_counts"],
                {"AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION": 1},
            )
            auth_blocker = records["PROJ-FIELD-AUTH"]["runtime_blocker_ledger_records"][0]
            self.assertEqual(auth_blocker["runtime_layer"], "browser worker")
            self.assertEqual(auth_blocker["required_input"], ["authorized_browser_storage_state_or_user_data_dir"])
            self.assertEqual(auth_blocker["retry_policy"], "retry_only_after_authorized_session_available")
            self.assertEqual(
                records["PROJ-FIELD-AUTH"]["runtime_blocker_subqueue_routes"],
                ["browser_worker", "retry", "operator_action"],
            )
            self.assertEqual(
                auth_blocker["operator_next_action"],
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            )
            self.assertEqual(auth_blocker["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertTrue(str(auth_blocker["artifact_ref"]).endswith("guangdong-local-field-query-probe-v1.json"))
            self.assertEqual(records["PROJ-FIELD-NOTFOUND"]["loop_terminal_state"], "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW")
            self.assertEqual(
                records["PROJ-FIELD-NOTFOUND"]["release_field_query_adapter_result_state_counts"],
                {"NOT_FOUND": 1},
            )
            self.assertEqual(
                records["PROJ-FIELD-NOTFOUND"]["runtime_blocker_ledger_state_counts"],
                {"NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED": 1},
            )
            not_found_blocker = records["PROJ-FIELD-NOTFOUND"]["runtime_blocker_ledger_records"][0]
            self.assertEqual(not_found_blocker["runtime_layer"], "source adapter")
            self.assertEqual(not_found_blocker["required_input"], ["fallback_source_or_project_local_authority_path"])
            self.assertEqual(not_found_blocker["retry_policy"], "retry_only_with_fallback_source_or_more_precise_identifiers")
            self.assertEqual(
                records["PROJ-FIELD-NOTFOUND"]["runtime_blocker_subqueue_routes"],
                ["fallback_source", "retry", "operator_action"],
            )
            self.assertEqual(
                not_found_blocker["operator_next_action"],
                "record_not_found_without_clearance_claim_or_try_project_local_authority",
            )
            self.assertTrue(str(not_found_blocker["artifact_ref"]).endswith("guangdong-local-field-query-probe-v1.json"))
            next_subqueue_json = root / "out" / "stage6-review-loop-runtime-blocker-next-subqueues.json"
            self.assertTrue(next_subqueue_json.exists())
            next_subqueues = json.loads(next_subqueue_json.read_text(encoding="utf-8"))
            self.assertEqual(next_subqueues["summary"]["next_subqueue_record_count"], 13)
            self.assertEqual(
                next_subqueues["summary"]["subqueue_route_counts"],
                summary["runtime_blocker_subqueue_counts"],
            )
            next_subqueue_records = {
                (record["project_id"], record["subqueue_route"]): record
                for record in next_subqueues["records"]
            }
            auth_browser_queue = next_subqueue_records[("PROJ-FIELD-AUTH", "browser_worker")]
            self.assertTrue(auth_browser_queue["controller_consumable"])
            self.assertEqual(
                auth_browser_queue["subqueue_state"],
                "BROWSER_WORKER_WAITING_FOR_AUTHORIZED_SESSION",
            )
            self.assertEqual(
                auth_browser_queue["required_input"],
                ["authorized_browser_storage_state_or_user_data_dir"],
            )
            self.assertIn(
                str(root / "field-query" / "guangdong-local-field-query-probe-v1.json"),
                auth_browser_queue["input_artifact_refs"],
            )
            not_found_fallback_queue = next_subqueue_records[("PROJ-FIELD-NOTFOUND", "fallback_source")]
            self.assertEqual(not_found_fallback_queue["subqueue_state"], "FALLBACK_SOURCE_REQUIRED")
            self.assertEqual(
                not_found_fallback_queue["required_input"],
                ["fallback_source_or_project_local_authority_path"],
            )
            self.assertEqual(
                result["manifest"]["runtime_blocker_next_subqueue_table"]["summary"],
                next_subqueues["summary"],
            )
            self.assertTrue(
                str(result["manifest"]["runtime_blocker_next_subqueue_json"]).endswith(
                    "stage6-review-loop-runtime-blocker-next-subqueues.json"
                )
            )

            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json",
                search_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )
            self.assertTrue(projection["owner_can_observe_without_raw_json"])
            self.assertEqual(projection["summary"]["project_count"], 8)
            self.assertEqual(projection["summary"]["manual_hold_count"], 3)
            self.assertEqual(projection["summary"]["waiting_for_controlled_execution_count"], 2)
            self.assertEqual(projection["summary"]["runtime_blocker_ledger_count"], 4)
            self.assertEqual(
                projection["summary"]["runtime_blocker_ledger_state_counts"],
                summary["runtime_blocker_ledger_state_counts"],
            )
            self.assertEqual(
                projection["summary"]["runtime_blocker_ledger_scope_counts"],
                summary["runtime_blocker_ledger_scope_counts"],
            )
            self.assertEqual(
                projection["summary"]["runtime_blocker_ledger_required_input_counts"],
                summary["runtime_blocker_ledger_required_input_counts"],
            )
            self.assertEqual(
                projection["summary"]["runtime_blocker_ledger_retry_policy_counts"],
                summary["runtime_blocker_ledger_retry_policy_counts"],
            )
            self.assertEqual(
                projection["summary"]["runtime_blocker_ledger_operator_next_action_counts"],
                summary["runtime_blocker_ledger_operator_next_action_counts"],
            )
            self.assertEqual(
                projection["summary"]["runtime_blocker_ledger_reopen_condition_counts"],
                summary["runtime_blocker_ledger_reopen_condition_counts"],
            )
            self.assertEqual(
                projection["summary"]["runtime_blocker_subqueue_counts"],
                summary["runtime_blocker_subqueue_counts"],
            )
            self.assertEqual(projection["summary"]["owner_assignment_state_counts"], {"ASSIGNED_OWNER_READY": 8})
            self.assertEqual(projection["summary"]["assigned_owner_counts"], {"卡卡罗特": 8})
            projected = {row["project_id"]: row for row in projection["project_status_rows"]}
            self.assertEqual(projected["PROJ-P13B-HOLD"]["closeout_precedence_state"], "SUPPRESS_DUPLICATE_WORKER_DISPATCH")
            self.assertEqual(projected["PROJ-P13B-HOLD"]["project_owner_label"], "single_operator：卡卡罗特")
            self.assertEqual(
                projected["PROJ-P13B-HOLD"]["owner_assignment_source_ref"],
                "control/operator_assignment_roster_defaults.yaml#defaults",
            )
            projected_p13b_hold_blocker = projected["PROJ-P13B-HOLD"]["runtime_blocker_ledger_records"][0]
            self.assertEqual(projected_p13b_hold_blocker["task_scope"], "p13b_follow_up")
            self.assertEqual(
                projected_p13b_hold_blocker["source_ledger_scopes"],
                ["stage6_review_action_plan", "stage6_review_loop"],
            )
            self.assertEqual(
                projected_p13b_hold_blocker["source_ledger_scope_labels"],
                ["Stage6 动作计划", "Stage6 复核循环"],
            )
            self.assertIn("当前按一条阻断处理", projected_p13b_hold_blocker["source_trace_label"])
            self.assertEqual(projected_p13b_hold_blocker["required_input"], ["operator_retry_budget", "continuation_budget_reason"])
            self.assertEqual(
                projected_p13b_hold_blocker["required_input_labels"],
                ["操作者确认的续跑预算", "续跑预算原因"],
            )
            self.assertEqual(projected_p13b_hold_blocker["operator_next_action"], "operator_confirms_higher_budget_before_retry")
            self.assertEqual(projected_p13b_hold_blocker["operator_next_action_label"], "操作者确认提高预算后再重试。")
            self.assertEqual(
                projected_p13b_hold_blocker["subqueue_routes"],
                ["retry", "manual_hold", "suspend_dead_letter", "operator_action"],
            )
            self.assertIn("进入 suspend/dead-letter", projected_p13b_hold_blocker["subqueue_labels"][2])
            self.assertEqual(projected["PROJ-REL-TERM"]["closeout_precedence_state"], "SUPPRESS_TERMINAL_CLOSEOUT")
            self.assertEqual(projected["PROJ-REL-TERM"]["input_refs"]["marker_state"], "MATCHED")
            self.assertEqual(
                projected["PROJ-REL-TERM"]["output_artifact_refs"],
                ["tmp/field-query/guangdong-local-field-query-probe-v1.json"],
            )
            self.assertEqual(projected["PROJ-FIELD-AUTH"]["blocker_reason"], "release_field_query_gap_or_blocker")
            self.assertIn(
                str(root / "field-query" / "guangdong-local-field-query-probe-v1.json"),
                projected["PROJ-FIELD-AUTH"]["output_artifact_refs"],
            )
            projected_auth_blocker = projected["PROJ-FIELD-AUTH"]["runtime_blocker_ledger_records"][0]
            self.assertEqual(projected_auth_blocker["required_input"], ["authorized_browser_storage_state_or_user_data_dir"])
            self.assertEqual(projected_auth_blocker["retry_policy"], "retry_only_after_authorized_session_available")
            self.assertEqual(
                projected["PROJ-FIELD-AUTH"]["runtime_blocker_subqueue_routes"],
                ["browser_worker", "retry", "operator_action"],
            )
            self.assertEqual(
                projected_auth_blocker["operator_next_action"],
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            )
            self.assertIn(
                str(root / "field-query" / "guangdong-local-field-query-probe-v1.json"),
                projected_auth_blocker["artifact_ref"],
            )
            projected_not_found_blocker = projected["PROJ-FIELD-NOTFOUND"]["runtime_blocker_ledger_records"][0]
            self.assertEqual(projected_not_found_blocker["required_input"], ["fallback_source_or_project_local_authority_path"])
            self.assertEqual(projected_not_found_blocker["retry_policy"], "retry_only_with_fallback_source_or_more_precise_identifiers")
            self.assertEqual(
                projected["PROJ-FIELD-NOTFOUND"]["runtime_blocker_subqueue_routes"],
                ["fallback_source", "retry", "operator_action"],
            )
            self.assertEqual(
                projected_not_found_blocker["operator_next_action"],
                "record_not_found_without_clearance_claim_or_try_project_local_authority",
            )
            self.assertFalse(projection["customer_visible_allowed"])
            self.assertTrue(projection["query_miss_is_not_clearance"])

    def test_missing_dispatch_and_batch_closeout_reports_single_input_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "missing-dispatch",
                batch_closeout_root=root / "missing-closeout",
                output_root=root / "out",
                auto_discover_latest_batch_closeout=False,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["blocking_reasons"], ["stage6_loop_input_missing_dispatch_or_batch_closeout"])
            self.assertEqual(result["summary"]["loop_input_state"], "INPUT_BLOCKED_NO_DISPATCH_OR_BATCH_CLOSEOUT")
            self.assertEqual(result["summary"]["project_status_record_count"], 0)
            self.assertEqual(result["summary"]["next_cycle_skip_reason"], "dispatch_or_batch_closeout_input_missing")

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)

            result = run_stage6_review_loop_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            self.assertFalse(result["manifest"]["safety"]["stage7_to_stage9_live_execution_enabled"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)
            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_sha256"], _fingerprint_without_manifest_sha(manifest))


def _write_evidence_state(root: Path) -> Path:
    path = root / "evidence-orchestration-state-v1.json"
    _write_json(
        path,
        {
            "manifest": {
                "manifest_id": "STATE-1",
                "source_stage16_storage_json": "tmp/storage.json",
                "source_p13b_company_history_json": "tmp/p13b.json",
                "source_original_notice_backtrace_json": "tmp/original.json",
                "source_design_survey_public_registry_fallback_json": "tmp/design-fallback.json",
            },
            "summary": {},
        },
    )
    return path


def _write_dispatch(root: Path, *, evidence_state_json: str | Path) -> None:
    _write_json(
        root / "stage6-review-action-dispatch-v1.json",
        {
            "manifest": {
                "manifest_id": "DISPATCH-1",
                "dispatch_task_table": {
                    "records": [
                        {
                            "dispatch_task_id": "DISPATCH-PROJ-D",
                            "project_id": "PROJ-D",
                            "project_name": "D project",
                            "dispatch_task_type": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
                            "dispatch_readiness_state": "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN",
                            "source_refs": {"evidence_state_json": str(evidence_state_json)},
                            "customer_visible_allowed": False,
                            "no_legal_conclusion": True,
                            "query_miss_is_not_clearance": True,
                        }
                    ],
                    "summary": {},
                },
            },
            "summary": {},
        },
    )


def _write_release_dispatch(root: Path, *, evidence_state_json: str | Path) -> None:
    _write_json(
        root / "stage6-review-action-dispatch-v1.json",
        {
            "manifest": {
                "manifest_id": "DISPATCH-RELEASE-1",
                "dispatch_task_table": {
                    "records": [
                        {
                            "dispatch_task_id": "DISPATCH-PROJ-REL",
                            "project_id": "PROJ-REL",
                            "project_name": "Release project",
                            "dispatch_task_type": "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
                            "dispatch_readiness_state": "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN",
                            "source_refs": {
                                "evidence_state_json": str(evidence_state_json),
                                "evidence_batch_closeout_json": str(root.parent / "closeout" / "evidence-batch-closeout-v1.json"),
                                "p13b_operational_closeout_root": str(root.parent / "p13b-operational"),
                            },
                            "customer_visible_allowed": False,
                            "no_legal_conclusion": True,
                            "query_miss_is_not_clearance": True,
                        }
                    ],
                    "summary": {},
                },
            },
            "summary": {},
        },
    )


def _write_release_adapter_plan(root: Path) -> None:
    _write_json(
        root / "release-evidence-adapter-plan-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "RELEASE-PLAN-1",
                "release_evidence_adapter_task_records": [
                    {
                        "release_evidence_adapter_task_id": "REL-TASK-1",
                        "project_id": "PROJ-REL",
                        "project_name": "Release project",
                        "candidate_company_name": "A company",
                        "matched_person_names": ["张三"],
                        "release_evidence_target_type": "construction_permit",
                        "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
                        "query_params": {
                            "projectName": "Release project",
                            "companyName": "A company",
                            "personName": "张三",
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                ],
            },
            "summary": {"release_evidence_adapter_task_count": 1},
        },
    )


def _write_terminal_suppressed_release_adapter_plan(root: Path) -> None:
    _write_json(
        root / "release-evidence-adapter-plan-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "RELEASE-PLAN-SUPPRESS-1",
                "project_release_evidence_plan_records": [
                    {
                        "project_id": "PROJ-REL-SUPPRESS",
                        "project_name": "Release suppressed project",
                        "assigned_owner": "卡卡罗特",
                        "assigned_owner_role": "single_operator",
                        "reviewer": "卡卡罗特",
                        "reviewer_role": "single_operator",
                        "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
                        "release_evidence_project_plan_state": "RELEASE_EVIDENCE_TERMINAL_CLOSEOUT_SUPPRESSED",
                        "recommended_next_action": "project_to_review_ready_status_projection_without_duplicate_dispatch",
                        "closeout_precedence": {
                            "closeout_precedence_state": "SUPPRESS_TERMINAL_CLOSEOUT",
                            "task_scope": "release_evidence_query",
                            "task_type": "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
                            "suppressed_dispatch": True,
                            "should_suppress_dispatch": True,
                            "suppression_reason": "terminal_closeout_or_backfill_marker_present",
                            "runtime_layer": "controller decision:release_evidence_adapter_plan",
                            "operator_next_action": "project_to_review_ready_status_projection_without_duplicate_dispatch",
                            "next_action": "project_to_review_ready_status_projection_without_duplicate_dispatch",
                            "blocker_taxonomy": ["terminal_closeout_or_backfill_marker_present"],
                            "marker_source_refs": [
                                {
                                    "source_ref": "runtime_closeout_marker",
                                    "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                                }
                            ],
                            "terminal_marker": {
                                "task_family": "release_evidence_query",
                                "terminal_state": "MATCHED",
                                "marker_state": "MATCHED",
                                "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                                "task_id": "REL-TASK-SUPPRESS-1",
                            },
                            "required_input": ["operator_override_reason_or_new_machine_readable_input"],
                            "reopen_conditions": [
                                "new_machine_readable_input_artifact_available",
                                "prior_blocker_resolved_without_clearance_claim",
                                "operator_override_records_scope_budget_and_reason",
                            ],
                            "retry_policy": "do_not_retry_same_worker_without_new_input_or_operator_override",
                        },
                        "closeout_precedence_state": "SUPPRESS_TERMINAL_CLOSEOUT",
                        "closeout_precedence_suppressed": True,
                        "runtime_blocker_ledger_record": {},
                        "runtime_blocker_ledger_records": [],
                    }
                ],
            },
            "summary": {
                "project_plan_count": 1,
                "adapter_task_count": 0,
                "runtime_blocker_ledger_count": 1,
            },
        },
    )


def _write_standalone_original_backtrace_continuation(root: Path) -> None:
    _write_json(
        root / "p13b-original-backtrace-continuation-controller-v2.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "ORIG-CONT-STANDALONE-1",
                "continuation_plan_records": [
                    {
                        "original_notice_task_id": "TASK-ORIG-READY",
                        "project_id": "PROJ-ORIG-READY",
                        "project_name": "Original ready project",
                        "continuation_state": "RELEASE_EVIDENCE_READY",
                        "recommended_next_action": "build_release_evidence_regional_adapter_plan",
                        "next_queue": "release_evidence_query",
                        "closeout_precedence": {
                            "closeout_precedence_state": "SUPPRESS_DUPLICATE_WORKER_DISPATCH",
                            "task_scope": "original_readback",
                            "task_type": "p13b_original_notice_backtrace",
                            "suppressed_dispatch": True,
                            "should_suppress_dispatch": True,
                            "suppression_reason": "terminal_source_gap_no_delta_manual_review_only",
                            "runtime_layer": "closeout",
                            "operator_next_action": "build_release_evidence_regional_adapter_plan",
                            "next_action": "build_release_evidence_regional_adapter_plan",
                            "blocker_taxonomy": ["terminal_source_gap_no_delta_manual_review_only"],
                            "marker_source_refs": [
                                {
                                    "source_ref": "original_backtrace_continuation_no_delta",
                                    "artifact_ref": "tmp/original-readback/p13b-original-backtrace-continuation-controller-v2.json",
                                }
                            ],
                            "terminal_marker": {
                                "task_family": "original_readback",
                                "terminal_state": "RELEASE_EVIDENCE_READY",
                                "marker_state": "RELEASE_EVIDENCE_READY",
                                "artifact_ref": "tmp/original-readback/p13b-original-backtrace-continuation-controller-v2.json",
                                "task_id": "TASK-ORIG-READY",
                            },
                            "required_input": ["operator_override_reason_or_new_machine_readable_input"],
                            "reopen_conditions": [
                                "new_machine_readable_input_artifact_available",
                                "prior_blocker_resolved_without_clearance_claim",
                                "operator_override_records_scope_budget_and_reason",
                            ],
                            "retry_policy": "do_not_retry_same_worker_without_new_input_or_operator_override",
                        },
                        "closeout_precedence_state": "SUPPRESS_DUPLICATE_WORKER_DISPATCH",
                        "closeout_precedence_suppressed": True,
                        "runtime_blocker_ledger_record": {},
                        "runtime_blocker_ledger_records": [],
                        "operator_projection": {
                            "projection_state": "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK",
                            "next_action": "build_release_evidence_regional_adapter_plan",
                            "raw_json_required_for_next_step": False,
                        },
                    },
                    {
                        "original_notice_task_id": "TASK-ORIG-RETRY",
                        "project_id": "PROJ-ORIG-RETRY",
                        "project_name": "Original retry project",
                        "continuation_state": "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT",
                        "recommended_next_action": "run_next_live_original_notice_backtrace_batch",
                        "next_queue": "original_readback_retry",
                        "closeout_precedence": {
                            "closeout_precedence_state": "ALLOW_DISPATCH_NO_TERMINAL_MARKER",
                            "task_scope": "original_readback",
                            "task_type": "p13b_original_notice_backtrace",
                            "suppressed_dispatch": False,
                            "should_suppress_dispatch": False,
                        },
                        "closeout_precedence_state": "ALLOW_DISPATCH_NO_TERMINAL_MARKER",
                        "closeout_precedence_suppressed": False,
                        "runtime_blocker_ledger_record": {
                            "blocker_ledger_id": "BLK-ORIG-RETRY-1",
                            "ledger_scope": "p13b_original_readback",
                            "project_id": "PROJ-ORIG-RETRY",
                            "project_name": "Original retry project",
                            "task_id": "TASK-ORIG-RETRY",
                            "task_scope": "original_readback",
                            "task_type": "p13b_original_notice_backtrace",
                            "blocker_state": "ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED",
                            "blocker_reason": "original_notice_backtrace_budget_deferred_or_incomplete",
                            "runtime_layer": "retry policy",
                            "required_input": ["next_original_notice_backtrace_budget_or_new_source_snapshot"],
                            "retry_policy": "retry_next_original_backtrace_batch_with_bounded_budget",
                            "reopen_conditions": [
                                "bounded_original_notice_backtrace_budget_available",
                                "new_machine_readable_original_notice_source_available",
                            ],
                            "operator_next_action": "operator_reviews_retry_budget_or_keeps_original_readback_suspended",
                            "next_action": "run_next_live_original_notice_backtrace_batch",
                        },
                        "operator_projection": {
                            "projection_state": "NEXT_ORIGINAL_READBACK_SUBQUEUE_READY",
                            "next_action": "run_next_live_original_notice_backtrace_batch",
                            "raw_json_required_for_next_step": False,
                        },
                    },
                ],
            },
            "summary": {
                "continuation_plan_record_count": 2,
                "next_queue_counts": {
                    "original_readback_retry": 1,
                    "release_evidence_query": 1,
                },
            },
        },
    )


def _write_standalone_stage16_p13b_continuation(root: Path) -> None:
    _write_json(
        root / "stage16-p13b-continuation-controller-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "STAGE16-P13B-STANDALONE-1",
                "project_continuation_records": [
                    {
                        "project_id": "PROJ-P13B-READY",
                        "project_name": "P13B ready project",
                        "continuation_state": "READY_FOR_P13B_DATA_GGZY",
                        "recommended_next_action": "run_data_ggzy_company_history_overlap_triage",
                        "closeout_precedence": {
                            "closeout_precedence_state": "ALLOW_DISPATCH_NO_TERMINAL_MARKER",
                            "task_scope": "p13b_follow_up",
                            "task_type": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                            "suppressed_dispatch": False,
                            "should_suppress_dispatch": False,
                        },
                        "closeout_precedence_state": "ALLOW_DISPATCH_NO_TERMINAL_MARKER",
                        "closeout_precedence_suppressed": False,
                        "operator_projection": {
                            "projection_state": "P13B_CONTINUATION_READY",
                            "next_action": "run_data_ggzy_company_history_overlap_triage",
                            "raw_json_required_for_next_step": False,
                        },
                    },
                    {
                        "project_id": "PROJ-P13B-HOLD",
                        "project_name": "P13B hold project",
                        "continuation_state": "P13B_TERMINAL_CLOSEOUT_SUPPRESSED",
                        "recommended_next_action": "operator_confirms_higher_budget_before_retry",
                        "closeout_precedence": {
                            "closeout_precedence_state": "SUPPRESS_TERMINAL_CLOSEOUT",
                            "task_scope": "p13b_follow_up",
                            "task_type": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                            "suppressed_dispatch": True,
                            "should_suppress_dispatch": True,
                            "suppression_reason": "terminal_closeout_or_backfill_marker_present",
                            "runtime_layer": "controller decision:stage16_p13b_continuation",
                            "operator_next_action": "operator_confirms_higher_budget_before_retry",
                            "next_action": "operator_confirms_higher_budget_before_retry",
                            "blocker_taxonomy": ["terminal_closeout_or_backfill_marker_present"],
                            "marker_source_refs": [
                                {
                                    "source_ref": "runtime_closeout_marker",
                                    "artifact_ref": "tmp/p13b-operational-closeout-v1/p13b-operational-closeout-v1.json",
                                }
                            ],
                            "terminal_marker": {
                                "task_family": "p13b_followup",
                                "terminal_state": "SOURCE_LIMIT_DEFERRED",
                                "marker_state": "SOURCE_LIMIT_DEFERRED",
                                "artifact_ref": "tmp/p13b-operational-closeout-v1/p13b-operational-closeout-v1.json",
                                "task_id": "PROJ-P13B-HOLD",
                            },
                            "required_input": ["operator_retry_budget", "continuation_budget_reason"],
                            "reopen_conditions": [
                                "new_machine_readable_input_artifact_available",
                                "prior_blocker_resolved_without_clearance_claim",
                                "operator_override_records_scope_budget_and_reason",
                            ],
                            "retry_policy": "retry_only_after_budget_increase_or_new_source",
                        },
                        "closeout_precedence_state": "SUPPRESS_TERMINAL_CLOSEOUT",
                        "closeout_precedence_suppressed": True,
                        "runtime_blocker_ledger_record": {
                            "blocker_ledger_id": "BLK-P13B-HOLD-1",
                            "ledger_scope": "p13b_continuation",
                            "project_id": "PROJ-P13B-HOLD",
                            "project_name": "P13B hold project",
                            "task_id": "PROJ-P13B-HOLD",
                            "task_scope": "p13b_follow_up",
                            "task_type": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                            "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                            "blocker_reason": "terminal_closeout_or_backfill_marker_present",
                            "runtime_layer": "controller decision:stage16_p13b_continuation",
                            "required_input": ["operator_retry_budget", "continuation_budget_reason"],
                            "retry_policy": "retry_only_after_budget_increase_or_new_source",
                            "reopen_conditions": [
                                "new_machine_readable_input_artifact_available",
                                "prior_blocker_resolved_without_clearance_claim",
                                "operator_override_records_scope_budget_and_reason",
                            ],
                            "operator_next_action": "operator_confirms_higher_budget_before_retry",
                            "next_action": "operator_confirms_higher_budget_before_retry",
                            "terminal_marker": {
                                "task_family": "p13b_followup",
                                "terminal_state": "SOURCE_LIMIT_DEFERRED",
                                "marker_state": "SOURCE_LIMIT_DEFERRED",
                                "artifact_ref": "tmp/p13b-operational-closeout-v1/p13b-operational-closeout-v1.json",
                            },
                        },
                        "operator_projection": {
                            "projection_state": "P13B_CONTINUATION_OPERATOR_HOLD",
                            "next_action": "operator_confirms_higher_budget_before_retry",
                            "raw_json_required_for_next_step": False,
                        },
                    },
                ],
            },
            "summary": {
                "source_project_count": 2,
                "ready_for_p13b_count": 1,
                "runtime_blocker_ledger_count": 1,
            },
        },
    )


def _write_release_field_query_result(root: Path) -> None:
    _write_json(
        root / "guangdong-local-field-query-probe-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-1",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-TASK-1",
                        "project_id": "PROJ-REL",
                        "project_name": "Release project",
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "adapter_result_state": "MATCHED",
                        "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                        "field_summary": {
                            "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                            "gdcic_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
                            "gdcic_publicity_period_readback_ready_count": 1,
                            "sample_person_names": ["王先耀"],
                            "sample_certificate_nos": ["粤1332006200810171"],
                            "sample_permit_codes": ["441900202206061001"],
                            "sample_id_card_hashes": ["sha256:abc123"],
                            "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                            "authorized_session_input_ready": True,
                            "authorization_readiness_state_counts": {
                                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED": 1,
                            },
                            "operator_next_actions": [
                                "review_gdcic_authorized_query_terms_or_capture_more_precise_field_page",
                            ],
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 1,
                "release_evidence_downstream_abcd_grade_counts": {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
            },
        },
    )


def _write_matched_field_query_without_downstream_grade(root: Path) -> None:
    _write_json(
        root / "guangdong-local-field-query-probe-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-MATCHED-NO-ABCD",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-TASK-MATCHED-NO-ABCD",
                        "project_id": "PROJ-MATCHED-NO-ABCD",
                        "project_name": "Matched public readback",
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "adapter_result_state": "MATCHED",
                        "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
                        "field_summary": {
                            "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                            "gdcic_query_probe_state": "READBACK_READY_PUBLIC_SOURCE",
                            "sample_person_names": ["廖伟文"],
                        },
                        "field_match_summary": {
                            "source_specific_records": [
                                {
                                    "route_id": "publicity_period_project_person_by_project_id",
                                    "record_type": "personnel_public_record",
                                    "name": "王先耀",
                                    "regCertNum": "粤1332006200810171",
                                    "certNum": "441900202206061001",
                                }
                            ]
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 1,
                "adapter_result_state_counts": {"MATCHED": 1},
            },
        },
    )


def _write_browser_authorized_project_manager_change_field_query(root: Path) -> None:
    _write_json(
        root / "guangdong-local-field-query-probe-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-BROWSER-PM-CHANGE",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-TASK-BROWSER-PM-CHANGE",
                        "project_id": "PROJ-BROWSER-PM-CHANGE",
                        "project_name": "Browser project manager change",
                        "source_profile_id": "GUANGDONG-GDCIC-HOME",
                        "release_evidence_target_type": "project_manager_change_notice",
                        "adapter_result_state": "MATCHED",
                        "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
                        "downstream_release_evidence_abcd_grade": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
                        "field_summary": {
                            "source_specific_adapter_id": "guangdong_gdcic_browser_authorized_readback_v1",
                            "source_profile_id": "GUANGDONG-GDCIC-HOME",
                            "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                            "authorized_session_input_ready": True,
                            "authorization_readiness_state_counts": {
                                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED": 1,
                            },
                        },
                        "field_match_summary": {
                            "source_specific_records": [
                                {
                                    "record_type": "project_manager_change_browser_authorized_record",
                                    "source_specific_adapter_id": "guangdong_gdcic_browser_authorized_readback_v1",
                                    "source_profile_id": "GUANGDONG-GDCIC-HOME",
                                    "project_name_probe": "Browser project manager change",
                                    "company_name_probe": "广州测试建设有限公司",
                                    "project_manager_name_probe": "张三",
                                    "original_project_manager_name_probe": "张三",
                                    "new_project_manager_name_probe": "李四",
                                    "change_date_probe": "2026-01-15",
                                    "project_manager_change_release_window_interpretation": (
                                        "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"
                                    ),
                                    "query_miss_is_not_clearance": True,
                                    "readback_is_line_clue_not_final_conclusion": True,
                                }
                            ]
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                        "query_miss_is_not_clearance": True,
                    }
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 1,
                "adapter_result_state_counts": {"MATCHED": 1},
                "release_evidence_downstream_abcd_grade_counts": {
                    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1
                },
            },
        },
    )


def _write_live_style_release_field_query_result(root: Path) -> None:
    _write_json(
        root / "guangdong-local-field-query-probe-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-LIVE-STYLE-1",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-TASK-LIVE-1",
                        "project_id": "PROJ-LIVE-AUTH",
                        "project_name": "Live auth project",
                        "adapter_result_state": "NEEDS_BROWSER",
                        "downstream_release_evidence_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                        "field_summary": {
                            "authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT",
                            "authorized_session_input_ready": False,
                            "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                            "required_runtime_capability": "AUTHORIZED_SESSION_STORAGE_STATE_OR_USER_DATA_DIR",
                            "operator_next_actions": [
                                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                                "do_not_treat_http_dynamic_stealthy_as_login_state_replacement",
                            ],
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 1,
                "release_evidence_downstream_abcd_grade_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 1},
            },
        },
    )


def _write_batch_closeout(root: Path, *, evidence_state_json: str | Path) -> None:
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-1",
                "closeout_records": [
                    {
                        "project_id": "PROJ-D",
                        "project_name": "D project",
                        "engineering_work_lane": "construction_or_epc",
                        "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                        "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
                        "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
                        "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
                        "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
                        "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                        "stage6_ready": True,
                        "stage7_commercial_input_allowed": False,
                        "review_reasons": ["original_notice_backtrace_no_a_signal"],
                        "source_refs": {"evidence_state_json": str(evidence_state_json)},
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                        "query_miss_is_not_clearance": True,
                    }
                ],
                "summary": {"project_count": 1},
            },
            "summary": {"project_count": 1},
        },
    )


def _write_terminal_batch_closeout(root: Path, *, evidence_state_json: str | Path) -> None:
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-TERMINAL",
                "closeout_records": [
                    {
                        "project_id": "PROJ-D",
                        "project_name": "D project",
                        "engineering_work_lane": "construction_or_epc",
                        "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                        "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
                        "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
                        "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
                        "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
                        "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                        "stage6_ready": True,
                        "stage7_commercial_input_allowed": False,
                        "pending_adapter_job_count": 0,
                        "review_reasons": ["original_notice_backtrace_no_a_signal"],
                        "source_refs": {"evidence_state_json": str(evidence_state_json)},
                        "continuation_lineage": {
                            "state_after_adapter_job_count": 0,
                            "final_original_backtrace_continuation_recommended_next_action": (
                                "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
                            ),
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                        "query_miss_is_not_clearance": True,
                    }
                ],
                "summary": {"project_count": 1},
            },
            "summary": {"project_count": 1},
        },
    )


def _write_release_terminal_marker_batch_closeout(root: Path, *, evidence_state_json: str | Path) -> None:
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-RELEASE-TERMINAL",
                "closeout_records": [
                    {
                        "project_id": "PROJ-REL-TERM",
                        "project_name": "Release terminal project",
                        "engineering_work_lane": "construction_or_epc",
                        "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
                        "evidence_grade": "A_STRONG_SIGNAL",
                        "evidence_signal_source": "P13B_OVERLAP_TRIAGE",
                        "batch_triage_bucket": "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
                        "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
                        "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY",
                        "stage6_ready": True,
                        "stage7_commercial_input_allowed": False,
                        "review_reasons": ["release_evidence_query_already_terminal_backfilled"],
                        "source_refs": {"evidence_state_json": str(evidence_state_json)},
                        "terminal_closeout_markers": [
                            {
                                "task_family": "release_evidence_query",
                                "marker_state": "MATCHED",
                                "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                            }
                        ],
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                        "query_miss_is_not_clearance": True,
                    }
                ],
                "summary": {"project_count": 1},
            },
            "summary": {"project_count": 1},
        },
    )


def _write_combo_batch_closeout(root: Path, *, evidence_state_json: str | Path) -> None:
    batch_path = root / "evidence-batch-closeout-v1.json"
    source_refs = {
        "evidence_state_json": str(evidence_state_json),
        "evidence_batch_closeout_json": str(batch_path),
        "p13b_operational_closeout_root": str(root.parent / "p13b-operational-closeout-v1"),
    }
    owner_fields = {
        "assigned_owner": "卡卡罗特",
        "assigned_owner_role": "single_operator",
        "reviewer": "卡卡罗特",
        "reviewer_role": "single_operator",
        "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
    }
    records = [
        {
            "project_id": "PROJ-P13B-DISPATCH",
            "project_name": "P13B ready dispatch project",
            **owner_fields,
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_SIGNAL",
            "evidence_signal_source": "P13B_OVERLAP_TRIAGE",
            "batch_triage_bucket": "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
            "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "review_reasons": ["p13b_overlap_signal_ready_for_release_evidence_query"],
            "source_refs": source_refs,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-P13B-HOLD",
            "project_name": "P13B operator hold project",
            **owner_fields,
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "evidence_signal_source": "P13B_OVERLAP_TRIAGE",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "p13b_followup_terminal_state": "SOURCE_LIMIT_DEFERRED",
            "review_reasons": ["p13b_followup_budget_deferred_operator_hold"],
            "source_refs": {
                **source_refs,
                "p13b_operational_closeout_json": str(root / "p13b-operational-closeout-v1.json"),
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-REL-TERM",
            "project_name": "Terminal release project",
            **owner_fields,
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_SIGNAL",
            "evidence_signal_source": "P13B_OVERLAP_TRIAGE",
            "batch_triage_bucket": "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
            "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "review_reasons": ["release_evidence_query_already_terminal_backfilled"],
            "source_refs": source_refs,
            "terminal_closeout_markers": [
                {
                    "task_family": "release_evidence_query",
                    "marker_state": "MATCHED",
                    "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                }
            ],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-ORIG-RETRY",
            "project_name": "Original readback retry project",
            **owner_fields,
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "pending_adapter_job_count": 1,
            "review_reasons": ["original_notice_readback_retry_scope_available"],
            "source_refs": {"evidence_state_json": str(evidence_state_json)},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-ORIG-SUSPEND",
            "project_name": "Original readback suspended project",
            **owner_fields,
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "pending_adapter_job_count": 0,
            "review_reasons": ["original_notice_backtrace_no_a_signal"],
            "source_refs": {"evidence_state_json": str(evidence_state_json)},
            "continuation_lineage": {
                "state_after_adapter_job_count": 0,
                "final_original_backtrace_continuation_recommended_next_action": (
                    "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
                ),
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    ]
    _write_json(
        batch_path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-COMBO",
                "closeout_records": records,
                "summary": {"project_count": len(records)},
            },
            "summary": {"project_count": len(records)},
        },
    )


def _write_combo_release_field_query_result(root: Path) -> None:
    owner_fields = {
        "assigned_owner": "卡卡罗特",
        "assigned_owner_role": "single_operator",
        "reviewer": "卡卡罗特",
        "reviewer_role": "single_operator",
        "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
    }
    _write_json(
        root / "guangdong-local-field-query-probe-v1.json",
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-COMBO",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-COMBO-READY",
                        "project_id": "PROJ-FIELD-READY",
                        "project_name": "Release field ready project",
                        **owner_fields,
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "adapter_result_state": "MATCHED",
                        "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                        "field_summary": {
                            "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                            "gdcic_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
                            "gdcic_publicity_period_readback_ready_count": 1,
                            "sample_person_names": ["王先耀"],
                            "sample_certificate_nos": ["粤1332006200810171"],
                            "sample_permit_codes": ["441900202206061001"],
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                    {
                        "field_query_task_id": "GD-FIELD-COMBO-AUTH",
                        "project_id": "PROJ-FIELD-AUTH",
                        "project_name": "Authorization hold project",
                        **owner_fields,
                        "source_profile_id": "GUANGDONG-GDCIC-HOME",
                        "adapter_result_state": "NEEDS_BROWSER",
                        "downstream_release_evidence_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                        "field_summary": {
                            "authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT",
                            "authorized_session_input_ready": False,
                            "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                            "operator_next_actions": [
                                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                                "do_not_treat_http_dynamic_stealthy_as_login_state_replacement",
                            ],
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                    {
                        "field_query_task_id": "GD-FIELD-COMBO-NOTFOUND",
                        "project_id": "PROJ-FIELD-NOTFOUND",
                        "project_name": "Not found project",
                        **owner_fields,
                        "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
                        "adapter_result_state": "NOT_FOUND",
                        "downstream_release_evidence_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                        "field_summary": {
                            "operator_next_actions": [
                                "record_not_found_without_clearance_claim_or_try_project_local_authority"
                            ],
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 3,
                "adapter_result_state_counts": {
                    "MATCHED": 1,
                    "NEEDS_BROWSER": 1,
                    "NOT_FOUND": 1,
                },
                "release_evidence_downstream_abcd_grade_counts": {
                    "B_ENHANCEMENT_OFFICIAL_READBACK": 1,
                    "D_INSUFFICIENT_OR_BLOCKED_READBACK": 2,
                },
            },
        },
    )


def _write_stage5_calibration_sample_table(root: Path) -> None:
    _write_json(
        root / "stage5-calibration-sample-table.json",
        {
            "summary": {
                "stage5_calibration_sample_count": 1,
                "stage5_calibration_review_bucket_counts": {"POTENTIAL_FALSE_POSITIVE_REVIEW": 1},
            },
            "records": [
                {
                    "stage5_calibration_sample_id": "STAGE5-CAL-SAMPLE-1",
                    "project_id": "PROJ-STAGE5-CAL",
                    "project_name": "Stage5 calibration project",
                    "stage5_rule_gate_status": "PASS",
                    "stage5_evidence_gate_status": "PASS",
                    "stage5_gate_result_state": "STAGE5_GATE_PASS",
                    "stage5_calibration_review_bucket": "POTENTIAL_FALSE_POSITIVE_REVIEW",
                    "stage5_abcd_calibration_bucket": "B_PUBLIC_READBACK_REVIEW_REQUIRED",
                    "stage5_calibration_evidence_strength": "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED",
                    "stage5_calibration_review_family": "manual_public_readback_review",
                    "stage5_calibration_review_reasons": [
                        "STAGE5_PASS_WITH_ACTIVE_STAGE4_GAP",
                        "MISSING_RELEASE_EVIDENCE_FIELD:contract_public_info",
                    ],
                    "calibration_truth_label_required": True,
                    "suggested_calibration_action": "review_truth_label_before_rule_relaxation_or_tightening",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ],
        },
    )


def _arg(argv: list[str], name: str) -> str:
    index = argv.index(name)
    return argv[index + 1]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fingerprint_without_manifest_sha(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
