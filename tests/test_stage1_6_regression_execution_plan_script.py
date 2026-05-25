from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StageOneSixRegressionExecutionPlanScriptTests(unittest.TestCase):
    def test_applies_followup_execution_plan_in_describe_mode_without_enabling_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            queue_json = root / "stage4-backfill-followup-queue-v1.json"
            queue_json.write_text(
                json.dumps(
                    {
                        "next_regression_execution_plan": {
                            "plan_state": "PUBLIC_SOURCE_DEEPENING_RUN_RECOMMENDED",
                            "recommended_switches": [
                                "RunP13BPublicSourceChain",
                                "RunYgpBackfillFieldQuery",
                                "RunStage6MergedProjection",
                            ],
                            "recommended_parameter_overrides": {
                                "MaxLiveP13BCompanies": 10,
                                "MaxBidRecordsPerCompany": 3,
                                "MaxBidListPagesPerCompany": 2,
                                "MaxLongTailBidShowsPerCompany": 1,
                                "MaxLiveOriginalNotices": 14,
                                "MaxLiveYgpOriginalNotices": 9,
                                "MaxLiveYgpBackfillTasks": 9,
                            },
                            "target_project_ids": [
                                "PROJ-CN-GD-JG2026-11408",
                                "PROJ-CN-GD-JG2026-11526",
                            ],
                            "live_execution_enabled_by_default": False,
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "run-stage1-6-sellable-rate-regression-v1.ps1"),
                    "-RunRoot",
                    str(root / "run"),
                    "-SourceRegressionRunRoot",
                    str(root / "source-run"),
                    "-Stage4BackfillFollowupQueueJson",
                    str(queue_json),
                    "-ApplyStage4FollowupExecutionPlan",
                    "-MaxLiveP13BCompanies",
                    "12",
                    "-DescribeEffectivePlanAndExit",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        payload = _json_from_stdout(completed.stdout)
        self.assertEqual(payload["source_regression_run_root"], str(root / "source-run"))
        self.assertTrue(payload["run_switches"]["RunP13BPublicSourceChain"])
        self.assertTrue(payload["run_switches"]["RunYgpBackfillFieldQuery"])
        self.assertTrue(payload["run_switches"]["RunStage6MergedProjection"])
        self.assertFalse(payload["run_switches"]["EnableLivePublicQuery"])
        self.assertFalse(payload["run_switches"]["EnableLiveBrowserExecution"])
        self.assertEqual(payload["budget_parameters"]["MaxLiveP13BCompanies"], 12)
        self.assertEqual(payload["budget_parameters"]["MaxLiveOriginalNotices"], 14)
        self.assertEqual(payload["budget_parameters"]["MaxLiveYgpOriginalNotices"], 9)
        self.assertEqual(payload["budget_parameters"]["MaxLiveYgpBackfillTasks"], 9)
        self.assertEqual(
            payload["target"]["ProjectIds"],
            "PROJ-CN-GD-JG2026-11408,PROJ-CN-GD-JG2026-11526",
        )
        self.assertFalse(payload["safety"]["customer_visible_allowed"])
        self.assertTrue(payload["safety"]["live_public_query_requires_explicit_switch"])
        self.assertTrue(payload["safety"]["query_miss_is_not_clearance"])

    def test_reuses_gdcic_readback_ref_from_scoreboard_when_source_run_lacks_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            queue_json = root / "stage4-backfill-followup-queue-v1.json"
            scoreboard_json = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            field_query_json = root / "reused-field-query" / "guangdong-local-field-query-probe-v1.json"
            gdcic_json = root / "reused-gdcic" / "gdcic-browser-authorized-readback-v1.json"
            field_query_json.parent.mkdir(parents=True)
            field_query_json.write_text(json.dumps({"summary": {"adapter_result_state_counts": {"NEEDS_BROWSER": 1}}}), encoding="utf-8")
            gdcic_json.parent.mkdir(parents=True)
            gdcic_json.write_text(json.dumps({"summary": {"authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT"}}), encoding="utf-8")
            scoreboard_json.parent.mkdir(parents=True)
            scoreboard_json.write_text(
                json.dumps(
                    {
                        "input_refs": {
                            "release_field_query_json": str(field_query_json),
                            "gdcic_browser_authorized_readback_json": str(gdcic_json),
                        },
                        "scoreboard": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            queue_json.write_text(
                json.dumps(
                    {
                        "input_refs": {"scoreboard_json": str(scoreboard_json)},
                        "next_regression_execution_plan": {
                            "recommended_switches": ["RunP13BPublicSourceChain"],
                            "target_project_ids": ["PROJ-CN-GD-JG2026-11408"],
                            "live_execution_enabled_by_default": False,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "run-stage1-6-sellable-rate-regression-v1.ps1"),
                    "-RunRoot",
                    str(root / "run"),
                    "-SourceRegressionRunRoot",
                    str(root / "source-run-without-gdcic"),
                    "-Stage4BackfillFollowupQueueJson",
                    str(queue_json),
                    "-ApplyStage4FollowupExecutionPlan",
                    "-DescribeEffectivePlanAndExit",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        payload = _json_from_stdout(completed.stdout)
        self.assertEqual(payload["input_refs"]["EffectiveFieldQueryRoot"], str(field_query_json.parent))
        self.assertEqual(payload["input_refs"]["EffectiveGdcicBrowserReadbackRoot"], str(gdcic_json.parent))
        self.assertTrue(payload["run_switches"]["RunP13BPublicSourceChain"])

    def test_reuses_pressure_root_from_prior_scoreboard_when_source_run_is_followup_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure_root = root / "baseline" / "pressure"
            pressure_summary_json = pressure_root / "pressure-summary.json"
            release_plan_json = pressure_root / "stage4-release-adapter-bridge-plan.json"
            queue_json = root / "followup" / "stage4-backfill-followup-queue-v1.json"
            scoreboard_json = root / "followup" / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            source_run_followup_only = root / "source-followup-only"
            (source_run_followup_only / "field-query").mkdir(parents=True)
            pressure_root.mkdir(parents=True)
            pressure_summary_json.write_text(json.dumps({"summary": {"candidate_count": 1}}), encoding="utf-8")
            release_plan_json.write_text(json.dumps({"tasks": []}), encoding="utf-8")
            scoreboard_json.parent.mkdir(parents=True)
            scoreboard_json.write_text(
                json.dumps(
                    {
                        "input_refs": {
                            "pressure_summary_json": str(pressure_summary_json),
                        },
                        "scoreboard": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            queue_json.parent.mkdir(parents=True, exist_ok=True)
            queue_json.write_text(
                json.dumps(
                    {
                        "input_refs": {"scoreboard_json": str(scoreboard_json)},
                        "next_regression_execution_plan": {
                            "recommended_switches": ["RunP13BPublicSourceChain"],
                            "target_project_ids": ["PROJ-CN-GD-JG2026-11526"],
                            "live_execution_enabled_by_default": False,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "run-stage1-6-sellable-rate-regression-v1.ps1"),
                    "-RunRoot",
                    str(root / "run"),
                    "-SourceRegressionRunRoot",
                    str(source_run_followup_only),
                    "-Stage4BackfillFollowupQueueJson",
                    str(queue_json),
                    "-ApplyStage4FollowupExecutionPlan",
                    "-DescribeEffectivePlanAndExit",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        payload = _json_from_stdout(completed.stdout)
        self.assertEqual(payload["input_refs"]["EffectivePressureRoot"], str(pressure_root))
        self.assertEqual(
            payload["target"]["ProjectIds"],
            "PROJ-CN-GD-JG2026-11526",
        )
        self.assertTrue(payload["run_switches"]["RunP13BPublicSourceChain"])
        self.assertFalse(payload["safety"]["customer_visible_allowed"])
        self.assertTrue(payload["safety"]["query_miss_is_not_clearance"])

    def test_prefers_followup_continuation_input_refs_for_effective_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pressure_root = root / "machine-refs" / "pressure"
            field_root = root / "machine-refs" / "field-query"
            gdcic_root = root / "machine-refs" / "gdcic-browser-authorized-readback"
            scoreboard_json = root / "machine-refs" / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            queue_json = root / "queue" / "stage4-backfill-followup-queue-v1.json"
            _write_json(pressure_root / "pressure-summary.json", {"summary": {"candidate_count": 1}})
            _write_json(pressure_root / "stage4-release-adapter-bridge-plan.json", {"tasks": []})
            _write_json(field_root / "guangdong-local-field-query-probe-v1.json", {"summary": {"adapter": "ready"}})
            _write_json(gdcic_root / "gdcic-browser-authorized-readback-v1.json", {"summary": {"auth": "missing"}})
            _write_json(scoreboard_json, {"scoreboard": {}})
            _write_json(
                queue_json,
                {
                    "input_refs": {"scoreboard_json": str(scoreboard_json)},
                    "continuation_input_refs": {
                        "prior_scoreboard_json": str(scoreboard_json),
                        "effective_pressure_root": str(pressure_root),
                        "effective_release_field_query_root": str(field_root),
                        "effective_gdcic_browser_readback_root": str(gdcic_root),
                        "customer_visible_allowed": False,
                        "query_miss_is_not_clearance": True,
                        "no_legal_conclusion": True,
                    },
                    "next_regression_execution_plan": {
                        "recommended_switches": ["RunP13BPublicSourceChain"],
                        "target_project_ids": ["PROJ-CN-GD-JG2026-11463-002"],
                        "live_execution_enabled_by_default": False,
                    },
                },
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "run-stage1-6-sellable-rate-regression-v1.ps1"),
                    "-RunRoot",
                    str(root / "run"),
                    "-SourceRegressionRunRoot",
                    str(root / "wrong-source-root"),
                    "-Stage4BackfillFollowupQueueJson",
                    str(queue_json),
                    "-ApplyStage4FollowupExecutionPlan",
                    "-DescribeEffectivePlanAndExit",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        payload = _json_from_stdout(completed.stdout)
        self.assertEqual(payload["input_refs"]["EffectivePressureRoot"], str(pressure_root))
        self.assertEqual(payload["input_refs"]["EffectiveFieldQueryRoot"], str(field_root))
        self.assertEqual(payload["input_refs"]["EffectiveGdcicBrowserReadbackRoot"], str(gdcic_root))
        self.assertEqual(payload["target"]["ProjectIds"], "PROJ-CN-GD-JG2026-11463-002")
        self.assertFalse(payload["safety"]["customer_visible_allowed"])


def _json_from_stdout(stdout: str) -> dict:
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"stdout did not contain JSON: {stdout}")
    return json.loads(stdout[start:])


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
