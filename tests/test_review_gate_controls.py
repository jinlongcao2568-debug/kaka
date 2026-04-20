from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
READINESS_SCRIPT = ROOT / "scripts" / "check-automation-readiness.ps1"
READINESS_FIXTURES = (
    "docs/自动化开发动作门禁表.md",
    "control/automation_action_matrix.yaml",
    "control/automation_stop_conditions.yaml",
    "control/automation_task_packet_rules.yaml",
    "control/review_gate_matrix.yaml",
    "control/owners.yaml",
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def extract_domain_block(text: str, domain_id: str) -> str:
    marker = f"  - domain_id: {domain_id}"
    start = text.index(marker)
    next_domain = text.find("\n  - domain_id:", start + len(marker))
    if next_domain == -1:
        next_domain = len(text)
    return text[start:next_domain]


class TestReviewGateControls(unittest.TestCase):
    def _build_temp_repo_for_readiness(
        self,
        *,
        declared_paths: list[str],
        allowed_paths: list[str],
    ) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        repo = Path(tempdir.name)

        for relative_path in READINESS_FIXTURES:
            source = ROOT / relative_path
            target = repo / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

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
                "task_packet": {
                    "version": 1,
                    "packet_kind": "EXECUTABLE_SCOPED_SUBPACKET",
                    "source_blueprint_batch_id": "POST-FF-CONTROL-01",
                    "packet_id": "TEST-PRECHECK",
                    "subpacket_id": "TEST-PRECHECK",
                    "title": "precheck scope test",
                    "status": "ACTIVE",
                    "objective": "verify preflight scope enforcement",
                    "non_goals": [
                        "do not relax readiness",
                        "not an external unlock implementation",
                    ],
                    "affected_stages": ["automation_control"],
                    "risk_level": "HIGH",
                    "change_class": "MANDATORY_HUMAN_REVIEW",
                    "change_domains": [
                        "automation_control_core",
                        "governance_release_core",
                    ],
                    "declared_changed_paths": declared_paths,
                    "allowed_modification_paths": allowed_paths,
                    "forbidden_modification_paths": [
                        "src/**",
                        "contracts/**",
                        "handoff/**",
                    ],
                    "impacted_assets": {
                        "docs": [],
                        "control": ["control/current_task.yaml"],
                        "contracts": [],
                        "handoff": [],
                        "scripts": ["scripts/check-automation-readiness.ps1"],
                        "tests": [],
                        "runtime": [],
                    },
                    "required_scripts": [
                        "pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/check-automation-readiness.ps1",
                    ],
                    "stop_conditions": [
                        "required script fails",
                        "actual changed path falls outside declared scope",
                    ],
                    "definition_of_done": [
                        "preflight scope check works",
                    ],
                    "deliverables": [
                        "scope preflight validation",
                    ],
                    "human_review_required": True,
                    "owner_reviews_required": [
                        "automation_owner",
                        "governance_owner",
                        "testing_owner",
                        "release_approver",
                    ],
                    "review_evidence": {
                        "declared": True,
                        "signoff_required": True,
                        "signoff_status": "REQUESTED_NOT_APPROVED",
                    },
                },
            },
        }
        write_yaml(repo / "control/current_task.yaml", current_task)

        tracked_rule_file = repo / "control/automation_task_packet_rules.yaml"
        tracked_rule_file.write_text(
            tracked_rule_file.read_text(encoding="utf-8") + "\n# baseline\n",
            encoding="utf-8",
        )

        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Codex Test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)
        return repo

    def test_review_gate_matrix_defines_required_classes_and_domains(self) -> None:
        text = read("control/review_gate_matrix.yaml")
        for token in (
            "LOW_RISK_DIRECT",
            "DRAFT_WITH_REVIEW",
            "MANDATORY_HUMAN_REVIEW",
            "STOP_AND_ESCALATE",
            "shared_runtime_core",
            "governance_release_core",
            "provider_vendor_source_policy_core",
            "stage8_stage9_high_risk_execution",
            "automation_control_core",
        ):
            self.assertIn(token, text)

    def test_current_task_packet_declares_hard_fields(self) -> None:
        text = read("control/current_task.yaml")
        for token in (
            "task_packet:",
            "declared_changed_paths:",
            "allowed_modification_paths:",
            "forbidden_modification_paths:",
            "required_scripts:",
            "stop_conditions:",
            "definition_of_done:",
            "deliverables:",
            "change_class:",
            "change_domains:",
            "human_review_required:",
            "owner_reviews_required:",
            "review_evidence:",
        ):
            self.assertIn(token, text)
        self.assertNotIn("启动前 readiness review 已通过", text)

    def test_release_and_regression_assets_cover_review_gate(self) -> None:
        release = json.loads(read("contracts/testing/release_checklist.json"))
        release_item_ids = {
            item["itemId"]
            for section in release["sections"]
            for item in section["items"]
        }
        for item_id in ("REL-110", "REL-111", "REL-112", "REL-113", "REL-114", "REL-193", "REL-194"):
            self.assertIn(item_id, release_item_ids)

        regression = json.loads(read("contracts/testing/regression_manifest.json"))
        suite_ids = {suite["suite_id"] for suite in regression["suites"]}
        for suite_id in (
            "REG-CHANGE-CLASS-REVIEW-GATE",
            "REG-TASK-PACKET-HARD-GATE",
            "REG-REVIEW-GATE-STOP-LINKAGE",
            "REG-RELEASE-READINESS-REVIEW-GATE",
            "REG-RELEASE-UMBRELLA-COVERAGE",
        ):
            self.assertIn(suite_id, suite_ids)

    def test_scripts_enforce_review_gate(self) -> None:
        readiness = read("scripts/check-automation-readiness.ps1")
        release = read("scripts/check-release.ps1")
        for token in (
            "DECLARED_CHANGE_CLASS_TOO_LOW",
            "OWNER_REVIEW_MISSING",
            "STOP_AND_ESCALATE_TRIGGERED",
            "PLANNED_PATH_NOT_DECLARED",
            "ACTUAL_PATH_NOT_ALLOWED",
            "PlannedTargetPaths",
            "control/review_gate_matrix.yaml",
        ):
            self.assertIn(token, readiness)
        self.assertIn("check-automation-readiness.ps1", release)
        self.assertIn("doctor.ps1", release)
        self.assertIn("check-handoff-dependencies.ps1", release)
        self.assertIn("REL-110", release)
        self.assertIn("REL-193", release)
        self.assertIn("REL-194", release)
        self.assertIn("REG-CHANGE-CLASS-REVIEW-GATE", release)
        self.assertIn("REG-RELEASE-UMBRELLA-COVERAGE", release)
        self.assertIn("REG-BLUEPRINT-REGISTRY-COMPATIBILITY", release)
        self.assertIn("UNREGISTERED_SOURCE_BLUEPRINT_BATCH", release)
        self.assertIn("control/task_packet_library.yaml", release)
        self.assertNotIn("CURRENT_TASK_PACKET_ID_MISMATCH", release)
        self.assertIn("sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))", readiness)
        self.assertIn("sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))", release)

    def test_check_release_reads_step_issues_defensively(self) -> None:
        release = read("scripts/check-release.ps1")

        self.assertIn("Get-FieldValue -Object $sr -Name 'result'", release)
        self.assertIn("Get-FieldValue -Object $resultObject -Name 'issues'", release)
        self.assertNotIn("$sr.result.issues", release)

    def test_baseline_dirty_paths_remains_optional_and_script_handles_missing_field(self) -> None:
        task_rules = read("control/automation_task_packet_rules.yaml")
        readiness = read("scripts/check-automation-readiness.ps1")

        self.assertIn("baseline_dirty_paths is optional but recommended", task_rules)
        self.assertIn("planned_target_path_not_declared", task_rules)
        self.assertIn("planned target paths are a preflight input", task_rules)
        self.assertIn("Get-FieldValue -Object $taskPacket -Name 'baseline_dirty_paths'", readiness)
        self.assertNotIn("$taskPacket.baseline_dirty_paths", readiness)

    def test_readiness_preflight_rejects_planned_target_outside_declared_scope(self) -> None:
        repo = self._build_temp_repo_for_readiness(
            declared_paths=["control/current_task.yaml"],
            allowed_paths=["control/current_task.yaml"],
        )

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(READINESS_SCRIPT),
                "-RepoRoot",
                str(repo),
                "-PlannedTargetPaths",
                "docs/outside.md",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("PLANNED_PATH_NOT_DECLARED", result.stdout)

    def test_readiness_rejects_actual_changed_path_outside_allowed_scope(self) -> None:
        repo = self._build_temp_repo_for_readiness(
            declared_paths=["control/current_task.yaml"],
            allowed_paths=["control/current_task.yaml"],
        )

        tracked_rule_file = repo / "control/automation_task_packet_rules.yaml"
        tracked_rule_file.write_text(
            tracked_rule_file.read_text(encoding="utf-8") + "\n# dirty-change\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(READINESS_SCRIPT),
                "-RepoRoot",
                str(repo),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("ACTUAL_PATH_NOT_ALLOWED", result.stdout)

    def test_validate_contracts_stage9_writeback_check_is_semantic_not_legacy_token_bound(self) -> None:
        validator = read("scripts/validate-contracts.ps1")

        self.assertIn("writeback_target_resolution = self.impact_executor.resolve_effective_targets(", validator)
        self.assertIn('writeback_source_contracts=writeback_target_resolution["writeback_source_contracts"]', validator)
        self.assertIn('writeback_target_sources=writeback_target_resolution["writeback_target_sources"]', validator)
        self.assertIn("WRITEBACK_SOURCE_CONTRACTS_MISSING", validator)
        self.assertIn("WRITEBACK_SOURCE_CONTRACT_MISSING", validator)
        self.assertIn("WRITEBACK_SOURCE_CONTRACT_INCOMPLETE", validator)
        self.assertIn("STAGE9_WRITEBACK_VALIDATOR_DRIFT", validator)
        self.assertIn("def resolve_effective_targets(", read("src/stage9_delivery/impact_executor.py"))
        self.assertIn("writeback_source_contracts", read("contracts/governance/writeback_impact_policy.json"))
        self.assertNotIn('effective_writeback_targets = list(outcome_writeback_targets)', validator)
        self.assertNotIn('if target not in effective_writeback_targets:', validator)

    def test_vendor_registry_catalog_is_mandatory_human_review(self) -> None:
        text = read("control/review_gate_matrix.yaml")
        provider_domain = extract_domain_block(text, "provider_vendor_source_policy_core")

        self.assertIn("change_class: MANDATORY_HUMAN_REVIEW", provider_domain)
        self.assertIn('"contracts/sales/vendor_registry_catalog.json"', provider_domain)
        self.assertIn('"architecture_owner"', provider_domain)
        self.assertIn('"governance_owner"', provider_domain)

        readiness = read("scripts/check-automation-readiness.ps1")
        self.assertIn("contracts/sales/vendor_registry_catalog.json", readiness)
        self.assertIn("REVIEW_GATE_PATH_CLASS_MISMATCH", readiness)
        self.assertIn("REVIEW_GATE_PATH_OWNER_MISSING", readiness)

    def test_deleted_blueprint_doc_is_not_referenced_by_task_packet_library(self) -> None:
        self.assertNotIn(
            "docs/AX9S_高+中任务包蓝图.md",
            read("control/task_packet_library.yaml"),
        )


if __name__ == "__main__":
    unittest.main()
