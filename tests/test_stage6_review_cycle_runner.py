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

import storage.stage6_review_cycle_runner as cycle_runner  # noqa: E402
import tests.test_stage6_review_loop_runner as loop_runner_test_support  # noqa: E402
from storage.stage6_review_cycle_runner import (  # noqa: E402
    _bootstrap_source_registry_rows,
    run_stage6_review_cycle_runner,
)
from storage.stage6_review_loop_operator_projection import load_stage6_review_loop_operator_projection  # noqa: E402


class Stage6ReviewCycleRunnerTests(unittest.TestCase):
    def test_bootstrap_handler_registry_is_dispatchable(self) -> None:
        source_registry = _bootstrap_source_registry_rows()
        dispatch_map = cycle_runner._bootstrap_handler_dispatch_map()

        self.assertTrue(dispatch_map)
        self.assertEqual(
            {item["handler_kind"] for item in source_registry},
            set(dispatch_map.keys()),
        )
        self.assertTrue(
            all(item["handler_kind"] in dispatch_map for item in source_registry)
        )

    def test_missing_bootstrap_registry_blocks_cycle_machine_readably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            original_registry = cycle_runner.DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH
            cycle_runner.DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH = Path(
                root / "missing-stage6-bootstrap-registry.yaml"
            )
            try:
                result = run_stage6_review_cycle_runner(
                    batch_closeout_root=root / "closeout",
                    output_root=root / "out",
                    created_at="2026-05-23T00:00:00+08:00",
                )
            finally:
                cycle_runner.DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH = original_registry

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(
                result["summary"]["stage6_review_cycle_bootstrap_registry_state"],
                "BOOTSTRAP_REGISTRY_MISSING_OR_INVALID",
            )
            self.assertEqual(
                result["summary"]["stage6_review_cycle_bootstrap_source_kind"],
                "BOOTSTRAP_REGISTRY_BLOCKED",
            )
            self.assertEqual(
                result["summary"]["runtime_blocker_next_subqueue_input_state"],
                "BOOTSTRAP_REGISTRY_BLOCKED",
            )
            self.assertIn(
                "stage6_review_cycle_bootstrap_registry_missing_or_invalid",
                result["blocking_reasons"],
            )
            self.assertEqual(
                result["summary"]["stage6_review_cycle_bootstrap_registry_validation_error_count"],
                1,
            )
            self.assertEqual(
                result["manifest"]["stage6_review_cycle_bootstrap_registry_validation_error_records"],
                [
                    {
                        "source_index": None,
                        "source_kind": "BOOTSTRAP_REGISTRY",
                        "field": "registry_path",
                        "error_code": "registry_missing_or_invalid",
                        "invalid_value": str(root / "missing-stage6-bootstrap-registry.yaml"),
                        "runtime_layer": "schema/contract:stage6_review_cycle_bootstrap_registry",
                        "blocking_reason": "stage6_review_cycle_bootstrap_registry_missing_or_invalid",
                        "required_input": ["valid_stage6_review_cycle_bootstrap_registry_yaml"],
                        "operator_next_action": "restore_stage6_review_cycle_bootstrap_registry_yaml_then_rerun_cycle",
                    }
                ],
            )
            self.assertEqual(result["manifest"]["stage6_review_cycle_bootstrap_source_registry"], [])
            self.assertEqual(result["manifest"]["stage6_review_cycle_bootstrap_candidate_registry"], [])
            self.assertEqual(result["manifest"]["stage6_review_cycle_bootstrap_handler_registry"], [])
            projection_table = result["manifest"]["operator_projection_status_table"]
            self.assertEqual(
                projection_table["summary"]["operator_projection_source"],
                "stage6_review_cycle_bootstrap_registry_blocker",
            )
            self.assertEqual(projection_table["summary"]["project_status_record_count"], 1)
            system_row = projection_table["records"][0]
            self.assertEqual(
                system_row["project_id"],
                "SYSTEM-STAGE6-REVIEW-CYCLE-BOOTSTRAP-REGISTRY",
            )
            self.assertEqual(
                system_row["loop_terminal_state"],
                "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
            )
            self.assertEqual(
                system_row["next_recommended_action"],
                "restore_stage6_review_cycle_bootstrap_registry_yaml_then_rerun_cycle",
            )
            self.assertEqual(
                system_row["runtime_blocker_ledger_state_counts"],
                {"STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_BLOCKED": 1},
            )
            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json"
            )
            self.assertEqual(projection["surface_state"], "MANUAL_REVIEW_HOLD")
            projected_row = projection["project_status_rows"][0]
            self.assertEqual(
                projected_row["blocker_reason_label"],
                "Stage6 cycle bootstrap registry 缺失或不可解析，需先恢复 registry 再续跑。",
            )
            self.assertEqual(
                projected_row["runtime_blocker_ledger_records"][0]["operator_next_action_label"],
                "恢复 Stage6 cycle bootstrap registry YAML 后再重跑。",
            )

    def test_invalid_bootstrap_registry_entries_block_cycle_machine_readably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            bad_registry = root / "bad-stage6-bootstrap-registry.yaml"
            bad_registry.write_text(
                json.dumps(
                    {
                        "registry_id": "bad-stage6-bootstrap-registry",
                        "registry_version": 1,
                        "sources": [
                            {
                                "source_kind": "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON",
                                "source_ref_key": "runtime_blocker_next_subqueue_json",
                                "handler_kind": "not_a_real_handler",
                            },
                            {
                                "source_kind": "STAGE6_REVIEW_LOOP_JSON",
                                "handler_kind": "stage6_loop_runner_artifact",
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            original_registry = cycle_runner.DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH
            cycle_runner.DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH = bad_registry
            try:
                result = run_stage6_review_cycle_runner(
                    batch_closeout_root=root / "closeout",
                    output_root=root / "out",
                    created_at="2026-05-23T00:00:00+08:00",
                )
            finally:
                cycle_runner.DEFAULT_STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_PATH = original_registry

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(
                result["summary"]["stage6_review_cycle_bootstrap_registry_state"],
                "BOOTSTRAP_REGISTRY_SCHEMA_INVALID",
            )
            self.assertEqual(
                result["summary"]["stage6_review_cycle_bootstrap_source_kind"],
                "BOOTSTRAP_REGISTRY_BLOCKED",
            )
            self.assertIn(
                "stage6_review_cycle_bootstrap_registry_schema_invalid",
                result["blocking_reasons"],
            )
            self.assertEqual(
                result["manifest"]["stage6_review_cycle_bootstrap_registry_validation_errors"],
                [
                    "source[0]:unknown_handler_kind:not_a_real_handler",
                    "source[1]:missing_fields:source_ref_key",
                ],
            )
            self.assertEqual(
                result["summary"]["stage6_review_cycle_bootstrap_registry_validation_error_count"],
                2,
            )
            self.assertEqual(
                result["manifest"]["stage6_review_cycle_bootstrap_registry_validation_error_records"],
                [
                    {
                        "source_index": 0,
                        "source_kind": "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON",
                        "field": "handler_kind",
                        "error_code": "unknown_handler_kind",
                        "invalid_value": "not_a_real_handler",
                        "runtime_layer": "schema/contract:stage6_review_cycle_bootstrap_registry",
                        "blocking_reason": "stage6_review_cycle_bootstrap_registry_schema_invalid",
                        "required_input": ["valid_stage6_review_cycle_bootstrap_registry_yaml"],
                        "operator_next_action": "fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                    },
                    {
                        "source_index": 1,
                        "source_kind": "STAGE6_REVIEW_LOOP_JSON",
                        "field": "source_ref_key",
                        "error_code": "missing_required_field",
                        "invalid_value": "",
                        "runtime_layer": "schema/contract:stage6_review_cycle_bootstrap_registry",
                        "blocking_reason": "stage6_review_cycle_bootstrap_registry_schema_invalid",
                        "required_input": ["valid_stage6_review_cycle_bootstrap_registry_yaml"],
                        "operator_next_action": "fix_stage6_review_cycle_bootstrap_registry_schema_then_rerun_cycle",
                    },
                ],
            )
            projection_table = result["manifest"]["operator_projection_status_table"]
            self.assertEqual(
                projection_table["summary"]["operator_projection_source"],
                "stage6_review_cycle_bootstrap_registry_blocker",
            )
            self.assertEqual(projection_table["summary"]["project_status_record_count"], 1)
            self.assertEqual(
                projection_table["records"][0]["runtime_blocker_ledger_state_counts"],
                {"STAGE6_REVIEW_CYCLE_BOOTSTRAP_REGISTRY_BLOCKED": 2},
            )

    def test_bootstrap_resolver_uses_handler_dispatch_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "manual-next-subqueue.json"
            source_path.write_text("{}", encoding="utf-8")

            original_dispatch_map = cycle_runner._bootstrap_handler_dispatch_map
            calls: list[tuple[str, Path]] = []

            def fake_dispatch_map():
                return {
                    "next_subqueue_json": lambda **kwargs: (
                        calls.append((kwargs["candidate"]["source_kind"], kwargs["source_path"])) or {
                            "table_kind": "runtime_blocker_next_subqueue_table_v1",
                            "summary": {"next_subqueue_record_count": 99},
                            "records": [],
                        },
                        "SENTINEL_STATE",
                        "",
                        kwargs["source_path"],
                        None,
                        kwargs["candidate"]["source_kind"],
                    )
                }

            cycle_runner._bootstrap_handler_dispatch_map = fake_dispatch_map
            try:
                result = cycle_runner._resolve_runtime_blocker_next_subqueue_input(
                    candidates=[
                        {
                            "source_kind": "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON",
                            "handler_kind": "next_subqueue_json",
                            "source_path": source_path,
                        }
                    ],
                    stage6_loop_output_root=root / "loop",
                    derived_output_path=root / "derived.json",
                )
            finally:
                cycle_runner._bootstrap_handler_dispatch_map = original_dispatch_map

            table, state, blocker, effective_path, effective_status_path, source_kind = result
            self.assertEqual(state, "SENTINEL_STATE")
            self.assertEqual(table["summary"]["next_subqueue_record_count"], 99)
            self.assertEqual(blocker, "")
            self.assertEqual(effective_path, source_path)
            self.assertIsNone(effective_status_path)
            self.assertEqual(source_kind, "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON")
            self.assertEqual(calls, [("RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON", source_path)])

    def test_builds_next_stage6_dispatch_cycle_with_dry_run_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_input_closeout_project_count"], 4)
            self.assertEqual(summary["stage6_project_fact_count"], 3)
            self.assertEqual(summary["stage6_review_action_plan_count"], 3)
            self.assertEqual(summary["dispatch_task_count"], 3)
            self.assertEqual(summary["dispatch_runner_group_count"], 3)
            self.assertEqual(summary["dispatch_runner_dry_run_ready_group_count"], 3)
            self.assertEqual(
                summary["stage6_review_action_family_counts"],
                {
                    "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW": 1,
                    "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW": 1,
                    "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW": 1,
                },
            )
            self.assertTrue((root / "out" / "1" / "stage6-fact-package-v1.json").exists())
            self.assertTrue((root / "out" / "2" / "stage6-review-action-dispatch-v1.json").exists())
            self.assertTrue((root / "out" / "3" / "stage6-review-action-dispatch-runner-v1.json").exists())

    def test_execute_dispatch_uses_dispatch_runner_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                execute_dispatch=True,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 3)
            self.assertEqual(result["summary"]["dispatch_runner_executed_success_group_count"], 3)
            self.assertTrue(all(call[0][0] == "pwsh" for call in calls))

    def test_terminal_manual_only_cycle_does_not_call_dispatch_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_terminal_manual_only_batch_closeout(root / "closeout")
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                execute_dispatch=True,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(calls, [])
            summary = result["summary"]
            self.assertEqual(summary["dispatch_task_count"], 0)
            self.assertEqual(summary["manual_only_action_plan_count"], 1)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "stage6_dispatch_has_no_automated_tasks")
            self.assertTrue(summary["stage6_dispatch_runner_safe"])

    def test_consumes_runtime_blocker_next_subqueue_artifact_as_controller_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_terminal_manual_only_batch_closeout(root / "closeout")
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "READY")
            self.assertEqual(summary["runtime_blocker_next_subqueue_record_count"], 4)
            self.assertEqual(
                summary["runtime_blocker_next_subqueue_route_counts"],
                {"browser_worker": 2, "operator_action": 1, "retry": 1},
            )
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 4)
            self.assertEqual(
                summary["runtime_blocker_controller_route_state_counts"],
                {
                    "OPERATOR_ACTION_ROUTE_RECORDED": 1,
                    "WAIT_FOR_BROWSER_WORKER_OR_AUTHORIZED_SESSION_INPUT": 2,
                    "WAIT_FOR_RETRY_REOPEN_INPUT_OR_BUDGET": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_controller_dispatch_worker_family_counts"],
                {"browser_worker": 2, "operator_action": 1, "retry_policy": 1},
            )
            self.assertEqual(summary["runtime_blocker_controller_automated_worker_dispatch_allowed_count"], 1)
            self.assertEqual(summary["runtime_blocker_controller_dispatch_task_count"], 4)
            self.assertEqual(
                summary["runtime_blocker_controller_dispatch_readiness_state_counts"],
                {
                    "BLOCKED_REQUIRED_INPUT_OR_WORKER_SPEC_MISSING": 1,
                    "OPERATOR_ACTION_RECORDED_NO_WORKER_DISPATCH": 1,
                    "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH": 1,
                    "RETRY_REOPEN_INPUT_REQUIRED": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_controller_dispatch_route_counts"],
                {"browser_worker": 2, "operator_action": 1, "retry": 1},
            )
            self.assertEqual(summary["runtime_blocker_controller_dispatch_ready_count"], 1)
            self.assertEqual(
                summary["runtime_blocker_controller_dispatch_blocking_reason_counts"],
                {"required_input_missing_or_operator_action_pending": 2},
            )
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 4)
            self.assertEqual(
                summary["runtime_blocker_dispatch_runner_execution_state_counts"],
                {"DRY_RUN_READY": 1, "WORKER_DISPATCH_NOT_READY_RECORDED": 3},
            )
            self.assertEqual(
                summary["runtime_blocker_dispatch_runner_readback_state_counts"],
                {
                    "WAITING_FOR_CONTROLLED_WORKER_EXECUTION": 1,
                    "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED": 3,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_dispatch_runner_closeout_state_counts"],
                {
                    "KEPT_IN_RUNTIME_BLOCKER_SUBQUEUE": 3,
                    "WAITING_FOR_CONTROLLED_WORKER_EXECUTION": 1,
                },
            )
            self.assertEqual(summary["runtime_blocker_dispatch_runner_dry_run_ready_count"], 1)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_followup_task_count"], 1)
            self.assertEqual(
                summary["runtime_blocker_dispatch_runner_followup_task_type_counts"],
                {"RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT": 1},
            )
            controller_queue_path = root / "out" / "stage6-review-cycle-runtime-blocker-controller-queue.json"
            self.assertTrue(controller_queue_path.exists())
            controller_dispatch_path = root / "out" / "stage6-review-cycle-runtime-blocker-controller-dispatch-tasks.json"
            self.assertTrue(controller_dispatch_path.exists())
            dispatch_runner_path = root / "out" / "stage6-review-cycle-runtime-blocker-controller-dispatch-runner.json"
            self.assertTrue(dispatch_runner_path.exists())
            followup_queue_path = root / "out" / "stage6-review-cycle-runtime-blocker-worker-followup-queue.json"
            self.assertTrue(followup_queue_path.exists())
            controller_queue = json.loads(controller_queue_path.read_text(encoding="utf-8"))
            controller_dispatch = json.loads(controller_dispatch_path.read_text(encoding="utf-8"))
            dispatch_runner = json.loads(dispatch_runner_path.read_text(encoding="utf-8"))
            followup_queue = json.loads(followup_queue_path.read_text(encoding="utf-8"))
            self.assertEqual(controller_queue["summary"]["controller_queue_record_count"], 4)
            self.assertEqual(controller_dispatch["summary"]["controller_dispatch_task_count"], 4)
            self.assertEqual(
                dispatch_runner["summary"]["runtime_blocker_dispatch_runner_task_count"],
                4,
            )
            self.assertEqual(followup_queue["summary"]["followup_task_count"], 1)
            self.assertEqual(
                followup_queue["summary"]["followup_task_type_counts"],
                {"RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT": 1},
            )
            controller_records = {
                (record["project_id"], record["subqueue_route"]): record
                for record in controller_queue["records"]
            }
            dispatch_records = {
                (record["project_id"], record["dispatch_route"]): record
                for record in controller_dispatch["records"]
            }
            auth_record = controller_records[("PROJ-FIELD-AUTH", "browser_worker")]
            self.assertTrue(auth_record["controller_consumable"])
            self.assertEqual(auth_record["dispatch_worker_family"], "browser_worker")
            self.assertEqual(
                auth_record["controller_next_action"],
                "route_to_browser_worker_when_authorized_session_or_same_session_input_available",
            )
            self.assertEqual(
                auth_record["required_input"],
                ["authorized_browser_storage_state_or_user_data_dir"],
            )
            ready_dispatch_record = dispatch_records[("PROJ-FIELD-BROWSER-READY", "browser_worker")]
            self.assertEqual(
                ready_dispatch_record["dispatch_readiness_state"],
                "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
            )
            self.assertEqual(
                ready_dispatch_record["recommended_script"],
                "scripts/build-gdcic-browser-authorized-readback-v1.ps1",
            )
            self.assertIn("-ReleaseEvidenceAdapterPlanJson", ready_dispatch_record["recommended_command_argv"])
            self.assertEqual(ready_dispatch_record["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertFalse(ready_dispatch_record["live_execution_enabled"])
            self.assertTrue(ready_dispatch_record["requires_operator_approval_before_execution"])
            self.assertEqual(
                result["manifest"]["runtime_blocker_subqueue_controller_table"]["summary"],
                controller_queue["summary"],
            )
            self.assertEqual(
                result["manifest"]["runtime_blocker_controller_dispatch_table"]["summary"],
                controller_dispatch["summary"],
            )
            self.assertEqual(
                result["manifest"]["runtime_blocker_controller_dispatch_runner"]["summary"],
                dispatch_runner["summary"],
            )
            self.assertEqual(
                result["manifest"]["runtime_blocker_worker_followup_queue"]["summary"],
                followup_queue["summary"],
            )
            self.assertEqual(
                result["manifest"]["source_runtime_blocker_next_subqueue_json"],
                str(next_subqueue_json),
            )

    def test_explicit_runtime_blocker_next_subqueue_takes_precedence_over_batch_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON")
            self.assertEqual(summary["stage6_review_cycle_input_mode"], "RUNTIME_BLOCKER_SUBQUEUE_ONLY")
            self.assertEqual(summary["dispatch_task_count"], 0)
            self.assertEqual(summary["stage6_review_action_plan_count"], 0)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])

    def test_standalone_runtime_blocker_queue_without_batch_closeout_builds_controller_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "READY")
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 4)
            self.assertEqual(summary["runtime_blocker_controller_dispatch_task_count"], 4)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 4)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["operator_projection_status_table"]["summary"]["project_status_record_count"], 2)
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-FIELD-BROWSER-READY"]["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")
            self.assertEqual(
                status_records["PROJ-FIELD-BROWSER-READY"]["next_recommended_action"],
                "run_controlled_dispatch_task_or_record_operator_skip",
            )
            self.assertEqual(status_records["PROJ-FIELD-AUTH"]["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")
            self.assertEqual(
                status_records["PROJ-FIELD-AUTH"]["runtime_blocker_worker_followup_task_type_counts"],
                {"RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT": 1},
            )
            self.assertEqual(
                status_records["PROJ-FIELD-AUTH"]["runtime_blocker_ledger_state_counts"],
                {"AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION": 1},
            )
            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json"
            )
            self.assertEqual(projection["surface_state"], "ACTION_READY")
            projected = {row["project_id"]: row for row in projection["project_status_rows"]}
            self.assertEqual(projected["PROJ-FIELD-BROWSER-READY"]["owner_status_label"], "等待受控执行")
            self.assertTrue(projected["PROJ-FIELD-BROWSER-READY"]["automated_dispatch_available"])
            self.assertIn("阻断 worker 已产出", projected["PROJ-FIELD-AUTH"]["owner_status_label"])
            self.assertFalse(projected["PROJ-FIELD-AUTH"]["automated_dispatch_available"])

    def test_derives_runtime_blocker_next_subqueue_from_stage6_status_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            status_json = _write_stage6_review_loop_status_table_for_runtime_blockers(root / "status-table")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                stage6_review_loop_status_json=status_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "STAGE6_REVIEW_LOOP_STATUS_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_STATUS_TABLE")
            self.assertEqual(summary["runtime_blocker_next_subqueue_record_count"], 4)
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 4)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 4)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(
                result["manifest"]["source_stage6_review_loop_status_json"],
                str(status_json),
            )
            self.assertTrue(
                str(result["manifest"]["source_runtime_blocker_next_subqueue_json"]).endswith(
                    "stage6-review-cycle-runtime-blocker-next-subqueues.json"
                )
            )
            derived_table_path = root / "out" / "stage6-review-cycle-runtime-blocker-next-subqueues.json"
            self.assertTrue(derived_table_path.exists())
            derived_table = json.loads(derived_table_path.read_text(encoding="utf-8"))
            self.assertEqual(
                derived_table["summary"]["subqueue_route_counts"],
                {"browser_worker": 2, "operator_action": 1, "retry": 1},
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-FIELD-BROWSER-READY"]["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")
            self.assertEqual(status_records["PROJ-FIELD-AUTH"]["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")

    def test_consumes_stage6_review_loop_runner_artifact_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            loop_json = _write_stage6_review_loop_runner_artifact(root / "loop-runner")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                stage6_review_loop_json=loop_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "STAGE6_REVIEW_LOOP_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "IMPORTED_FROM_STAGE6_LOOP_RUNNER_ARTIFACT")
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 4)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 4)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["source_stage6_review_loop_json"], str(loop_json))
            self.assertEqual(result["manifest"]["source_stage6_review_loop_status_json"], str(loop_json))
            self.assertTrue(
                str(result["manifest"]["source_runtime_blocker_next_subqueue_json"]).endswith(
                    "stage6-review-cycle-runtime-blocker-next-subqueues.json"
                )
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-FIELD-BROWSER-READY"]["loop_terminal_state"], "WAITING_FOR_DISPATCH_EXECUTION")
            self.assertEqual(status_records["PROJ-FIELD-AUTH"]["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")

    def test_bootstrap_resolution_trace_prefers_higher_priority_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            loop_json = _write_stage6_review_loop_runner_artifact(root / "loop-runner")
            stage16_json = _write_standalone_stage16_p13b_continuation(root / "p13b-continuation")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                stage6_review_loop_json=loop_json,
                stage16_p13b_continuation_json=stage16_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["stage6_review_cycle_bootstrap_source_kind"], "STAGE6_REVIEW_LOOP_JSON")
            self.assertEqual(result["summary"]["stage6_review_cycle_bootstrap_selected_handler_kind"], "stage6_loop_runner_artifact")
            self.assertEqual(
                result["manifest"]["stage6_review_cycle_bootstrap_registry_id"],
                "stage6-review-cycle-bootstrap-registry-v1",
            )
            self.assertEqual(
                result["manifest"]["stage6_review_cycle_bootstrap_registry_version"],
                1,
            )
            self.assertTrue(
                str(result["manifest"]["stage6_review_cycle_bootstrap_registry_path"]).endswith(
                    "control\\stage6_review_cycle_bootstrap_registry.yaml"
                )
            )
            trace = result["manifest"]["stage6_review_cycle_bootstrap_resolution_trace"]
            by_kind = {item["source_kind"]: item for item in trace}
            self.assertTrue(by_kind["STAGE6_REVIEW_LOOP_JSON"]["provided"])
            self.assertTrue(by_kind["STAGE6_REVIEW_LOOP_JSON"]["selected"])
            self.assertEqual(by_kind["STAGE6_REVIEW_LOOP_JSON"]["handler_kind"], "stage6_loop_runner_artifact")
            self.assertEqual(
                by_kind["STAGE6_REVIEW_LOOP_JSON"]["resolution_state"],
                "IMPORTED_FROM_STAGE6_LOOP_RUNNER_ARTIFACT",
            )
            self.assertTrue(by_kind["STAGE16_P13B_CONTINUATION_JSON"]["provided"])
            self.assertFalse(by_kind["STAGE16_P13B_CONTINUATION_JSON"]["selected"])
            self.assertEqual(by_kind["STAGE16_P13B_CONTINUATION_JSON"]["handler_kind"], "loop_runner_bootstrap")
            self.assertEqual(by_kind["STAGE16_P13B_CONTINUATION_JSON"]["loop_runner_arg"], "stage16_p13b_continuation_json")
            self.assertEqual(
                by_kind["STAGE16_P13B_CONTINUATION_JSON"]["resolution_state"],
                "SKIPPED_HIGHER_PRIORITY_SOURCE_SELECTED",
            )
            registry = result["manifest"]["stage6_review_cycle_bootstrap_source_registry"]
            self.assertEqual(
                [item["source_kind"] for item in registry],
                [
                    "RELEASE_FIELD_QUERY_JSON",
                    "RUNTIME_BLOCKER_NEXT_SUBQUEUE_JSON",
                    "STAGE6_REVIEW_LOOP_JSON",
                    "STAGE6_REVIEW_LOOP_STATUS_JSON",
                    "RELEASE_EVIDENCE_ADAPTER_PLAN_JSON",
                    "GDCIC_BROWSER_READBACK_JSON",
                    "ORIGINAL_BACKTRACE_CONTINUATION_JSON",
                    "STAGE16_P13B_CONTINUATION_JSON",
                    "STAGE5_CALIBRATION_SAMPLE_JSON",
                ],
            )
            self.assertEqual(registry[0]["priority_order"], 1)
            self.assertEqual(registry[1]["source_ref_key"], "runtime_blocker_next_subqueue_json")
            handler_registry = result["manifest"]["stage6_review_cycle_bootstrap_handler_registry"]
            self.assertEqual(handler_registry[0]["handler_kind"], "loop_runner_bootstrap")
            self.assertEqual(handler_registry[0]["loop_runner_arg"], "release_field_query_json")
            self.assertEqual(handler_registry[1]["handler_kind"], "next_subqueue_json")
            self.assertEqual(handler_registry[2]["handler_kind"], "stage6_loop_runner_artifact")
            self.assertEqual(handler_registry[3]["handler_kind"], "status_table_json")
            self.assertEqual(handler_registry[5]["handler_kind"], "derived_release_field_query")
            self.assertEqual(handler_registry[7]["loop_runner_arg"], "stage16_p13b_continuation_json")
            self.assertEqual(handler_registry[8]["loop_runner_arg"], "stage5_calibration_sample_json")
            candidate_registry = result["manifest"]["stage6_review_cycle_bootstrap_candidate_registry"]
            candidate_by_kind = {item["source_kind"]: item for item in candidate_registry}
            self.assertEqual(
                candidate_by_kind["STAGE6_REVIEW_LOOP_JSON"]["source_root_ref_key"],
                "stage6_review_loop_root",
            )
            self.assertEqual(
                candidate_by_kind["STAGE6_REVIEW_LOOP_JSON"]["default_filename"],
                "stage6-review-loop-runner-v1.json",
            )
            self.assertEqual(
                candidate_by_kind["RELEASE_FIELD_QUERY_JSON"]["source_root_ref_key"],
                "release_field_query_root",
            )
            self.assertEqual(
                candidate_by_kind["RELEASE_FIELD_QUERY_JSON"]["default_filename"],
                "guangdong-local-field-query-probe-v1.json",
            )
            self.assertEqual(
                candidate_by_kind["STAGE5_CALIBRATION_SAMPLE_JSON"]["source_root_ref_key"],
                "stage5_calibration_sample_root",
            )
            self.assertEqual(
                candidate_by_kind["STAGE5_CALIBRATION_SAMPLE_JSON"]["default_filename"],
                "stage5-calibration-sample-table.json",
            )

    def test_bootstraps_from_standalone_stage16_p13b_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stage16_json = _write_standalone_stage16_p13b_continuation(root / "p13b-continuation")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                stage16_p13b_continuation_json=stage16_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "STAGE16_P13B_CONTINUATION_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_LOOP_RUNNER")
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 4)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 4)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(
                result["manifest"]["source_stage16_p13b_continuation_json"],
                str(stage16_json),
            )
            self.assertTrue(
                str(result["manifest"]["source_stage6_review_loop_status_json"]).endswith(
                    "stage6-review-loop-project-status-table.json"
                )
            )
            self.assertTrue(
                str(result["manifest"]["source_runtime_blocker_next_subqueue_json"]).endswith(
                    "stage6-review-cycle-runtime-blocker-next-subqueues.json"
                )
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-P13B-HOLD"]["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")
            self.assertEqual(
                status_records["PROJ-P13B-HOLD"]["runtime_blocker_ledger_state_counts"],
                {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
            )

    def test_bootstraps_from_standalone_stage5_calibration_sample_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            loop_runner_test_support._write_stage5_calibration_sample_table(root / "stage5")
            stage5_json = root / "stage5" / "stage5-calibration-sample-table.json"

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                stage5_calibration_sample_json=stage5_json,
                output_root=root / "out",
                created_at="2026-05-24T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "STAGE5_CALIBRATION_SAMPLE_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_LOOP_RUNNER")
            self.assertEqual(summary["runtime_blocker_next_subqueue_record_count"], 0)
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 0)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(summary["stage5_calibration_sample_count"], 1)
            self.assertEqual(summary["stage5_calibration_truth_label_required_count"], 1)
            self.assertEqual(
                summary["stage5_abcd_calibration_counts"],
                {"B_PUBLIC_READBACK_REVIEW_REQUIRED": 1},
            )
            self.assertEqual(
                summary["stage5_calibration_evidence_strength_counts"],
                {"PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED": 1},
            )
            self.assertEqual(
                summary["stage5_calibration_review_family_counts"],
                {"manual_public_readback_review": 1},
            )
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["source_stage5_calibration_sample_json"], str(stage5_json))
            self.assertTrue(
                str(result["manifest"]["source_stage6_review_loop_status_json"]).endswith(
                    "stage6-review-loop-project-status-table.json"
                )
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(
                status_records["PROJ-STAGE5-CAL"]["loop_terminal_state"],
                "STAGE5_CALIBRATION_REVIEW_READY",
            )
            self.assertEqual(
                status_records["PROJ-STAGE5-CAL"]["next_recommended_action"],
                "review_stage5_calibration_samples_before_rule_change",
            )
            self.assertEqual(
                status_records["PROJ-STAGE5-CAL"]["stage5_abcd_calibration_bucket"],
                "B_PUBLIC_READBACK_REVIEW_REQUIRED",
            )
            self.assertEqual(
                status_records["PROJ-STAGE5-CAL"]["stage5_calibration_evidence_strength"],
                "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED",
            )
            self.assertEqual(
                status_records["PROJ-STAGE5-CAL"]["stage5_calibration_review_family"],
                "manual_public_readback_review",
            )

            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json"
            )
            projected = projection["project_status_rows"][0]
            self.assertEqual(projected["current_stage"], "Stage5_RULE_GATE_CALIBRATION")
            self.assertIn("潜在误放", projected["stage5_calibration_review_bucket_label"])

    def test_bootstraps_from_standalone_release_evidence_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            release_plan_json = _write_standalone_release_evidence_plan(root / "release-plan")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                release_evidence_adapter_plan_json=release_plan_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "RELEASE_EVIDENCE_ADAPTER_PLAN_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_LOOP_RUNNER")
            self.assertEqual(summary["runtime_blocker_next_subqueue_record_count"], 0)
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 0)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 0)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(
                result["manifest"]["source_release_evidence_adapter_plan_json"],
                str(release_plan_json),
            )
            self.assertTrue(
                str(result["manifest"]["source_stage6_review_loop_status_json"]).endswith(
                    "stage6-review-loop-project-status-table.json"
                )
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-REL-SUPPRESS"]["loop_terminal_state"], "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH")
            self.assertEqual(status_records["PROJ-REL-SUPPRESS"]["runtime_blocker_ledger_state_counts"], {})
            self.assertEqual(status_records["PROJ-REL-SUPPRESS"]["runtime_blocker_subqueue_routes"], [])

    def test_bootstraps_from_standalone_original_backtrace_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_json = _write_standalone_original_backtrace_continuation(root / "original-readback")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                original_backtrace_continuation_json=original_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "ORIGINAL_BACKTRACE_CONTINUATION_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_LOOP_RUNNER")
            self.assertEqual(summary["runtime_blocker_next_subqueue_record_count"], 3)
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 3)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 3)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(
                result["manifest"]["source_original_backtrace_continuation_json"],
                str(original_json),
            )
            self.assertTrue(
                str(result["manifest"]["source_stage6_review_loop_status_json"]).endswith(
                    "stage6-review-loop-project-status-table.json"
                )
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-ORIG-READY"]["loop_terminal_state"], "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK")
            self.assertEqual(status_records["PROJ-ORIG-RETRY"]["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")
            self.assertEqual(status_records["PROJ-ORIG-READY"]["runtime_blocker_ledger_state_counts"], {})
            self.assertEqual(
                status_records["PROJ-ORIG-RETRY"]["runtime_blocker_ledger_state_counts"],
                {"ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED": 1},
            )

    def test_bootstraps_from_standalone_release_field_query_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            field_query_json = _write_standalone_release_field_query_result(root / "field-query")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                release_field_query_json=field_query_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "RELEASE_FIELD_QUERY_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_LOOP_RUNNER")
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 3)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 3)
            self.assertEqual(summary["stage6_dispatch_runner_skip_reason"], "standalone_runtime_blocker_queue_only")
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(
                result["manifest"]["source_release_field_query_json"],
                str(field_query_json),
            )
            self.assertTrue(
                str(result["manifest"]["source_stage6_review_loop_status_json"]).endswith(
                    "stage6-review-loop-project-status-table.json"
                )
            )
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(status_records["PROJ-FIELD-AUTH"]["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")
            self.assertEqual(
                status_records["PROJ-FIELD-AUTH"]["runtime_blocker_ledger_state_counts"],
                {"AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION": 1},
            )

    def test_release_field_query_project_code_hit_and_not_found_are_projected_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            field_query_json = _write_standalone_release_field_query_project_code_mix(root / "field-query")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                release_field_query_json=field_query_json,
                output_root=root / "out",
                created_at="2026-05-24T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json"
            )
            rows = {record["project_id"]: record for record in projection["project_status_rows"]}
            matched = rows["PROJ-FIELD-PROJECT-CODE"]
            self.assertEqual(matched["release_field_query_state"], "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY")
            self.assertEqual(matched["release_field_query_adapter_result_state_counts"], {"MATCHED": 1})
            self.assertIn("项目编码：440100202605190001", matched["release_field_query_source_hit_summary_labels"][0])
            self.assertIn("公开源字段已有读回", matched["owner_status_label"])

            not_found = rows["PROJ-FIELD-NOTFOUND"]
            self.assertEqual(not_found["release_field_query_state"], "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW")
            self.assertEqual(not_found["release_field_query_adapter_result_state_counts"], {"NOT_FOUND": 1})
            self.assertEqual(
                not_found["runtime_blocker_ledger_state_counts"],
                {"NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED": 1},
            )
            self.assertIn(
                "record_not_found_without_clearance_claim_or_try_project_local_authority",
                not_found["release_field_query_operator_next_actions"],
            )
            text = json.dumps(projection, ensure_ascii=False)
            for forbidden in ("无风险", "无冲突", "确认本人", "无在建", "是不是本人"):
                self.assertNotIn(forbidden, text)

    def test_release_field_query_input_takes_precedence_over_stale_runtime_blocker_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")
            field_query_json = _write_standalone_release_field_query_result(root / "field-query")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                release_field_query_json=field_query_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "RELEASE_FIELD_QUERY_JSON")
            self.assertEqual(summary["runtime_blocker_next_subqueue_input_state"], "DERIVED_FROM_STAGE6_LOOP_RUNNER")
            self.assertEqual(summary["runtime_blocker_controller_queue_record_count"], 3)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 3)
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertEqual(set(status_records), {"PROJ-FIELD-AUTH"})

    def test_release_field_query_bootstrap_keeps_batch_closeout_only_projects_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            field_query_json = _write_standalone_release_field_query_result(root / "field-query")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                release_field_query_json=field_query_json,
                output_root=root / "out",
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertIn("PROJ-D", status_records)
            self.assertEqual(
                status_records["PROJ-D"]["loop_terminal_state"],
                "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
            )
            self.assertEqual(
                status_records["PROJ-D"]["stage6_fact_package_state"],
                "REVIEW_FACT_PACKAGE_READY",
            )
            self.assertIn("PROJ-FIELD-AUTH", status_records)
            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json"
            )
            projected_rows = {row["project_id"]: row for row in projection["project_status_rows"]}
            self.assertEqual(projected_rows["PROJ-D"]["input_refs"]["project_id"], "PROJ-D")
            self.assertTrue(
                any(
                    "evidence-batch-closeout-v1.json" in item.get("artifact_ref", "")
                    for item in projected_rows["PROJ-D"]["input_refs"]["marker_source_refs"]
                )
            )
            self.assertTrue(
                any("stage6-internal-evidence-pack.json" in item for item in projected_rows["PROJ-D"]["output_artifact_refs"])
            )

    def test_second_cycle_with_stale_queue_and_fresh_field_query_keeps_combo_batch_and_does_not_redispatch_closed_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            loop_runner_test_support._write_combo_batch_closeout(
                root / "closeout",
                evidence_state_json=state_json,
            )
            loop_runner_test_support._write_combo_release_field_query_result(root / "field-query")
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                release_field_query_root=root / "field-query",
                output_root=root / "out",
                created_at="2026-05-24T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["stage6_review_cycle_bootstrap_source_kind"], "RELEASE_FIELD_QUERY_JSON")
            status_records = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            self.assertNotIn("PROJ-FIELD-BROWSER-READY", status_records)
            self.assertEqual(
                status_records["PROJ-FIELD-READY"]["loop_terminal_state"],
                "RELEASE_FIELD_QUERY_REVIEW_READY",
            )
            self.assertIn("PROJ-FIELD-AUTH", status_records)
            self.assertIn("PROJ-FIELD-NOTFOUND", status_records)
            self.assertIn("PROJ-P13B-DISPATCH", status_records)
            self.assertIn("PROJ-P13B-HOLD", status_records)
            self.assertIn("PROJ-ORIG-SUSPEND", status_records)
            controller_queue_projects = {
                str(record.get("project_id") or "")
                for record in result["manifest"]["runtime_blocker_subqueue_controller_table"]["records"]
            }
            self.assertNotIn("PROJ-FIELD-BROWSER-READY", controller_queue_projects)
            self.assertIn("PROJ-FIELD-AUTH", controller_queue_projects)
            self.assertIn("PROJ-FIELD-NOTFOUND", controller_queue_projects)

    def test_runtime_blocker_dispatch_execution_output_feeds_field_query_followup_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_terminal_manual_only_batch_closeout(root / "closeout")
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                output_root = Path(argv[argv.index("-OutputRoot") + 1])
                release_plan_json = Path(argv[argv.index("-ReleaseEvidenceAdapterPlanJson") + 1])
                _write_gdcic_readback(
                    output_root / "gdcic-browser-authorized-readback-v1.json",
                    release_plan_json,
                )
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                output_root=root / "out",
                execute_runtime_blocker_dispatch=True,
                runtime_blocker_dispatch_max_tasks=1,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 1)
            summary = result["summary"]
            self.assertEqual(summary["runtime_blocker_dispatch_runner_executed_success_count"], 1)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_ready_for_field_query_backfill_count"], 1)
            self.assertEqual(summary["runtime_blocker_dispatch_runner_followup_task_count"], 2)
            self.assertEqual(
                summary["runtime_blocker_dispatch_runner_followup_task_type_counts"],
                {
                    "RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT": 1,
                    "RUN_GUANGDONG_LOCAL_FIELD_QUERY_WITH_GDCIC_BROWSER_READBACK": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_dispatch_runner_closeout_state_counts"],
                {
                    "KEPT_IN_RUNTIME_BLOCKER_SUBQUEUE": 3,
                    "READY_FOR_GUANGDONG_FIELD_QUERY_BACKFILL": 1,
                },
            )
            followup_queue = result["manifest"]["runtime_blocker_worker_followup_queue"]
            self.assertEqual(len(followup_queue["records"]), 2)
            followup = next(
                record
                for record in followup_queue["records"]
                if record["followup_task_type"] == "RUN_GUANGDONG_LOCAL_FIELD_QUERY_WITH_GDCIC_BROWSER_READBACK"
            )
            self.assertEqual(followup["formal_entrypoint_id"], "guangdong_local_field_query_probe")
            self.assertIn("scripts/run-guangdong-local-field-query-probe-v1.ps1", followup["recommended_command_argv"])
            self.assertIn("-GdcicBrowserReadbackJson", followup["recommended_command_argv"])
            self.assertIn("-ReleaseEvidenceAdapterPlanJson", followup["recommended_command_argv"])
            self.assertEqual(followup["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertFalse(followup["live_execution_enabled"])
            status_table_path = root / "out" / "stage6-review-loop-project-status-table.json"
            self.assertTrue(status_table_path.exists())
            status_table = json.loads(status_table_path.read_text(encoding="utf-8"))
            self.assertEqual(status_table["summary"]["runtime_blocker_worker_followup_count"], 2)
            browser_ready_row = next(
                record for record in status_table["records"] if record["project_id"] == "PROJ-FIELD-BROWSER-READY"
            )
            self.assertEqual(browser_ready_row["loop_terminal_state"], "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY")
            self.assertEqual(browser_ready_row["runtime_blocker_worker_followup_count"], 1)

            projection = load_stage6_review_loop_operator_projection(status_table_path=status_table_path)
            self.assertEqual(projection["summary"]["runtime_blocker_worker_followup_count"], 2)
            projected_row = next(
                row for row in projection["project_status_rows"] if row["project_id"] == "PROJ-FIELD-BROWSER-READY"
            )
            self.assertEqual(projected_row["project_id"], "PROJ-FIELD-BROWSER-READY")
            self.assertIn("阻断 worker 已产出", projected_row["owner_status_label"])
            self.assertIn("字段查询回灌", projected_row["owner_next_action_label"])
            self.assertEqual(
                projected_row["runtime_blocker_worker_followup_records"][0]["formal_entrypoint_id"],
                "guangdong_local_field_query_probe",
            )
            self.assertFalse(projected_row["runtime_blocker_worker_followup_records"][0]["live_execution_enabled"])

    def test_gdcic_browser_readback_artifact_is_derived_into_field_query_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            release_plan_json = _write_gdcic_release_plan_for_stage6_cycle(root / "release-plan")
            gdcic_readback_json = _write_gdcic_project_manager_change_readback(root / "gdcic-readback")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing-closeout",
                release_evidence_adapter_plan_json=release_plan_json,
                gdcic_browser_readback_json=gdcic_readback_json,
                output_root=root / "out",
                created_at="2026-05-24T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["stage6_review_cycle_bootstrap_source_kind"], "RELEASE_FIELD_QUERY_JSON")
            derived_path = Path(result["manifest"]["derived_release_field_query_from_gdcic_browser_readback_json"])
            self.assertTrue(derived_path.exists())
            self.assertEqual(result["manifest"]["source_gdcic_browser_readback_json"], str(gdcic_readback_json))
            rows = {
                record["project_id"]: record
                for record in result["manifest"]["operator_projection_status_table"]["records"]
            }
            row = rows["PROJ-GDCIC-PM-CHANGE"]
            self.assertEqual(row["release_field_query_state"], "RELEASE_FIELD_QUERY_REVIEW_READY")
            self.assertEqual(row["release_field_query_adapter_result_state_counts"], {"MATCHED": 1})
            self.assertEqual(
                row["release_field_query_downstream_abcd_grade_counts"],
                {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            )
            self.assertIn("原项目经理：张三", row["release_field_query_source_hit_summary_labels"][0])
            self.assertIn("新项目经理：李四", row["release_field_query_source_hit_summary_labels"][0])
            projection = load_stage6_review_loop_operator_projection(
                status_table_path=root / "out" / "stage6-review-loop-project-status-table.json"
            )
            text = json.dumps(projection, ensure_ascii=False)
            self.assertIn("释放证据字段查询已有 B/C 读回", text)
            for forbidden in ("无风险", "无冲突", "确认本人", "无在建", "是不是本人"):
                self.assertNotIn(forbidden, text)

    def test_runtime_blocker_followup_projection_keeps_other_projects_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_terminal_manual_only_batch_closeout(root / "closeout")
            next_subqueue_json = _write_runtime_blocker_next_subqueue_table(root / "next-subqueues")

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                output_root = Path(argv[argv.index("-OutputRoot") + 1])
                release_plan_json = Path(argv[argv.index("-ReleaseEvidenceAdapterPlanJson") + 1])
                _write_gdcic_readback(
                    output_root / "gdcic-browser-authorized-readback-v1.json",
                    release_plan_json,
                )
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                runtime_blocker_next_subqueue_json=next_subqueue_json,
                output_root=root / "out",
                execute_runtime_blocker_dispatch=True,
                runtime_blocker_dispatch_max_tasks=1,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            status_table = result["manifest"]["operator_projection_status_table"]
            self.assertEqual(status_table["summary"]["project_status_record_count"], 3)
            records = {record["project_id"]: record for record in status_table["records"]}
            self.assertEqual(
                records["PROJ-FIELD-BROWSER-READY"]["loop_terminal_state"],
                "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY",
            )
            self.assertEqual(
                records["PROJ-FIELD-AUTH"]["loop_terminal_state"],
                "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY",
            )
            self.assertEqual(
                records["PROJ-FIELD-AUTH"]["runtime_blocker_worker_followup_task_type_counts"],
                {"RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT": 1},
            )
            self.assertEqual(
                records["PROJ-FIELD-AUTH"]["runtime_blocker_ledger_state_counts"],
                {"AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION": 1},
            )
            self.assertEqual(
                records["PROJ-TERMINAL-D"]["loop_terminal_state"],
                "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
            )

    def test_missing_batch_closeout_blocks_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["stage6_review_cycle_runner_mode"], "INPUT_BLOCKED_OR_PARTIAL")
            self.assertIn("evidence_batch_closeout_missing_or_invalid", result["blocking_reasons"])

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
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

    def test_explicit_missing_runtime_blocker_next_subqueue_blocks_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_terminal_manual_only_batch_closeout(root / "closeout")

            result = run_stage6_review_cycle_runner(
                batch_closeout_root=root / "closeout",
                runtime_blocker_next_subqueue_json=root / "missing" / "stage6-review-loop-runtime-blocker-next-subqueues.json",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["runtime_blocker_next_subqueue_input_state"], "MISSING_OR_INVALID")
            self.assertIn(
                "runtime_blocker_next_subqueue_json_missing_or_invalid",
                result["blocking_reasons"],
            )


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


def _write_batch_closeout(root: Path, *, evidence_state_json: str | Path) -> None:
    records = [
        {
            "project_id": "PROJ-A",
            "project_name": "A project",
            "engineering_work_lane": "construction_or_epc",
            "candidate_group_members": ["A company"],
            "responsible_person_name": "张三",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
            "evidence_signal_source": "data_ggzy_bid_show",
            "batch_triage_bucket": "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
            "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": True,
            "review_reasons": ["same_person_company_time_window_overlap_review"],
            "source_refs": {
                "evidence_state_json": str(evidence_state_json),
                "evidence_batch_closeout_json": str(root / "evidence-batch-closeout-v1.json"),
                "p13b_operational_closeout_root": str(root.parent / "p13b-operational-closeout-v1"),
            },
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-D",
            "project_name": "D project",
            "engineering_work_lane": "construction_or_epc",
            "responsible_person_name": "李四",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "batch_stop_reason": "release_evidence_or_original_readback_insufficient_or_blocked",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "review_reasons": ["original_notice_backtrace_no_a_signal"],
            "source_refs": {"evidence_state_json": str(evidence_state_json)},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-SURVEY",
            "project_name": "Survey project",
            "engineering_work_lane": "design_survey",
            "candidate_group_members": ["Survey company"],
            "responsible_person_name": "胡昌华",
            "evidence_state": "DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY",
            "evidence_grade": "B_ENHANCED_EVIDENCE",
            "evidence_signal_source": "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
            "batch_triage_bucket": "B_ENHANCED_REVIEW",
            "closeout_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "review_reasons": ["design_survey_registry_identity_match_review"],
            "evidence_artifacts": [
                {
                    "evidence_artifact_type": "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
                    "verification_result": "MATCHED",
                    "identity_fields": {"person_name": "胡昌华"},
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ],
            "source_refs": {"evidence_state_json": str(evidence_state_json)},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-CONTINUE",
            "project_name": "Continue project",
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "P13B_ORIGINAL_BACKTRACE_REQUIRED",
            "evidence_grade": "PENDING_ORIGINAL_BACKTRACE",
            "closeout_state": "CONTINUE_EVIDENCE_RUN",
            "stage6_fact_package_state": "NOT_READY",
            "stage6_ready": False,
            "stage7_commercial_input_allowed": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    ]
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-1",
                "closeout_records": records,
                "summary": {"project_count": len(records)},
            },
            "summary": {"project_count": len(records)},
        },
    )


def _write_terminal_manual_only_batch_closeout(root: Path) -> None:
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-TERMINAL-D",
                "closeout_records": [
                    {
                        "project_id": "PROJ-TERMINAL-D",
                        "project_name": "Terminal D project",
                        "engineering_work_lane": "construction_or_epc",
                        "responsible_person_name": "王五",
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


def _write_runtime_blocker_next_subqueue_table(root: Path) -> Path:
    path = root / "stage6-review-loop-runtime-blocker-next-subqueues.json"
    _write_json(
        path,
        {
            "table_kind": "runtime_blocker_next_subqueue_table_v1",
            "source_status_table_ref": "tmp/out/stage6-review-loop-project-status-table.json",
            "summary": {
                "next_subqueue_record_count": 4,
                "subqueue_route_counts": {
                    "browser_worker": 2,
                    "operator_action": 1,
                    "retry": 1,
                },
            },
            "records": [
                {
                    "next_subqueue_record_id": "RUNTIME-SUBQUEUE-BROWSER-READY",
                    "subqueue_route": "browser_worker",
                    "subqueue_state": "BROWSER_WORKER_READY",
                    "project_id": "PROJ-FIELD-BROWSER-READY",
                    "project_name": "Browser worker ready project",
                    "assigned_owner": "卡卡罗特",
                    "assigned_owner_role": "single_operator",
                    "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
                    "loop_terminal_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "project_next_recommended_action": "run_controlled_browser_worker_plan",
                    "release_field_query_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "blocker_ledger_id": "BLK-BROWSER-READY",
                    "blocker_state": "BROWSER_WORKER_READY_FOR_CONTROLLED_PLAN",
                    "blocker_reason": "AUTHORIZED_SESSION_INPUT_AVAILABLE",
                    "runtime_layer": "browser worker",
                    "ledger_scope": "stage4_release_evidence_query",
                    "task_scope": "release_evidence_query",
                    "task_type": "project_manager_change",
                    "task_id": "GD-FIELD-BROWSER-READY",
                    "required_input": [],
                    "retry_policy": "retry_only_with_same_session_budget",
                    "reopen_conditions": ["same_session_browser_context_available"],
                    "operator_next_action": "run_allowlisted_gdcic_browser_authorized_readback_plan",
                    "input_artifact_refs": ["tmp/plan/release-evidence-adapter-plan-v1.json"],
                    "controller_consumable": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
                {
                    "next_subqueue_record_id": "RUNTIME-SUBQUEUE-AUTH-BROWSER",
                    "subqueue_route": "browser_worker",
                    "subqueue_state": "BROWSER_WORKER_WAITING_FOR_AUTHORIZED_SESSION",
                    "project_id": "PROJ-FIELD-AUTH",
                    "project_name": "Authorization hold project",
                    "assigned_owner": "卡卡罗特",
                    "assigned_owner_role": "single_operator",
                    "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
                    "loop_terminal_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "project_next_recommended_action": "authorize_browser_or_keep_manual_hold",
                    "release_field_query_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "blocker_ledger_id": "BLK-AUTH",
                    "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                    "blocker_reason": "LOGIN_OR_SSO_REQUIRED",
                    "runtime_layer": "browser worker",
                    "ledger_scope": "stage4_release_evidence_query",
                    "task_scope": "release_evidence_query",
                    "task_type": "project_manager_change",
                    "task_id": "GD-FIELD-AUTH",
                    "required_input": ["authorized_browser_storage_state_or_user_data_dir"],
                    "retry_policy": "retry_only_after_authorized_session_available",
                    "reopen_conditions": ["authorized_browser_storage_state_available"],
                    "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                    "input_artifact_refs": ["tmp/field/guangdong-local-field-query-probe-v1.json"],
                    "controller_consumable": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
                {
                    "next_subqueue_record_id": "RUNTIME-SUBQUEUE-AUTH-RETRY",
                    "subqueue_route": "retry",
                    "subqueue_state": "RETRY_WAITING_FOR_REOPEN_INPUT",
                    "project_id": "PROJ-FIELD-AUTH",
                    "project_name": "Authorization hold project",
                    "blocker_ledger_id": "BLK-AUTH",
                    "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                    "runtime_layer": "browser worker",
                    "required_input": ["authorized_browser_storage_state_or_user_data_dir"],
                    "retry_policy": "retry_only_after_authorized_session_available",
                    "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                    "input_artifact_refs": ["tmp/field/guangdong-local-field-query-probe-v1.json"],
                    "controller_consumable": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
                {
                    "next_subqueue_record_id": "RUNTIME-SUBQUEUE-AUTH-OPERATOR",
                    "subqueue_route": "operator_action",
                    "subqueue_state": "OPERATOR_ACTION_REQUIRED",
                    "project_id": "PROJ-FIELD-AUTH",
                    "project_name": "Authorization hold project",
                    "blocker_ledger_id": "BLK-AUTH",
                    "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                    "runtime_layer": "browser worker",
                    "required_input": ["authorized_browser_storage_state_or_user_data_dir"],
                    "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                    "input_artifact_refs": ["tmp/field/guangdong-local-field-query-probe-v1.json"],
                    "controller_consumable": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                    "query_miss_is_not_clearance": True,
                },
            ],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    )
    return path


def _write_stage6_review_loop_status_table_for_runtime_blockers(root: Path) -> Path:
    path = root / "stage6-review-loop-project-status-table.json"
    _write_json(
        path,
        {
            "summary": {
                "project_status_record_count": 2,
            },
            "records": [
                {
                    "project_id": "PROJ-FIELD-BROWSER-READY",
                    "project_name": "Browser worker ready project",
                    "assigned_owner": "卡卡罗特",
                    "assigned_owner_role": "single_operator",
                    "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
                    "loop_terminal_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "next_recommended_action": "run_controlled_browser_worker_plan",
                    "release_field_query_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "runtime_blocker_ledger_records": [
                        {
                            "blocker_ledger_id": "BLK-BROWSER-READY",
                            "ledger_scope": "stage4_release_evidence_query",
                            "project_id": "PROJ-FIELD-BROWSER-READY",
                            "project_name": "Browser worker ready project",
                            "task_id": "GD-FIELD-BROWSER-READY",
                            "task_scope": "release_evidence_query",
                            "task_type": "project_manager_change",
                            "blocker_state": "BROWSER_WORKER_READY_FOR_CONTROLLED_PLAN",
                            "blocker_reason": "AUTHORIZED_SESSION_INPUT_AVAILABLE",
                            "runtime_layer": "browser worker",
                            "required_input": [],
                            "artifact_ref": "tmp/plan/release-evidence-adapter-plan-v1.json",
                        }
                    ],
                },
                {
                    "project_id": "PROJ-FIELD-AUTH",
                    "project_name": "Authorization hold project",
                    "assigned_owner": "卡卡罗特",
                    "assigned_owner_role": "single_operator",
                    "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
                    "loop_terminal_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "next_recommended_action": "authorize_browser_or_keep_manual_hold",
                    "release_field_query_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "runtime_blocker_ledger_records": [
                        {
                            "blocker_ledger_id": "BLK-AUTH",
                            "ledger_scope": "stage4_release_evidence_query",
                            "project_id": "PROJ-FIELD-AUTH",
                            "project_name": "Authorization hold project",
                            "task_id": "GD-FIELD-AUTH",
                            "task_scope": "release_evidence_query",
                            "task_type": "project_manager_change",
                            "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                            "blocker_reason": "LOGIN_OR_SSO_REQUIRED",
                            "runtime_layer": "browser worker",
                            "required_input": ["authorized_browser_storage_state_or_user_data_dir"],
                            "retry_policy": "retry_only_after_authorized_session_available",
                            "reopen_conditions": ["authorized_browser_storage_state_available"],
                            "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                            "artifact_ref": "tmp/field/guangdong-local-field-query-probe-v1.json",
                        }
                    ],
                },
            ],
        },
    )
    return path


def _write_stage6_review_loop_runner_artifact(root: Path) -> Path:
    path = root / "stage6-review-loop-runner-v1.json"
    status_path = _write_stage6_review_loop_status_table_for_runtime_blockers(root / "embedded-status")
    next_subqueue_path = _write_runtime_blocker_next_subqueue_table(root / "embedded-next-subqueues")
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "STAGE6-LOOP-RUNNER-ARTIFACT-1",
                "project_status_table": json.loads(status_path.read_text(encoding="utf-8")),
                "runtime_blocker_next_subqueue_table": json.loads(next_subqueue_path.read_text(encoding="utf-8")),
            },
            "summary": {},
        },
    )
    return path


def _write_standalone_stage16_p13b_continuation(root: Path) -> Path:
    path = root / "stage16-p13b-continuation-controller-v1.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "STAGE16-P13B-STANDALONE-CYCLE-1",
                "project_continuation_records": [
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
                    }
                ],
            },
            "summary": {
                "source_project_count": 1,
                "ready_for_p13b_count": 0,
                "runtime_blocker_ledger_count": 1,
            },
        },
    )
    return path


def _write_standalone_release_evidence_plan(root: Path) -> Path:
    path = root / "release-evidence-adapter-plan-v1.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "RELEASE-PLAN-STANDALONE-CYCLE-1",
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
                        "operator_projection": {
                            "projection_state": "RELEASE_EVIDENCE_TERMINAL_STATUS_PROJECTION",
                            "next_action": "project_to_review_ready_status_projection_without_duplicate_dispatch",
                            "raw_json_required_for_next_step": False,
                        },
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
    return path


def _write_standalone_original_backtrace_continuation(root: Path) -> Path:
    path = root / "p13b-original-backtrace-continuation-controller-v2.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "ORIG-CONT-STANDALONE-CYCLE-1",
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
    return path


def _write_standalone_release_field_query_result(root: Path) -> Path:
    path = root / "guangdong-local-field-query-probe-v1.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-STANDALONE-CYCLE-1",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-AUTH",
                        "project_id": "PROJ-FIELD-AUTH",
                        "project_name": "Authorization hold project",
                        "assigned_owner": "卡卡罗特",
                        "assigned_owner_role": "single_operator",
                        "reviewer": "卡卡罗特",
                        "reviewer_role": "single_operator",
                        "owner_assignment_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
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
                    }
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 1,
                "release_evidence_downstream_abcd_grade_counts": {
                    "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1,
                },
            },
        },
    )
    return path


def _write_standalone_release_field_query_project_code_mix(root: Path) -> Path:
    path = root / "guangdong-local-field-query-probe-v1.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GD-FIELD-PROJECT-CODE-MIX-1",
                "field_task_records": [
                    {
                        "field_query_task_id": "GD-FIELD-PROJECT-CODE",
                        "project_id": "PROJ-FIELD-PROJECT-CODE",
                        "project_name": "Project code matched project",
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                        "adapter_result_state": "MATCHED",
                        "downstream_release_evidence_abcd_grade": "",
                        "query_params": {
                            "projectCode": "440100202605190001",
                            "projectCodeVariants": ["440100202605190001", "JG2026-11337"],
                            "gdcicProjectCodeVariants": ["440100202605190001"],
                            "tradeProjectCode": "JG2026-11337",
                        },
                        "field_summary": {
                            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
                            "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                            "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                        },
                        "field_match_summary": {
                            "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                            "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                            "source_specific_records": [
                                {
                                    "record_type": "construction_permit_public_record",
                                    "projectCode": "440100202605190001",
                                    "permitCode": "440100202605190001-SGXK",
                                }
                            ],
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                    {
                        "field_query_task_id": "GD-FIELD-NOTFOUND",
                        "project_id": "PROJ-FIELD-NOTFOUND",
                        "project_name": "Not found project",
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                        "adapter_result_state": "NOT_FOUND",
                        "downstream_release_evidence_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                        "query_params": {"projectCode": "440100202605190099"},
                        "field_summary": {
                            "field_query_probe_state": "FIELD_READBACK_NOT_FOUND",
                        },
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    },
                ],
            },
            "summary": {
                "guangdong_local_field_query_task_count": 2,
                "release_evidence_downstream_abcd_grade_counts": {
                    "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1,
                },
            },
        },
    )
    return path


def _write_gdcic_release_plan_for_stage6_cycle(root: Path) -> Path:
    path = root / "release-evidence-adapter-plan-v1.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
                "manifest_id": "RELEASE-PLAN-GDCIC-PM-CHANGE",
                "release_evidence_adapter_task_records": [
                    {
                        "release_evidence_adapter_task_id": "REL-GDCIC-PM-CHANGE",
                        "project_id": "PROJ-GDCIC-PM-CHANGE",
                        "project_name": "GDCIC project manager change project",
                        "candidate_company_name": "广州测试建设有限公司",
                        "matched_person_names": ["张三"],
                        "release_evidence_target_type": "project_manager_change_notice",
                        "release_evidence_grade_on_match": "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
                        "release_evidence_query_region_code": "CN-GD",
                        "local_housing_authority_adapter_region_code": "CN-GD",
                        "source_profile_id": "GUANGDONG-GDCIC-HOME",
                        "query_params": {
                            "projectId": "PROJ-GDCIC-PM-CHANGE",
                            "projectName": "GDCIC project manager change project",
                            "companyName": "广州测试建设有限公司",
                            "personName": "张三",
                            "keywords": ["GDCIC project manager change project", "广州测试建设有限公司", "张三"],
                        },
                        "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                ],
            },
            "summary": {"adapter_task_count": 1},
        },
    )
    return path


def _write_gdcic_project_manager_change_readback(root: Path) -> Path:
    path = root / "gdcic-browser-authorized-readback-v1.json"
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_kind": "gdcic_browser_authorized_readback_v1_manifest",
                "manifest_id": "GDCIC-PM-CHANGE-READBACK",
                "execution_mode": "LIVE_BROWSER_EXECUTION_ATTEMPTED",
                "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                "browser_readback_records": [
                    {
                        "gdcic_browser_readback_task_id": "GDCIC-PM-CHANGE-TASK",
                        "release_evidence_adapter_task_id": "REL-GDCIC-PM-CHANGE",
                        "project_id": "PROJ-GDCIC-PM-CHANGE",
                        "project_name": "GDCIC project manager change project",
                        "candidate_company_name": "广州测试建设有限公司",
                        "person_name": "张三",
                        "source_profile_id": "GUANGDONG-GDCIC-HOME",
                        "release_evidence_target_type": "project_manager_change_notice",
                        "target_source_types": ["project_manager_change_notice"],
                        "readback_state": "BROWSER_AUTHORIZED_READBACK_READY",
                        "adapter_result_state": "MATCHED",
                        "authorization_readiness_state": "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
                        "field_surface_state": "TARGET_FIELD_MATCHED_REVIEW_REQUIRED",
                        "records": [
                            {
                                "record_type": "project_manager_change_browser_authorized_record",
                                "project_name": "GDCIC project manager change project",
                                "company_name": "广州测试建设有限公司",
                                "original_project_manager_name": "张三",
                                "new_project_manager_name": "李四",
                                "change_date": "2026-01-15",
                                "project_manager_change_release_window_interpretation": (
                                    "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"
                                ),
                                "original_project_manager_matches_query_person": True,
                                "new_project_manager_matches_query_person": False,
                            }
                        ],
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                    }
                ],
                "summary": {
                    "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                    "authorized_session_input_ready": True,
                    "gdcic_browser_readback_ready_count": 1,
                },
            },
            "summary": {
                "authorized_session_input_state": "INJECTED_BROWSER_RUNNER",
                "authorized_session_input_ready": True,
                "gdcic_browser_readback_ready_count": 1,
            },
        },
    )
    return path


def _write_gdcic_readback(path: Path, release_plan_json: Path) -> None:
    _write_json(
        path,
        {
            "safe_to_execute": True,
            "blocking_reasons": [],
            "manifest": {
                "manifest_id": "GDCIC-READBACK-READY",
                "execution_mode": "LIVE_BROWSER_EXECUTION_ATTEMPTED",
                "source_release_evidence_adapter_plan_json": str(release_plan_json),
                "browser_readback_records": [
                    {
                        "readback_state": "BROWSER_AUTHORIZED_READBACK_READY",
                        "adapter_result_state": "MATCHED",
                        "project_id": "PROJ-FIELD-BROWSER-READY",
                    }
                ],
            },
            "summary": {
                "execution_mode": "LIVE_BROWSER_EXECUTION_ATTEMPTED",
                "gdcic_browser_readback_record_count": 1,
                "gdcic_browser_readback_ready_count": 1,
                "blocking_reasons": [],
            },
        },
    )


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
