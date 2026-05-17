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

from storage.real_public_stage4_9_pressure_report import (  # noqa: E402
    build_real_public_stage4_9_pressure_report,
    build_real_public_stage4_9_pressure_summary,
    run_real_public_stage4_9_pressure,
)


class RealPublicStage49PressureReportTests(unittest.TestCase):
    def test_run_helper_reuses_operator_search_and_writes_outputs(self) -> None:
        fake_result = _fake_run_result()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch(
                "storage.real_public_stage4_9_pressure_report.run_operator_autonomous_opportunity_search",
                return_value=fake_result,
            ) as runner:
                result = run_real_public_stage4_9_pressure(output_root=root)

            runner.assert_called_once()
            payload = runner.call_args.args[0]
            self.assertEqual(payload["region_codes"], ["CN-GD"])
            self.assertEqual(payload["source_profile_ids"], ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"])
            self.assertEqual(payload["project_types"], ["construction", "municipal", "water_conservancy", "highway"])
            self.assertEqual(payload["candidate_limit"], 10)
            self.assertEqual(payload["detail_capture_limit"], 10)
            self.assertEqual(payload["attachment_capture_limit"], 20)
            self.assertEqual(payload["notice_stage"], "candidate_notice")
            self.assertFalse(payload["allow_offline_sample_candidates"])
            self.assertTrue((root / "run-result.json").exists())
            self.assertTrue((root / "pressure-summary.json").exists())
            self.assertEqual(result["summary"]["candidate_count"], 4)
            self.assertEqual(result["summary"]["selected_candidate_count"], 4)
            self.assertEqual(result["summary"]["coverage_state"], "PARTIAL_SOURCE_COVERAGE")

    def test_summary_and_report_classify_states_and_next_actions(self) -> None:
        run_result = _fake_run_result()
        summary = build_real_public_stage4_9_pressure_summary(
            run_result,
            payload={"source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"]},
            target_accepted_candidate_count=10,
        )

        self.assertEqual(summary["candidate_count"], 4)
        self.assertEqual(summary["selected_candidate_count"], 4)
        self.assertEqual(summary["closed_loop_results_count"], 4)
        self.assertEqual(summary["coverage_state"], "PARTIAL_SOURCE_COVERAGE")
        self.assertEqual(summary["real_public_stage4_9_chain_state_counts"]["INTERNAL_READY"], 1)
        self.assertEqual(summary["real_public_stage4_9_chain_state_counts"]["REVIEW_REQUIRED"], 1)
        self.assertEqual(summary["real_public_stage4_9_chain_state_counts"]["PENDING_STAGE2_DETAIL_CAPTURE"], 1)
        self.assertEqual(summary["real_public_stage4_9_chain_state_counts"]["PENDING_TIME_BUDGET"], 1)
        self.assertEqual(summary["company_first_identity_resolution_required_count"], 1)
        self.assertEqual(summary["stage5_rule_gate_status_counts"]["PASS"], 1)
        self.assertEqual(summary["stage5_rule_gate_status_counts"]["REVIEW"], 1)
        self.assertEqual(summary["fail_closed_reason_counts"]["stage2_detail_capture_pending"], 1)
        self.assertEqual(summary["remaining_real_world_gap_counts"]["missing_stage4_5_source_type:construction_permit"], 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_real_public_stage4_9_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
                target_accepted_candidate_count=10,
            )

            self.assertTrue(report["safe_to_execute"])
            self.assertTrue((root / "real-public-stage4-9-pressure-report-v1.json").exists())
            self.assertTrue((root / "candidate-pressure-table.json").exists())
            self.assertTrue((root / "gap-summary-table.json").exists())
            candidate_rows = report["manifest"]["candidate_pressure_records"]
            next_actions = {row["project_id"]: row["recommended_next_action"] for row in candidate_rows}
            self.assertEqual(
                next_actions["PROJ-REAL-001"],
                "advance_to_stage7_9_internal_review",
            )
            self.assertEqual(
                next_actions["PROJ-REAL-002"],
                "run_company_first_identifier_resolution_before_sellable_evidence",
            )
            self.assertEqual(
                next_actions["PROJ-REAL-003"],
                "increase_detail_capture_limit_or_stage2_detail_capture_time_budget",
            )
            self.assertEqual(
                next_actions["PROJ-REAL-004"],
                "increase_stage1_6_time_budget",
            )
            gap_rows = report["manifest"]["gap_summary_records"]
            gap_index = {(row["gap_family"], row["gap_value"]): row for row in gap_rows}
            self.assertIn(("remaining_real_world_gap", "missing_stage4_5_source_type:construction_permit"), gap_index)
            self.assertIn(("fail_closed_reason", "stage2_detail_capture_pending"), gap_index)
            self.assertIn(("responsible_role_gap_code", "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY"), gap_index)

    def test_forbidden_terms_still_fail_closed(self) -> None:
        run_result = _fake_run_result(project_name="无风险项目")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_real_public_stage4_9_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )
        self.assertFalse(report["safe_to_execute"])
        self.assertEqual(report["summary"]["forbidden_term_scan_state"], "FAIL")


def _fake_run_result(project_name: str = "广州真实候选项目") -> dict:
    return {
        "search_scope": {
            "candidate_count": 4,
            "selected_candidate_count": 4,
        },
        "candidate_options": [
            {
                "project_id": "PROJ-REAL-001",
                "project_name": project_name,
                "source_url": "https://example.invalid/001",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东甲公司",
                "stage2_detail_capture_state": "FETCHED",
                "stage3_parse_state": "PARSED_WITH_REVIEW",
                "real_public_stage4_9_chain_state": "INTERNAL_READY",
                "real_public_stage1_6_chain_state": "INTERNAL_READY",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "stage2_detail_capture_pending": False,
                "stage1_6_time_budget_pending": False,
                "responsible_role_gap_code": "",
            },
            {
                "project_id": "PROJ-REAL-002",
                "project_name": "广州真实候选项目二",
                "source_url": "https://example.invalid/002",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东乙公司",
                "stage2_detail_capture_state": "FETCHED",
                "stage3_parse_state": "PARSED_WITH_REVIEW",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "stage2_detail_capture_pending": False,
                "stage1_6_time_budget_pending": False,
                "responsible_role_gap_code": "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
            },
            {
                "project_id": "PROJ-REAL-003",
                "project_name": "广州真实候选项目三",
                "source_url": "https://example.invalid/003",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东丙公司",
                "stage2_detail_capture_state": "PENDING_DETAIL_CAPTURE",
                "stage3_parse_state": "PENDING_DETAIL_CAPTURE",
                "real_public_stage4_9_chain_state": "PENDING_STAGE2_DETAIL_CAPTURE",
                "real_public_stage1_6_chain_state": "PENDING_STAGE2_DETAIL_CAPTURE",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "stage2_detail_capture_pending": True,
                "stage1_6_time_budget_pending": False,
                "responsible_role_gap_code": "",
            },
            {
                "project_id": "PROJ-REAL-004",
                "project_name": "广州真实候选项目四",
                "source_url": "https://example.invalid/004",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东丁公司",
                "stage2_detail_capture_state": "FETCHED",
                "stage3_parse_state": "PARSED_WITH_REVIEW",
                "real_public_stage4_9_chain_state": "PENDING_TIME_BUDGET",
                "real_public_stage1_6_chain_state": "PENDING_TIME_BUDGET",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "stage2_detail_capture_pending": False,
                "stage1_6_time_budget_pending": True,
                "responsible_role_gap_code": "",
            },
        ],
        "closed_loop_results": [
            {
                "project_id": "PROJ-REAL-001",
                "real_public_stage4_9_chain_state": "INTERNAL_READY",
                "real_public_stage1_6_chain_state": "INTERNAL_READY",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": [],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "PASS",
                    "stage5_evidence_gate_status": "PASS",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": [],
                    "fail_closed_reasons": [],
                    "customer_sellable_evidence_ready": False,
                },
            },
            {
                "project_id": "PROJ-REAL-002",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
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
                "project_id": "PROJ-REAL-003",
                "real_public_stage4_9_chain_state": "PENDING_STAGE2_DETAIL_CAPTURE",
                "real_public_stage1_6_chain_state": "PENDING_STAGE2_DETAIL_CAPTURE",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["stage2_detail_capture_pending"],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "",
                    "stage5_evidence_gate_status": "",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": [],
                    "fail_closed_reasons": ["stage2_detail_capture_pending"],
                    "customer_sellable_evidence_ready": False,
                },
            },
            {
                "project_id": "PROJ-REAL-004",
                "real_public_stage4_9_chain_state": "PENDING_TIME_BUDGET",
                "real_public_stage1_6_chain_state": "PENDING_TIME_BUDGET",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["stage1_6_loop_time_budget_pending"],
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "",
                    "stage5_evidence_gate_status": "",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": [],
                    "fail_closed_reasons": ["stage1_6_loop_time_budget_pending"],
                    "customer_sellable_evidence_ready": False,
                },
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
