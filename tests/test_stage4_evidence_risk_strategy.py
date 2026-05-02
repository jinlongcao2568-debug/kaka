from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from stage4_verification.hard_defect_strategy import (
    READY_FOR_PUBLIC_VERIFICATION,
    REVIEW_REQUIRED,
)
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service


def _field(
    name: str,
    value: str,
    *,
    confidence: float = 0.91,
    source_file_ref: str = "SNAP-HARD-DEFECT-001",
    source_slice_sha256: str | None = None,
    review_required: bool = False,
) -> dict[str, object]:
    return {
        "field_name": name,
        "field_value_optional": value,
        "source_file_ref": source_file_ref,
        "source_slice": f"{name}: {value}",
        "source_slice_sha256": source_slice_sha256 if source_slice_sha256 is not None else f"SHA-{name}",
        "confidence": confidence,
        "parser_version": "stage3-real-parser-v1",
        "review_required": review_required,
    }


def _parsed_context(*, weak: bool = False) -> dict[str, object]:
    confidence = 0.62 if weak else 0.91
    source_slice_sha256 = "" if weak else None
    return {
        "parse_run_id": "PARSE-HARD-DEFECT-001",
        "snapshot_id": "SNAP-HARD-DEFECT-001",
        "source_url": "https://example.invalid/public/hard-defect.html",
        "lineage_status": "NORMALIZED",
        "conflict_state": "CONSISTENT",
        "parsed_fields": [
            _field("project_name", "City road expansion", confidence=confidence),
            _field("bidder_name", "Alpha Construction Co", confidence=confidence),
            _field("project_manager_name", "Li Wei", confidence=confidence),
            _field(
                "project_manager_public_identifier_optional",
                "" if weak else "CERT-PM-001",
                confidence=confidence,
                source_slice_sha256=source_slice_sha256,
                review_required=weak,
            ),
            _field("qualification_certificate", "QUAL-A-001", confidence=confidence),
            _field("credit_penalty_record", "CREDIT-PENALTY-001", confidence=confidence),
            _field("construction_permit_no", "PERMIT-001", confidence=confidence),
            _field("contract_record_no", "CONTRACT-001", confidence=confidence),
            _field("completion_filing_no", "COMPLETION-001", confidence=confidence),
            _field("performance_record_no", "PERFORMANCE-001", confidence=confidence),
            _field("procedure_timeline_marker", "NOTICE-CLOCK-001", confidence=confidence),
        ],
    }


def _stage4_bundle_with_inputs(extra_inputs: dict[str, object]) -> StageBundle:
    stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
    return StageBundle(
        stage=4,
        records=dict(stage4.records),
        handoff=dict(stage4.handoff),
        trace_rules=list(stage4.trace_rules),
        inputs={**stage4.inputs, **extra_inputs},
    )


class Stage4EvidenceRiskStrategyTests(unittest.TestCase):
    def test_strategy_selects_hard_defect_public_verification_targets_from_stage3_fields(self) -> None:
        strategy = Stage4Service().build_evidence_risk_hard_defect_strategy(_parsed_context())
        readback = Stage4Service().build_evidence_risk_hard_defect_strategy_readback(strategy)

        self.assertTrue(strategy["strategy_run_id"].startswith("ST4HDS-"))
        self.assertEqual(strategy["evidence_risk_state"], READY_FOR_PUBLIC_VERIFICATION)
        self.assertFalse(strategy["review_required"])
        self.assertTrue(strategy["public_verification_required"])
        self.assertTrue(strategy["weak_evidence_fails_closed"])
        self.assertFalse(strategy["customer_visible"])
        self.assertTrue(strategy["no_llm_fact_adjudication"])
        self.assertFalse(strategy["llm_allowed_for_verification_decision"])

        strategy_keys = {target["strategy_key"] for target in strategy["strategy_targets"]}
        self.assertTrue(
            {
                "project_manager_active_conflict",
                "enterprise_qualification",
                "credit_penalty_blacklist",
                "construction_permit",
                "contract_public_info",
                "completion_filing",
                "performance_public_record",
                "procedure_public_notice_timeline",
            }.issubset(strategy_keys)
        )
        target_types = {target["verification_target_type"] for target in strategy["verification_targets"]}
        self.assertTrue(
            {
                "personnel_public_record",
                "enterprise_public_record",
                "enterprise_qualification",
                "credit_penalty_blacklist",
                "construction_permit",
                "contract_public_info",
                "completion_filing",
                "performance_public_record",
                "public_notice_timeline",
            }.issubset(target_types)
        )
        active_conflict_target = next(
            target
            for target in strategy["strategy_targets"]
            if target["strategy_key"] == "project_manager_active_conflict"
        )
        source_families = active_conflict_target["preferred_source_families"]
        self.assertLess(
            source_families.index("public_resource_trading_platform"),
            source_families.index("national_construction_market_platform"),
        )
        self.assertLess(
            source_families.index("local_housing_construction_permit_platform"),
            source_families.index("national_construction_market_platform"),
        )
        chain_roles = {
            role["role"]: role
            for role in active_conflict_target["verification_chain_roles"]
        }
        self.assertTrue(
            {
                "award_commitment_chain",
                "performance_time_chain",
                "contract_filing_chain",
                "completion_release_chain",
                "manager_change_chain",
                "identity_archive_chain",
                "risk_signal_chain",
            }.issubset(chain_roles)
        )
        self.assertIn("not sole no-risk proof", chain_roles["identity_archive_chain"]["gate_use"])
        conflict_verification_target = next(
            target
            for target in strategy["verification_targets"]
            if target["strategy_key"] == "project_manager_active_conflict"
            and target["verification_target_type"] == "contract_public_info"
        )
        self.assertIn(
            "completion_release_chain",
            {role["role"] for role in conflict_verification_target["verification_chain_roles"]},
        )
        self.assertEqual(
            strategy["stage5_requested_rule_codes"],
            [
                "PM-001",
                "PM-002",
                "QUAL-001",
                "CREDIT-001",
                "ENG-001",
                "ENG-002",
                "PERF-001",
                "PROC-001",
                "PROC-002",
            ],
        )
        self.assertEqual(readback["readback_state"], "READBACK_READY")
        self.assertFalse(readback["fail_closed"])
        self.assertIn("project_base", readback["stage5_supported_upstream_objects"])

    def test_procedure_strategy_plans_public_notice_timeline_target(self) -> None:
        context = {
            "parse_run_id": "PARSE-PROC-146",
            "snapshot_id": "SNAP-PROC-146",
            "project_id": "PROJECT-PROC-146",
            "source_url": "https://example.invalid/public/procedure.html",
            "lineage_status": "NORMALIZED",
            "conflict_state": "CONSISTENT",
            "parsed_fields": [
                _field("procedure_timeline_marker", "NOTICE-CLOCK-146"),
            ],
        }

        strategy = Stage4Service().build_evidence_risk_hard_defect_strategy(context)

        self.assertEqual(strategy["evidence_risk_state"], READY_FOR_PUBLIC_VERIFICATION)
        self.assertEqual(strategy["stage5_requested_rule_codes"], ["PROC-001", "PROC-002"])
        self.assertEqual(
            [target["verification_target_type"] for target in strategy["verification_targets"]],
            ["public_notice_timeline"],
        )
        self.assertFalse(strategy["fail_closed"])

    def test_project_manager_strategy_uses_manager_or_company_as_conflict_search_identifier(self) -> None:
        context = {
            "parse_run_id": "PARSE-PM-SEARCH-146",
            "snapshot_id": "SNAP-PM-SEARCH-146",
            "project_id": "PROJECT-PM-SEARCH-146",
            "source_url": "https://example.invalid/public/project-manager.html",
            "lineage_status": "NORMALIZED",
            "conflict_state": "CONSISTENT",
            "parsed_fields": [
                _field("project_manager_name", "Li Wei"),
                _field("project_manager_public_identifier_optional", "CERT-PM-001"),
                _field("bidder_name", "Alpha Construction Co"),
            ],
        }

        strategy = Stage4Service().build_evidence_risk_hard_defect_strategy(context)
        targets = {
            target["verification_target_type"]: target
            for target in strategy["verification_targets"]
        }

        self.assertEqual(strategy["evidence_risk_state"], READY_FOR_PUBLIC_VERIFICATION)
        self.assertFalse(strategy["fail_closed"])
        for target_type in ("performance_public_record", "contract_public_info", "completion_filing"):
            self.assertEqual(targets[target_type]["target_identifier"], "CERT-PM-001")
            self.assertFalse(targets[target_type]["missing_identifier"])
        self.assertNotIn("target_identifier_missing", strategy["fail_closed_reasons"])

    def test_company_only_context_starts_enterprise_credit_and_performance_precheck(self) -> None:
        context = {
            "parse_run_id": "PARSE-COMPANY-FIRST-146",
            "snapshot_id": "SNAP-COMPANY-FIRST-146",
            "project_id": "PROJECT-COMPANY-FIRST-146",
            "source_url": "https://example.invalid/public/company-first.html",
            "lineage_status": "NORMALIZED",
            "conflict_state": "CONSISTENT",
            "parsed_fields": [
                _field("project_name", "City school renovation supervision"),
                _field("candidate_company_name", "Alpha Construction Co"),
            ],
        }

        strategy = Stage4Service().build_evidence_risk_hard_defect_strategy(context)
        strategy_keys = {target["strategy_key"] for target in strategy["strategy_targets"]}
        targets = {
            target["verification_target_type"]: target
            for target in strategy["verification_targets"]
        }

        self.assertEqual(strategy["evidence_risk_state"], READY_FOR_PUBLIC_VERIFICATION)
        self.assertFalse(strategy["fail_closed"])
        self.assertTrue(
            {
                "enterprise_qualification",
                "credit_penalty_blacklist",
                "performance_public_record",
            }.issubset(strategy_keys)
        )
        for target_type in (
            "enterprise_public_record",
            "enterprise_qualification",
            "credit_penalty_blacklist",
            "performance_public_record",
        ):
            self.assertEqual(targets[target_type]["target_identifier"], "Alpha Construction Co")
            self.assertFalse(targets[target_type]["missing_identifier"])

    def test_weak_or_ambiguous_evidence_fails_closed_to_review(self) -> None:
        strategy = Stage4Service().build_evidence_risk_hard_defect_strategy(_parsed_context(weak=True))
        readback = Stage4Service().build_evidence_risk_hard_defect_strategy_readback(strategy)

        self.assertEqual(strategy["evidence_risk_state"], REVIEW_REQUIRED)
        self.assertTrue(strategy["review_required"])
        self.assertTrue(strategy["fail_closed"])
        self.assertTrue(readback["fail_closed"])
        self.assertIn("weak_field_confidence", strategy["fail_closed_reasons"])
        self.assertIn("missing_source_slice", strategy["fail_closed_reasons"])
        self.assertIn("same_name_not_disambiguated", strategy["fail_closed_reasons"])
        self.assertIn("WEAK_EVIDENCE", strategy["evidence_risk_taxonomy"])
        self.assertIn("SAME_NAME_NOT_DISAMBIGUATED", strategy["evidence_risk_taxonomy"])
        self.assertFalse(strategy["customer_visible"])

    def test_strategy_readback_feeds_stage5_rules_and_weak_evidence_stays_review(self) -> None:
        service = Stage4Service()
        strategy = service.build_evidence_risk_hard_defect_strategy(_parsed_context(weak=True))
        active_conflict_readback = {
            "readback_state": "READBACK_READY",
            "replayable": True,
            "fail_closed": False,
            "public_only": True,
            "customer_visible": False,
            "no_legal_conclusion": True,
            "missing_required_fields": [],
            "active_conflict_run_id": "PMAC-RUN-146",
            "overlap_judgement": "OVERLAP_RISK",
            "review_required": True,
        }
        stage4 = _stage4_bundle_with_inputs(
            {
                "project_manager_id_optional": "PM-146",
                "stage5_rule_confidence": 0.92,
            }
        )

        stage5 = Stage5Service().run_evidence_risk_hard_defect_strategy_readback(
            stage4,
            strategy,
            project_manager_active_conflict_readback=active_conflict_readback,
        )

        self.assertEqual(stage5.inputs["stage5_rule_codes"], strategy["stage5_requested_rule_codes"])
        self.assertEqual(stage5.inputs["evidence_risk_state"], REVIEW_REQUIRED)
        self.assertEqual(stage5.record("evidence_gate_decision").get("evidence_gate_status"), "REVIEW")
        self.assertEqual(stage5.record("rule_gate_decision").get("rule_gate_status"), "REVIEW")
        self.assertIn("review_request", stage5.records)
        self.assertEqual(stage5.record("review_request").get("missing_condition_family"), "MISSING_EVIDENCE")
        self.assertEqual(stage5.record("review_request").get("review_lane"), "HIGH_PRIORITY")
        self.assertIn("evidence_risk_hard_defect_strategy_readback", stage5.inputs)
        self.assertIn(strategy["strategy_run_id"], stage5.inputs["source_object_refs"])
        self.assertNotIn("project_fact", stage5.records)
        self.assertNotIn("customer_material", stage5.inputs)


if __name__ == "__main__":
    unittest.main()
