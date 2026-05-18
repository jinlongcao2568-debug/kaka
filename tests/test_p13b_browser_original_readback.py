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

from storage.p13b_browser_original_readback import build_p13b_browser_original_readback  # noqa: E402
from storage.p13b_original_notice_backtrace import build_p13b_original_notice_backtrace  # noqa: E402


class P13BBrowserOriginalReadbackTests(unittest.TestCase):
    def test_plan_only_generates_browser_tasks_from_js_shell_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(result["summary"]["browser_original_readback_task_count"], 1)
            self.assertEqual(result["summary"]["browser_original_readback_count"], 0)

    def test_live_browser_readback_extracts_person_and_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_readback_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["browser_original_readback_ready_count"], 1)
            self.assertEqual(summary["browser_original_person_period_extracted_count"], 1)
            record = result["manifest"]["browser_original_readback_records"][0]
            self.assertEqual(record["browser_readback_state"], "BROWSER_ORIGINAL_READBACK_READY")
            self.assertEqual(record["extracted_responsible_person_names"], ["王杰"])
            self.assertIn("365日历天", record["extracted_period_text"])

    def test_service_time_is_extracted_as_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_service_time_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            record = result["manifest"]["browser_original_readback_records"][0]
            self.assertIn("30天", record["extracted_period_text"])

    def test_table_layout_fields_are_extractable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_table_layout_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            record = result["manifest"]["browser_original_readback_records"][0]
            self.assertEqual(record["extracted_responsible_person_names"], ["赵六"])
            self.assertIn("中国市政工程华北设计研究总院有限公司", record["extracted_company_names"])
            self.assertIn("完整正文", record["text_extractable"])

    def test_non_person_table_labels_are_not_responsible_people(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_non_person_label_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            record = result["manifest"]["browser_original_readback_records"][0]
            self.assertEqual(record["extracted_responsible_person_names"], [])
            self.assertIn("中国化学工程第六建设有限公司", record["extracted_company_names"])

    def test_slash_role_label_and_winning_duration_are_extractable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_slash_role_duration_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            record = result["manifest"]["browser_original_readback_records"][0]
            self.assertEqual(record["extracted_responsible_person_names"], ["豆连旺"])
            self.assertEqual(record["extracted_period_text"], "180日历天")

    def test_original_backtrace_consumes_browser_readback_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            p13b_root = root / "p13b"
            original_root = root / "original"
            browser_root = root / "browser"
            _write_company_history_input(p13b_root)
            original = build_p13b_original_notice_backtrace(
                input_root=p13b_root,
                output_root=original_root,
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_js_shell_original_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )
            self.assertIn(
                "original_notice_browser_readback_required",
                original["manifest"]["original_notice_extraction_records"][0]["blocker_taxonomy"],
            )
            build_p13b_browser_original_readback(
                input_root=original_root,
                output_root=browser_root,
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_readback_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            repaired = build_p13b_original_notice_backtrace(
                input_root=p13b_root,
                browser_readback_root=f"{root / 'empty-browser'};{browser_root}",
                output_root=root / "repaired",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertEqual(repaired["summary"]["browser_readback_ready_count"], 1)
            self.assertEqual(repaired["summary"]["original_notice_person_period_extracted_count"], 1)
            self.assertEqual(repaired["summary"]["original_notice_overlap_signal_review_required_count"], 1)
            extraction = repaired["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["extraction_source"], "BROWSER_ORIGINAL_READBACK")
            self.assertEqual(extraction["extracted_responsible_person_names"], ["王杰"])

    def test_report_never_contains_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_browser_original_readback(
                input_root=root,
                output_root=root / "browser",
                enable_live_public_query=True,
                max_live_browser_readbacks=1,
                browser_readback_getter=_fake_browser_readback_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_original_backtrace_input(root: Path) -> None:
    _write_json(
        root / "original-notice-backtrace-v1.json",
        {
            "manifest": {
                "original_notice_extraction_records": [
                    {
                        "original_notice_task_id": "P13B-ORIGINAL-NOTICE-1",
                        "project_id": "PROJ-CN-GD-JG2026-20002",
                        "candidate_company_name": "上海能源建设集团有限公司",
                        "responsible_person_names": ["王杰"],
                        "bid_project_name": "历史燃气工程",
                        "original_notice_url": "https://example.gov.cn/history/js-shell.html",
                        "source_url": "https://example.gov.cn/history/js-shell.html",
                        "original_notice_extraction_state": "ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                        "blocker_taxonomy": [
                            "original_notice_person_period_not_extracted_review",
                            "original_notice_browser_readback_required",
                        ],
                    }
                ]
            }
        },
    )


def _write_company_history_input(root: Path) -> None:
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {
            "manifest": {
                "manual_original_url_backtrace_table": [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-20002",
                        "candidate_company_name": "上海能源建设集团有限公司",
                        "responsible_person_names": ["王杰"],
                        "bid_project_name": "历史燃气工程",
                        "historical_project_area_code": "上海市",
                        "original_notice_url": "https://example.gov.cn/history/js-shell.html",
                        "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    }
                ]
            }
        },
    )


def _fake_js_shell_original_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "url": url,
        "body": "window._AMapSecurityConfig = {}; We're sorry but 交易平台 doesn't work properly without JavaScript enabled. Please enable it to continue.",
    }


def _fake_browser_readback_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/plain; charset=utf-8",
        "url": url,
        "body": "历史燃气工程中标结果公告\n中标单位：上海能源建设集团有限公司\n项目经理：王杰\n工期：365日历天\n中标日期：2025年10月15日",
    }


def _fake_browser_service_time_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/plain; charset=utf-8",
        "url": url,
        "body": "历史燃气工程中标结果公告\n供应商名称：上海能源建设集团有限公司\n服务时间：30天",
    }


def _fake_browser_table_layout_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/plain; charset=utf-8",
        "url": url,
        "body": "完整正文\n中标人信息\n单位名称\n中国市政工程华北设计研究总院有限公司\n项目负责人\n赵六\n服务期：30天",
    }


def _fake_browser_non_person_label_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/plain; charset=utf-8",
        "url": url,
        "body": "项目负责人姓名\n中标人\n中国化学工程第六建设有限公司\n中标价：100万元",
    }


def _fake_browser_slash_role_duration_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/plain; charset=utf-8",
        "url": url,
        "body": "中标单位：上海能源建设工程设计研究有限公司\n中标工期（日历天）：180\n建筑师/总监/负责人：豆连旺",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
