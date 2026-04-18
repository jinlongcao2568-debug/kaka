from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def extract_domain_block(text: str, domain_id: str) -> str:
    marker = f"  - domain_id: {domain_id}"
    start = text.index(marker)
    next_domain = text.find("\n  - domain_id:", start + len(marker))
    if next_domain == -1:
        next_domain = len(text)
    return text[start:next_domain]


class TestReviewGateControls(unittest.TestCase):
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

    def test_release_and_regression_assets_cover_review_gate(self) -> None:
        release = json.loads(read("contracts/testing/release_checklist.json"))
        release_item_ids = {
            item["itemId"]
            for section in release["sections"]
            for item in section["items"]
        }
        for item_id in ("REL-110", "REL-111", "REL-112", "REL-113", "REL-114"):
            self.assertIn(item_id, release_item_ids)

        regression = json.loads(read("contracts/testing/regression_manifest.json"))
        suite_ids = {suite["suite_id"] for suite in regression["suites"]}
        for suite_id in (
            "REG-CHANGE-CLASS-REVIEW-GATE",
            "REG-TASK-PACKET-HARD-GATE",
            "REG-REVIEW-GATE-STOP-LINKAGE",
            "REG-RELEASE-READINESS-REVIEW-GATE",
        ):
            self.assertIn(suite_id, suite_ids)

    def test_scripts_enforce_review_gate(self) -> None:
        readiness = read("scripts/check-automation-readiness.ps1")
        release = read("scripts/check-release.ps1")
        for token in (
            "DECLARED_CHANGE_CLASS_TOO_LOW",
            "OWNER_REVIEW_MISSING",
            "STOP_AND_ESCALATE_TRIGGERED",
            "control/review_gate_matrix.yaml",
        ):
            self.assertIn(token, readiness)
        self.assertIn("check-automation-readiness.ps1", release)
        self.assertIn("REL-110", release)
        self.assertIn("REG-CHANGE-CLASS-REVIEW-GATE", release)

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


if __name__ == "__main__":
    unittest.main()
