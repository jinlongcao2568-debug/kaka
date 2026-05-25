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


def _json_from_stdout(stdout: str) -> dict:
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"stdout did not contain JSON: {stdout}")
    return json.loads(stdout[start:])


if __name__ == "__main__":
    unittest.main()
