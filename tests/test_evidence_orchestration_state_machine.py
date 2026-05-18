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

from storage.evidence_orchestration_state_machine import build_evidence_orchestration_state  # noqa: E402


class EvidenceOrchestrationStateMachineTests(unittest.TestCase):
    def test_builds_ready_p13b_and_design_defer_states_without_p13b_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_count"], 3)
            self.assertEqual(summary["ready_for_p13b_project_count"], 2)
            self.assertEqual(
                summary["evidence_state_counts"],
                {
                    "DEFER_DESIGN_SURVEY_RESPONSIBLE_OVERLAP_ADAPTER": 1,
                    "READY_FOR_P13B_DATA_GGZY": 2,
                },
            )
            adapter_jobs = json.loads((root / "out" / "adapter-job-table.json").read_text(encoding="utf-8"))
            self.assertEqual(adapter_jobs["summary"]["job_type_counts"]["data_ggzy_company_history_overlap_triage"], 2)
            self.assertTrue((root / "out" / "stage6-fact-package-readiness-table.json").exists())

    def test_p13b_backtrace_required_becomes_original_notice_adapter_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            self.assertEqual(by_project["PROJ-CN-GD-JG2026-11398-002"]["evidence_state"], "P13B_ORIGINAL_BACKTRACE_REQUIRED")
            self.assertEqual(by_project["PROJ-CN-GD-JG2026-11398-002"]["evidence_grade"], "PENDING_ORIGINAL_BACKTRACE")
            adapter_jobs = result["manifest"]["adapter_job_table"]["records"]
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11398-002"
                    and job["job_type"] == "p13b_original_notice_backtrace"
                    for job in adapter_jobs
                )
            )

    def test_data_ggzy_direct_overlap_creates_a_signal_and_release_probe_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_direct_a_signal(p13b_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "A_STRONG_TIME_OVERLAP_SIGNAL_READY")
            self.assertEqual(rqsg2["evidence_grade"], "A_STRONG_SIGNAL")
            self.assertEqual(rqsg2["stage6_fact_package_state"], "A_STRONG_SIGNAL_FACT_PACKAGE_READY")
            self.assertTrue(rqsg2["release_evidence_probe_required"])
            fact_rows = result["manifest"]["stage6_fact_package_readiness_table"]["records"]
            fact = _records_by_project(fact_rows)["PROJ-CN-GD-JG2026-11398-002"]
            self.assertTrue(fact["stage7_commercial_input_allowed"])
            self.assertTrue(
                any(
                    job["project_id"] == "PROJ-CN-GD-JG2026-11398-002"
                    and job["job_type"] == "release_evidence_regional_adapter_plan"
                    for job in result["manifest"]["adapter_job_table"]["records"]
                )
            )

    def test_original_notice_overlap_upgrades_backtrace_to_a_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_original_notice_a_signal(original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "A_STRONG_TIME_OVERLAP_SIGNAL_READY")
            self.assertEqual(rqsg2["evidence_signal_source"], "ORIGINAL_NOTICE_BACKTRACE")
            self.assertIn("project_manager_change_notice", rqsg2["release_evidence_source_targets"])

    def test_partial_live_backtrace_deferred_by_budget_stays_pending_not_d_grade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_two_backtrace_required(p13b_root)
            _write_original_notice_partial_deferred(original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "P13B_ORIGINAL_BACKTRACE_REQUIRED")
            self.assertEqual(rqsg2["evidence_grade"], "PENDING_ORIGINAL_BACKTRACE")
            self.assertEqual(rqsg2["recommended_next_action"], "continue_p13b_original_notice_backtrace")
            self.assertIn("original_notice_backtrace_budget_deferred_or_incomplete", rqsg2["review_reasons"])

    def test_browser_readback_blocker_keeps_d_state_retry_reason_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            supplement_json = root / "stage4-inputs.json"
            p13b_root = root / "p13b"
            original_root = root / "original"
            _write_stage16_storage(storage_json)
            _write_company_first_inputs(supplement_json)
            _write_p13b_backtrace_required(p13b_root)
            _write_original_notice_browser_blocked(original_root)

            result = build_evidence_orchestration_state(
                stage16_storage_json=storage_json,
                company_first_stage4_inputs_json=supplement_json,
                p13b_company_history_root=p13b_root,
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            by_project = _records_by_project(result["manifest"]["evidence_state_table"]["records"])
            rqsg2 = by_project["PROJ-CN-GD-JG2026-11398-002"]
            self.assertEqual(rqsg2["evidence_state"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertEqual(rqsg2["recommended_next_action"], "manual_review_or_retry_blocked_original_notice_backtrace")
            self.assertIn("original_notice_backtrace_blocked_or_source_unsupported", rqsg2["review_reasons"])


def _write_stage16_storage(path: Path) -> None:
    candidates = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "project_name": "RQSG2中标候选人公示",
            "source_url": "https://example.test/rqsg2.html",
            "candidate_company": "（主）中国化学工程第六建设有限公司,（成）中国市政工程华北设计研究总院有限公司",
            "primary_responsible_person_name": "曾凡伟",
            "project_manager_name": "曾凡伟",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-001",
            "project_name": "RQSG1中标候选人公示",
            "source_url": "https://example.test/rqsg1.html",
            "candidate_company": "（主）上海能源建设集团有限公司,（成）上海能源建设工程设计研究有限公司",
            "primary_responsible_person_name": "王杰",
            "project_manager_name": "王杰",
            "project_manager_certificate_no": "22ZEZACJ0034",
            "engineering_work_lane": "construction_or_epc",
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "project_name": "规划测绘项目中标候选人公示",
            "source_url": "https://example.test/design.html",
            "candidate_company": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
            "primary_responsible_person_name": "胡昌华",
            "project_manager_name": "",
            "project_manager_certificate_no": "",
            "engineering_work_lane": "survey_design",
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "stage2_detail_capture_state": "FETCHED",
            "stage3_detail_parse_state": "PARSED_WITH_REVIEW",
        },
    ]
    closed = [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": True,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "REVIEW",
            },
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-001",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        },
        {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": False,
                "stage5_rule_gate_status": "REVIEW",
                "stage5_evidence_gate_status": "PASS",
            },
        },
    ]
    payload = {
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
    }
    _write_json(path, payload)


def _write_company_first_inputs(path: Path) -> None:
    _write_json(
        path,
        {
            "items": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-11398-002",
                    "project_name": "RQSG2中标候选人公示",
                    "candidate_company_name": "中国化学工程第六建设有限公司",
                    "candidate_group_id": "CANDIDATE-GROUP-JG2026-11398-002-COMPANY-FIRST-1",
                    "candidate_group_members": ["中国化学工程第六建设有限公司", "中国市政工程华北设计研究总院有限公司"],
                    "responsible_person_name": "曾凡伟",
                    "certificate_no": "鄂1422014201516008",
                    "person_public_id_optional": "002303160131952780",
                }
            ]
        },
    )


def _write_p13b_backtrace_required(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目",
                        "original_notice_url": "https://example.test/history.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    }
                ],
                "manual_original_url_backtrace_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目",
                        "original_notice_url": "https://example.test/history.html",
                    }
                ],
            }
        },
    )


def _write_p13b_direct_a_signal(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "matched_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目",
                        "historical_project_area_code": "襄阳市",
                        "extracted_period_text": "2025-08-01至2026-08-01",
                        "overlap_signal_state": "OVERLAP_SIGNAL_REVIEW_REQUIRED",
                    }
                ]
            }
        },
    )


def _write_p13b_two_backtrace_required(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目一",
                        "original_notice_url": "https://example.test/history-1.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["曾凡伟"],
                        "bid_project_name": "历史项目二",
                        "original_notice_url": "https://example.test/history-2.html",
                        "overlap_signal_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    },
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
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                    }
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "matched_person_names": ["曾凡伟"],
                        "historical_project_area_code": "襄阳市",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED",
                        "release_evidence_probe_triggered": True,
                    }
                ],
                "manual_release_evidence_probe_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "matched_person_names": ["曾凡伟"],
                        "historical_project_area_code": "襄阳市",
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


def _write_original_notice_partial_deferred(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_fetch_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCH_BLOCKED",
                        "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
                        "blocker_taxonomy": ["max_live_original_notices_deferred"],
                    },
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "release_evidence_probe_triggered": False,
                    }
                ],
                "manual_release_evidence_probe_table": [],
            }
        },
    )


def _write_original_notice_browser_blocked(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_fetch_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
                    }
                ],
                "original_notice_extraction_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "original_notice_extraction_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "blocker_taxonomy": [
                            "original_notice_person_period_not_extracted_review",
                            "original_notice_browser_readback_required",
                        ],
                    }
                ],
                "original_notice_overlap_signal_records": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11398-002",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "release_evidence_probe_triggered": False,
                    }
                ],
                "manual_release_evidence_probe_table": [],
            }
        },
    )


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
