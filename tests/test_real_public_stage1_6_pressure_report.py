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

from storage.real_public_stage1_6_pressure_report import (  # noqa: E402
    build_stage1_6_real_public_pressure_report,
    build_stage1_6_real_public_pressure_summary,
    run_stage1_6_real_public_pressure,
)


class StageOneSixRealPublicPressureReportTests(unittest.TestCase):
    def test_run_helper_reuses_operator_search_and_writes_outputs(self) -> None:
        fake_result = _fake_run_result()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch(
                "storage.real_public_stage1_6_pressure_report.run_operator_autonomous_opportunity_search",
                return_value=fake_result,
            ) as runner:
                result = run_stage1_6_real_public_pressure(output_root=root)

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
        summary = build_stage1_6_real_public_pressure_summary(
            run_result,
            payload={"source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"]},
            target_accepted_candidate_count=10,
        )

        self.assertEqual(summary["candidate_count"], 4)
        self.assertEqual(summary["selected_candidate_count"], 4)
        self.assertEqual(summary["closed_loop_results_count"], 4)
        self.assertEqual(summary["coverage_state"], "PARTIAL_SOURCE_COVERAGE")
        self.assertEqual(summary["real_public_stage1_6_chain_state_counts"]["INTERNAL_READY"], 1)
        self.assertEqual(summary["real_public_stage1_6_chain_state_counts"]["REVIEW_REQUIRED"], 1)
        self.assertEqual(summary["real_public_stage1_6_chain_state_counts"]["PENDING_STAGE2_DETAIL_CAPTURE"], 1)
        self.assertEqual(summary["real_public_stage1_6_chain_state_counts"]["PENDING_TIME_BUDGET"], 1)
        self.assertEqual(summary["company_first_identity_resolution_required_count"], 1)
        self.assertEqual(summary["stage5_rule_gate_status_counts"]["PASS"], 1)
        self.assertEqual(summary["stage5_rule_gate_status_counts"]["REVIEW"], 1)
        self.assertEqual(summary["fail_closed_reason_counts"]["stage2_detail_capture_pending"], 1)
        self.assertEqual(summary["remaining_real_world_gap_counts"]["missing_stage4_5_source_type:construction_permit"], 1)
        self.assertEqual(summary["stage1_6_readiness_record_count"], 4)
        self.assertEqual(summary["stage1_6_readiness_state_counts"]["STAGE1_6_INTERNAL_READY"], 1)
        self.assertEqual(summary["stage1_6_readiness_state_counts"]["STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED"], 1)
        self.assertEqual(summary["stage1_6_readiness_state_counts"]["PENDING_STAGE2_DETAIL_CAPTURE"], 1)
        self.assertEqual(summary["stage1_6_readiness_state_counts"]["PENDING_TIME_BUDGET"], 1)
        self.assertEqual(summary["stage4_release_adapter_bridge_task_count"], 1)
        self.assertEqual(summary["stage4_release_adapter_bridge_project_count"], 1)
        self.assertEqual(
            summary["stage4_release_adapter_bridge_project_code_recall_summary"]["project_code_recall_state"],
            "ONLY_TRADE_OR_NO_GDCIC_PROJECT_CODE_VARIANTS",
        )
        self.assertEqual(summary["stage5_calibration_sample_count"], 4)
        self.assertEqual(
            summary["stage5_calibration_review_bucket_counts"],
            {
                "STAGE5_PASS_WITH_NO_ACTIVE_GAP_BASELINE": 1,
                "STAGE5_REVIEW_WITH_ACTIVE_SOURCE_GAP_BASELINE": 1,
                "STAGE5_CALIBRATION_INPUT_INCOMPLETE": 2,
            },
        )
        self.assertEqual(summary["stage4_release_adapter_bridge_target_type_counts"]["construction_permit"], 1)
        self.assertEqual(summary["stage4_release_adapter_bridge_execution_mode_counts"]["PLAN_ONLY_NOT_EXECUTED"], 1)
        self.assertEqual(summary["stage1_6_bottleneck_stage_counts"]["READY"], 1)
        self.assertEqual(summary["stage1_6_bottleneck_stage_counts"]["Stage2"], 1)
        self.assertEqual(summary["stage1_6_bottleneck_stage_counts"]["Stage3"], 1)
        self.assertEqual(summary["stage1_6_bottleneck_stage_counts"]["Stage4"], 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
                target_accepted_candidate_count=10,
            )

            self.assertTrue(report["safe_to_execute"])
            self.assertTrue((root / "stage1-6-real-public-pressure-report-v1.json").exists())
            self.assertTrue((root / "candidate-pressure-table.json").exists())
            self.assertTrue((root / "stage1-6-readiness-table.json").exists())
            self.assertTrue((root / "stage1-6-gap-summary-table.json").exists())
            self.assertTrue((root / "stage4-release-adapter-bridge-table.json").exists())
            self.assertTrue((root / "stage4-release-adapter-bridge-plan.json").exists())
            self.assertTrue((root / "stage5-calibration-sample-table.json").exists())
            self.assertTrue((root / "gap-summary-table.json").exists())
            candidate_rows = report["manifest"]["candidate_pressure_records"]
            readiness_rows = report["manifest"]["stage1_6_readiness_records"]
            bridge_rows = report["manifest"]["stage4_release_adapter_bridge_records"]
            calibration_rows = report["manifest"]["stage5_calibration_records"]
            readiness_by_project = {row["project_id"]: row for row in readiness_rows}
            calibration_by_project = {row["project_id"]: row for row in calibration_rows}
            self.assertEqual(
                readiness_by_project["PROJ-REAL-001"]["stage1_6_readiness_state"],
                "STAGE1_6_INTERNAL_READY",
            )
            self.assertEqual(readiness_by_project["PROJ-REAL-001"]["bottleneck_stage"], "READY")
            self.assertEqual(readiness_by_project["PROJ-REAL-001"]["stage1_6_bottleneck_stage"], "READY")
            self.assertEqual(
                readiness_by_project["PROJ-REAL-002"]["stage1_6_readiness_state"],
                "STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED",
            )
            self.assertEqual(readiness_by_project["PROJ-REAL-002"]["bottleneck_stage"], "Stage3")
            self.assertEqual(readiness_by_project["PROJ-REAL-002"]["stage1_6_bottleneck_stage"], "Stage3")
            self.assertEqual(
                readiness_by_project["PROJ-REAL-003"]["recommended_next_action"],
                "increase_detail_capture_limit_or_stage2_detail_capture_time_budget",
            )
            self.assertEqual(
                readiness_by_project["PROJ-REAL-003"]["next_recommended_action"],
                "increase_detail_capture_limit_or_stage2_detail_capture_time_budget",
            )
            self.assertEqual(
                readiness_by_project["PROJ-REAL-004"]["recommended_next_action"],
                "increase_stage1_6_time_budget",
            )
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
            stage16_gap_rows = report["manifest"]["stage1_6_gap_summary_records"]
            stage16_gap_index = {(row["gap_family"], row["gap_value"]): row for row in stage16_gap_rows}
            self.assertIn(("stage1_6_bottleneck_stage", "Stage2"), stage16_gap_index)
            self.assertIn(("stage1_6_bottleneck_stage", "Stage3"), stage16_gap_index)
            self.assertIn(("stage1_6_bottleneck_stage", "Stage4"), stage16_gap_index)
            self.assertIn(("stage1_6_readiness_state", "PENDING_STAGE2_DETAIL_CAPTURE"), stage16_gap_index)
            self.assertIn(("stage1_6_readiness_state", "PENDING_TIME_BUDGET"), stage16_gap_index)
            self.assertEqual(len(bridge_rows), 1)
            bridge_row = bridge_rows[0]
            self.assertEqual(bridge_row["project_id"], "PROJ-REAL-002")
            self.assertEqual(bridge_row["release_evidence_source_type"], "construction_permit")
            self.assertEqual(bridge_row["release_evidence_target_type"], "construction_permit")
            self.assertEqual(bridge_row["source_profile_id"], "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY")
            self.assertEqual(bridge_row["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertFalse(bridge_row["readback_ready"])
            self.assertTrue(bridge_row["query_miss_is_not_clearance"])
            bridge_plan = json.loads((root / "stage4-release-adapter-bridge-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(bridge_plan["manifest_kind"], "real_public_stage4_release_adapter_bridge_plan_v1_manifest")
            self.assertEqual(len(bridge_plan["release_evidence_adapter_task_records"]), 1)
            self.assertEqual(
                bridge_plan["release_evidence_adapter_task_records"][0]["query_params"]["targetSourceTypes"],
                ["construction_permit"],
            )
            calibration_table = json.loads(
                (root / "stage5-calibration-sample-table.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(calibration_table["records"]), 4)
            self.assertEqual(
                calibration_by_project["PROJ-REAL-002"]["stage5_calibration_review_bucket"],
                "STAGE5_REVIEW_WITH_ACTIVE_SOURCE_GAP_BASELINE",
            )
            self.assertFalse(
                calibration_by_project["PROJ-REAL-002"]["calibration_truth_label_required"]
            )

    def test_forbidden_terms_still_fail_closed(self) -> None:
        run_result = _fake_run_result(project_name="无风险项目")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )
        self.assertFalse(report["safe_to_execute"])
        self.assertEqual(report["summary"]["forbidden_term_scan_state"], "FAIL")

    def test_stage1_6_readiness_uses_field_signals_when_stage3_state_is_missing(self) -> None:
        run_result = _fake_run_result()
        run_result["candidate_options"].append(
            {
                "project_id": "PROJ-REAL-005",
                "project_name": "广州真实候选项目五",
                "source_url": "https://example.invalid/005",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东戊公司",
                "stage2_detail_capture_state": "FETCHED",
                "stage3_parse_state": "",
                "engineering_work_lane": "construction_or_epc",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
                "expected_responsible_role_present": True,
                "primary_responsible_person_name": "王五",
                "project_manager_name": "王五",
                "stage2_detail_capture_pending": False,
                "stage1_6_time_budget_pending": False,
                "responsible_role_gap_code": "",
            }
        )
        run_result["search_scope"]["candidate_count"] = 5
        run_result["search_scope"]["selected_candidate_count"] = 4

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        rows = {
            row["project_id"]: row
            for row in report["manifest"]["stage1_6_readiness_records"]
        }
        row = rows["PROJ-REAL-005"]
        self.assertEqual(row["stage3_field_parse_state"], "PARSED_FROM_FIELD_SIGNALS")
        self.assertEqual(row["stage4_public_verification_state"], "NOT_ATTEMPTED_BY_STAGE1_6_SELECTION_OR_CHAIN_LIMIT")
        self.assertEqual(row["bottleneck_stage"], "Stage4")
        self.assertEqual(row["stage1_6_readiness_state"], "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED")
        self.assertEqual(
            row["recommended_next_action"],
            "run_stage1_6_closed_loop_for_candidate_or_increase_attempt_budget",
        )

    def test_stage1_6_readiness_marks_review_only_candidates_at_stage1(self) -> None:
        run_result = _fake_run_result()
        run_result["candidate_options"].append(
            {
                "project_id": "PROJ-REAL-006",
                "project_name": "广州真实候选项目六",
                "source_url": "https://example.invalid/006",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东己公司",
                "stage2_detail_capture_state": "FETCHED",
                "engineering_work_lane": "construction_or_epc",
                "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
                "expected_responsible_role_present": True,
                "primary_responsible_person_name": "赵六",
                "project_manager_name": "赵六",
                "analysis_priority": "REVIEW",
                "review_reasons": [
                    "source_candidate_preserved_for_review:objection_window_expired",
                    "candidate_publicity_window_expired",
                ],
            }
        )
        run_result["search_scope"]["candidate_count"] = 5
        run_result["search_scope"]["selected_candidate_count"] = 4

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        row = {
            item["project_id"]: item
            for item in report["manifest"]["stage1_6_readiness_records"]
        }["PROJ-REAL-006"]
        self.assertEqual(row["stage1_candidate_discovery_state"], "CANDIDATE_REVIEW_ONLY_NOT_SELECTED_FOR_STAGE1_6")
        self.assertEqual(row["bottleneck_stage"], "Stage1")
        self.assertEqual(row["stage1_6_readiness_state"], "STAGE1_REVIEW_ONLY_NOT_SELECTED")
        self.assertEqual(
            row["recommended_next_action"],
            "skip_or_owner_select_candidate_for_manual_stage1_6_reopen",
        )

    def test_stage1_3_stability_gaps_are_promoted_to_stage1_6_readiness(self) -> None:
        run_result = _fake_run_result()
        run_result["candidate_options"].append(
            {
                "project_id": "PROJ-REAL-007",
                "project_name": "广州真实候选项目七",
                "source_url": "https://example.invalid/007",
                "notice_stage": "candidate_notice",
                "candidate_company": "广东庚公司",
                "stage2_detail_capture_state": "FETCHED",
                "stage3_parse_state": "PARSED_WITH_REVIEW",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "stage2_detail_capture_pending": False,
                "stage1_6_time_budget_pending": False,
                "attachment_capture_attempted_count": 2,
                "attachment_snapshot_count": 1,
                "degraded_reasons": ["attachment_snapshot_readback_missing"],
                "attachment_ocr_required_count": 2,
                "attachment_ocr_extracted_count": 1,
                "attachment_text_cache_hit_count": 1,
                "responsible_role_gap_review_required": True,
                "responsible_role_gap_code": "B_ROLE_MISSING_REQUIRES_ATTACHMENT_OCR_REVIEW",
            }
        )
        run_result["closed_loop_results"].append(
            {
                "project_id": "PROJ-REAL-007",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": [],
                "real_public_stage1_6_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "REVIEW",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": [],
                    "fail_closed_reasons": [],
                    "customer_sellable_evidence_ready": False,
                },
            }
        )
        run_result["search_scope"]["candidate_count"] = 5
        run_result["search_scope"]["selected_candidate_count"] = 5

        summary = build_stage1_6_real_public_pressure_summary(
            run_result,
            payload={"source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"]},
            target_accepted_candidate_count=10,
        )
        stability = summary["stage1_3_stability_summary"]
        self.assertEqual(stability["stage2_attachment_capture_attempted_count"], 2)
        self.assertEqual(stability["stage2_attachment_snapshot_count"], 1)
        self.assertEqual(stability["stage2_attachment_snapshot_missing_count"], 1)
        self.assertEqual(stability["attachment_snapshot_readback_missing_count"], 1)
        self.assertEqual(stability["stage3_attachment_ocr_required_count"], 2)
        self.assertEqual(stability["stage3_attachment_ocr_extracted_count"], 1)
        self.assertEqual(stability["stage3_attachment_ocr_pending_count"], 1)
        self.assertEqual(stability["attachment_text_cache_hit_count"], 1)
        self.assertEqual(stability["stage3_responsible_role_gap_count"], 2)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        row = {
            item["project_id"]: item
            for item in report["manifest"]["stage1_6_readiness_records"]
        }["PROJ-REAL-007"]
        self.assertEqual(row["stage2_attachment_snapshot_missing_count"], 1)
        self.assertEqual(row["attachment_snapshot_readback_missing_count"], 1)
        self.assertEqual(row["stage3_attachment_ocr_pending_count"], 1)
        self.assertEqual(row["attachment_text_cache_hit_count"], 1)
        self.assertEqual(row["stage3_responsible_role_gap_count"], 1)
        self.assertEqual(row["stage2_detail_capture_state"], "ATTACHMENT_SNAPSHOT_MISSING_REVIEW_REQUIRED")
        self.assertEqual(row["bottleneck_stage"], "Stage2")
        self.assertEqual(row["stage1_6_readiness_state"], "STAGE2_ATTACHMENT_CAPTURE_REVIEW_REQUIRED")
        self.assertEqual(
            row["recommended_next_action"],
            "rerun_stage2_attachment_capture_or_repair_snapshot_readback",
        )
        gap_index = {
            (item["gap_family"], item["gap_value"]): item
            for item in report["manifest"]["stage1_6_gap_summary_records"]
        }
        self.assertIn(("stage1_3_stability_gap", "attachment_snapshot_gap"), gap_index)
        self.assertIn(("stage1_3_stability_gap", "attachment_snapshot_readback_gap"), gap_index)
        self.assertIn(("stage1_3_stability_gap", "attachment_ocr_gap"), gap_index)
        self.assertIn(("stage1_3_stability_gap", "stage3_responsible_role_gap"), gap_index)
        self.assertEqual(report["summary"]["forbidden_term_scan_state"], "PASS")

    def test_stage4_release_bridge_uses_gdcic_openplatform_for_contract_performance(self) -> None:
        run_result = _fake_run_result()
        run_result["candidate_options"][1]["project_id"] = "PROJ-CN-GD-JG2026-11337"
        run_result["closed_loop_results"][1]["project_id"] = "PROJ-CN-GD-JG2026-11337"
        run_result["candidate_options"][1]["candidate_company"] = "(主)广东乙公司;(成)广东联合设计有限公司"
        run_result["closed_loop_results"][1]["real_public_stage1_6_readback"]["remaining_real_world_gaps"] = [
            "missing_stage4_5_source_type:contract_public_info",
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        bridge_rows = report["manifest"]["stage4_release_adapter_bridge_records"]
        self.assertEqual(len(bridge_rows), 1)
        row = bridge_rows[0]
        self.assertEqual(row["project_id"], "PROJ-CN-GD-JG2026-11337")
        self.assertEqual(row["release_evidence_source_type"], "contract_public_info")
        self.assertEqual(row["release_evidence_target_type"], "contract_performance")
        self.assertEqual(row["source_profile_id"], "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM")
        self.assertEqual(row["next_adapter"], "guangdong_gdcic_openplatform_public_api_query_v1")
        self.assertEqual(row["runtime_status"], "PUBLIC_API_VERIFIED_ANONYMOUS_READBACK")
        self.assertEqual(row["query_params"]["projectCode"], "")
        self.assertEqual(row["query_params"]["projectCodeVariants"], ["JG2026-11337"])
        self.assertEqual(row["query_params"]["gdcicProjectCodeVariants"], [])
        self.assertEqual(row["query_params"]["tradeProjectCode"], "JG2026-11337")
        self.assertEqual(row["query_params"]["targetSourceTypes"], ["contract_public_info"])
        self.assertEqual(
            row["query_params"]["companyVariants"],
            ["(主)广东乙公司;(成)广东联合设计有限公司", "广东乙公司", "广东联合设计有限公司"],
        )

    def test_stage4_release_bridge_extracts_numeric_gdcic_project_code_from_readback(self) -> None:
        run_result = _fake_run_result()
        numeric_project_code = "440100202605190001"
        enterprise_credit_code = "914400001903237820"
        run_result["candidate_options"][1]["project_id"] = "PROJ-CN-GD-JG2026-11337"
        run_result["closed_loop_results"][1]["project_id"] = "PROJ-CN-GD-JG2026-11337"
        readback = run_result["closed_loop_results"][1]["real_public_stage1_6_readback"]
        readback["remaining_real_world_gaps"] = ["missing_stage4_5_source_type:contract_public_info"]
        readback["regional_hard_defect_source_readback"] = {
            "query_context": {
                "project_codes": [numeric_project_code],
            },
            "source_results": [
                {
                    "query_input": {"project_code": numeric_project_code},
                    "sample_records": [
                        {
                            "projectCode": numeric_project_code,
                            "unifiedSocialCreditCode": enterprise_credit_code,
                        }
                    ],
                }
            ],
        }
        readback["source_refs"] = {
            "stage6": {
                "parsed_field_refs": [
                    {
                        "field_name": "统一社会信用代码",
                        "field_value_optional": enterprise_credit_code,
                    },
                    {
                        "field_name": "项目代码",
                        "field_value_optional": numeric_project_code,
                    },
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        row = report["manifest"]["stage4_release_adapter_bridge_records"][0]
        self.assertEqual(row["query_params"]["projectCode"], numeric_project_code)
        self.assertEqual(
            row["query_params"]["projectCodeVariants"],
            ["JG2026-11337", numeric_project_code],
        )
        self.assertEqual(row["query_params"]["gdcicProjectCodeVariants"], [numeric_project_code])
        self.assertEqual(row["query_params"]["tradeProjectCode"], "JG2026-11337")
        self.assertNotIn(enterprise_credit_code, row["query_params"]["projectCodeVariants"])
        self.assertNotIn(enterprise_credit_code, row["query_params"]["gdcicProjectCodeVariants"])

    def test_stage4_release_bridge_extracts_project_codes_from_ygp_and_bid_show_artifacts(self) -> None:
        run_result = _fake_run_result()
        ygp_project_code = "441900029-2025-00741"
        gdcic_url_project_code = "E4401002701502243001"
        investment_project_code = "2605-440100-04-01-000001"
        enterprise_credit_code = "914400001903237820"
        certificate_no = "粤1332006200810171"
        run_result["candidate_options"][1]["project_id"] = "PROJ-CN-GD-JG2026-11337"
        run_result["closed_loop_results"][1]["project_id"] = "PROJ-CN-GD-JG2026-11337"
        readback = run_result["closed_loop_results"][1]["real_public_stage1_6_readback"]
        readback["remaining_real_world_gaps"] = ["missing_stage4_5_source_type:contract_public_info"]
        readback["data_ggzy_bid_show_records"] = [
            {
                "source_url": (
                    "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=abc"
                    f"&projectCode={gdcic_url_project_code}"
                ),
                "project_name": "广州真实候选项目二",
                "project_no": ygp_project_code,
                "detail": {"proofOrSerialCode": investment_project_code},
                "unifiedSocialCreditCode": enterprise_credit_code,
                "certificateNo": certificate_no,
            }
        ]
        readback["guangdong_ygp_flow_matrix"] = {
            "manifest": {
                "ygp_project_records": [
                    {
                        "resolved_project_route": {
                            "projectCode": ygp_project_code,
                            "siteCode": "441900",
                            "bizCode": "3871",
                        },
                        "project_code": ygp_project_code,
                    }
                ],
                "ygp_flow_matrix_records": [
                    {
                        "flow_no": "11",
                        "document_kind": "contract_public_info",
                        "nodeList": [
                            {
                                "detail": {
                                    "projectCode": gdcic_url_project_code,
                                    "projectName": "广州真实候选项目二",
                                },
                                "dsList": [
                                    {
                                        "项目编号": ygp_project_code,
                                        "项目代码": investment_project_code,
                                        "统一社会信用代码": enterprise_credit_code,
                                        "证书编号": certificate_no,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        row = report["manifest"]["stage4_release_adapter_bridge_records"][0]
        recall = report["summary"]["stage4_release_adapter_bridge_project_code_recall_summary"]
        self.assertEqual(row["query_params"]["projectCode"], gdcic_url_project_code)
        self.assertEqual(
            row["query_params"]["projectCodeVariants"],
            ["JG2026-11337", gdcic_url_project_code, ygp_project_code, investment_project_code],
        )
        self.assertEqual(
            row["query_params"]["gdcicProjectCodeVariants"],
            [gdcic_url_project_code, ygp_project_code],
        )
        self.assertEqual(row["query_params"]["tradeProjectCode"], "JG2026-11337")
        self.assertNotIn("PROJ-CN-GD-JG2026-11337", row["query_params"]["projectCodeVariants"])
        self.assertNotIn(enterprise_credit_code, row["query_params"]["projectCodeVariants"])
        self.assertNotIn(certificate_no, row["query_params"]["projectCodeVariants"])
        self.assertNotIn(enterprise_credit_code, row["query_params"]["gdcicProjectCodeVariants"])
        self.assertNotIn(certificate_no, row["query_params"]["gdcicProjectCodeVariants"])
        self.assertEqual(recall["project_code_recall_state"], "GDCIC_PROJECT_CODE_VARIANTS_PRESENT")
        self.assertEqual(recall["with_gdcic_project_code_variant_task_count"], 1)
        self.assertEqual(recall["missing_gdcic_project_code_variant_task_count"], 0)

    def test_stage5_calibration_flags_pass_with_active_stage4_gap_as_review_sample(self) -> None:
        run_result = _fake_run_result()
        readback = run_result["closed_loop_results"][0]["real_public_stage1_6_readback"]
        readback["stage5_rule_gate_status"] = "PASS"
        readback["stage5_evidence_gate_status"] = "PASS"
        readback["remaining_real_world_gaps"] = [
            "missing_stage4_5_source_type:contract_public_info"
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "run-result.json").write_text(json.dumps(run_result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = build_stage1_6_real_public_pressure_report(
                run_result_json=root / "run-result.json",
                output_root=root,
            )

        calibration_by_project = {
            row["project_id"]: row for row in report["manifest"]["stage5_calibration_records"]
        }
        row = calibration_by_project["PROJ-REAL-001"]
        self.assertEqual(row["stage5_calibration_review_bucket"], "POTENTIAL_FALSE_POSITIVE_REVIEW")
        self.assertTrue(row["calibration_truth_label_required"])
        self.assertIn(
            "stage5_passed_while_stage4_or_runtime_gap_still_exists",
            row["stage5_calibration_review_reasons"],
        )
        self.assertEqual(
            row["suggested_calibration_action"],
            "review_stage5_pass_against_stage4_source_gap_before_rule_relaxation",
        )


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
                "real_public_stage1_6_chain_state": "INTERNAL_READY",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": [],
                "real_public_stage1_6_readback": {
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
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["source_gap_review_required"],
                "real_public_stage1_6_readback": {
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
                "real_public_stage1_6_chain_state": "PENDING_STAGE2_DETAIL_CAPTURE",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["stage2_detail_capture_pending"],
                "real_public_stage1_6_readback": {
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
                "real_public_stage1_6_chain_state": "PENDING_TIME_BUDGET",
                "real_world_hard_defect_gate_state": "SOURCE_COVERAGE_PENDING",
                "customer_sellable_evidence_ready": False,
                "fail_closed_reasons": ["stage1_6_loop_time_budget_pending"],
                "real_public_stage1_6_readback": {
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
