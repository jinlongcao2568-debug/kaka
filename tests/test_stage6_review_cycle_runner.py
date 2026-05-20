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

from storage.stage6_review_cycle_runner import run_stage6_review_cycle_runner  # noqa: E402


class Stage6ReviewCycleRunnerTests(unittest.TestCase):
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
