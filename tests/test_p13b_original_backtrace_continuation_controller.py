from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.p13b_original_backtrace_continuation_controller import (  # noqa: E402
    build_p13b_original_backtrace_continuation_controller,
)


class P13BOriginalBacktraceContinuationControllerTests(unittest.TestCase):
    def test_deferred_tasks_become_delta_backtrace_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_root = root / "original"
            _write_partial_original_backtrace(original_root)

            result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                project_ids=["JG2026-20001"],
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["continuation_run_task_count"], 1)
            self.assertEqual(summary["deferred_task_count"], 1)
            self.assertEqual(summary["targeted_person_readback_required_count"], 1)
            self.assertEqual(summary["recommended_next_action"], "RUN_NEXT_ORIGINAL_BACKTRACE_BATCH")
            states = summary["continuation_state_counts"]
            self.assertEqual(states["CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT"], 1)
            self.assertEqual(states["TARGETED_PERSON_READBACK_REQUIRED"], 1)
            self.assertEqual(states["TARGETED_YGP_READBACK_REQUIRED"], 1)
            self.assertEqual(states["PARK_DIFFERENT_PERSON_WITH_PERIOD"], 1)
            self.assertEqual(summary["closeout_precedence_suppressed_count"], 3)
            self.assertEqual(summary["original_readback_terminal_marker_count"], 3)
            self.assertEqual(summary["runtime_blocker_ledger_count"], 1)
            self.assertEqual(
                summary["next_queue_counts"],
                {
                    "manual_hold": 1,
                    "original_readback_retry": 1,
                    "route_specific_original_readback": 1,
                    "targeted_person_readback": 1,
                },
            )
            self.assertEqual(
                summary["runtime_blocker_ledger_state_counts"],
                {"ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED": 1},
            )

            continuation_input = json.loads(
                (
                    root
                    / "out"
                    / "continuation-input"
                    / "company-history-overlap-triage-v1.json"
                ).read_text(encoding="utf-8")
            )
            rows = continuation_input["manifest"]["manual_original_url_backtrace_table"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["original_notice_url"], "https://example.test/deferred.html")
            self.assertEqual(rows[0]["backtrace_reason"], "CONTINUE_ORIGINAL_BACKTRACE_WITH_BUDGET_LIMIT")

    def test_original_readback_outputs_terminal_markers_ledgers_and_operator_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_root = root / "original"
            _write_partial_original_backtrace(original_root)

            result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                project_ids=["JG2026-20001"],
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["continuation_plan_record_count"], 4)
            self.assertEqual(summary["original_readback_terminal_marker_count"], 3)
            self.assertEqual(summary["closeout_precedence_suppressed_count"], 3)
            self.assertEqual(summary["runtime_blocker_ledger_count"], 1)
            self.assertEqual(
                summary["next_queue_counts"],
                {
                    "manual_hold": 1,
                    "original_readback_retry": 1,
                    "route_specific_original_readback": 1,
                    "targeted_person_readback": 1,
                },
            )
            records = {
                record["original_notice_task_id"]: record
                for record in result["manifest"]["continuation_plan_records"]
            }
            deferred = records["TASK-DEFERRED"]
            self.assertFalse(deferred["closeout_precedence_suppressed"])
            self.assertEqual(deferred["next_queue"], "original_readback_retry")
            self.assertEqual(
                deferred["runtime_blocker_ledger_record"]["blocker_state"],
                "ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED",
            )
            self.assertEqual(
                deferred["runtime_blocker_ledger_records"],
                [deferred["runtime_blocker_ledger_record"]],
            )
            targeted = records["TASK-PERIOD-NO-PERSON"]
            self.assertTrue(targeted["closeout_precedence_suppressed"])
            self.assertEqual(targeted["next_queue"], "targeted_person_readback")
            self.assertEqual(targeted["terminal_closeout_markers"][0]["task_family"], "original_readback")
            self.assertEqual(
                targeted["operator_projection"]["projection_state"],
                "NEXT_ORIGINAL_READBACK_SUBQUEUE_READY",
            )
            self.assertEqual(targeted["runtime_blocker_ledger_record"], {})
            self.assertEqual(targeted["runtime_blocker_ledger_records"], [])
            ygp = records["TASK-YGP"]
            self.assertEqual(ygp["next_queue"], "route_specific_original_readback")
            self.assertTrue(ygp["terminal_backfill_markers"])
            self.assertEqual(ygp["runtime_blocker_ledger_record"], {})
            self.assertEqual(ygp["runtime_blocker_ledger_records"], [])
            different = records["TASK-DIFFERENT"]
            self.assertEqual(different["continuation_state"], "PARK_DIFFERENT_PERSON_WITH_PERIOD")
            self.assertTrue(different["closeout_precedence_suppressed"])
            self.assertEqual(different["runtime_blocker_ledger_record"], {})
            self.assertEqual(different["runtime_blocker_ledger_records"], [])

    def test_consumed_ygp_readback_does_not_loop_back_to_ygp_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_root = root / "original"
            _write_consumed_ygp_original_backtrace(original_root)

            result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                project_ids=["PROJ-CN-GD-JG2026-20001"],
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            states = summary["continuation_state_counts"]
            self.assertNotIn("TARGETED_YGP_READBACK_REQUIRED", states)
            self.assertEqual(states["PARK_NO_EXTRACTED_MATCH_FIELDS"], 1)
            self.assertEqual(summary["recommended_next_action"], "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM")
            self.assertEqual(summary["closeout_precedence_suppressed_count"], 1)
            self.assertEqual(summary["original_readback_terminal_marker_count"], 1)
            self.assertEqual(summary["next_queue_counts"], {"manual_hold": 1})
            record = result["manifest"]["continuation_plan_records"][0]
            self.assertTrue(record["closeout_precedence_suppressed"])
            self.assertEqual(record["original_readback_closeout_state"], "TERMINAL_ORIGINAL_READBACK_CLOSEOUT")
            self.assertEqual(
                record["operator_projection"]["projection_state"],
                "ORIGINAL_READBACK_MANUAL_HOLD",
            )

    def test_consumed_targeted_person_readback_does_not_loop_back_to_targeted_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_root = root / "original"
            targeted_root = root / "targeted"
            _write_partial_original_backtrace(original_root)
            _write_targeted_person_readback_not_found(targeted_root)

            result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_root=original_root,
                targeted_person_readback_root=targeted_root,
                output_root=root / "out",
                project_ids=["PROJ-CN-GD-JG2026-20001"],
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            states = result["summary"]["continuation_state_counts"]
            self.assertEqual(states["PARK_TARGETED_PERSON_NOT_FOUND"], 1)
            self.assertEqual(states.get("TARGETED_PERSON_READBACK_REQUIRED", 0), 0)

    def test_blocked_original_notice_uses_formal_manual_hold_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_root = root / "original"
            _write_blocked_original_backtrace(original_root)

            result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                project_ids=["PROJ-CN-GD-JG2026-30001"],
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["continuation_state_counts"], {"BLOCKED_OR_SOURCE_UNSUPPORTED": 1})
            self.assertEqual(summary["next_queue_counts"], {"manual_hold": 1})
            record = result["manifest"]["continuation_plan_records"][0]
            self.assertEqual(record["continuation_state"], "BLOCKED_OR_SOURCE_UNSUPPORTED")
            self.assertEqual(record["next_queue"], "manual_hold")
            self.assertEqual(
                record["operator_projection"]["projection_state"],
                "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
            )
            self.assertTrue(record["runtime_blocker_ledger_record"]["operator_next_action"])

    def test_release_evidence_ready_original_readback_records_projection_suppression_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_root = root / "original"
            _write_ready_original_backtrace(original_root)

            result = build_p13b_original_backtrace_continuation_controller(
                original_notice_backtrace_root=original_root,
                output_root=root / "out",
                project_ids=["PROJ-CN-GD-JG2026-40001"],
                created_at="2026-05-23T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["runtime_blocker_ledger_count"], 1)
            record = result["manifest"]["continuation_plan_records"][0]
            self.assertEqual(record["continuation_state"], "RELEASE_EVIDENCE_READY")
            self.assertTrue(record["closeout_precedence_suppressed"])
            self.assertEqual(
                record["runtime_blocker_ledger_record"]["blocker_state"],
                "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
            )
            self.assertEqual(
                record["runtime_blocker_ledger_records"],
                [record["runtime_blocker_ledger_record"]],
            )
            self.assertEqual(
                record["operator_projection"]["projection_state"],
                "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK",
            )


def _write_partial_original_backtrace(root: Path) -> None:
    records = [
        {
            "original_notice_task_id": "TASK-DEFERRED",
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "bid_project_name": "历史道路工程一",
            "historical_project_area_code": "广州市",
            "original_notice_url": "https://example.test/deferred.html",
            "bid_show_record_id": "BID-1",
            "bid_show_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
            "original_notice_live_priority_score": 90,
            "original_notice_live_priority_rank": 1,
            "fetch_state": "ORIGINAL_NOTICE_FETCH_BLOCKED",
            "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
            "blocker_taxonomy": ["max_live_original_notices_deferred"],
        },
        {
            "original_notice_task_id": "TASK-PERIOD-NO-PERSON",
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "bid_project_name": "历史道路工程二",
            "original_notice_url": "https://example.test/company-period.html",
            "fetch_state": "ORIGINAL_NOTICE_FETCHED",
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        },
        {
            "original_notice_task_id": "TASK-DIFFERENT",
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "bid_project_name": "历史道路工程三",
            "original_notice_url": "https://example.test/different.html",
            "fetch_state": "ORIGINAL_NOTICE_FETCHED",
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
        },
        {
            "original_notice_task_id": "TASK-YGP",
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "bid_project_name": "历史道路工程四",
            "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/abc-3C52",
            "original_notice_route_class": "YGP_MAPPING_POINTER",
            "original_notice_live_budget_eligible": False,
            "fetch_state": "ORIGINAL_NOTICE_FETCH_BLOCKED",
            "execution_mode": "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT",
            "blocker_taxonomy": ["max_live_original_notices_deferred"],
        },
    ]
    overlap_records = [
        {
            "original_notice_task_id": "TASK-PERIOD-NO-PERSON",
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "original_notice_backtrace_match_state": "PERIOD_AND_COMPANY_NO_PERSON",
            "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
            "candidate_company_matched": True,
            "performance_period_present": True,
            "extracted_period_text": "180日历天",
        },
        {
            "original_notice_task_id": "TASK-DIFFERENT",
            "project_id": "PROJ-CN-GD-JG2026-20001",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "different_person_names": ["李四"],
            "original_notice_backtrace_match_state": "EXTRACTED_DIFFERENT_PERSON_WITH_PERIOD",
            "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
            "candidate_company_matched": True,
            "performance_period_present": True,
            "extracted_period_text": "365日历天",
        },
    ]
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_task_records": records,
                "original_notice_fetch_records": records,
                "original_notice_overlap_signal_records": overlap_records,
            }
        },
    )


def _write_consumed_ygp_original_backtrace(root: Path) -> None:
    record = {
        "original_notice_task_id": "TASK-YGP-CONSUMED",
        "project_id": "PROJ-CN-GD-JG2026-20001",
        "candidate_company_name": "广东甲公司",
        "responsible_person_names": ["张三"],
        "bid_project_name": "历史道路工程四",
        "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/abc-3C52",
        "original_notice_route_class": "YGP_MAPPING_POINTER",
        "original_notice_live_budget_eligible": False,
        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
        "execution_mode": "LOCAL_YGP_READBACK_CONSUMED",
        "blocker_taxonomy": [],
    }
    overlap = {
        "original_notice_task_id": "TASK-YGP-CONSUMED",
        "project_id": "PROJ-CN-GD-JG2026-20001",
        "candidate_company_name": "广东甲公司",
        "responsible_person_names": ["张三"],
        "original_notice_backtrace_match_state": "NO_COMPANY_PERSON_PERIOD_MATCH",
        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
        "candidate_company_matched": False,
        "performance_period_present": False,
        "extracted_period_text": "",
    }
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_task_records": [record],
                "original_notice_fetch_records": [record],
                "original_notice_overlap_signal_records": [overlap],
            }
        },
    )


def _write_targeted_person_readback_not_found(root: Path) -> None:
    _write_json(
        root / "p13b-targeted-person-readback-v1.json",
        {
            "manifest": {
                "targeted_person_readback_records": [
                    {
                        "original_notice_task_id": "TASK-PERIOD-NO-PERSON",
                        "targeted_person_readback_state": "TARGETED_PERSON_NOT_FOUND_IN_TARGETED_READBACK",
                        "same_person_company_period_signal_ready": False,
                        "blocker_taxonomy": ["targeted_person_not_found_in_page_or_attachments"],
                        "review_reasons": ["targeted_person_not_found_in_page_or_attachments"],
                    }
                ]
            }
        },
    )


def _write_blocked_original_backtrace(root: Path) -> None:
    record = {
        "original_notice_task_id": "TASK-BLOCKED-URL",
        "project_id": "PROJ-CN-GD-JG2026-30001",
        "candidate_company_name": "广东乙公司",
        "responsible_person_names": ["王五"],
        "bid_project_name": "历史道路工程五",
        "original_notice_url": "",
        "original_notice_route_class": "INVALID_OR_MISSING_URL",
        "fetch_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
        "execution_mode": "LIVE_PUBLIC_QUERY_BLOCKED",
        "blocker_taxonomy": ["original_notice_url_missing_or_invalid"],
    }
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_task_records": [record],
                "original_notice_fetch_records": [record],
                "original_notice_overlap_signal_records": [],
            }
        },
    )


def _write_ready_original_backtrace(root: Path) -> None:
    record = {
        "original_notice_task_id": "TASK-SAME-PERSON-READY",
        "project_id": "PROJ-CN-GD-JG2026-40001",
        "candidate_company_name": "广东丙公司",
        "responsible_person_names": ["赵六"],
        "bid_project_name": "历史道路工程六",
        "original_notice_url": "https://example.test/ready.html",
        "fetch_state": "ORIGINAL_NOTICE_FETCHED",
        "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
    }
    overlap = {
        "original_notice_task_id": "TASK-SAME-PERSON-READY",
        "project_id": "PROJ-CN-GD-JG2026-40001",
        "candidate_company_name": "广东丙公司",
        "responsible_person_names": ["赵六"],
        "original_notice_backtrace_match_state": "SAME_PERSON_COMPANY_PERIOD_SIGNAL",
        "original_notice_overlap_signal_state": "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED",
        "candidate_company_matched": True,
        "performance_period_present": True,
        "extracted_period_text": "240日历天",
    }
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_task_records": [record],
                "original_notice_fetch_records": [record],
                "original_notice_overlap_signal_records": [overlap],
            }
        },
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
