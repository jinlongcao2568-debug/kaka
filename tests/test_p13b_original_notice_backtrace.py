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

from storage.p13b_original_notice_backtrace import build_p13b_original_notice_backtrace  # noqa: E402


class P13BOriginalNoticeBacktraceTests(unittest.TestCase):
    def test_plan_only_generates_original_notice_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["original_notice_task_count"], 3)
            self.assertEqual(summary["original_notice_fetch_count"], 0)
            tasks = result["manifest"]["original_notice_task_records"]
            self.assertTrue(any(task["ygp_original_url_pointer_only"] for task in tasks))
            self.assertTrue((root / "out" / "original-notice-backtrace-v1.json").exists())

    def test_live_original_notice_extracts_overlap_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["original_notice_person_period_extracted_count"], 1)
            self.assertEqual(summary["original_notice_overlap_signal_review_required_count"], 1)
            self.assertEqual(summary["manual_release_evidence_probe_count"], 1)
            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["extracted_responsible_person_names"], ["张三"])
            self.assertIn("365日历天", extraction["extracted_period_text"])
            self.assertEqual(extraction["extracted_award_date"], "2026年05月01日")
            release_table = result["manifest"]["manual_release_evidence_probe_table"]
            self.assertEqual(release_table[0]["suggested_next_step"], "targeted_release_evidence_probe")

    def test_company_without_person_does_not_trigger_release_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="https://example.gov.cn/original/no-person.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["original_notice_overlap_signal_review_required_count"], 0)
            self.assertEqual(summary["overlap_signal_state_counts"]["ORIGINAL_NOTICE_NO_MATCH_REVIEW"], 1)
            self.assertEqual(result["manifest"]["manual_release_evidence_probe_table"], [])

    def test_blocked_original_notice_is_taxonomized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="https://example.gov.cn/original/blocked.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=3,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["fetch_state_counts"]["ORIGINAL_NOTICE_FETCH_BLOCKED"], 1)
            self.assertEqual(summary["fetch_state_counts"]["ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"], 1)
            self.assertIn("original_notice_forbidden_or_rate_limited_review", summary["blocker_taxonomy_counts"])

    def test_report_never_contains_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_p13b_input(root: Path, *, first_url: str = "https://example.gov.cn/original/overlap.html") -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "manual_original_url_backtrace_table": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20001",
                    "candidate_company_name": "广东甲公司",
                    "responsible_person_names": ["张三"],
                    "bid_project_name": "历史道路工程",
                    "original_notice_url": first_url,
                    "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    "suggested_next_step": "targeted_original_notice_01_to_12_backtrace",
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    "suggested_next_step": "targeted_original_notice_01_to_12_backtrace",
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20003",
                    "candidate_company_name": "广东丙公司",
                    "responsible_person_names": ["王五"],
                    "bid_project_name": "历史隧道工程",
                    "original_notice_url": "ftp://example.invalid/unsupported",
                    "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    "suggested_next_step": "targeted_original_notice_01_to_12_backtrace",
                },
            ],
            "bid_show_records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20001",
                    "candidate_company_name": "广东甲公司",
                    "bid_show_record_id": "BID-SHOW-1",
                    "bid_show_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
                    "bid_project_name": "历史道路工程",
                    "original_notice_url": first_url,
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "bid_show_record_id": "BID-SHOW-2",
                    "bid_show_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=2",
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                },
            ],
        }
    }
    _write_json(root / "company-history-overlap-triage-v1.json", payload)


def _fake_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if url.endswith("/blocked.html"):
        return {"status_code": 403, "content_type": "text/html", "body": "forbidden"}
    if url.endswith("/no-person.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": "<html><body><p>中标人：广东甲公司</p><p>工期：180日历天</p><p>中标日期：2026年05月02日</p></body></html>",
        }
    return {
        "status_code": 200,
        "content_type": "text/html",
        "body": "<html><body><p>中标人：广东甲公司</p><p>项目负责人：张三</p><p>工期（交货期）：365日历天</p><p>中标日期：2026年05月01日</p></body></html>",
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
