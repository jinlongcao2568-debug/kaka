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
                project_ids=["PROJ-CN-GD-JG2026-20001"],
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


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
