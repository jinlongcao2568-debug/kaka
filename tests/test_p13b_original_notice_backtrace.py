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

from storage.p13b_original_notice_backtrace import (  # noqa: E402
    _canonical_original_notice_url,
    _request_safe_url,
    build_p13b_original_notice_backtrace,
    main,
)


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
            self.assertIn("original_notice_route_class_counts", summary)
            self.assertTrue((root / "out" / "original-notice-task-triage-table.json").exists())
            self.assertTrue((root / "out" / "original-notice-backtrace-v1.json").exists())

    def test_plan_only_prioritizes_direct_official_notice_before_bad_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input_from_rows(
                root,
                [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史服务采购结果公告",
                        "original_notice_url": "公告地址为空",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程施工中标结果公告",
                        "original_notice_url": "https://ggzy.zj.gov.cn/jyxxgk/002001/002001005/20260501/direct.html",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史设计中标结果公告",
                        "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    },
                ],
            )

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            tasks = result["manifest"]["original_notice_task_records"]
            self.assertEqual(tasks[0]["original_notice_route_class"], "OFFICIAL_DIRECT_HTML")
            self.assertEqual(tasks[0]["original_notice_live_priority_band"], "P0_DIRECT_OFFICIAL_HTML")
            self.assertEqual(tasks[-1]["original_notice_route_class"], "INVALID_OR_MISSING_URL")
            triage = result["manifest"]["original_notice_task_triage_table"]
            self.assertEqual(triage["summary"]["route_class_counts"]["OFFICIAL_DIRECT_HTML"], 1)
            self.assertEqual(result["summary"]["original_notice_budget_eligible_count"], 1)

    def test_live_budget_uses_prioritized_direct_notice_before_bad_first_row(self) -> None:
        called_urls: list[str] = []

        def getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
            called_urls.append(url)
            return _fake_http_getter(url, context)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            direct_url = "https://ggzy.zj.gov.cn/jyxxgk/002001/002001005/20260501/direct.html"
            _write_p13b_input_from_rows(
                root,
                [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史服务采购结果公告",
                        "original_notice_url": "公告地址为空",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "广东甲公司",
                        "responsible_person_names": ["张三"],
                        "bid_project_name": "历史道路工程施工中标结果公告",
                        "original_notice_url": direct_url,
                    },
                ],
            )

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(called_urls, [direct_url])
            fetch = result["manifest"]["original_notice_fetch_records"][0]
            self.assertEqual(fetch["original_notice_route_class"], "OFFICIAL_DIRECT_HTML")
            self.assertEqual(fetch["original_notice_url"], direct_url)

    def test_table_layout_project_responsible_person_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input_from_rows(
                root,
                [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["尹家驹"],
                        "bid_project_name": "10t/d 垃圾焚烧飞灰资源化综合利用中试研究项目施工标段中标结果公示",
                        "original_notice_url": "https://example.gov.cn/original/table-person.html",
                    },
                ],
            )

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["extracted_responsible_person_names"], ["尹家驹"])
            self.assertEqual(extraction["extracted_period_text"], "150日历天")
            self.assertEqual(result["summary"]["original_notice_overlap_signal_review_required_count"], 1)

    def test_columnar_table_period_after_amount_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input_from_rows(
                root,
                [
                    {
                        "project_id": "PROJ-CN-GD-JG2026-30001",
                        "candidate_company_name": "中国化学工程第六建设有限公司",
                        "responsible_person_names": ["胡琦"],
                        "bid_project_name": "大型模块化深冷装备智能制造基地项目工程总承包（EPC）中标结果公告",
                        "original_notice_url": "https://example.gov.cn/original/column-table-person.html",
                    },
                ],
            )

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["extracted_responsible_person_names"], ["胡琦"])
            self.assertEqual(extraction["extracted_period_text"], "270天")
            self.assertEqual(result["summary"]["original_notice_overlap_signal_review_required_count"], 1)

    def test_plan_only_does_not_call_http_getter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                http_getter=_raising_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(result["summary"]["original_notice_fetch_count"], 0)

    def test_request_safe_url_quotes_chinese_path_and_query(self) -> None:
        url = "https://example.gov.cn/公告/中标结果.html?title=历史项目&x=1"

        safe_url = _request_safe_url(url)

        self.assertIn("%E5%85%AC%E5%91%8A", safe_url)
        self.assertIn("title=%E5%8E%86%E5%8F%B2%E9%A1%B9%E7%9B%AE", safe_url)
        safe_url.encode("ascii")

    def test_original_notice_url_canonicalization_repairs_scheme_less_domain(self) -> None:
        url, blockers = _canonical_original_notice_url("www.tjconstruct.cn/jyxx/notice.html?x=1")

        self.assertEqual(url, "https://www.tjconstruct.cn/jyxx/notice.html?x=1")
        self.assertEqual(blockers, [])

    def test_original_notice_url_canonicalization_marks_placeholder_as_missing(self) -> None:
        url, blockers = _canonical_original_notice_url("公告地址为空")

        self.assertEqual(url, "公告地址为空")
        self.assertEqual(blockers, ["original_notice_url_missing_review"])

    def test_original_notice_url_canonicalization_keeps_unsupported_scheme_blocked(self) -> None:
        url, blockers = _canonical_original_notice_url("ftp://example.invalid/unsupported")

        self.assertEqual(url, "ftp://example.invalid/unsupported")
        self.assertEqual(blockers, ["original_notice_unsupported_url_scheme"])

    def test_live_original_notice_fetches_normalized_scheme_less_url(self) -> None:
        called_urls: list[str] = []

        def getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
            called_urls.append(url)
            return _fake_http_getter(url, context)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="www.example.gov.cn/original/overlap.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            fetch = result["manifest"]["original_notice_fetch_records"][0]
            self.assertEqual(called_urls, ["https://www.example.gov.cn/original/overlap.html"])
            self.assertEqual(fetch["original_notice_url_raw"], "www.example.gov.cn/original/overlap.html")
            self.assertEqual(fetch["original_notice_url_normalized"], "https://www.example.gov.cn/original/overlap.html")
            self.assertTrue(fetch["original_notice_url_was_normalized"])
            self.assertEqual(result["summary"]["source_unsupported_count"], 0)

    def test_scheme_less_https_transport_error_falls_back_to_http(self) -> None:
        called_urls: list[str] = []

        def getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
            called_urls.append(url)
            if url.startswith("https://www.tjconstruct.cn"):
                return {
                    "status_code": 0,
                    "content_type": "",
                    "body": "",
                    "url": url,
                    "error": "[SSL: WRONG_VERSION_NUMBER] wrong version number",
                }
            return _fake_http_getter(url, context)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="www.tjconstruct.cn/original/overlap.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            fetch = result["manifest"]["original_notice_fetch_records"][0]
            self.assertEqual(
                called_urls,
                [
                    "https://www.tjconstruct.cn/original/overlap.html",
                    "http://www.tjconstruct.cn/original/overlap.html",
                ],
            )
            self.assertTrue(fetch["original_notice_http_fallback_attempted"])
            self.assertEqual(fetch["fetch_state"], "ORIGINAL_NOTICE_FETCHED")
            self.assertEqual(fetch["route_attempt"]["requested_url"], "http://www.tjconstruct.cn/original/overlap.html")
            self.assertEqual(len(fetch["route_attempts"]), 2)

    def test_company_history_triage_root_reads_manual_backtrace_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            triage_root = root / "triage"
            _write_p13b_input(triage_root)

            result = build_p13b_original_notice_backtrace(
                input_root=root / "unused",
                company_history_triage_root=triage_root,
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["original_notice_task_count"], 3)
            self.assertEqual(result["manifest"]["source_input_root"], str(triage_root))
            self.assertEqual(result["manifest"]["source_company_history_triage_root"], str(triage_root))

    def test_project_ids_filter_original_notice_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                project_ids=["JG2026-20002"],
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["original_notice_task_count"], 1)
            task = result["manifest"]["original_notice_task_records"][0]
            self.assertEqual(task["project_id"], "PROJ-CN-GD-JG2026-20002")

    def test_cli_accepts_company_history_triage_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            triage_root = root / "triage"
            out_root = root / "out"
            _write_p13b_input(triage_root)

            exit_code = main(
                [
                    "--input-root",
                    str(root / "unused"),
                    "--company-history-triage-root",
                    str(triage_root),
                    "--output-root",
                    str(out_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads((out_root / "original-notice-backtrace-v1.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["original_notice_task_count"], 3)

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

    def test_fetched_notice_without_extractable_fields_is_review_not_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="https://example.gov.cn/original/no-fields.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["fetch_state_counts"]["ORIGINAL_NOTICE_FETCHED"], 1)
            self.assertEqual(summary["extraction_state_counts"]["ORIGINAL_NOTICE_NO_MATCH_REVIEW"], 1)
            self.assertEqual(summary["source_unsupported_count"], 0)
            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertIn("original_notice_person_period_not_extracted_review", extraction["blocker_taxonomy"])

    def test_fetched_notice_with_unextractable_body_keeps_blocker_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="https://example.gov.cn/original/empty-text.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["fetch_state_counts"]["ORIGINAL_NOTICE_FETCHED"], 1)
            self.assertEqual(summary["extraction_state_counts"]["ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"], 1)
            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertIn("original_notice_body_not_extractable_review", extraction["blocker_taxonomy"])

    def test_javascript_shell_is_taxonomized_as_browser_readback_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="https://example.gov.cn/original/js-shell.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["original_notice_extraction_state"], "ORIGINAL_NOTICE_NO_MATCH_REVIEW")
            self.assertIn("original_notice_person_period_not_extracted_review", extraction["blocker_taxonomy"])
            self.assertIn("original_notice_browser_readback_required", extraction["blocker_taxonomy"])

    def test_long_boilerplate_page_still_extracts_company_and_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root, first_url="https://example.gov.cn/original/long-boilerplate.html")

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["original_notice_extraction_state"], "ORIGINAL_NOTICE_NO_MATCH_REVIEW")
            self.assertIn("深圳中铁二局工程有限公司", extraction["extracted_company_names"])
            self.assertIn("730日历天", extraction["extracted_period_text"])
            self.assertEqual(extraction["extracted_responsible_person_names"], [])
            self.assertIn("original_notice_person_period_not_extracted_review", extraction["blocker_taxonomy"])

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
            self.assertEqual(summary["fetch_state_counts"]["ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"], 2)
            self.assertIn("original_notice_forbidden_or_rate_limited_review", summary["blocker_taxonomy_counts"])

    def test_ygp_original_link_requires_local_readback_not_direct_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_ygp_only_input(root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_raising_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["fetch_state_counts"]["ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"], 1)
            self.assertEqual(result["summary"]["source_unsupported_count"], 1)
            fetch = result["manifest"]["original_notice_fetch_records"][0]
            self.assertEqual(fetch["blocker_taxonomy"], ["ygp_original_readback_required"])

    def test_ygp_readback_root_consumes_local_readback_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_root = root / "ygp-readback"
            _write_ygp_only_input(root)
            _write_ygp_readback(readback_root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                ygp_readback_root=readback_root,
                output_root=root / "out",
                http_getter=_raising_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["ygp_readback_ready_count"], 1)
            self.assertEqual(result["summary"]["original_notice_person_period_extracted_count"], 1)
            extraction = result["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["extraction_source"], "YGP_ORIGINAL_READBACK")
            self.assertEqual(extraction["extracted_responsible_person_names"], ["李四"])
            self.assertIn("240日历天", extraction["extracted_period_text"])

    def test_ygp_readback_text_probe_is_reparsed_when_structured_fields_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_root = root / "ygp-readback"
            _write_ygp_only_input(root)
            _write_ygp_text_readback(readback_root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                ygp_readback_root=readback_root,
                output_root=root / "out",
                http_getter=_raising_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["original_notice_person_period_extracted_count"], 1)
            self.assertEqual(summary["original_notice_overlap_signal_review_required_count"], 1)
            self.assertEqual(summary["manual_release_evidence_probe_count"], 1)
            release_row = result["manifest"]["manual_release_evidence_probe_table"][0]
            self.assertEqual(release_row["original_notice_url"], "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52")
            self.assertIn("construction_permit", release_row["release_evidence_source_targets"])

    def test_ygp_readback_matches_route_attempt_original_url_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_root = root / "ygp-readback"
            _write_ygp_only_input(root)
            _write_ygp_text_readback(readback_root, route_attempt_only=True)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                ygp_readback_root=readback_root,
                output_root=root / "out",
                http_getter=_raising_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["ygp_readback_ready_count"], 1)
            self.assertEqual(result["summary"]["original_notice_overlap_signal_review_required_count"], 1)

    def test_partial_ygp_readback_keeps_missing_readback_pointer_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readback_root = root / "ygp-readback"
            missing_url = "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/missing-3C52"
            _write_p13b_input(root, first_url=missing_url)
            _write_ygp_readback(readback_root)

            result = build_p13b_original_notice_backtrace(
                input_root=root,
                ygp_readback_root=readback_root,
                output_root=root / "out",
                http_getter=_raising_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["original_notice_fetch_count"], 2)
            self.assertEqual(summary["ygp_readback_ready_count"], 1)
            self.assertEqual(summary["source_unsupported_count"], 1)
            missing_fetches = [
                record
                for record in result["manifest"]["original_notice_fetch_records"]
                if record["blocker_taxonomy"] == ["ygp_local_readback_missing"]
            ]
            self.assertEqual(len(missing_fetches), 1)

    def test_writes_all_output_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p13b_input(root)

            build_p13b_original_notice_backtrace(
                input_root=root,
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            for file_name in (
                "original-notice-backtrace-v1.json",
                "original-notice-task-triage-table.json",
                "original-notice-fetch-records.json",
                "original-notice-extraction-records.json",
                "original-notice-overlap-signal-records.json",
                "manual-release-evidence-probe-table.json",
            ):
                self.assertTrue((root / "out" / file_name).exists(), file_name)

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


def _write_p13b_input_from_rows(root: Path, rows: list[Mapping[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload_rows = []
    bid_show_records = []
    for index, row in enumerate(rows, start=1):
        record = {
            "project_id": row.get("project_id") or "PROJ-CN-GD-JG2026-30001",
            "candidate_company_name": row.get("candidate_company_name") or "广东甲公司",
            "responsible_person_names": row.get("responsible_person_names") or ["张三"],
            "bid_project_name": row.get("bid_project_name") or f"历史项目{index}",
            "original_notice_url": row.get("original_notice_url") or "",
            "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
            "suggested_next_step": "targeted_original_notice_01_to_12_backtrace",
        }
        payload_rows.append(record)
        bid_show_records.append(
            {
                "project_id": record["project_id"],
                "candidate_company_name": record["candidate_company_name"],
                "bid_show_record_id": f"BID-SHOW-{index}",
                "bid_show_url": f"https://data.ggzy.gov.cn/yjcx/index/bid_show?id={index}",
                "bid_project_name": record["bid_project_name"],
                "original_notice_url": record["original_notice_url"],
            }
        )
    _write_json(
        root / "company-history-overlap-triage-v1.json",
        {"manifest": {"manual_original_url_backtrace_table": payload_rows, "bid_show_records": bid_show_records}},
    )


def _write_ygp_only_input(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    url = "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52"
    payload = {
        "manifest": {
            "manual_original_url_backtrace_table": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": url,
                    "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    "suggested_next_step": "targeted_original_notice_01_to_12_backtrace",
                }
            ],
            "bid_show_records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "bid_show_record_id": "BID-SHOW-2",
                    "bid_show_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=2",
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": url,
                }
            ],
        }
    }
    _write_json(root / "company-history-overlap-triage-v1.json", payload)


def _write_ygp_readback(root: Path) -> None:
    url = "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52"
    payload = {
        "manifest": {
            "ygp_original_readback_records": [
                {
                    "original_notice_url": url,
                    "source_url": url,
                    "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                    "ygp_extraction_state": "YGP_ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED",
                    "status_code": 200,
                    "content_type": "application/json",
                    "extracted_responsible_person_names": ["李四"],
                    "extracted_period_text": "工期：240日历天",
                    "extracted_award_date": "2026年05月03日",
                    "extracted_company_names": ["广东乙公司"],
                    "text_probe": "中标人：广东乙公司。项目负责人：李四。工期：240日历天。",
                    "text_probe_sha256": "text-sha",
                    "record_payload_sha256": "record-sha",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ]
        }
    }
    _write_json(root / "ygp-original-readback-v1.json", payload)


def _write_ygp_text_readback(root: Path, *, route_attempt_only: bool = False) -> None:
    url = "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52"
    expanded_url = "https://ygp.gdzwfw.gov.cn/ggzy-portal/#/44/new/jygg/v3/D?noticeId=notice-123&projectCode=project-123&bizCode=3C52"
    payload = {
        "manifest": {
            "ygp_original_readback_records": [
                {
                    "original_notice_url": expanded_url if route_attempt_only else url,
                    "source_url": expanded_url,
                    "ygp_readback_state": "YGP_ORIGINAL_URL_READBACK_READY",
                    "ygp_extraction_state": "YGP_ORIGINAL_NOTICE_NO_MATCH_REVIEW",
                    "status_code": 200,
                    "content_type": "text/plain",
                    "text_probe": "中标人：广东乙公司。项目负责人：李四。工期：240日历天。中标日期：2026年05月03日。",
                    "route_attempt": {"url": url} if route_attempt_only else {},
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ]
        }
    }
    _write_json(root / "ygp-original-readback-v1.json", payload)


def _fake_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if url.endswith("/blocked.html"):
        return {"status_code": 403, "content_type": "text/html", "body": "forbidden"}
    if url.endswith("/no-fields.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": "<html><body><h1>公告正文</h1><p>本页面为平台公告。</p></body></html>",
        }
    if url.endswith("/empty-text.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": "<html><head><script></script><style></style></head></html>",
        }
    if url.endswith("/js-shell.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": "<html><body>交易平台 window._AMapSecurityConfig = {}; We're sorry but 交易平台 doesn't work properly without JavaScript enabled. Please enable it to continue.</body></html>",
        }
    if url.endswith("/no-person.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": "<html><body><p>中标人：广东甲公司</p><p>工期：180日历天</p><p>中标日期：2026年05月02日</p></body></html>",
        }
    if url.endswith("/long-boilerplate.html"):
        boilerplate = "<div>站点模板</div>" * 300
        body = (
            "<html><body>"
            + boilerplate
            + "<div>中标人名称：深圳中铁二局工程有限公司、长厦安基工程设计有限公司</div>"
            + "<div>工期：730日历天</div>"
            + "</body></html>"
        )
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": body,
        }
    if url.endswith("/table-person.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": (
                "<html><body><div>中标单位 中国化学工程第六建设有限公司</div>"
                "<div>工期（交货期） 150日历天</div>"
                "<div>项目负责人 姓名 执业或职业资格 职称 证书名称 证书编号 职称专业 职称级别 "
                "尹家驹 一级注册建造师 鄂1422021202201042 市政公用工程 中级</div></body></html>"
            ),
        }
    if url.endswith("/column-table-person.html"):
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": (
                "<html><body><div>中标人 中标价 工期（或服务期、交货期） 质量承诺 项目负责人</div>"
                "<div>中国化学工程第六建设有限公司 156,576,147.20元 270天 "
                "设计质量要求：符合现行国家有关工程设计质量评定标准的合格要求 胡琦</div></body></html>"
            ),
        }
    return {
        "status_code": 200,
        "content_type": "text/html",
        "body": "<html><body><p>中标人：广东甲公司</p><p>项目负责人：张三</p><p>工期（交货期）：365日历天</p><p>中标日期：2026年05月01日</p></body></html>",
    }


def _raising_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    raise AssertionError(f"unexpected http getter call: {url}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
