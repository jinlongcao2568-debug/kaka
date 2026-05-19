from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.evidence_stage6_fact_package import build_evidence_stage6_fact_package  # noqa: E402


class EvidenceStage6FactPackageTests(unittest.TestCase):
    def test_builds_fact_and_review_packages_from_batch_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "closeout")

            result = build_evidence_stage6_fact_package(
                batch_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["input_closeout_project_count"], 3)
            self.assertEqual(summary["project_fact_count"], 2)
            self.assertEqual(summary["internal_evidence_pack_count"], 2)
            self.assertEqual(summary["review_queue_count"], 2)
            self.assertEqual(summary["review_action_plan_count"], 2)
            self.assertEqual(summary["stage7_preview_seed_count"], 1)
            self.assertEqual(summary["formal_h06_handoff_ready_count"], 0)
            self.assertEqual(
                summary["stage6_intake_state_counts"],
                {
                    "DEFER_UNTIL_EVIDENCE_CONTINUED": 1,
                    "STAGE6_FACT_PACKAGE_READY": 1,
                    "STAGE6_REVIEW_PACKAGE_READY": 1,
                },
            )
            facts = _records_by_project(result["manifest"]["project_fact_table"]["records"])
            self.assertEqual(facts["PROJ-A"]["sale_gate_status"], "REVIEW")
            self.assertEqual(facts["PROJ-A"]["coverage_sellable_state"], "RESTRICTED_INTERNAL_PREVIEW")
            self.assertEqual(facts["PROJ-D"]["sale_gate_status"], "HOLD")
            self.assertEqual(facts["PROJ-D"]["evidence_gate_status"], "BLOCK")
            self.assertNotIn("PROJ-B", facts)
            plans = _records_by_project(result["manifest"]["stage6_review_action_plan_table"]["records"])
            self.assertEqual(plans["PROJ-A"]["action_family"], "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW")
            self.assertIn(
                "historical_overlap_project_local_housing_construction_or_competent_authority_public_source",
                plans["PROJ-A"]["target_source_scope"],
            )
            self.assertEqual(
                plans["PROJ-A"]["regional_routing_policy"],
                "route_by_historical_overlap_project_jurisdiction_no_guangdong_fallback_for_non_guangdong",
            )
            self.assertEqual(
                plans["PROJ-D"]["action_family"],
                "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
            )
            self.assertTrue(plans["PROJ-D"]["query_miss_is_not_clearance"])

    def test_d_project_is_review_only_and_keeps_query_miss_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "closeout")

            result = build_evidence_stage6_fact_package(batch_closeout_root=root / "closeout", output_root=root / "out")

            review = _records_by_project(result["manifest"]["review_queue_table"]["records"])["PROJ-D"]
            action = _records_by_project(result["manifest"]["legal_action_recommendation_table"]["records"])["PROJ-D"]
            pack = _records_by_project(result["manifest"]["internal_evidence_pack_table"]["records"])["PROJ-D"]
            self.assertEqual(review["review_lane"], "D_EVIDENCE_GAP_REVIEW")
            self.assertEqual(action["action_family"], "REVIEW_ONLY")
            self.assertTrue(pack["query_miss_is_not_clearance"])
            self.assertFalse(pack["formal_customer_delivery_ready"])
            self.assertFalse(result["manifest"]["safety"]["stage7_to_stage9_live_execution_enabled"])

    def test_terminal_source_gap_no_delta_is_manual_only_without_auto_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(
                root / "closeout" / "evidence-batch-closeout-v1.json",
                {
                    "manifest": {
                        "manifest_id": "BATCH-CLOSEOUT-TERMINAL-D",
                        "closeout_records": [
                            {
                                "project_id": "PROJ-TERMINAL-D",
                                "project_name": "终态 D 项目",
                                "engineering_work_lane": "construction_or_epc",
                                "responsible_person_name": "王五",
                                "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                                "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
                                "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
                                "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
                                "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
                                "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                                "stage6_ready": True,
                                "stage7_commercial_input_allowed": False,
                                "pending_adapter_job_count": 0,
                                "review_reasons": ["original_notice_backtrace_no_a_signal"],
                                "continuation_lineage": {
                                    "state_after_adapter_job_count": 0,
                                    "final_original_backtrace_continuation_recommended_next_action": (
                                        "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
                                    ),
                                },
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                    },
                    "summary": {"project_count": 1},
                },
            )

            result = build_evidence_stage6_fact_package(batch_closeout_root=root / "closeout", output_root=root / "out")

            plan = result["manifest"]["stage6_review_action_plan_table"]["records"][0]
            review = result["manifest"]["review_queue_table"]["records"][0]
            self.assertFalse(plan["automated_dispatch_allowed"])
            self.assertEqual(plan["dispatch_block_reason"], "terminal_source_gap_no_delta_manual_review_only")
            self.assertIn(
                "do_not_auto_retry_until_new_source_or_operator_override",
                [item["action_label"] for item in plan["action_items"]],
            )
            self.assertEqual(
                review["recommended_next_action"],
                "park_manual_review_until_new_source_or_operator_override_without_clearance_claim",
            )

    def test_design_survey_registry_artifact_gets_qualification_service_clock_action_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(
                root / "closeout" / "evidence-batch-closeout-v1.json",
                {
                    "manifest": {
                        "manifest_id": "BATCH-CLOSEOUT-DESIGN-SURVEY",
                        "closeout_records": [
                            {
                                "project_id": "PROJ-SURVEY",
                                "project_name": "规划测绘项目",
                                "engineering_work_lane": "design_survey",
                                "candidate_group_members": ["广州市城市规划勘测设计研究院有限公司"],
                                "responsible_person_name": "胡昌华",
                                "evidence_state": "DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY",
                                "evidence_grade": "B_ENHANCED_EVIDENCE",
                                "evidence_signal_source": "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
                                "batch_triage_bucket": "B_ENHANCED_REVIEW",
                                "batch_stop_reason": "",
                                "closeout_state": "REVIEW_FACT_PACKAGE_READY",
                                "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                                "stage6_ready": True,
                                "stage7_commercial_input_allowed": False,
                                "next_action_label": "review_design_survey_registry_qualification_and_service_clock",
                                "review_reasons": ["design_survey_registry_identity_match_review"],
                                "evidence_artifacts": [
                                    {
                                        "evidence_artifact_type": "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
                                        "verification_result": "MATCHED",
                                        "identity_fields": {
                                            "person_name": "胡昌华",
                                            "registered_unit_name": "广州市城市规划勘测设计研究院有限公司",
                                        },
                                        "source_snapshot_sha256": "survey-snapshot-sha256",
                                        "customer_visible_allowed": False,
                                        "no_legal_conclusion": True,
                                    }
                                ],
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                    },
                    "summary": {"project_count": 1},
                },
            )

            result = build_evidence_stage6_fact_package(batch_closeout_root=root / "closeout", output_root=root / "out")

            plan = _records_by_project(result["manifest"]["stage6_review_action_plan_table"]["records"])["PROJ-SURVEY"]
            summary = json.loads(
                (root / "out" / "packages" / "PROJ-SURVEY" / "stage6-review-summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                plan["action_family"],
                "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW",
            )
            self.assertEqual(
                plan["target_adapter_scope"],
                "DesignSurveyPublicRegistryReadback + natural_resources_public_registry_adapter",
            )
            self.assertIn(
                "plan_qualification_service_clock_and_current_assignment_review",
                [item["action_label"] for item in plan["action_items"]],
            )
            self.assertEqual(
                summary["review_action_family"],
                "DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW",
            )

    def test_writes_per_project_brief_and_pack_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "closeout")

            result = build_evidence_stage6_fact_package(batch_closeout_root=root / "closeout", output_root=root / "out")

            report = _records_by_project(result["manifest"]["report_record_table"]["records"])["PROJ-A"]
            brief_path = Path(report["brief_path"])
            pack_path = Path(report["evidence_pack_path"])
            review_summary_path = Path(report["review_summary_path"])
            review_summary_markdown_path = Path(report["review_summary_markdown_path"])
            review_action_plan_path = Path(report["review_action_plan_path"])
            self.assertTrue(brief_path.exists())
            self.assertTrue(pack_path.exists())
            self.assertTrue(review_summary_path.exists())
            self.assertTrue(review_summary_markdown_path.exists())
            self.assertTrue(review_action_plan_path.exists())
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            review_summary = json.loads(review_summary_path.read_text(encoding="utf-8"))
            review_action_plan = json.loads(review_action_plan_path.read_text(encoding="utf-8"))
            review_summary_markdown = review_summary_markdown_path.read_text(encoding="utf-8")
            self.assertEqual(brief["project_id"], "PROJ-A")
            self.assertEqual(pack["project_fact"]["project_id"], "PROJ-A")
            self.assertEqual(brief["review_summary_path"], str(review_summary_path))
            self.assertEqual(brief["review_action_plan_path"], str(review_action_plan_path))
            self.assertEqual(brief["review_action_family"], "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW")
            self.assertEqual(pack["review_summary"]["project_id"], "PROJ-A")
            self.assertEqual(
                pack["stage6_review_action_plan"]["action_family"],
                "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
            )
            self.assertEqual(review_summary["review_summary_state"], "INTERNAL_REVIEW_SUMMARY_READY")
            self.assertEqual(review_summary["review_action_plan_path"], str(review_action_plan_path))
            self.assertEqual(review_action_plan["review_action_plan_state"], "INTERNAL_ACTION_PLAN_READY")
            self.assertEqual(brief["evidence_artifact_count"], 1)
            self.assertEqual(
                brief["evidence_artifact_types"],
                ["DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK"],
            )
            self.assertEqual(
                pack["internal_evidence_pack"]["evidence_artifacts"][0]["identity_fields"]["person_name"],
                "胡昌华",
            )
            self.assertEqual(review_summary["evidence_artifacts"][0]["person_name"], "胡昌华")
            self.assertIn("Stage6 Internal Review Summary", review_summary_markdown)
            self.assertIn("Review Action Plan", review_summary_markdown)
            self.assertIn("snapshot-sha256", review_summary_markdown)
            self.assertFalse(pack["customer_visible_allowed"])

    def test_missing_batch_closeout_blocks_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_evidence_stage6_fact_package(
                batch_closeout_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["evidence_stage6_fact_package_mode"], "INPUT_BLOCKED")
            self.assertIn("evidence_batch_closeout_missing_or_invalid", result["blocking_reasons"])
            self.assertEqual(result["summary"]["stage6_fact_package_state"], "EVIDENCE_STAGE6_INPUT_BLOCKED")

    def test_output_avoids_customer_material_and_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "closeout")

            result = build_evidence_stage6_fact_package(batch_closeout_root=root / "closeout", output_root=root / "out")

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertFalse(result["manifest"]["summary"]["formal_customer_delivery_ready"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_batch_closeout(root: Path) -> None:
    records = [
        {
            "project_id": "PROJ-A",
            "project_name": "A 项目",
            "engineering_work_lane": "construction_or_epc",
            "candidate_group_members": ["A 公司"],
            "responsible_person_name": "张三",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
            "evidence_signal_source": "data_ggzy_bid_show",
            "batch_triage_bucket": "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
            "batch_stop_reason": "",
            "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": True,
            "next_action_label": "build_release_evidence_regional_adapter_plan_and_stage6_fact_package",
            "review_reasons": ["same_person_company_time_window_overlap_review"],
            "signal_counts": {"p13b_a_strong_direct_signal_count": 1},
            "evidence_artifacts": [
                {
                    "evidence_artifact_type": "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
                    "verification_result": "MATCHED",
                    "identity_fields": {
                        "person_name": "胡昌华",
                        "registered_unit_name": "广州市城市规划勘测设计研究院有限公司",
                    },
                    "source_snapshot_sha256": "snapshot-sha256",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ],
            "source_refs": {"evidence_state_json": "state.json"},
            "continuation_lineage": {},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-D",
            "project_name": "D 项目",
            "engineering_work_lane": "construction_or_epc",
            "candidate_group_members": ["D 公司"],
            "responsible_person_name": "李四",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "evidence_signal_source": "ORIGINAL_BACKTRACE_CONTINUATION",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "batch_stop_reason": "release_evidence_or_original_readback_insufficient_or_blocked",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
            "next_action_label": "manual_review_or_retry_blocked_original_notice_backtrace_without_clearance_claim",
            "review_reasons": ["original_notice_backtrace_no_a_signal"],
            "signal_counts": {"original_notice_fetch_blocked_count": 1},
            "source_refs": {"evidence_state_json": "state.json"},
            "continuation_lineage": {"state_after_evidence_state_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 1}},
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-B",
            "project_name": "B 项目",
            "engineering_work_lane": "construction_or_epc",
            "evidence_state": "P13B_ORIGINAL_BACKTRACE_REQUIRED",
            "evidence_grade": "PENDING_ORIGINAL_BACKTRACE",
            "evidence_signal_source": "p13b_company_history",
            "batch_triage_bucket": "CONTINUE_ORIGINAL_BACKTRACE",
            "closeout_state": "CONTINUE_EVIDENCE_RUN",
            "stage6_fact_package_state": "NOT_READY",
            "stage6_ready": False,
            "stage7_commercial_input_allowed": False,
            "next_action_label": "continue_p13b_original_notice_backtrace",
            "review_reasons": ["original_notice_person_period_not_extracted_review"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    ]
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "BATCH-CLOSEOUT-1",
                "closeout_records": records,
                "summary": {
                    "project_count": len(records),
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
            },
            "summary": {"project_count": len(records)},
        },
    )


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
