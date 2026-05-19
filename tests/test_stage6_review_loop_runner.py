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
