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

from storage.stage6_review_action_result_runner import (  # noqa: E402
    run_stage6_review_action_result_runner,
)


class Stage6ReviewActionResultRunnerTests(unittest.TestCase):
    def test_dry_run_reads_allowlisted_routing_commands_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_routing(root / "routing")

            result = run_stage6_review_action_result_runner(
                result_routing_root=root / "routing",
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["result_runner_record_count"], 3)
            self.assertEqual(summary["dry_run_ready_count"], 2)
            self.assertEqual(summary["executed_success_count"], 0)
            self.assertEqual(summary["skipped_not_ready_count"], 1)
            self.assertEqual(summary["allowlist_blocked_count"], 0)
            records = _records_by_project(result["manifest"]["result_runner_table"]["records"])
            self.assertEqual(records["PROJ-ORIG"]["expected_output_artifact"], "evidence-batch-closeout-v1.json")
            self.assertEqual(records["PROJ-FIELD"]["expected_output_artifact"], "guangdong-local-field-query-probe-v1.json")
            self.assertTrue((root / "out" / "stage6-review-action-result-runner-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-result-runner-table.json").exists())

    def test_execute_uses_structured_argv_and_project_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_routing(root / "routing")
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_action_result_runner(
                result_routing_root=root / "routing",
                output_root=root / "out",
                execute_commands=True,
                project_ids=["PROJ-ORIG"],
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 1)
            self.assertIn("scripts/build-evidence-batch-closeout-v1.ps1", calls[0][0])
            summary = result["summary"]
            self.assertEqual(summary["executed_success_count"], 1)
            self.assertEqual(summary["execution_state_counts"]["SKIPPED_BY_PROJECT_FILTER"], 2)
            records = _records_by_project(result["manifest"]["result_runner_table"]["records"])
            self.assertEqual(records["PROJ-ORIG"]["execution_state"], "EXECUTED_SUCCEEDED")
            self.assertEqual(records["PROJ-ORIG"]["stdout_excerpt"], "ok")

    def test_blocks_missing_argv_and_live_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_routing(
                root / "routing",
                records=[
                    _routing_record(
                        "PROJ-NO-ARGV",
                        next_task_type="REBUILD_EVIDENCE_STATE_WITH_ORIGINAL_BACKTRACE_CONTINUATION",
                        argv=[],
                    ),
                    _routing_record(
                        "PROJ-LIVE",
                        next_task_type="RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE",
                        argv=[
                            "pwsh",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            "scripts/run-guangdong-local-field-query-probe-v1.ps1",
                            "-ReleaseEvidenceAdapterPlanJson",
                            "tmp/release.json",
                            "-EnableLivePublicQuery",
                            "-OutputRoot",
                            "tmp/field",
                        ],
                    ),
                ],
            )

            result = run_stage6_review_action_result_runner(
                result_routing_root=root / "routing",
                output_root=root / "out",
                execute_commands=True,
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["allowlist_blocked_count"], 2)
            records = _records_by_project(result["manifest"]["result_runner_table"]["records"])
            self.assertEqual(records["PROJ-NO-ARGV"]["allowlist_reason"], "structured_recommended_command_argv_missing")
            self.assertEqual(records["PROJ-LIVE"]["allowlist_reason"], "live_or_external_execution_flag_present")

    def test_execute_skips_duplicate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            duplicate_argv = [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "scripts/build-evidence-batch-closeout-v1.ps1",
                "-ContinuationRunJson",
                "tmp/continuation-run.json",
                "-OutputRoot",
                "tmp/batch",
            ]
            _write_routing(
                root / "routing",
                records=[
                    _routing_record(
                        "PROJ-DUP-1",
                        next_task_type="REBUILD_BATCH_CLOSEOUT_WITH_CONTINUATION_RUN",
                        argv=duplicate_argv,
                    ),
                    _routing_record(
                        "PROJ-DUP-2",
                        next_task_type="REBUILD_BATCH_CLOSEOUT_WITH_CONTINUATION_RUN",
                        argv=duplicate_argv,
                    ),
                ],
            )
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_action_result_runner(
                result_routing_root=root / "routing",
                output_root=root / "out",
                execute_commands=True,
                command_executor=fake_executor,
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["summary"]["executed_success_count"], 1)
            self.assertEqual(result["summary"]["skipped_duplicate_command_count"], 1)
            records = _records_by_project(result["manifest"]["result_runner_table"]["records"])
            self.assertEqual(records["PROJ-DUP-2"]["execution_state"], "SKIPPED_DUPLICATE_COMMAND")

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_routing(root / "routing")

            result = run_stage6_review_action_result_runner(
                result_routing_root=root / "routing",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            self.assertFalse(result["manifest"]["safety"]["stage7_to_stage9_live_execution_enabled"])
            self.assertFalse(result["manifest"]["safety"]["shell_execution_enabled"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)
            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_sha256"], _fingerprint_without_manifest_sha(manifest))


def _write_routing(root: Path, *, records: list[Mapping[str, Any]] | None = None) -> None:
    routing_records = records or [
        _routing_record(
            "PROJ-ORIG",
            next_task_type="REBUILD_BATCH_CLOSEOUT_WITH_CONTINUATION_RUN",
            argv=[
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "scripts/build-evidence-batch-closeout-v1.ps1",
                "-ContinuationRunJson",
                "tmp/continuation-run.json",
                "-OutputRoot",
                "tmp/batch",
            ],
        ),
        _routing_record(
            "PROJ-FIELD",
            next_task_type="RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE",
            argv=[
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "scripts/run-guangdong-local-field-query-probe-v1.ps1",
                "-ReleaseEvidenceAdapterPlanJson",
                "tmp/release-adapter-plan.json",
                "-OutputRoot",
                "tmp/field",
            ],
        ),
        {
            "result_routing_id": "ROUTE-PROJ-WAIT",
            "project_id": "PROJ-WAIT",
            "project_name": "PROJ-WAIT project",
            "dispatch_task_type": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
            "result_routing_state": "WAITING_FOR_CONTROLLED_EXECUTION",
            "next_task_type": "RUN_OR_SKIP_DISPATCH_TASK",
            "recommended_command_ready": False,
            "recommended_command": "",
            "recommended_command_argv": [],
        },
    ]
    _write_json(
        root / "stage6-review-action-result-routing-v1.json",
        {
            "manifest": {
                "manifest_id": "RESULT-ROUTING-1",
                "result_routing_table": {"records": routing_records, "summary": {}},
            },
            "summary": {},
        },
    )


def _routing_record(project_id: str, *, next_task_type: str, argv: list[str]) -> dict[str, Any]:
    script = ""
    if "-File" in argv:
        script = argv[argv.index("-File") + 1]
    return {
        "result_routing_id": f"ROUTE-{project_id}",
        "dispatch_closeout_id": f"CLOSEOUT-{project_id}",
        "dispatch_task_id": f"DISPATCH-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} project",
        "dispatch_task_type": "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN"
        if next_task_type == "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE"
        else "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
        "result_routing_state": "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY"
        if next_task_type == "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE"
        else "READY_FOR_EVIDENCE_STATE_REBUILD",
        "next_task_type": next_task_type,
        "recommended_script": script,
        "recommended_command_ready": True,
        "recommended_command": " ".join(argv),
        "recommended_command_argv": argv,
    }


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


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
