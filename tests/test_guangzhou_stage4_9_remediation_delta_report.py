from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangzhou_stage4_9_remediation_delta_report import (  # noqa: E402
    build_guangzhou_stage4_9_remediation_delta_report,
    run_guangzhou_stage4_9_remediation_replay,
)


class GuangzhouStage49RemediationDeltaReportTests(unittest.TestCase):
    def test_replay_uses_explicit_notice_candidates_and_applies_writebacks(self) -> None:
        baseline_run = _baseline_run_result()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(root / "baseline-run.json", baseline_run)
            _write_json(root / "baseline-candidate-table.json", _baseline_candidate_table())
            _write_json(root / "company-first-remediation.json", _company_first_remediation())
            _write_json(root / "source-gap-probe.json", _source_gap_probe())

            with patch(
                "storage.guangzhou_stage4_9_remediation_delta_report.run_operator_autonomous_opportunity_search",
                return_value=_replay_run_result(),
            ) as runner:
                result = run_guangzhou_stage4_9_remediation_replay(
                    baseline_run_result_json=root / "baseline-run.json",
                    baseline_candidate_pressure_json=root / "baseline-candidate-table.json",
                    company_first_remediation_json=root / "company-first-remediation.json",
                    source_gap_probe_json=root / "source-gap-probe.json",
                    output_root=root / "out",
                )

            runner.assert_called_once()
            payload = runner.call_args.args[0]
            self.assertEqual(payload["notice_candidates"][0]["notice_stage"], "candidate_notice")
            self.assertEqual(payload["notice_candidates"][0]["candidate_count"], 1)
            self.assertEqual(payload["notice_candidates"][0]["competitor_count"], 1)
            self.assertEqual(payload["notice_candidates"][0]["project_manager_certificate_no"], "粤1442020202100011")
            self.assertIn("project_manager_certificate_no", payload["notice_candidates"][0]["p2_replay_writeback_fields_applied"])
            self.assertEqual(payload["notice_candidates"][1]["project_manager_name"], "李四")
            self.assertEqual(payload["notice_candidates"][1]["responsible_role_gap_code"], "")
            self.assertEqual(payload["notice_candidates"][1]["projectCode"], "GC002")
            self.assertEqual(payload["notice_candidates"][1]["project_code"], "GC002")
            self.assertEqual(payload["notice_candidates"][1]["gdcic_project_code"], "GC002")
            self.assertEqual(payload["notice_candidates"][1]["project_public_code"], "GC002")
            self.assertIn("projectCode", payload["notice_candidates"][1]["p2_replay_writeback_fields_applied"])
            self.assertEqual(payload["notice_candidates"][0]["source_candidate_mode"], "REAL_PUBLIC_SOURCE_CANDIDATES")
            self.assertTrue((root / "out" / "run-result.json").exists())
            self.assertTrue((root / "out" / "pressure-summary.json").exists())
            self.assertTrue((root / "out" / "stage4-9-remediation-delta-report-v1.json").exists())
            self.assertTrue(result["delta_report"]["safe_to_execute"])

    def test_delta_report_computes_before_after_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(root / "baseline-run.json", _baseline_run_result())
            _write_json(root / "baseline-candidate-table.json", _baseline_candidate_table())
            _write_json(root / "company-first-remediation.json", _company_first_remediation())
            _write_json(root / "source-gap-probe.json", _source_gap_probe())
            _write_json(root / "replay-run.json", _replay_run_result())
            _write_json(root / "replay-candidate-table.json", _replay_candidate_table())

            result = build_guangzhou_stage4_9_remediation_delta_report(
                baseline_run_result_json=root / "baseline-run.json",
                baseline_candidate_pressure_json=root / "baseline-candidate-table.json",
                company_first_remediation_json=root / "company-first-remediation.json",
                source_gap_probe_json=root / "source-gap-probe.json",
                replay_run_result_json=root / "replay-run.json",
                replay_candidate_pressure_json=root / "replay-candidate-table.json",
                output_root=root / "out",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["company_first_identity_resolution_required_count_before"], 1)
            self.assertEqual(summary["company_first_identity_resolution_required_count_after"], 0)
            self.assertEqual(summary["responsible_role_gap_code_count_before"], 1)
            self.assertEqual(summary["responsible_role_gap_code_count_after"], 0)
            self.assertEqual(summary["stage5_evidence_gate_status_counts_before"], {"PASS": 1, "REVIEW": 1})
            self.assertEqual(summary["stage5_evidence_gate_status_counts_after"], {"PASS": 2})
            self.assertIn("missing_stage4_5_source_type:construction_permit", summary["remaining_real_world_gap_counts_before"])
            self.assertEqual(
                summary["project_code_resolution_failure_counts_after"],
                {"gdcic_project_code_candidates_present_but_not_matched": 1},
            )
            candidate_rows = {row["project_id"]: row for row in result["manifest"]["candidate_delta_records"]}
            self.assertEqual(candidate_rows["PROJ-1"]["delta_state"], "COMPANY_FIRST_IMPROVED")
            self.assertEqual(candidate_rows["PROJ-2"]["delta_state"], "ROLE_GAP_IMPROVED")
            self.assertEqual(candidate_rows["PROJ-2"]["source_gap_project_code_candidates"], ["GC002"])
            gap_rows = {(row["gap_family"], row["gap_value"]): row for row in result["manifest"]["gap_delta_records"]}
            self.assertIn(("remaining_real_world_gap", "missing_stage4_5_source_type:construction_permit"), gap_rows)
            self.assertTrue((root / "out" / "candidate-delta-table.json").exists())
            self.assertTrue((root / "out" / "gap-delta-table.json").exists())


def _baseline_run_result() -> dict:
    return {
        "candidate_options": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目一",
                "source_url": "https://example.invalid/1",
                "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                "candidate_company": "广州甲公司",
                "project_manager_name": "张三",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "张三",
                "primary_responsible_role": "project_manager",
                "responsible_role_gap_code": "",
                "region_code": "CN-GD",
            },
            {
                "project_id": "PROJ-2",
                "project_name": "广州候选项目二",
                "source_url": "https://example.invalid/2",
                "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                "candidate_company": "广州乙公司",
                "project_manager_name": "",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "",
                "primary_responsible_role": "project_manager",
                "responsible_role_gap_code": "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
                "region_code": "CN-GD",
            },
        ],
        "search_scope": {"candidate_count": 2, "selected_candidate_count": 2},
        "closed_loop_results": [
            {
                "project_id": "PROJ-1",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["source_gap_review_required"],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "REVIEW",
                    "jzsc_company_first_identity_resolution_required": True,
                    "remaining_real_world_gaps": ["missing_stage4_5_source_type:construction_permit"],
                    "fail_closed_reasons": ["source_gap_review_required"],
                    "customer_sellable_evidence_ready": False,
                },
            },
            {
                "project_id": "PROJ-2",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["source_gap_review_required"],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "PASS",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": ["missing_stage4_5_source_type:project_manager_change_notice"],
                    "fail_closed_reasons": ["source_gap_review_required"],
                    "customer_sellable_evidence_ready": False,
                },
            },
        ],
    }


def _replay_run_result() -> dict:
    return {
        "candidate_options": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目一",
                "source_url": "https://example.invalid/1",
                "notice_stage": "candidate_notice",
                "candidate_company": "广州甲公司",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "jzsc_company_first_identity_resolution_required": False,
                "responsible_role_gap_code": "",
                "p2_replay_writeback_fields_applied": ["project_manager_certificate_no"],
            },
            {
                "project_id": "PROJ-2",
                "project_name": "广州候选项目二",
                "source_url": "https://example.invalid/2",
                "notice_stage": "candidate_notice",
                "candidate_company": "广州乙公司",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "jzsc_company_first_identity_resolution_required": False,
                "responsible_role_gap_code": "",
                "p2_replay_writeback_fields_applied": ["project_manager_name", "primary_responsible_person_name"],
            },
        ],
        "search_scope": {"candidate_count": 2, "selected_candidate_count": 2},
        "closed_loop_results": [
            {
                "project_id": "PROJ-1",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["source_gap_review_required"],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "PASS",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": ["missing_stage4_5_source_type:construction_permit"],
                    "fail_closed_reasons": ["source_gap_review_required"],
                    "customer_sellable_evidence_ready": False,
                },
            },
            {
                "project_id": "PROJ-2",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["source_gap_review_required"],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "PASS",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": [],
                    "fail_closed_reasons": ["source_gap_review_required"],
                    "customer_sellable_evidence_ready": False,
                },
            },
        ],
    }


def _baseline_candidate_table() -> dict:
    return {
        "records": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目一",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "REVIEW",
                "jzsc_company_first_identity_resolution_required": True,
                "responsible_role_gap_code": "",
                "remaining_real_world_gaps": ["missing_stage4_5_source_type:construction_permit"],
                "fail_closed_reasons": ["source_gap_review_required"],
            },
            {
                "project_id": "PROJ-2",
                "project_name": "广州候选项目二",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
                "jzsc_company_first_identity_resolution_required": False,
                "responsible_role_gap_code": "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
                "remaining_real_world_gaps": ["missing_stage4_5_source_type:project_manager_change_notice"],
                "fail_closed_reasons": ["source_gap_review_required"],
            },
        ]
    }


def _replay_candidate_table() -> dict:
    return {
        "records": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目一",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
                "jzsc_company_first_identity_resolution_required": False,
                "responsible_role_gap_code": "",
                "remaining_real_world_gaps": ["missing_stage4_5_source_type:construction_permit"],
                "fail_closed_reasons": ["source_gap_review_required"],
                "p2_replay_writeback_fields_applied": ["project_manager_certificate_no"],
            },
            {
                "project_id": "PROJ-2",
                "project_name": "广州候选项目二",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
                "jzsc_company_first_identity_resolution_required": False,
                "responsible_role_gap_code": "",
                "remaining_real_world_gaps": [],
                "fail_closed_reasons": ["source_gap_review_required"],
                "p2_replay_writeback_fields_applied": ["project_manager_name", "primary_responsible_person_name"],
            },
        ]
    }


def _company_first_remediation() -> dict:
    return {
        "records": [
            {
                "project_id": "PROJ-1",
                "remediation_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                "replay_field_writeback": {
                    "project_manager_certificate_no": "粤1442020202100011",
                    "project_manager_public_identifier_optional": "person-zhang",
                },
            }
        ],
        "summary": {"candidate_count": 1},
    }


def _source_gap_probe() -> dict:
    return {
        "records": [
            {
                "project_id": "PROJ-2",
                "recommended_next_action": "apply_stage4_responsible_role_writeback_in_replay",
                "project_code_candidates": ["GC002"],
                "project_code_resolution_failure_reasons": ["gdcic_project_code_candidates_present_but_not_matched"],
                "replay_identifier_hints": {"project_code_candidates": ["GC002"]},
                "stage4_responsible_role_writeback_state": "RESPONSIBLE_ROLE_WRITEBACK_CANDIDATE_FROM_STAGE4_SOURCE",
                "replay_field_writeback": {
                    "project_manager_name": "李四",
                    "project_manager_name_parse_state": "P2_STAGE4_SOURCE_GAP_PROBE",
                    "primary_responsible_person_name": "李四",
                    "primary_responsible_person_name_parse_state": "P2_STAGE4_SOURCE_GAP_PROBE",
                },
            }
        ],
        "summary": {"candidate_count": 1},
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
