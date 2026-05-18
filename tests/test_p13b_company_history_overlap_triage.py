from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.p13b_company_history_overlap_triage import build_p13b_company_history_overlap_triage  # noqa: E402


class P13BCompanyHistoryOverlapTriageTests(unittest.TestCase):
    def test_plan_only_selects_external_conflict_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root)

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["project_task_count"], 2)
            self.assertEqual(summary["company_history_query_task_count"], 3)
            states = {record["query_state"] for record in result["manifest"]["company_history_query_records"]}
            self.assertEqual(states, {"PLAN_ONLY_NOT_EXECUTED"})
            self.assertTrue((root / "out" / "company-history-overlap-triage-v1.json").exists())

    def test_live_fake_query_extracts_person_period_and_overlap_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root)

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=1,
                max_bid_records_per_company=10,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["company_history_record_found_count"], 1)
            self.assertEqual(summary["bid_show_person_and_period_extracted_count"], 1)
            self.assertEqual(summary["overlap_signal_review_required_count"], 1)
            self.assertEqual(summary["company_query_state_counts"]["COMPANY_HISTORY_RECORD_FOUND"], 1)
            self.assertEqual(summary["overlap_signal_state_counts"]["OVERLAP_SIGNAL_REVIEW_REQUIRED"], 1)
            bid_show = result["manifest"]["bid_show_records"][0]
            self.assertEqual(bid_show["extracted_responsible_person_names"], ["张三"])
            self.assertIn("365日历天", bid_show["extracted_period_text"])
            self.assertEqual(bid_show["time_window_review_state"], "TIME_WINDOW_OVERLAP_REVIEW")
            self.assertEqual(bid_show["estimated_performance_end_date"], "2027-05-01")
            self.assertEqual(bid_show["original_notice_url"], "https://example.gov.cn/original/overlap.html")
            self.assertFalse(bid_show["original_notice_backtrace_required"])
            overlap = result["manifest"]["overlap_signal_records"][0]
            self.assertEqual(overlap["overlap_source_stage"], "DATA_GGZY_BID_SHOW_DIRECT")
            self.assertFalse(overlap["original_notice_backtrace_required"])
            self.assertEqual(result["manifest"]["manual_original_url_backtrace_table"], [])

    def test_bid_show_contract_or_delivery_period_directly_triggers_overlap_without_original_backtrace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root, first_company="合同周期公司", first_person="周七")

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["bid_show_person_and_period_extracted_count"], 1)
            self.assertEqual(summary["overlap_signal_review_required_count"], 1)
            self.assertEqual(summary["original_notice_backtrace_required_count"], 0)
            bid_show = result["manifest"]["bid_show_records"][0]
            self.assertEqual(bid_show["bid_show_state"], "BID_SHOW_PERSON_AND_PERIOD_EXTRACTED")
            self.assertIn("2026年12月31日", bid_show["extracted_period_text"])
            self.assertEqual(bid_show["time_window_review_state"], "TIME_WINDOW_OVERLAP_REVIEW")
            self.assertEqual(bid_show["estimated_performance_end_date"], "2026-12-31")
            self.assertFalse(bid_show["original_notice_backtrace_required"])
            overlap = result["manifest"]["overlap_signal_records"][0]
            self.assertEqual(overlap["review_reasons"], ["same_responsible_person", "candidate_company_matched", "contract_or_delivery_time_present_in_bid_show"])
            self.assertEqual(result["manifest"]["manual_original_url_backtrace_table"], [])

    def test_bid_show_completed_period_does_not_trigger_release_or_original_backtrace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root, first_company="完工公司", first_person="吴八")

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["bid_show_person_and_period_extracted_count"], 1)
            self.assertEqual(summary["overlap_signal_review_required_count"], 0)
            self.assertEqual(summary["original_notice_backtrace_required_count"], 0)
            bid_show = result["manifest"]["bid_show_records"][0]
            self.assertEqual(bid_show["time_window_review_state"], "TIME_WINDOW_NO_OVERLAP_REVIEW")
            overlap = result["manifest"]["overlap_signal_records"][0]
            self.assertEqual(overlap["overlap_signal_state"], "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW")
            self.assertEqual(result["manifest"]["manual_original_url_backtrace_table"], [])

    def test_bid_show_original_url_without_person_triggers_backtrace_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root, first_company="广东乙公司", first_person="李四")

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["bid_show_state_counts"]["ORIGINAL_NOTICE_BACKTRACE_REQUIRED"], 1)
            self.assertEqual(summary["original_notice_backtrace_required_count"], 1)
            manual = result["manifest"]["manual_original_url_backtrace_table"]
            self.assertEqual(len(manual), 1)
            self.assertEqual(manual[0]["suggested_next_step"], "targeted_original_notice_01_to_12_backtrace")

    def test_source_blockers_and_empty_results_are_taxonomized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root, first_company="阻断公司", first_person="王五")

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=3,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["company_query_state_counts"]["SOURCE_BLOCKED_RETRY_REQUIRED"], 1)
            self.assertEqual(summary["company_query_state_counts"]["NO_PUBLIC_OVERLAP_SIGNAL_REVIEW"], 2)
            self.assertIn("data_ggzy_forbidden_or_rate_limited_review", summary["blocker_taxonomy_counts"])

    def test_company_search_suffix_fallback_matches_shareholding_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(
                root,
                first_company="广东省水利电力勘测设计研究院有限公司",
                first_person="陈工",
            )

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["company_query_state_counts"]["COMPANY_HISTORY_RECORD_FOUND"], 1)
            record = result["manifest"]["company_history_query_records"][0]
            self.assertEqual(record["matched_search_keyword"], "广东省水利电力勘测设计研究院")
            self.assertEqual(record["matched_company_name"], "广东省水利电力勘测设计研究院股份有限公司")
            self.assertIn("广东省水利电力勘测设计研究院", record["candidate_company_variants"])

    def test_ygp_plan_only_reads_overlap_inputs_and_dedupes_companies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_ygp_tables(root)

            result = build_p13b_company_history_overlap_triage(
                ygp_expansion_root=root / "ygp-expansion",
                ygp_coverage_closeout_root=root / "coverage",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["input_mode"], "YGP_ORIGINAL_READBACK_EXPANSION")
            self.assertEqual(summary["ygp_input_count"], 4)
            self.assertEqual(summary["unique_company_count"], 3)
            self.assertEqual(summary["queried_company_count"], 0)
            tasks = result["manifest"]["company_history_query_records"]
            self.assertEqual(len([task for task in tasks if task["candidate_company_name"] == "广东甲公司"]), 1)

    def test_ygp_live_fake_query_extracts_overlap_and_backtrace_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_ygp_tables(root)

            result = build_p13b_company_history_overlap_triage(
                ygp_expansion_root=root / "ygp-expansion",
                ygp_coverage_closeout_root=root / "coverage",
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=3,
                max_bid_records_per_company=5,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["ygp_input_count"], 4)
            self.assertEqual(summary["unique_company_count"], 3)
            self.assertEqual(summary["queried_company_count"], 3)
            self.assertEqual(summary["company_search_hit_count"], 2)
            self.assertEqual(summary["bid_list_hit_count"], 2)
            self.assertEqual(summary["bid_show_record_count"], 2)
            self.assertEqual(summary["overlap_signal_count"], 1)
            self.assertEqual(summary["original_notice_backtrace_required_count"], 1)

    def test_report_never_contains_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_tables(root)

            result = build_p13b_company_history_overlap_triage(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_companies=1,
                http_getter=_fake_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_p12_tables(root: Path, *, first_company: str = "广东甲公司", first_person: str = "张三") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "project-value-table.json",
        {
            "summary": {"project_count": 3},
            "records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20001",
                    "project_name": "广州道路工程施工中标候选人公示",
                    "value_closeout_state": "EXTERNAL_CONFLICT_SOURCE_REQUIRED",
                    "candidate_notice_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-a.html"],
                    "project_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-a.html"],
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "project_name": "广州桥梁工程施工中标候选人公示",
                    "value_closeout_state": "EXTERNAL_CONFLICT_SOURCE_REQUIRED",
                    "candidate_notice_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-b.html"],
                    "project_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-b.html"],
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20003",
                    "project_name": "设备采购项目中标候选人公示",
                    "value_closeout_state": "LOW_VALUE_OR_NOT_APPLICABLE",
                },
            ],
        },
    )
    _write_json(
        root / "candidate-group-verification-table.json",
        {
            "summary": {"candidate_group_count": 4},
            "records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20001",
                    "project_name": "广州道路工程施工中标候选人公示",
                    "candidate_group_id": "CANDIDATE-GROUP-1",
                    "candidate_group_members": [first_company],
                    "responsible_person_name": first_person,
                    "certificate_no": "粤244000000000",
                    "source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-a.html"],
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "project_name": "广州桥梁工程施工中标候选人公示",
                    "candidate_group_id": "CANDIDATE-GROUP-2",
                    "candidate_group_members": ["广东丙公司", "广东丁公司"],
                    "responsible_person_name": "赵六",
                    "source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-b.html"],
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20003",
                    "project_name": "设备采购项目中标候选人公示",
                    "candidate_group_id": "CANDIDATE-GROUP-3",
                    "candidate_group_members": ["低价值公司"],
                    "responsible_person_name": "",
                },
            ],
        },
    )


def _write_ygp_tables(root: Path) -> None:
    expansion = root / "ygp-expansion"
    coverage = root / "coverage"
    expansion.mkdir(parents=True, exist_ok=True)
    coverage.mkdir(parents=True, exist_ok=True)
    records = [
        _ygp_overlap_input("P1", "440200", "广东甲公司", ["张三"]),
        _ygp_overlap_input("P1", "440200", "广东乙公司", ["李四"]),
        _ygp_overlap_input("P2", "440800", "广东甲公司", ["张三"]),
        _ygp_overlap_input("P3", "441800", "广东丙公司", ["王五"]),
    ]
    _write_json(expansion / "p13b-ygp-overlap-triage-input-table.json", {"summary": {"overlap_triage_input_count": 4}, "records": records})
    _write_json(
        expansion / "p13b-ygp-original-readback-expansion-v1.json",
        {
            "manifest": {"overlap_triage_input_records": records},
            "summary": {"overlap_triage_input_count": 4},
        },
    )
    _write_json(
        coverage / "guangdong-ygp-city-coverage-closeout-v1.json",
        {
            "manifest": {
                "city_coverage_records": [
                    _coverage_record("P1", "440200", "YGP_CITY_COVERAGE_READY_FOR_P13B"),
                    _coverage_record("P2", "440800", "YGP_CITY_COVERAGE_READY_WITH_BACKLOG", oversize=1),
                    _coverage_record("P3", "441800", "YGP_CITY_COVERAGE_NO_PUBLIC_ATTACHMENT_REVIEW"),
                ]
            },
            "summary": {"p13b_overlap_input_count": 4},
        },
    )


def _ygp_overlap_input(project_suffix: str, city_code: str, company: str, people: list[str]) -> dict[str, Any]:
    project_id = f"PROJ-CN-GD-YGP-{project_suffix}"
    return {
        "city_code": city_code,
        "project_id": project_id,
        "project_name": f"{project_suffix}测试项目",
        "candidate_company_name": company,
        "responsible_person_candidates": people,
        "certificate_no_candidates": [],
        "service_period_text": "365日历天",
        "award_date": "2026-05-01",
        "publish_date": "2026-05-01",
        "source_url": f"https://ygp.gdzwfw.gov.cn/detail/{project_suffix}",
        "source_07_url": f"https://ygp.gdzwfw.gov.cn/detail/{project_suffix}",
        "backlog_tracked": city_code == "440800",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _coverage_record(project_suffix: str, city_code: str, state: str, *, oversize: int = 0) -> dict[str, Any]:
    return {
        "city_code": city_code,
        "project_id": f"PROJ-CN-GD-YGP-{project_suffix}",
        "project_name": f"{project_suffix}测试项目",
        "city_coverage_state": state,
        "recommended_next_action": "KEEP_BACKLOG_AND_ENTER_P13B" if oversize else "ENTER_P13B_COMPANY_HISTORY_OVERLAP_TRIAGE",
        "oversize_queue_count": oversize,
        "limit_deferred_queue_count": 0,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _fake_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.path.endswith("/search"):
        keyword = query.get("keyword", [""])[0]
        if keyword == "阻断公司":
            return {"status_code": 403, "content_type": "application/json", "body": "{\"message\":\"forbidden\"}"}
        if keyword == "广东省水利电力勘测设计研究院有限公司":
            return _json_response({"success": True, "code": 200, "result": {"records": [], "total": 0}})
        if keyword == "广东省水利电力勘测设计研究院":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {"records": [{"uniscid": "91440000123456789X", "entname": "广东省水利电力勘测设计研究院股份有限公司", "bidCount": 1}], "total": 1},
                }
            )
        if keyword == "广东甲公司":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {"records": [{"uniscid": "914400000000000001", "entname": "广东甲公司", "bidCount": 1}], "total": 1},
                }
            )
        if keyword == "合同周期公司":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {"records": [{"uniscid": "914400000000000003", "entname": "合同周期公司", "bidCount": 1}], "total": 1},
                }
            )
        if keyword == "完工公司":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {"records": [{"uniscid": "914400000000000004", "entname": "完工公司", "bidCount": 1}], "total": 1},
                }
            )
        if keyword == "广东乙公司":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {"records": [{"uniscid": "914400000000000002", "entname": "广东乙公司", "bidCount": 1}], "total": 1},
                }
            )
        return _json_response({"success": True, "code": 200, "result": {"records": [], "total": 0}})
    if parsed.path.endswith("/bid_list"):
        uniscid = query.get("uniscid", [""])[0]
        record_id = "overlap-record" if uniscid.endswith("1") else "needs-original-record"
        if uniscid == "914400000000000003":
            record_id = "contract-period-record"
        if uniscid == "914400000000000004":
            record_id = "completed-period-record"
        if uniscid == "91440000123456789X":
            record_id = "needs-original-record"
        return _json_response(
            {
                "success": True,
                "code": 200,
                "result": {
                    "data": {
                        "records": [
                            {
                                "id": record_id,
                                "projectName": "历史道路工程",
                                "areaCode": "广州市",
                                "createTime": "2026-05-01",
                                "bidPrice": "1000.00",
                            }
                        ],
                        "total": 1,
                    }
                },
            }
        )
    if parsed.path.endswith("/bid_show"):
        record_id = query.get("id", [""])[0]
        if record_id == "overlap-record":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {
                        "title": "历史道路工程中标结果公告",
                        "content": "<p>中标人：广东甲公司</p><p>项目负责人：张三</p><p>工期（交货期）：365日历天</p><p>中标日期：2026年05月01日</p>",
                        "url": "https://example.gov.cn/original/overlap.html",
                    },
                }
            )
        if record_id == "contract-period-record":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {
                        "title": "历史合同周期项目中标结果公告",
                        "content": "<p>中标人：合同周期公司</p><p>项目经理：周七</p><p>合同履行期限：合同签订之日起至2026年12月31日完成交付</p>",
                        "url": "https://example.gov.cn/original/contract-period.html",
                    },
                }
            )
        if record_id == "completed-period-record":
            return _json_response(
                {
                    "success": True,
                    "code": 200,
                    "result": {
                        "title": "历史已完工项目中标结果公告",
                        "content": "<p>中标人：完工公司</p><p>项目经理：吴八</p><p>工期：30日历天</p><p>中标日期：2024年01月01日</p>",
                        "url": "https://example.gov.cn/original/completed-period.html",
                    },
                }
            )
        return _json_response(
            {
                "success": True,
                "code": 200,
                "result": {
                    "title": "历史桥梁工程中标结果公告",
                    "content": "<p>中标人：广东乙公司</p><p>工期（交货期）：180日历天</p>",
                    "url": "https://example.gov.cn/original/missing-person.html",
                },
            }
        )
    return {"status_code": 404, "content_type": "application/json", "body": "{}"}


def _json_response(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"status_code": 200, "content_type": "application/json", "body": json.dumps(payload, ensure_ascii=False)}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
