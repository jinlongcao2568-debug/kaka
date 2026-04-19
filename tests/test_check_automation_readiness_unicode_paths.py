from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-automation-readiness.ps1"
COPIED_FIXTURES = (
    "docs/自动化开发动作门禁表.md",
    "control/automation_action_matrix.yaml",
    "control/automation_stop_conditions.yaml",
    "control/automation_task_packet_rules.yaml",
    "control/review_gate_matrix.yaml",
    "control/owners.yaml",
)


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, capture_output=True, check=True)


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class TestCheckAutomationReadinessUnicodePaths(unittest.TestCase):
    def _build_temp_repo(
        self,
        *,
        baseline_dirty_paths: list[str] | None = None,
        tracked_pyc_dirty: bool = False,
        allow_dirty_doc_path: bool = True,
    ) -> tuple[Path, str]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        repo = Path(tempdir.name)

        for relative_path in COPIED_FIXTURES:
            source = ROOT / relative_path
            target = repo / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        dirty_relative_path = "docs/中文路径验证.md"
        dirty_file = repo / dirty_relative_path
        dirty_file.parent.mkdir(parents=True, exist_ok=True)
        dirty_file.write_text("baseline\n", encoding="utf-8")

        tracked_pyc_relative_path = "tests/__pycache__/tracked_case.cpython-311.pyc"
        tracked_pyc_file = repo / tracked_pyc_relative_path
        if tracked_pyc_dirty:
            tracked_pyc_file.parent.mkdir(parents=True, exist_ok=True)
            tracked_pyc_file.write_bytes(b"baseline-pyc\n")

        current_task = {
            "version": 1,
            "templateState": "NAMED_ASSIGNED",
            "single_operator_mode": True,
            "updated_at": "2026-04-18",
            "currentPhase": "PHASE_5_INTERNAL_LEADOPS_DEVELOPMENT",
            "currentStatus": "READY_FOR_POST-REPAIR_MAINLINE_SELECTION",
            "current_state": "READY_FOR_POST-REPAIR_MAINLINE_SELECTION",
            "currentTask": {
                "task_id": "AX9S-TEST-UNICODE-PATH-HOTFIX",
                "title": "Unicode path readiness hotfix",
                "owner_role": "single_operator",
                "responsible_role": "single_operator",
                "responsible_person": "卡卡罗特",
                "task_packet": {
                    "version": 1,
                    "packet_kind": "EXECUTABLE_SCOPED_SUBPACKET",
                    "source_blueprint_batch_id": "B10",
                    "packet_id": "TEST-UNICODE-PATH-HOTFIX",
                    "subpacket_id": "TEST-UNICODE-PATH-HOTFIX",
                    "title": "Unicode path readiness hotfix",
                    "status": "CLOSED",
                    "objective": "Verify readiness validator handles unicode git paths.",
                    "non_goals": [
                        "not an external unlock implementation",
                        "Do not change automation semantics.",
                    ],
                    "affected_stages": ["automation_control"],
                    "risk_level": "HIGH",
                    "change_class": "MANDATORY_HUMAN_REVIEW",
                    "change_domains": [
                        "automation_control_core",
                        "scripts_and_tests_general",
                    ],
                    "declared_changed_paths": [
                        "control/current_task.yaml",
                        "scripts/check-automation-readiness.ps1",
                        "tests/test_check_automation_readiness_unicode_paths.py",
                    ],
                    "allowed_modification_paths": [
                        "control/current_task.yaml",
                        "scripts/check-automation-readiness.ps1",
                        "tests/test_check_automation_readiness_unicode_paths.py",
                    ],
                    "forbidden_modification_paths": [
                        "docs/L0.md",
                        "contracts/**",
                        "handoff/**",
                        "src/**",
                    ],
                    "impacted_assets": {
                        "docs": [],
                        "control": ["control/current_task.yaml"],
                        "contracts": [],
                        "handoff": [],
                        "scripts": ["scripts/check-automation-readiness.ps1"],
                        "tests": ["tests/test_check_automation_readiness_unicode_paths.py"],
                        "code": [],
                    },
                    "required_scripts": [
                        "pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-automation-readiness.ps1",
                        "python tests/run_tests.py",
                    ],
                    "stop_conditions": [
                        "required script fails",
                        "forbidden path touched",
                    ],
                    "definition_of_done": [
                        "unicode git paths are accepted",
                    ],
                    "deliverables": [
                        "unicode-path hotfix",
                    ],
                    "human_review_required": True,
                    "owner_reviews_required": [
                        "automation_owner",
                        "governance_owner",
                        "testing_owner",
                    ],
                    "review_evidence": {
                        "declared": True,
                        "signoff_required": True,
                        "signoff_status": "REQUESTED_NOT_APPROVED",
                    },
                },
            },
        }
        if baseline_dirty_paths is not None:
            current_task["currentTask"]["task_packet"]["baseline_dirty_paths"] = baseline_dirty_paths
        if allow_dirty_doc_path:
            current_task["currentTask"]["task_packet"]["allowed_modification_paths"].append(
                dirty_relative_path
            )
        write_yaml(repo / "control/current_task.yaml", current_task)

        run(["git", "init"], cwd=repo)
        run(["git", "config", "user.name", "Codex Test"], cwd=repo)
        run(["git", "config", "user.email", "codex@example.com"], cwd=repo)
        run(["git", "config", "core.quotepath", "true"], cwd=repo)
        run(["git", "add", "."], cwd=repo)
        run(["git", "commit", "-m", "baseline"], cwd=repo)

        dirty_file.write_text("baseline\nchanged\n", encoding="utf-8")
        if tracked_pyc_dirty:
            tracked_pyc_file.write_bytes(b"baseline-pyc\nchanged\n")
        return repo, dirty_relative_path

    def test_script_accepts_unicode_dirty_paths_when_git_porcelain_is_escaped(self) -> None:
        repo, dirty_relative_path = self._build_temp_repo(baseline_dirty_paths=[])

        porcelain = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        self.assertIn(b"\\346", porcelain.stdout)
        self.assertNotIn(dirty_relative_path.encode("utf-8"), porcelain.stdout)

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-RepoRoot",
                str(repo),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=textwrap.dedent(
                f"""\
                stdout:
                {result.stdout}
                stderr:
                {result.stderr}
                """
            ),
        )
        self.assertIn("[check-automation-readiness] PASS", result.stdout)
        self.assertNotIn("ACTUAL_PATH_NOT_ALLOWED", result.stdout)

    def test_script_treats_missing_baseline_dirty_paths_as_empty_array(self) -> None:
        repo, _ = self._build_temp_repo()
        current_task = yaml.safe_load((repo / "control/current_task.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("baseline_dirty_paths", current_task["currentTask"]["task_packet"])

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-RepoRoot",
                str(repo),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=textwrap.dedent(
                f"""\
                stdout:
                {result.stdout}
                stderr:
                {result.stderr}
                """
            ),
        )
        self.assertIn("[check-automation-readiness] PASS", result.stdout)
        self.assertNotIn("ACTUAL_PATH_NOT_ALLOWED", result.stdout)

    def test_script_ignores_tracked_python_cache_and_respects_baseline_dirty_paths(self) -> None:
        dirty_relative_path = "docs/中文路径验证.md"
        repo, _ = self._build_temp_repo(
            baseline_dirty_paths=[dirty_relative_path],
            tracked_pyc_dirty=True,
            allow_dirty_doc_path=False,
        )

        porcelain = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        self.assertIn(b"\\346", porcelain.stdout)
        self.assertIn(b"tracked_case.cpython-311.pyc", porcelain.stdout)

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-RepoRoot",
                str(repo),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=textwrap.dedent(
                f"""\
                stdout:
                {result.stdout}
                stderr:
                {result.stderr}
                """
            ),
        )
        self.assertIn("[check-automation-readiness] PASS", result.stdout)
        self.assertNotIn("ACTUAL_PATH_NOT_ALLOWED", result.stdout)

    def test_script_python_yaml_fallback_keeps_unicode_baseline_paths(self) -> None:
        dirty_relative_path = "docs/中文路径验证.md"
        repo, _ = self._build_temp_repo(
            baseline_dirty_paths=[dirty_relative_path],
            allow_dirty_doc_path=False,
        )

        command = textwrap.dedent(
            f"""\
            function Get-Command {{
                param([string]$Name, [object]$ErrorAction)
                if ($Name -in @('ConvertFrom-Yaml', 'yq')) {{
                    return $null
                }}
                Microsoft.PowerShell.Core\\Get-Command -Name $Name -ErrorAction SilentlyContinue
            }}
            & '{SCRIPT}' -RepoRoot '{repo}'
            """
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=textwrap.dedent(
                f"""\
                stdout:
                {result.stdout}
                stderr:
                {result.stderr}
                """
            ),
        )
        self.assertIn("[check-automation-readiness] PASS", result.stdout)
        self.assertNotIn("ACTUAL_PATH_NOT_ALLOWED", result.stdout)


if __name__ == "__main__":
    unittest.main()
