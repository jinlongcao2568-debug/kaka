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

from storage.stage6_review_action_dispatch_runner import (  # noqa: E402
    run_stage6_review_action_dispatch_runner,
)


class Stage6ReviewActionDispatchRunnerTests(unittest.TestCase):
    def test_dry_run_groups_dispatch_tasks_by_task_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)

            result = run_stage6_review_action_dispatch_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
                execute_commands=False,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["selected_dispatch_task_count"], 4)
            self.assertEqual(summary["dispatch_runner_group_count"], 3)
            self.assertEqual(summary["dry_run_ready_group_count"], 3)
            groups = _groups_by_type(result["manifest"]["dispatch_runner_group_table"]["records"])
            original = groups["RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW"]
            self.assertIn("-ProjectIds", original["recommended_command_argv"])
            self.assertIn("PROJ-O1,PROJ-O2", original["recommended_command_argv"])
            self.assertIn("scripts/run-evidence-orchestration-continuation-v1.ps1", original["recommended_command_argv"])
            design = groups["RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW"]
            self.assertIn("-PublicRegistryFallbackJson", design["recommended_command_argv"])
            roots = result["manifest"]["result_roots_by_task_type"]
            self.assertIn("BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN", roots)
            release = groups["BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN"]
            self.assertIn("-BatchCloseoutJson", release["recommended_command_argv"])
            self.assertIn("-P13BOperationalCloseoutRoot", release["recommended_command_argv"])
            self.assertTrue((root / "out" / "stage6-review-action-dispatch-runner-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-dispatch-runner-table.json").exists())

    def test_execute_uses_generated_structured_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)
            calls: list[tuple[list[str], Path]] = []

            def fake_executor(argv: list[str], cwd: Path) -> Mapping[str, Any]:
                calls.append((argv, cwd))
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            result = run_stage6_review_action_dispatch_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
                execute_commands=True,
                cwd=root,
                command_executor=fake_executor,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(len(calls), 3)
            self.assertEqual(result["summary"]["executed_success_group_count"], 3)
            self.assertTrue(all(str(call[0][0]).lower().startswith("pwsh") for call in calls))
            groups = result["manifest"]["dispatch_runner_group_table"]["records"]
            self.assertTrue(all(group["stdout_excerpt"] == "ok" for group in groups))

    def test_missing_evidence_state_blocks_state_dependent_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_dispatch(root / "dispatch", evidence_state_json=root / "missing" / "state.json", include_release=False)

            result = run_stage6_review_action_dispatch_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["blocked_missing_inputs_group_count"], 2)
            groups = _groups_by_type(result["manifest"]["dispatch_runner_group_table"]["records"])
            self.assertEqual(
                groups["RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW"]["skip_reason"],
                "stage16_storage_json_missing",
            )
            self.assertEqual(
                groups["RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW"]["skip_reason"],
                "design_survey_public_registry_fallback_json_missing",
            )

    def test_release_plan_group_blocks_when_source_refs_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(
                root / "dispatch",
                evidence_state_json=state_json,
                include_original=False,
                include_design=False,
                release_source_refs={"evidence_state_json": str(state_json)},
            )

            result = run_stage6_review_action_dispatch_runner(
                dispatch_root=root / "dispatch",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["selected_dispatch_task_count"], 1)
            self.assertEqual(result["summary"]["blocked_missing_inputs_group_count"], 1)
            group = result["manifest"]["dispatch_runner_group_table"]["records"][0]
            self.assertEqual(group["dispatch_task_type"], "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN")
            self.assertEqual(group["group_readiness_state"], "BLOCKED_RELEASE_EVIDENCE_INPUTS_MISSING")
            self.assertEqual(
                group["skip_reason"],
                "release_evidence_batch_closeout_and_p13b_operational_refs_missing",
            )
            self.assertEqual(group["recommended_command_argv"], [])

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_dispatch(root / "dispatch", evidence_state_json=state_json)

            result = run_stage6_review_action_dispatch_runner(
                dispatch_root=root / "dispatch",
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


def _write_dispatch(
    root: Path,
    *,
    evidence_state_json: str | Path,
    include_release: bool = True,
    include_original: bool = True,
    include_design: bool = True,
    release_source_refs: Mapping[str, Any] | None = None,
) -> None:
    records = []
    if include_original:
        records.extend(
            [
                _dispatch_task(
                    "PROJ-O1",
                    task_type="RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
                    evidence_state_json=evidence_state_json,
                ),
                _dispatch_task(
                    "PROJ-O2",
                    task_type="RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
                    evidence_state_json=evidence_state_json,
                ),
            ]
        )
    if include_design:
        records.append(
            _dispatch_task(
                "PROJ-D",
                task_type="RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW",
                evidence_state_json=evidence_state_json,
            )
        )
    if include_release:
        records.append(
            _dispatch_task(
                "PROJ-R",
                task_type="BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
                evidence_state_json=evidence_state_json,
                source_refs=release_source_refs
                or {
                    "evidence_state_json": str(evidence_state_json),
                    "evidence_batch_closeout_json": str(root.parent / "closeout" / "evidence-batch-closeout-v1.json"),
                    "p13b_operational_closeout_root": str(root.parent / "p13b-operational-closeout-v1"),
                },
            )
        )
    _write_json(
        root / "stage6-review-action-dispatch-v1.json",
        {
            "manifest": {
                "manifest_id": "DISPATCH-1",
                "dispatch_task_table": {"records": records, "summary": {}},
            },
            "summary": {},
        },
    )


def _dispatch_task(
    project_id: str,
    *,
    task_type: str,
    evidence_state_json: str | Path,
    source_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "dispatch_task_id": f"DISPATCH-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} project",
        "dispatch_task_type": task_type,
        "dispatch_readiness_state": "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN",
        "expected_output_artifact": "artifact.json",
        "source_refs": dict(source_refs or {"evidence_state_json": str(evidence_state_json)}),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _groups_by_type(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["dispatch_task_type"]): record for record in records}


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
