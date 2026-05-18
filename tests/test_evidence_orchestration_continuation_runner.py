from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Mapping


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


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
