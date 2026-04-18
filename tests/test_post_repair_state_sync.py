from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_json(relative_path: str) -> dict:
    return json.loads(read_text(relative_path))


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read_text(relative_path))


class TestPostRepairStateSync(unittest.TestCase):
    def test_canonical_readiness_is_single_across_formal_sources(self) -> None:
        current_task = read_yaml("control/current_task.yaml")
        milestone = read_yaml("control/milestone_status.yaml")
        release_manifest = read_yaml("control/release_manifest.yaml")
        model_manifest = read_yaml("control/model_release_manifest.yaml")
        repo_status = read_text("control/repo_status.md")
        status_board = read_text("docs/文档与资产状态板.md")
        launch_page = read_text("docs/正式业务代码开发开工裁决页.md")

        canonical = "READY_FOR_POST-REPAIR_MAINLINE_SELECTION"
        values = {
            current_task["currentStatus"],
            current_task["current_state"],
            milestone["summary"]["current_readiness_conclusion"],
            release_manifest["future_external_unlock_decision"]["repo_readiness"],
            model_manifest["future_externalization_decision"]["repo_readiness"],
        }
        self.assertEqual(values, {canonical})
        self.assertIn(f"Current Readiness Conclusion: {canonical}", repo_status)
        self.assertIn(f"- 当前判断：`{canonical}`", status_board)
        self.assertIn(f"- 当前仓库总体 readiness：`{canonical}`", launch_page)

    def test_layered_state_dimensions_are_not_mixed_with_current_readiness(self) -> None:
        current_task = read_yaml("control/current_task.yaml")
        milestone = read_yaml("control/milestone_status.yaml")
        release_manifest = read_yaml("control/release_manifest.yaml")
        model_manifest = read_yaml("control/model_release_manifest.yaml")
        repo_status = read_text("control/repo_status.md")
        status_board = read_text("docs/文档与资产状态板.md")
        launch_page = read_text("docs/正式业务代码开发开工裁决页.md")

        expected_flags = {
            "candidate_gap_active": False,
            "strategic_branch_active": False,
            "closure_review_active": False,
            "closure_review_completed": True,
            "mainline_selection_ready": True,
        }

        for field_name, expected in expected_flags.items():
            self.assertEqual(current_task["state_dimensions"][field_name], expected, field_name)
            self.assertEqual(milestone["summary"][field_name], expected, field_name)
            self.assertEqual(release_manifest["future_external_unlock_decision"][field_name], expected, field_name)
            self.assertEqual(model_manifest["future_externalization_decision"][field_name], expected, field_name)

        self.assertIn("Candidate Gap Active: false", repo_status)
        self.assertIn("Strategic Branch Active: false", repo_status)
        self.assertIn("Closure Review Active: false", repo_status)
        self.assertIn("Closure Review Completed: true", repo_status)
        self.assertIn("Mainline Selection Ready: true", repo_status)
        self.assertIn("当前是否 candidate-gap：`否`", status_board)
        self.assertIn("当前是否 strategic-branch：`否`", status_board)
        self.assertIn("当前 closure review：`已关闭`", status_board)
        self.assertIn("当前 mainline selection：`就绪`", status_board)
        self.assertIn("当前是否 candidate-gap：`否`", launch_page)
        self.assertIn("当前是否 strategic-branch：`否`", launch_page)
        self.assertIn("当前 closure review：`已关闭`", launch_page)
        self.assertIn("当前 mainline selection：`就绪`", launch_page)

    def test_reference_index_and_historical_decision_state_roles_are_explicit(self) -> None:
        reference_index = read_json("control/reference_index.json")
        prerequisite_state = read_yaml("control/external_unlock_prerequisite_state.yaml")
        decision_state = read_yaml("control/future_unlock_decision_state.yaml")

        self.assertEqual(
            reference_index["formalStatusSources"],
            {
                "repoStatus": "control/repo_status.md",
                "currentTask": "control/current_task.yaml",
                "milestoneStatus": "control/milestone_status.yaml",
                "statusBoard": "docs/文档与资产状态板.md",
                "launchAdjudicationScope": "docs/正式业务代码开发开工裁决页.md",
                "releaseManifest": "control/release_manifest.yaml",
                "modelReleaseManifest": "control/model_release_manifest.yaml",
            },
        )
        self.assertEqual(
            reference_index["historicalDecisionState"],
            {
                "externalUnlockPrerequisiteState": "control/external_unlock_prerequisite_state.yaml",
                "futureUnlockDecisionState": "control/future_unlock_decision_state.yaml",
            },
        )
        self.assertEqual(prerequisite_state["repo_readiness_at_decision_time"], "READY_FOR_POST-R6_CANDIDATE_GAP_BATCH")
        self.assertEqual(decision_state["repo_readiness_at_decision_time"], "READY_FOR_POST-R6_CANDIDATE_GAP_BATCH")

    def test_h01_source_route_authority_is_closed(self) -> None:
        route_policy = read_json("contracts/governance/route_policy_catalog.json")["policies"][0]
        h01_contract = read_json("handoff/stage1_to_stage2/contract.json")
        h01_example = read_json("handoff/stage1_to_stage2/example.json")["payload"]
        handoff_catalog = read_json("handoff/stage_handoff_catalog.json")
        integration_rows = {
            row["contractId"]: row for row in read_json("handoff/integration_matrix.json")["rows"]
        }

        expected_h01_fields = {
            "source_registry_id",
            "route_policy_id",
            "default_route",
            "fallback_route",
        }
        self.assertTrue(expected_h01_fields.issubset(set(route_policy["required_h01_fields"])))
        self.assertTrue(expected_h01_fields.issubset(set(h01_contract["required_payload_fields"])))
        self.assertTrue(expected_h01_fields.issubset(set(h01_contract["consumer_runtime_required_fields"])))
        self.assertTrue(expected_h01_fields.issubset(set(h01_example.keys())))

        catalog_entry = next(
            entry for entry in handoff_catalog["handoffs"] if entry["handoff_id"] == "H-01-STAGE1-TO-STAGE2"
        )
        self.assertTrue(expected_h01_fields.issubset(set(catalog_entry["required_payload_fields"])))

        must_not_recompute = set(integration_rows["H-01-STAGE1-TO-STAGE2"]["consumerMustNotRecompute"])
        self.assertTrue(
            {
                "source_family",
                "platform_level",
                "region_scope",
                "coverage_tier",
                "source_registry_id",
                "route_policy_id",
                "default_route",
                "fallback_route",
            }.issubset(must_not_recompute)
        )


if __name__ == "__main__":
    unittest.main()
