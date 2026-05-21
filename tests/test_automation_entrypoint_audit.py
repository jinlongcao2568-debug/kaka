from __future__ import annotations

import sys
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.automation_entrypoint_audit import build_automation_entrypoint_audit


class TestAutomationEntrypointAudit(unittest.TestCase):
    def test_current_registry_passes_and_replaces_human_memory(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)

        self.assertTrue(result["safe_to_continue_automation"], result["blocking_reasons"])
        self.assertEqual(result["manifest"]["audit_state"], "PASS")
        self.assertGreaterEqual(result["summary"]["script_count"], 100)
        self.assertEqual(result["summary"]["unclassified_script_count"], 0)
        self.assertEqual(result["summary"]["external_customer_action_enabled_count"], 0)
        self.assertTrue(
            all(item["replaces_human_memory"] for item in result["manifest"]["formal_entrypoints"])
        )

    def test_stage6_loop_and_gdcic_openplatform_are_formal_entrypoints(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }

        self.assertIn("stage6_review_loop_runner", entrypoints)
        self.assertTrue(entrypoints["stage6_review_loop_runner"]["script_exists"])
        self.assertEqual(entrypoints["stage6_review_loop_runner"]["module_or_command"], "storage.stage6_review_loop_runner")

        self.assertIn("guangdong_gdcic_openplatform_query_probe", entrypoints)
        self.assertTrue(entrypoints["guangdong_gdcic_openplatform_query_probe"]["script_exists"])
        self.assertEqual(
            entrypoints["guangdong_gdcic_openplatform_query_probe"]["module_or_command"],
            "storage.guangdong_gdcic_query_probe",
        )

    def test_internal_stage1_6_route_is_declared_preview_only(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }
        route = entrypoints["stage1_6_internal_http_orchestration_preview"]

        self.assertEqual(route["kind"], "http_route")
        self.assertEqual(route["status"], "INTERNAL_PREVIEW_ONLY")
        self.assertTrue(route["route_exists"])
        self.assertFalse(route["external_customer_action_enabled"])

    def test_readme_documents_scripts_as_thin_entrypoints(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("automation_entrypoint_registry.yaml", readme)
        self.assertIn("脚本不是状态机本体", readme)

    def test_powershell_wrapper_emits_final_gate_compatible_json(self) -> None:
        script = ROOT / "scripts" / "audit-automation-entrypoints.ps1"
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-RepoRoot",
                str(ROOT),
                "-EmitJson",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stdout + completed.stderr)
        self.assertIn('"script"', completed.stdout)
        self.assertIn('"ok"', completed.stdout)
        self.assertIn('"issues"', completed.stdout)

    def test_final_gate_runs_automation_entrypoint_audit(self) -> None:
        final_gate = (ROOT / "scripts" / "check-final-gate.ps1").read_text(encoding="utf-8")

        self.assertIn("audit-automation-entrypoints.ps1", final_gate)


if __name__ == "__main__":
    unittest.main()
