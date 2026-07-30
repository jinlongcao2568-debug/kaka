from __future__ import annotations

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

from storage.runtime_blocker_controller_dispatch_runner import (  # noqa: E402
    run_runtime_blocker_controller_dispatch_runner,
)


class RuntimeBlockerControllerDispatchRunnerTests(unittest.TestCase):
    def test_dry_run_records_ready_worker_and_keeps_holds_in_subqueues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            table = {
                "records": [
                    _controller_dispatch_record(
                        "PROJ-READY",
                        readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                        expected_output=root / "worker" / "ready" / "gdcic-browser-authorized-readback-v1.json",
                        input_artifact_refs=[str(root / "plan" / "release-evidence-adapter-plan-v1.json")],
                    ),
                    _controller_dispatch_record(
                        "PROJ-HOLD",
                        readiness="BLOCKED_REQUIRED_INPUT_OR_WORKER_SPEC_MISSING",
                        required_input=["authorized_browser_storage_state_or_user_data_dir"],
                        blocking_reasons=["required_input_missing_or_operator_action_pending"],
                    ),
                ]
            }

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table=table,
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-22T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["runtime_blocker_dispatch_runner_task_count"], 2)
            self.assertEqual(
                summary["execution_state_counts"],
                {"DRY_RUN_READY": 1, "WORKER_DISPATCH_NOT_READY_RECORDED": 1},
            )
            self.assertEqual(
                summary["worker_readback_state_counts"],
                {
                    "WAITING_FOR_CONTROLLED_WORKER_EXECUTION": 1,
                    "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED": 1,
                },
            )
            self.assertEqual(
                summary["worker_closeout_state_counts"],
                {
                    "KEPT_IN_RUNTIME_BLOCKER_SUBQUEUE": 1,
                    "WAITING_FOR_CONTROLLED_WORKER_EXECUTION": 1,
                },
            )
            self.assertEqual(summary["followup_task_count"], 0)
            self.assertTrue((root / "out" / "runtime-blocker-controller-dispatch-runner-v1.json").exists())
            self.assertTrue((root / "out" / "runtime-blocker-worker-followup-queue.json").exists())
            runner_records = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"]
            self.assertTrue(runner_records[0]["requires_operator_approval_before_execution"])
            self.assertTrue(runner_records[1]["requires_operator_approval_before_execution"])

    def test_fallback_source_followup_has_plan_artifact_and_operator_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _controller_dispatch_record(
                "PROJ-FALLBACK",
                readiness="FALLBACK_SOURCE_PLAN_REQUIRED",
                required_input=["fallback_source_or_project_local_authority_path"],
                input_artifact_refs=[str(root / "stage4-followup" / "stage4-backfill-followup-queue-v1.json")],
            )
            record.update(
                {
                    "dispatch_route": "fallback_source",
                    "dispatch_worker_family": "source_adapter",
                    "dispatch_blocking_reasons": ["required_input_missing_or_operator_action_pending"],
                    "recommended_script": "storage.runtime_blocker_fallback_source_plan",
                    "recommended_command_argv": [],
                    "expected_output_artifact": "runtime-blocker-fallback-source-plan-v1.json",
                    "expected_output_artifact_path": str(
                        root
                        / "out"
                        / "fallback_source"
                        / "PROJ-FALLBACK"
                        / "runtime-blocker-fallback-source-plan-v1.json"
                    ),
                    "operator_next_action": "record_not_found_without_clearance_claim_or_try_project_local_authority",
                }
            )

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table={"records": [record]},
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-26T00:00:00+08:00",
            )

        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(result["summary"]["followup_task_count"], 1)
        followup = result["manifest"]["runtime_blocker_worker_followup_queue"]["records"][0]
        self.assertEqual(followup["formal_entrypoint_id"], "runtime_blocker_fallback_source_plan_builder")
        self.assertEqual(followup["followup_task_type"], "BUILD_FALLBACK_SOURCE_ADAPTER_PLAN")
        self.assertEqual(followup["expected_output_artifact"], "runtime-blocker-fallback-source-plan-v1.json")
        self.assertTrue(followup["expected_output_artifact_path"].endswith("runtime-blocker-fallback-source-plan-v1.json"))
        self.assertEqual(followup["plan_artifact_kind"], "runtime_blocker_fallback_source_plan_v1")
        self.assertEqual(followup["recommended_command_argv"], [])
        self.assertIn("fallback_source_or_project_local_authority_path", followup["recommended_source_path_or_query_terms"])
        self.assertTrue(followup["requires_operator_action_before_live"])
        self.assertFalse(followup["customer_visible_allowed"])
        self.assertTrue(followup["query_miss_is_not_clearance"])

    def test_existing_browser_readback_output_creates_field_query_followup_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_json = root / "worker" / "gdcic-browser-authorized-readback-v1.json"
            release_plan = root / "plan" / "release-evidence-adapter-plan-v1.json"
            _write_gdcic_readback(readback_json, release_plan)
            table = {
                "records": [
                    _controller_dispatch_record(
                        "PROJ-BACKFILL",
                        readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                        expected_output=readback_json,
                        input_artifact_refs=[str(release_plan)],
                    )
                ]
            }

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table=table,
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-22T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["existing_output_consumed_count"], 1)
            self.assertEqual(summary["ready_for_field_query_backfill_count"], 1)
            self.assertEqual(summary["followup_task_count"], 1)
            self.assertEqual(
                summary["worker_closeout_state_counts"],
                {"READY_FOR_GUANGDONG_FIELD_QUERY_BACKFILL": 1},
            )
            followups = result["manifest"]["runtime_blocker_worker_followup_queue"]["records"]
            self.assertEqual(len(followups), 1)
            followup = followups[0]
            self.assertEqual(followup["formal_entrypoint_id"], "guangdong_local_field_query_probe")
            self.assertEqual(followup["gdcic_browser_readback_json"], str(readback_json))
            self.assertEqual(followup["release_evidence_adapter_plan_json"], str(release_plan))
            self.assertIn("scripts/run-guangdong-local-field-query-probe-v1.ps1", followup["recommended_command_argv"])
            self.assertIn("-GdcicBrowserReadbackJson", followup["recommended_command_argv"])
            self.assertIn("-EnableLivePublicQuery", followup["recommended_command_argv"])
            self.assertEqual(followup["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertTrue(followup["live_execution_enabled"])
            self.assertTrue(followup["requires_operator_approval_before_execution"])
            self.assertTrue(result["summary"]["live_execution_enabled"])
            self.assertTrue(result["manifest"]["safety"]["live_browser_execution_enabled"])

    def test_existing_output_is_not_reused_when_release_plan_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_json = root / "worker" / "gdcic-browser-authorized-readback-v1.json"
            old_release_plan = root / "plan-old" / "release-evidence-adapter-plan-v1.json"
            new_release_plan = root / "plan-new" / "release-evidence-adapter-plan-v1.json"
            _write_gdcic_readback(readback_json, old_release_plan)
            table = {
                "records": [
                    _controller_dispatch_record(
                        "PROJ-STALE-OUTPUT",
                        readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                        expected_output=readback_json,
                        input_artifact_refs=[str(new_release_plan)],
                    )
                ]
            }

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table=table,
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-22T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"][0]
            self.assertEqual(record["execution_state"], "DRY_RUN_READY")
            self.assertEqual(record["skip_reason"], "execute_commands_false")
            self.assertEqual(result["summary"]["existing_output_consumed_count"], 0)

    def test_execute_commands_blocks_non_allowlisted_argv_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _controller_dispatch_record(
                "PROJ-BAD-ARGV",
                readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                expected_output=root / "worker" / "bad" / "gdcic-browser-authorized-readback-v1.json",
                input_artifact_refs=[str(root / "plan" / "release-evidence-adapter-plan-v1.json")],
            )
            record["recommended_command_argv"] = ["python", "-c", "print('should not run')"]
            calls: list[list[str]] = []

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table={"records": [record]},
                output_root=root / "out",
                execute_commands=True,
                command_executor=lambda argv, cwd: calls.append(argv) or {"exit_code": 0},
                created_at="2026-05-22T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(calls, [])
            runner = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"][0]
            self.assertEqual(runner["execution_state"], "BLOCKED_BY_ALLOWLIST")
            self.assertEqual(runner["allowlist_state"], "ALLOWLIST_BLOCKED")
            self.assertEqual(runner["allowlist_reason"], "command_must_start_with_pwsh")
            self.assertEqual(result["summary"]["allowlist_blocked_count"], 1)

    def test_execute_commands_blocks_live_or_external_flags_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _controller_dispatch_record(
                "PROJ-LIVE-FLAG",
                readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                expected_output=root / "worker" / "live" / "gdcic-browser-authorized-readback-v1.json",
                input_artifact_refs=[str(root / "plan" / "release-evidence-adapter-plan-v1.json")],
            )
            record["recommended_command_argv"].append("-EnableLivePublicQuery")
            calls: list[list[str]] = []

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table={"records": [record]},
                output_root=root / "out",
                execute_commands=True,
                command_executor=lambda argv, cwd: calls.append(argv) or {"exit_code": 0},
                created_at="2026-05-22T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(calls, [])
            runner = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"][0]
            self.assertEqual(runner["execution_state"], "BLOCKED_BY_ALLOWLIST")
            self.assertEqual(runner["allowlist_reason"], "live_or_external_execution_flag_present")
            self.assertTrue(runner["live_execution_enabled"])
            self.assertTrue(result["summary"]["live_execution_enabled"])

    def test_existing_output_is_not_reused_when_same_path_plan_manifest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_json = root / "worker" / "gdcic-browser-authorized-readback-v1.json"
            release_plan = root / "plan" / "release-evidence-adapter-plan-v1.json"
            _write_gdcic_readback(
                readback_json,
                release_plan,
                source_manifest_id="RELEASE-PLAN-OLD",
                source_manifest_sha256="sha256-old",
            )
            _write_release_plan_fixture(
                release_plan,
                manifest_id="RELEASE-PLAN-NEW",
                manifest_sha256="sha256-new",
            )
            table = {
                "records": [
                    _controller_dispatch_record(
                        "PROJ-SAME-PATH-MUTATED",
                        readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                        expected_output=readback_json,
                        input_artifact_refs=[str(release_plan)],
                    )
                ]
            }

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table=table,
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-22T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"][0]
            self.assertEqual(record["execution_state"], "DRY_RUN_READY")
            self.assertEqual(result["summary"]["existing_output_consumed_count"], 0)

    def test_existing_output_is_not_reused_when_browser_readback_project_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_json = root / "worker" / "gdcic-browser-authorized-readback-v1.json"
            release_plan = root / "plan" / "release-evidence-adapter-plan-v1.json"
            _write_release_plan_fixture(
                release_plan,
                manifest_id="RELEASE-PLAN-FIXTURE-1",
                manifest_sha256="sha256-fixture",
            )
            _write_gdcic_readback(
                readback_json,
                release_plan,
                project_id="PROJ-OTHER",
            )
            table = {
                "records": [
                    _controller_dispatch_record(
                        "PROJ-CURRENT",
                        readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                        expected_output=readback_json,
                        input_artifact_refs=[str(release_plan)],
                    )
                ]
            }

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table=table,
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"][0]
            self.assertEqual(record["execution_state"], "DRY_RUN_READY")
            self.assertEqual(record["skip_reason"], "execute_commands_false")
            self.assertEqual(result["summary"]["existing_output_consumed_count"], 0)

    def test_existing_output_is_not_reused_when_browser_readback_task_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_json = root / "worker" / "gdcic-browser-authorized-readback-v1.json"
            release_plan = root / "plan" / "release-evidence-adapter-plan-v1.json"
            _write_release_plan_fixture(
                release_plan,
                manifest_id="RELEASE-PLAN-FIXTURE-1",
                manifest_sha256="sha256-fixture",
            )
            _write_gdcic_readback(
                readback_json,
                release_plan,
                project_id="PROJ-CURRENT",
                release_evidence_adapter_task_id="GD-FIELD-OTHER",
            )
            table = {
                "records": [
                    _controller_dispatch_record(
                        "PROJ-CURRENT",
                        readiness="READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH",
                        expected_output=readback_json,
                        input_artifact_refs=[str(release_plan)],
                        task_id="GD-FIELD-CURRENT",
                    )
                ]
            }

            result = run_runtime_blocker_controller_dispatch_runner(
                controller_dispatch_table=table,
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["runtime_blocker_dispatch_runner_table"]["records"][0]
            self.assertEqual(record["execution_state"], "DRY_RUN_READY")
            self.assertEqual(record["skip_reason"], "execute_commands_false")
            self.assertEqual(result["summary"]["existing_output_consumed_count"], 0)


def _controller_dispatch_record(
    project_id: str,
    *,
    readiness: str,
    expected_output: str | Path | None = None,
    input_artifact_refs: list[str] | None = None,
    required_input: list[str] | None = None,
    blocking_reasons: list[str] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    output_root = str(Path(expected_output).parent) if expected_output else ""
    argv = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/build-gdcic-browser-authorized-readback-v1.ps1",
        "-ReleaseEvidenceAdapterPlanJson",
        str((input_artifact_refs or ["tmp/plan/release-evidence-adapter-plan-v1.json"])[0]),
        "-OutputRoot",
        output_root or f"tmp/out/{project_id}",
    ]
    return {
        "controller_dispatch_task_id": f"RUNTIME-DISPATCH-{project_id}",
        "source_controller_queue_record_id": f"RUNTIME-QUEUE-{project_id}",
        "source_next_subqueue_record_id": f"RUNTIME-SUBQUEUE-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} project",
        "assigned_owner": "卡卡罗特",
        "assigned_owner_role": "single_operator",
        "dispatch_route": "browser_worker",
        "dispatch_worker_family": "browser_worker",
        "dispatch_readiness_state": readiness,
        "dispatch_blocking_reasons": list(blocking_reasons or []),
        "task_id": task_id or f"GD-FIELD-{project_id}",
        "task_scope": "release_evidence_query",
        "recommended_script": "scripts/build-gdcic-browser-authorized-readback-v1.ps1",
        "recommended_command_argv": argv,
        "expected_output_artifact": "gdcic-browser-authorized-readback-v1.json",
        "expected_output_artifact_path": str(expected_output or ""),
        "input_artifact_refs": list(input_artifact_refs or []),
        "required_input": list(required_input or []),
        "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _write_release_plan_fixture(path: Path, *, manifest_id: str, manifest_sha256: str) -> None:
    payload: Mapping[str, Any] = {
        "manifest": {
            "manifest_id": manifest_id,
            "manifest_sha256": manifest_sha256,
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_gdcic_readback(
    path: Path,
    release_plan_json: Path,
    *,
    source_manifest_id: str = "RELEASE-PLAN-FIXTURE-1",
    source_manifest_sha256: str = "sha256-fixture",
    project_id: str = "PROJ-BACKFILL",
    release_evidence_adapter_task_id: str = "",
) -> None:
    effective_task_id = release_evidence_adapter_task_id or f"GD-FIELD-{project_id}"
    payload: Mapping[str, Any] = {
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": {
            "manifest_id": "GDCIC-READBACK-READY",
            "execution_mode": "LIVE_BROWSER_EXECUTION_ATTEMPTED",
            "source_release_evidence_adapter_plan_json": str(release_plan_json),
            "source_release_evidence_adapter_plan_manifest_id": source_manifest_id,
            "source_release_evidence_adapter_plan_manifest_sha256": source_manifest_sha256,
            "browser_readback_records": [
                {
                    "readback_state": "BROWSER_AUTHORIZED_READBACK_READY",
                    "adapter_result_state": "MATCHED",
                    "release_evidence_adapter_task_id": effective_task_id,
                    "project_id": project_id,
                }
            ],
        },
        "summary": {
            "execution_mode": "LIVE_BROWSER_EXECUTION_ATTEMPTED",
            "gdcic_browser_readback_record_count": 1,
            "gdcic_browser_readback_ready_count": 1,
            "blocking_reasons": [],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
