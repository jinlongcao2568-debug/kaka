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

from storage.evidence_orchestration_continuation_runner import run_evidence_orchestration_continuation  # noqa: E402


class EvidenceOrchestrationContinuationRunnerTests(unittest.TestCase):
    def test_plan_only_runs_original_backtrace_and_rebuilds_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            p13b_root = root / "p13b"
            _write_stage16_storage(storage_json)
            _write_p13b_backtrace_required(p13b_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                p13b_company_history_root=p13b_root,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["original_action_state"], "ORIGINAL_BACKTRACE_PLAN_BUILT")
            self.assertEqual(summary["original_notice_task_count"], 1)
            self.assertEqual(
                summary["state_after_evidence_state_counts"],
                {"P13B_ORIGINAL_BACKTRACE_REQUIRED": 1},
            )
            self.assertTrue((root / "run" / "01-original-notice-backtrace" / "original-notice-backtrace-v1.json").exists())
            self.assertTrue((root / "run" / "02-evidence-state-after" / "evidence-state-table.json").exists())

    def test_existing_original_backtrace_signal_upgrades_state_without_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_original_notice_a_signal(original_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["original_action_state"], "EXISTING_ORIGINAL_BACKTRACE_CONSUMED")
            self.assertEqual(
                summary["state_after_evidence_state_counts"],
                {"A_STRONG_TIME_OVERLAP_SIGNAL_READY": 1},
            )
            self.assertEqual(summary["state_after_a_strong_signal_project_count"], 1)

    def test_project_ids_are_passed_to_original_backtrace_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            p13b_root = root / "p13b"
            _write_two_project_stage16_storage(storage_json)
            _write_two_project_p13b_backtrace_required(p13b_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                p13b_company_history_root=p13b_root,
                output_root=root / "run",
                project_ids=["JG2026-20002"],
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["state_before_project_count"], 1)
            self.assertEqual(summary["original_notice_task_count"], 1)
            original = json.loads(
                (root / "run" / "01-original-notice-backtrace" / "original-notice-backtrace-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                original["manifest"]["original_notice_task_records"][0]["project_id"],
                "PROJ-CN-GD-JG2026-20002",
            )

    def test_existing_partial_original_backtrace_does_not_block_remaining_pending_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_two_project_stage16_storage(storage_json)
            _write_two_project_p13b_backtrace_required(p13b_root)
            _write_original_notice_a_signal(original_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["original_action_state"], "ORIGINAL_BACKTRACE_CONTINUED_WITH_EXISTING_INPUT")
            self.assertEqual(summary["original_notice_task_count"], 1)
            self.assertEqual(
                summary["state_after_evidence_state_counts"],
                {
                    "A_STRONG_TIME_OVERLAP_SIGNAL_READY": 1,
                    "P13B_ORIGINAL_BACKTRACE_REQUIRED": 1,
                },
            )
            self.assertIn(str(original_root), result["manifest"]["original_notice_backtrace_root"])
            self.assertIn("01-original-notice-backtrace", result["manifest"]["original_notice_backtrace_root"])

    def test_browser_readback_root_is_passed_to_original_backtrace_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            p13b_root = root / "p13b"
            browser_root = root / "browser"
            _write_stage16_storage(storage_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_browser_readback(browser_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                p13b_company_history_root=p13b_root,
                browser_readback_root=browser_root,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["original_action_state"], "ORIGINAL_BACKTRACE_PLAN_BUILT")
            self.assertEqual(
                result["summary"]["state_after_evidence_state_counts"],
                {"A_STRONG_TIME_OVERLAP_SIGNAL_READY": 1},
            )
            original = json.loads(
                (root / "run" / "01-original-notice-backtrace" / "original-notice-backtrace-v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(original["summary"]["browser_readback_ready_count"], 1)

    def test_public_registry_readback_runs_from_existing_fallback_and_keeps_pending_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            fallback_root = root / "public-registry"
            _write_design_stage16_storage(storage_json)
            _write_design_survey_adapter_plan(plan_root)
            _write_design_survey_stage4_public_registry_required(stage4_root)
            _write_design_survey_public_registry_fallback(fallback_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                design_survey_adapter_plan_root=plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_public_registry_fallback_root=fallback_root,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["public_registry_readback_action_state"], "PUBLIC_REGISTRY_READBACK_EXECUTED")
            self.assertEqual(summary["public_registry_readback_record_count"], 1)
            self.assertEqual(
                summary["public_registry_readback_provider_result_state_counts"],
                {"PENDING_IMPLEMENTATION_REVIEW": 1},
            )
            self.assertEqual(
                summary["state_after_evidence_state_counts"],
                {"DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY": 1},
            )
            self.assertTrue(
                (
                    root
                    / "run"
                    / "01c-design-survey-public-registry-readback"
                    / "design-survey-public-registry-readback-v1.json"
                ).exists()
            )

    def test_public_registry_snapshot_match_upgrades_design_project_to_review_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            fallback_root = root / "public-registry"
            snapshot_path = root / "registered-surveyor-snapshot.html"
            _write_design_stage16_storage(storage_json)
            _write_design_survey_adapter_plan(plan_root)
            _write_design_survey_stage4_public_registry_required(stage4_root)
            _write_design_survey_public_registry_fallback(fallback_root)
            snapshot_path.write_text(
                "<table><tr><td>胡昌华</td><td>广州市城市规划勘测设计研究院有限公司</td>"
                "<td>粤测绘20260001</td><td>有效</td></tr></table>",
                encoding="utf-8",
            )

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                design_survey_adapter_plan_root=plan_root,
                design_survey_stage4_execution_root=stage4_root,
                design_survey_public_registry_fallback_root=fallback_root,
                public_registry_snapshot_html_path=snapshot_path,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["public_registry_readback_action_state"], "PUBLIC_REGISTRY_READBACK_EXECUTED")
            self.assertEqual(summary["public_registry_readback_matched_count"], 1)
            self.assertEqual(summary["public_registry_readback_snapshot_supplied_count"], 1)
            self.assertEqual(
                summary["state_after_evidence_state_counts"],
                {"DESIGN_SURVEY_PUBLIC_REGISTRY_IDENTITY_MATCH_READY": 1},
            )

    def test_public_registry_fallback_is_built_then_readback_runs_when_stage4_requires_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            plan_root = root / "design-plan"
            stage4_root = root / "design-stage4"
            _write_design_stage16_storage(storage_json)
            _write_design_survey_adapter_plan(plan_root)
            _write_design_survey_stage4_public_registry_required(stage4_root)

            result = run_evidence_orchestration_continuation(
                stage16_storage_json=storage_json,
                design_survey_adapter_plan_root=plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "run",
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["public_registry_fallback_action_state"], "PUBLIC_REGISTRY_FALLBACK_BUILT")
            self.assertEqual(summary["public_registry_readback_action_state"], "PUBLIC_REGISTRY_READBACK_EXECUTED")
            self.assertEqual(
                summary["state_after_evidence_state_counts"],
                {"DESIGN_SURVEY_PUBLIC_REGISTRY_TASKS_READY": 1},
            )
            self.assertTrue(
                (
                    root
                    / "run"
                    / "01b-design-survey-public-registry-fallback"
                    / "design-survey-public-registry-fallback-v1.json"
                ).exists()
            )


def _write_stage16_storage(path: Path) -> None:
    candidates = [
        {
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "project_name": "测试施工项目中标候选人公示",
            "source_url": "https://example.test/current.html",
            "candidate_company": "广东甲公司",
            "primary_responsible_person_name": "张三",
            "project_manager_name": "张三",
            "project_manager_certificate_no": "粤1442020202100001",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        }
    ]
    closed = [
        {
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        }
    ]
    _write_json(
        path,
        {
            "operator_actions": {
                "operator-autonomous-opportunity-search-runs": [
                    {
                        "object_refs": {
                            "candidate_options_json": json.dumps(candidates, ensure_ascii=False),
                            "closed_loop_results_json": json.dumps(closed, ensure_ascii=False),
                        }
                    }
                ]
            }
        },
    )


def _write_two_project_stage16_storage(path: Path) -> None:
    candidates = [
        {
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "project_name": "测试施工项目一中标候选人公示",
            "source_url": "https://example.test/current-1.html",
            "candidate_company": "广东甲公司",
            "primary_responsible_person_name": "张三",
            "project_manager_name": "张三",
            "project_manager_certificate_no": "粤1442020202100001",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-20002",
            "project_name": "测试施工项目二中标候选人公示",
            "source_url": "https://example.test/current-2.html",
            "candidate_company": "广东乙公司",
            "primary_responsible_person_name": "李四",
            "project_manager_name": "李四",
            "project_manager_certificate_no": "粤1442020202100002",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
    ]
    closed = [
        {
            "project_id": candidate["project_id"],
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        }
        for candidate in candidates
    ]
    _write_json(
        path,
        {
            "operator_actions": {
                "operator-autonomous-opportunity-search-runs": [
                    {
                        "object_refs": {
                            "candidate_options_json": json.dumps(candidates, ensure_ascii=False),
                            "closed_loop_results_json": json.dumps(closed, ensure_ascii=False),
                        }
                    }
                ]
            }
        },
    )


def _write_p13b_backtrace_required(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程",
                        "historical_project_area_code": "广州市",
                        "original_notice_url": "https://example.test/history.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    }
                ],
                "manual_original_url_backtrace_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程",
                        "historical_project_area_code": "广州市",
                        "original_notice_url": "https://example.test/history.html",
                        "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    }
                ],
            }
        },
    )


def _write_two_project_p13b_backtrace_required(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程一",
                        "historical_project_area_code": "广州市",
                        "original_notice_url": "https://example.test/history-1.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20002",
                        "candidate_company_name": "广东乙公司",
                        "responsible_person_names": ["李四"],
                        "bid_project_name": "历史道路工程二",
                        "historical_project_area_code": "深圳市",
                        "original_notice_url": "https://example.test/history-2.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                ],
                "manual_original_url_backtrace_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程一",
                        "historical_project_area_code": "广州市",
                        "original_notice_url": "https://example.test/history-1.html",
                        "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20002",
                        "candidate_company_name": "广东乙公司",
                        "responsible_person_names": ["李四"],
                        "bid_project_name": "历史道路工程二",
                        "historical_project_area_code": "深圳市",
                        "original_notice_url": "https://example.test/history-2.html",
                        "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                ],
            }
        },
    )


def _write_browser_readback(root: Path) -> None:
    _write_json(
        root / "browser-original-readback-v1.json",
        {
            "manifest": {
                "browser_original_readback_records": [
                    {
                        "original_notice_task_id": "",
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程",
                        "original_notice_url": "https://example.test/history.html",
                        "source_url": "https://example.test/history.html",
                        "browser_readback_state": "BROWSER_ORIGINAL_READBACK_READY",
                        "status_code": 200,
                        "content_type": "text/plain",
                        "extracted_responsible_person_names": ["张三"],
                        "extracted_company_names": ["广东甲公司"],
                        "extracted_period_text": "365日历天",
                        "extracted_award_date": "2025年10月15日",
                        "text_probe": "中标单位：广东甲公司\n项目经理：张三\n工期：365日历天",
                        "record_payload_sha256": "browser-readback-record",
                    }
                ]
            }
        },
    )


def _write_original_notice_a_signal(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_fetch_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                    }
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "matched_person_names": ["张三"],
                        "historical_project_area_code": "广州市",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED",
                        "release_evidence_probe_triggered": True,
                    }
                ],
                "manual_release_evidence_probe_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20001",
                        "candidate_company_name": "广东甲公司",
                        "matched_person_names": ["张三"],
                        "historical_project_area_code": "广州市",
                        "release_evidence_source_targets": [
                            "construction_permit",
                            "contract_public_info",
                            "completion_filing",
                            "project_manager_change_notice",
                        ],
                    }
                ],
            }
        },
    )


def _write_design_stage16_storage(path: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    candidates = [
        {
            "project_id": project_id,
            "project_name": "规划测绘项目中标候选人公示",
            "source_url": "https://example.test/design.html",
            "candidate_company": "广州市城市规划勘测设计研究院有限公司",
            "primary_responsible_person_name": "胡昌华",
            "engineering_work_lane": "survey_design",
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        }
    ]
    closed = [
        {
            "project_id": project_id,
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        }
    ]
    _write_json(
        path,
        {
            "operator_actions": {
                "operator-autonomous-opportunity-search-runs": [
                    {
                        "object_refs": {
                            "candidate_options_json": json.dumps(candidates, ensure_ascii=False),
                            "closed_loop_results_json": json.dumps(closed, ensure_ascii=False),
                        }
                    }
                ]
            }
        },
    )


def _write_design_survey_adapter_plan(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    company = "广州市城市规划勘测设计研究院有限公司"
    _write_json(
        root / "design-survey-responsible-adapter-plan-v1.json",
        {
            "manifest": {
                "project_table": {
                    "records": [
                        {
                            "design_survey_project_id": "DESIGN-SURVEY-PROJECT-1",
                            "project_id": project_id,
                            "project_name": "规划测绘项目中标候选人公示",
                            "candidate_group_members": [company],
                            "responsible_person_name": "胡昌华",
                            "engineering_work_lane": "survey_design",
                            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
                            "adapter_readiness_state": "READY_FOR_DESIGN_SURVEY_STAGE4_PLAN",
                            "customer_visible_allowed": False,
                            "no_legal_conclusion": True,
                        }
                    ]
                }
            }
        },
    )


def _write_design_survey_stage4_public_registry_required(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    _write_json(
        root / "company-first-stage4-execution.json",
        {
            "manifest": {
                "items": [
                    {
                        "job_id": "STAGE4-FLOW08-INPUT-JOB-1",
                        "project_id": project_id,
                        "project_name": "规划测绘项目中标候选人公示",
                        "candidate_company_name": "广州市城市规划勘测设计研究院有限公司",
                        "candidate_group_members": ["广州市城市规划勘测设计研究院有限公司"],
                        "responsible_person_name": "胡昌华",
                        "responsible_role": "survey_mapping_project_lead",
                        "source_certificate_no_optional": "粤测绘20260001",
                        "stage4_execution_state": "FAIL_CLOSED",
                        "identity_resolution_state": "UNKNOWN",
                        "supplement_after_execution_state": "DESIGN_SURVEY_PUBLIC_REGISTRY_FALLBACK_REQUIRED",
                        "candidate_group_resolution_state": "UNRESOLVED_NO_MEMBER_MATCHED",
                        "fail_closed_reasons": ["jzsc_does_not_cover_registered_surveyor_credential"],
                    }
                ],
                "stage4_candidate_verification_inputs": {"items": []},
                "summary": {"project_count": 1, "job_count": 1},
            }
        },
    )


def _write_design_survey_public_registry_fallback(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    company = "广州市城市规划勘测设计研究院有限公司"
    payload = {
        "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
        "provider_role": "registered_surveyor_person_company_certificate_identity",
        "source_probe_item": {
            "project_id": project_id,
            "project_name": "规划测绘项目中标候选人公示",
        },
        "target": {
            "project_id": project_id,
            "candidate_company_name": company,
            "candidate_group_members": [company],
            "responsible_person_name": "胡昌华",
            "certificate_no_optional": "粤测绘20260001",
        },
        "source_public_registry_task": {
            "public_registry_task_id": "DESIGN-SURVEY-PUBLIC-REG-TASK-1",
            "query_fields": {
                "person_name": "胡昌华",
                "registered_unit_or_candidate_company": company,
                "certificate_no_optional": "粤测绘20260001",
                "candidate_group_members": [company],
            },
        },
    }
    _write_json(
        root / "design-survey-public-registry-fallback-v1.json",
        {
            "manifest": {
                "public_registry_target_table": {
                    "records": [
                        {
                            "project_id": project_id,
                            "candidate_company_name": company,
                            "responsible_person_name": "胡昌华",
                            "target_readiness_state": "READY_FOR_REGISTERED_SURVEYOR_PUBLIC_REGISTRY",
                        }
                    ]
                },
                "public_registry_task_table": {
                    "records": [
                        {
                            "project_id": project_id,
                            "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
                            "task_type": "NATURAL_RESOURCE_REGISTERED_SURVEYOR_PERSON_COMPANY_MATCH",
                            "task_state": "PLAN_ONLY_ENTRY_NEEDS_LIVE_VERIFY",
                        }
                    ]
                },
                "stage4_provider_jobs": {
                    "jobs": [
                        {
                            "job_id": "STAGE4-PUBLIC-REG-JOB-1",
                            "project_id": project_id,
                            "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
                            "payload": payload,
                            "status": "QUEUED_NOT_EXECUTED",
                        }
                    ]
                },
            }
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
