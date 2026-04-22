from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASK_PACKET_SCRIPT = ROOT / "scripts" / "check-task-packet.ps1"
FIXTURES = (
    "docs/自动化开发动作门禁表.md",
    "control/automation_action_matrix.yaml",
    "control/automation_stop_conditions.yaml",
    "control/automation_task_packet_rules.yaml",
    "control/review_gate_matrix.yaml",
    "control/owners.yaml",
    "control/source_blueprint_registry.yaml",
    "control/operator_assignment_roster_defaults.yaml",
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


class TestReviewGateControls(unittest.TestCase):
    def _build_temp_repo_for_task_packet(self, *, declared_paths: list[str], allowed_paths: list[str]) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        repo = Path(tempdir.name)

        for relative_path in FIXTURES:
            source = ROOT / relative_path
            target = repo / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        stable_roster_source_ref = "control/operator_assignment_roster_defaults.yaml#defaults"
        stable_roster_defaults = yaml.safe_load((repo / "control/operator_assignment_roster_defaults.yaml").read_text(encoding="utf-8"))["defaults"]

        current_task = {
            "version": 1,
            "templateState": "NAMED_ASSIGNED",
            "single_operator_mode": True,
            "updated_at": "2026-04-20",
            "currentPhase": "PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT",
            "currentStatus": "READY_FOR_POST-REPAIR_MAINLINE_SELECTION",
            "current_state": "READY_FOR_POST-REPAIR_MAINLINE_SELECTION",
            "currentTask": {
                "task_id": "TEST-PRECHECK",
                "title": "precheck scope test",
                "owner_role": "single_operator",
                "responsible_role": "single_operator",
                "responsible_person": "卡卡罗特",
                "operator_assignment_roster_source_ref": stable_roster_source_ref,
                "operator_assignment_roster": stable_roster_defaults,
                "task_packet": {
                    "version": 1,
                    "packet_kind": "EXECUTABLE_SCOPED_SUBPACKET",
                    "source_blueprint_batch_id": "POST-FF-CONTROL-01",
                    "packet_id": "TEST-PRECHECK",
                    "subpacket_id": "TEST-PRECHECK",
                    "title": "precheck scope test",
                    "status": "ACTIVE",
                    "objective": "verify preflight scope enforcement",
                    "non_goals": ["do not relax readiness", "not an external unlock implementation"],
                    "affected_stages": ["automation_control"],
                    "risk_level": "HIGH",
                    "change_class": "MANDATORY_HUMAN_REVIEW",
                    "change_domains": ["automation_control_core", "governance_release_core"],
                    "declared_changed_paths": declared_paths,
                    "allowed_modification_paths": allowed_paths,
                    "forbidden_modification_paths": ["src/**", "contracts/**", "handoff/**"],
                    "impacted_assets": {"docs": [], "control": ["control/current_task.yaml"], "contracts": [], "handoff": [], "scripts": ["scripts/check-task-packet.ps1"], "tests": [], "runtime": []},
                    "required_scripts": ["pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-task-packet.ps1"],
                    "stop_conditions": ["required script fails", "actual changed path falls outside declared scope"],
                    "definition_of_done": ["preflight scope check works"],
                    "deliverables": ["scope preflight validation"],
                    "human_review_required": True,
                    "owner_reviews_required": ["automation_owner", "governance_owner", "testing_owner", "release_approver"],
                    "review_evidence": {"declared": True, "signoff_required": True, "signoff_status": "REQUESTED_NOT_APPROVED"},
                    "notes": ["current_task -> product_task_library -> repo_status"],
                },
            },
        }
        write_yaml(repo / "control/current_task.yaml", current_task)
        (repo / "control/product_task_library.yaml").write_text("version: 1\nrole: product_mainline_task_source\n", encoding="utf-8")
        (repo / "control/repo_status.md").write_text("Current Workstream: TEST\ncurrent_task -> product_task_library -> repo_status\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Codex Test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)
        return repo

    def _run_task_packet_check(self, repo: Path, planned_target_paths: list[str], *, via_array: bool = False) -> subprocess.CompletedProcess[str]:
        if via_array:
            quoted_paths = ", ".join(f"'{path}'" for path in planned_target_paths)
            command = textwrap.dedent(
                f"""\
                $paths = @({quoted_paths})
                & '{TASK_PACKET_SCRIPT}' -RepoRoot '{repo}' -PlannedTargetPaths $paths
                """
            )
            return subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        command = [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(TASK_PACKET_SCRIPT),
            "-RepoRoot",
            str(repo),
            "-PlannedTargetPaths",
            *planned_target_paths,
        ]
        return subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)

    def test_scripts_use_new_system(self) -> None:
        task_packet = read("scripts/check-task-packet.ps1")
        state = read("scripts/check-state-alignment.ps1")
        final_gate = read("scripts/check-final-gate.ps1")
        self.assertIn("control/source_blueprint_registry.yaml", task_packet)
        self.assertIn("control/operator_assignment_roster_defaults.yaml", task_packet)
        self.assertIn("control/product_task_library.yaml", state)
        self.assertIn("check-task-packet.ps1", final_gate)
        self.assertIn("check-state-alignment.ps1", final_gate)
        self.assertNotIn("check-automation-readiness.ps1", final_gate)
        self.assertNotIn("check-release.ps1", final_gate)

    def test_documents_use_new_system(self) -> None:
        agents = read("AGENTS.md")
        ax9s = read("docs/AX9S_开发执行路由图.md")
        template = read("docs/自动开发任务包模板.md")
        gate = read("docs/自动化开发动作门禁表.md")
        task_rules = read("control/automation_task_packet_rules.yaml")
        self.assertIn("current_task -> product_task_library -> repo_status", agents)
        self.assertIn("control/product_task_library.yaml", ax9s)
        self.assertIn("control/source_blueprint_registry.yaml#registered_blueprints", template)
        self.assertIn("scripts/check-task-packet.ps1", template)
        self.assertIn("-PlannedTargetPaths $paths", template)
        self.assertIn("单字符串逗号拼接形式有兼容处理", template)
        self.assertIn("-PlannedTargetPaths $paths", task_rules)
        self.assertIn("单字符串逗号拼接形式", task_rules)
        self.assertIn("check-final-gate.ps1", gate)
        self.assertIn("suggestion-only", ax9s)
        self.assertIn("manual_planning_review", ax9s)

    def test_product_planning_sync_registration_is_formalized(self) -> None:
        library = yaml.safe_load(read("control/product_task_library.yaml"))
        sync = library["planning_sync_implementation_registration"]
        self.assertEqual(sync["trigger_policy"], "warning_only")
        self.assertEqual(sync["implementation_state"], "IMPLEMENTED")
        self.assertTrue(sync["requires_human_confirmation"] if "requires_human_confirmation" in sync else sync["update_policy"]["requires_human_confirmation"])
        self.assertIn("manual_planning_review", sync["update_triggers"])

    def test_task_packet_preflight_accepts_array_planned_targets(self) -> None:
        repo = self._build_temp_repo_for_task_packet(
            declared_paths=["control/current_task.yaml", "control/repo_status.md"],
            allowed_paths=["control/current_task.yaml", "control/repo_status.md"],
        )
        result = self._run_task_packet_check(
            repo,
            ["control/current_task.yaml", "control/repo_status.md"],
            via_array=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("[check-task-packet] PASS", result.stdout)

    def test_task_packet_preflight_accepts_single_string_planned_target_variants(self) -> None:
        repo = self._build_temp_repo_for_task_packet(
            declared_paths=["control/current_task.yaml", "control/repo_status.md"],
            allowed_paths=["control/current_task.yaml", "control/repo_status.md"],
        )

        for raw_value in (
            "'control/current_task.yaml','control/repo_status.md'",
            '"control/current_task.yaml","control/repo_status.md"',
            "control/current_task.yaml,control/repo_status.md",
        ):
            with self.subTest(raw_value=raw_value):
                result = self._run_task_packet_check(repo, [raw_value])
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertIn("[check-task-packet] PASS", result.stdout)

    def test_task_packet_preflight_accepts_single_path(self) -> None:
        repo = self._build_temp_repo_for_task_packet(
            declared_paths=["control/current_task.yaml"],
            allowed_paths=["control/current_task.yaml"],
        )
        result = self._run_task_packet_check(repo, ["control/current_task.yaml"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("[check-task-packet] PASS", result.stdout)

    def test_task_packet_preflight_rejects_outside_declared_scope(self) -> None:
        repo = self._build_temp_repo_for_task_packet(declared_paths=["control/current_task.yaml"], allowed_paths=["control/current_task.yaml"])
        result = self._run_task_packet_check(repo, ["docs/outside.md"])
        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("PLANNED_PATH_NOT_DECLARED", result.stdout)

    def test_task_packet_rejects_missing_roster_source(self) -> None:
        repo = self._build_temp_repo_for_task_packet(declared_paths=["control/current_task.yaml"], allowed_paths=["control/current_task.yaml"])
        current_task_path = repo / "control/current_task.yaml"
        current_task = yaml.safe_load(current_task_path.read_text(encoding="utf-8"))
        del current_task["currentTask"]["operator_assignment_roster_source_ref"]
        write_yaml(current_task_path, current_task)
        result = subprocess.run([
            "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TASK_PACKET_SCRIPT),
            "-RepoRoot", str(repo)
        ], cwd=ROOT, check=False, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("OPERATOR_ROSTER_SOURCE_REF_MISSING", result.stdout)


if __name__ == "__main__":
    unittest.main()
