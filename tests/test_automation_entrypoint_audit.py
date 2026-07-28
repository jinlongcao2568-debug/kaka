from __future__ import annotations

import sys
import subprocess
import unittest
from pathlib import Path

import yaml


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

    def test_stage6_loop_cycle_and_gdcic_openplatform_are_formal_entrypoints(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }

        self.assertIn("stage6_review_loop_runner", entrypoints)
        self.assertTrue(entrypoints["stage6_review_loop_runner"]["script_exists"])
        self.assertEqual(entrypoints["stage6_review_loop_runner"]["status"], "SUPPORTING_TOOL")
        self.assertEqual(entrypoints["stage6_review_loop_runner"]["module_or_command"], "storage.stage6_review_loop_runner")
        self.assertEqual(
            entrypoints["stage6_review_loop_runner"]["superseded_by_entrypoint_id"],
            "stage6_review_cycle_runner",
        )
        self.assertEqual(
            entrypoints["stage6_review_loop_runner"]["cleanup_state"],
            "retained_for_compatibility_and_sample_replay_only",
        )
        self.assertEqual(
            entrypoints["stage6_review_loop_runner"]["purpose"],
            "Compatibility runner for older Stage6 review-loop artifacts; new continuation should use stage6_review_cycle_runner or runtime_controller_entrypoint_transport.",
        )

        self.assertIn("stage6_review_cycle_runner", entrypoints)
        self.assertTrue(entrypoints["stage6_review_cycle_runner"]["script_exists"])
        self.assertEqual(entrypoints["stage6_review_cycle_runner"]["status"], "FORMAL_CURRENT")
        self.assertEqual(entrypoints["stage6_review_cycle_runner"]["module_or_command"], "storage.stage6_review_cycle_runner")

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

    def test_operator_long_task_browser_worker_is_formal(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }
        worker = entrypoints["operator_long_task_browser_worker"]

        self.assertEqual(worker["kind"], "script")
        self.assertEqual(worker["status"], "FORMAL_CURRENT")
        self.assertEqual(worker["entrypoint_role"], "orchestrator")
        self.assertTrue(worker["script_exists"])
        self.assertEqual(worker["module_or_command"], "runtime.operator_long_task_worker")
        self.assertTrue(worker["module_exists"])
        self.assertFalse(worker["external_customer_action_enabled"])

    def test_runtime_controller_entrypoint_transport_is_formal_supporting_tool(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }
        transport = entrypoints["runtime_controller_entrypoint_transport"]

        self.assertEqual(transport["kind"], "script")
        self.assertEqual(transport["status"], "SUPPORTING_TOOL")
        self.assertEqual(transport["entrypoint_role"], "orchestrator")
        self.assertEqual(transport["script"], "scripts/run-runtime-entrypoint.ps1")
        self.assertTrue(transport["script_exists"])
        self.assertEqual(transport["module_or_command"], "runtime.entrypoint_cli")
        self.assertTrue(transport["module_exists"])
        self.assertFalse(transport["external_customer_action_enabled"])
        self.assertTrue(transport["replaces_human_memory"])

    def test_stage1_3_repair_worker_is_registered_internal_dispatch_runner(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }
        worker = entrypoints["stage1_3_repair_worker"]

        self.assertEqual(worker["kind"], "script")
        self.assertEqual(worker["status"], "FORMAL_CURRENT")
        self.assertEqual(worker["entrypoint_role"], "dispatch_runner")
        self.assertEqual(worker["script"], "scripts/run-runtime-entrypoint.ps1")
        self.assertTrue(worker["script_exists"])
        self.assertEqual(worker["module_or_command"], "runtime.stage13_repair_worker")
        self.assertTrue(worker["module_exists"])
        self.assertFalse(worker["external_customer_action_enabled"])
        self.assertTrue(worker["replaces_human_memory"])

    def test_gdcic_authorized_readback_builder_is_registered_state_builder(self) -> None:
        result = build_automation_entrypoint_audit(repo_root=ROOT)
        entrypoints = {
            item["entrypoint_id"]: item
            for item in result["manifest"]["formal_entrypoints"]
        }
        builder = entrypoints["gdcic_browser_authorized_readback_builder"]

        self.assertEqual(builder["kind"], "script")
        self.assertEqual(builder["status"], "FORMAL_CURRENT")
        self.assertEqual(builder["entrypoint_role"], "state_builder")
        self.assertEqual(builder["script"], "scripts/build-gdcic-browser-authorized-readback-v1.ps1")
        self.assertTrue(builder["script_exists"])
        self.assertEqual(builder["module_or_command"], "storage.gdcic_browser_authorized_readback")
        self.assertTrue(builder["module_exists"])
        self.assertFalse(builder["external_customer_action_enabled"])
        self.assertTrue(builder["replaces_human_memory"])

    def test_readme_documents_scripts_as_thin_entrypoints(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("automation_entrypoint_registry.yaml", readme)
        self.assertIn("脚本不是状态机本体", readme)

    def test_stage1_6_direct_dev_focus_guardrails_are_explicit(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        repo_status = (ROOT / "control" / "repo_status.md").read_text(encoding="utf-8")
        registry_text = (ROOT / "control" / "automation_entrypoint_registry.yaml").read_text(encoding="utf-8")
        operability_gap_matrix = (
            ROOT / "control" / "product_operability_gap_matrix.yaml"
        ).read_text(encoding="utf-8")
        current_task = yaml.safe_load((ROOT / "control" / "current_task.yaml").read_text(encoding="utf-8"))
        stage1_6_plan = yaml.safe_load(
            (ROOT / "control" / "stage1_6_priority_execution_plan.yaml").read_text(encoding="utf-8")
        )

        self.assertIn("NO_ACTIVE_PRODUCT_MAINLINE_PACKET", repo_status)
        self.assertEqual(current_task["currentTask"]["task_packet"]["status"], "COMPLETED")
        self.assertIn("HISTORICAL_COMPLETED_NOT_ACTIVE_FOR_ORDINARY_DIRECT_DEV", str(stage1_6_plan))
        self.assertEqual(stage1_6_plan["current_focus"]["priority_id"], "P0_STAGE4_RELEASE_EVIDENCE_CHAIN")
        self.assertIn("control/stage1_6_priority_execution_plan.yaml#current_focus", readme)
        self.assertIn("control/stage1_6_priority_execution_plan.yaml#current_focus", agents)
        self.assertIn("No product mainline packet is active", operability_gap_matrix)
        self.assertIn("P0_STAGE4_RELEASE_EVIDENCE_CHAIN", operability_gap_matrix)
        self.assertNotIn("PTL-I100-148 as the active", operability_gap_matrix)

        guardrails = stage1_6_plan["agent_execution_guardrails"]
        self.assertEqual(
            guardrails["ordinary_direct_dev_current_focus_ref"],
            "control/stage1_6_priority_execution_plan.yaml#current_focus",
        )
        self.assertIn("control/product_runtime_agent_registry.yaml", guardrails["absent_state_sources"])
        self.assertIn("authorization_readiness_state=LOGIN_OR_SSO_REQUIRED", guardrails["authorization_gap_policy"])
        self.assertIn("do_not_invent_product_autonomous_entrypoint_names_when_registry_has_formal_entrypoints", guardrails["forbidden_inference"])
        self.assertIn("do_not_use_legacy_stage_range_entrypoint_names", guardrails["forbidden_inference"])

        actual_entrypoints = {
            item["entrypoint_id"]
            for item in build_automation_entrypoint_audit(repo_root=ROOT)["manifest"]["formal_entrypoints"]
        }
        self.assertTrue(set(guardrails["stage1_6_p0_formal_entrypoints"]).issubset(actual_entrypoints))
        self.assertIn("stage1_6_real_public_pressure_runner", readme)
        self.assertIn("stage4_release_evidence_bridge_builder", readme)
        self.assertIn("stage6_review_cycle_runner", readme)
        self.assertIn("stage1_6_real_public_pressure_runner", registry_text)
        self.assertIn("stage4_release_evidence_bridge_builder", registry_text)
        self.assertIn("stage6_review_cycle_runner", registry_text)
        self.assertIn("stage6_review_cycle_runner", repo_status)
        old_pressure_entrypoint = "stage4" + "_9_real_public_pressure_runner"
        old_bridge_entrypoint = "stage4" + "_9_release_bridge_builder"
        self.assertNotIn(old_pressure_entrypoint, registry_text)
        self.assertNotIn(old_bridge_entrypoint, registry_text)
        removed_compat_status = "LEGACY" + "_COMPATIBLE"
        self.assertNotIn(removed_compat_status, registry_text)
        self.assertIn("guangdong_local_field_query_probe", repo_status)
        self.assertIn("NEEDS_AUTH", readme)
        self.assertIn("authorization_readiness_state=LOGIN_OR_SSO_REQUIRED", readme)

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
