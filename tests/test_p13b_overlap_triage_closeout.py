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

from storage.p13b_overlap_triage_closeout import build_p13b_overlap_triage_closeout  # noqa: E402


class P13BOverlapTriageCloseoutTests(unittest.TestCase):
    def test_closeout_combines_company_original_and_ygp_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, overlap=False)

            result = build_p13b_overlap_triage_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                ygp_readback_root=root / "ygp",
                ygp_coverage_closeout_root=root / "coverage",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(summary["project_count"], 2)
            self.assertEqual(summary["company_history_record_found_count"], 2)
            self.assertEqual(summary["ygp_readback_ready_count"], 0)
            self.assertEqual(summary["release_evidence_trigger_count"], 0)
            self.assertEqual(summary["project_state_counts"]["YGP_READBACK_BLOCKED_OR_UNSUPPORTED"], 1)
            self.assertTrue((root / "out" / "project-overlap-triage-table.json").exists())
            self.assertTrue((root / "out" / "release-evidence-trigger-table.json").exists())

    def test_overlap_signal_generates_release_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, overlap=True)

            result = build_p13b_overlap_triage_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                ygp_readback_root=root / "ygp",
                ygp_coverage_closeout_root=root / "coverage",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["release_evidence_trigger_count"], 1)
            self.assertEqual(summary["project_state_counts"]["OVERLAP_SIGNAL_REVIEW_REQUIRED"], 1)
            triggers = result["manifest"]["release_evidence_trigger_records"]
            self.assertEqual(triggers[0]["suggested_next_step"], "targeted_release_evidence_probe")

    def test_limit_deferred_is_not_source_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, overlap=False, include_deferred=True)

            result = build_p13b_overlap_triage_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                ygp_readback_root=root / "ygp",
                ygp_coverage_closeout_root=root / "coverage",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["source_limit_deferred_count"], 1)
            states = {row["project_overlap_triage_state"] for row in result["manifest"]["project_overlap_triage_records"]}
            self.assertIn("SOURCE_LIMIT_DEFERRED", states)

    def test_ygp_defaults_closed_when_not_explicitly_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, overlap=False)

            result = build_p13b_overlap_triage_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["ygp_readback_ready_count"], 0)
            self.assertEqual(result["summary"]["ygp_readback_blocked_or_unsupported_count"], 0)
            self.assertEqual(result["manifest"]["source_ygp_readback_root"], "")
            self.assertEqual(result["manifest"]["source_ygp_coverage_closeout_root"], "")

    def test_report_never_contains_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_inputs(root, overlap=False)

            result = build_p13b_overlap_triage_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                ygp_readback_root=root / "ygp",
                ygp_coverage_closeout_root=root / "coverage",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_inputs(root: Path, *, overlap: bool, include_deferred: bool = False) -> None:
    _write_company_history(root / "company", overlap=overlap, include_deferred=include_deferred)
    _write_original_notice(root / "original", overlap=overlap)
    _write_ygp_readback(root / "ygp")
    _write_coverage(root / "coverage")


def _write_company_history(root: Path, *, overlap: bool, include_deferred: bool) -> None:
    company_rows = [
        {
            "company_history_query_task_id": "QUERY-1",
            "project_id": "PROJ-1",
            "project_name": "项目一",
            "candidate_company_name": "广东甲公司",
            "responsible_person_names": ["张三"],
            "query_state": "COMPANY_HISTORY_RECORD_FOUND",
            "uniscid": "914400000000000001",
            "search_url": "https://data.ggzy.gov.cn/yjcx/index/search?keyword=广东甲公司",
            "search_total": 1,
            "bid_list_total": 1,
            "selected_bid_record_count": 1,
            "blocker_taxonomy": [],
        },
        {
            "company_history_query_task_id": "QUERY-2",
            "project_id": "PROJ-2",
            "project_name": "项目二",
            "candidate_company_name": "广东乙公司",
            "responsible_person_names": ["李四"],
            "query_state": "COMPANY_HISTORY_RECORD_FOUND",
            "uniscid": "914400000000000002",
            "search_url": "https://data.ggzy.gov.cn/yjcx/index/search?keyword=广东乙公司",
            "search_total": 1,
            "bid_list_total": 1,
            "selected_bid_record_count": 1,
            "blocker_taxonomy": [],
        },
    ]
    if include_deferred:
        company_rows.append(
            {
                "company_history_query_task_id": "QUERY-3",
                "project_id": "PROJ-3",
                "project_name": "项目三",
                "candidate_company_name": "广东丙公司",
                "responsible_person_names": ["王五"],
                "query_state": "SOURCE_BLOCKED_RETRY_REQUIRED",
                "blocker_taxonomy": ["max_live_companies_deferred"],
            }
        )
    project_task_records = [
        {"project_id": "PROJ-1", "project_name": "项目一", "city_code": "440100", "candidate_companies": ["广东甲公司"], "responsible_person_names": ["张三"]},
        {"project_id": "PROJ-2", "project_name": "项目二", "city_code": "440200", "candidate_companies": ["广东乙公司"], "responsible_person_names": ["李四"]},
    ]
    if include_deferred:
        project_task_records.append(
            {"project_id": "PROJ-3", "project_name": "项目三", "city_code": "440300", "candidate_companies": ["广东丙公司"], "responsible_person_names": ["王五"]}
        )
    overlap_state = "OVERLAP_SIGNAL_REVIEW_REQUIRED" if overlap else "ORIGINAL_NOTICE_BACKTRACE_REQUIRED"
    release = bool(overlap)
    payload = {
        "manifest": {
            "project_task_records": project_task_records,
            "company_history_query_records": company_rows,
            "bid_show_records": [
                {
                    "bid_show_record_id": "BID-1",
                    "project_id": "PROJ-1",
                    "project_name": "项目一",
                    "candidate_company_name": "广东甲公司",
                    "matched_company_names": ["广东甲公司"],
                    "responsible_person_names": ["张三"],
                    "bid_show_state": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                    "original_notice_url": "https://example.gov.cn/original/1.html",
                }
            ],
            "overlap_signal_records": [
                {
                    "project_id": "PROJ-1",
                    "project_name": "项目一",
                    "candidate_company_name": "广东甲公司",
                    "responsible_person_names": ["张三"],
                    "matched_person_names": ["张三"] if overlap else [],
                    "source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
                    "original_notice_url": "https://example.gov.cn/original/1.html",
                    "extracted_period_text": "365日历天" if overlap else "",
                    "extracted_award_date": "2025年10月1日",
                    "overlap_signal_state": overlap_state,
                    "release_evidence_probe_triggered": release,
                }
            ],
            "summary": {"overlap_signal_count": 1 if overlap else 0},
        }
    }
    _write_json(root / "company-history-overlap-triage-v1.json", payload)


def _write_original_notice(root: Path, *, overlap: bool) -> None:
    extraction_state = "ORIGINAL_NOTICE_PERSON_PERIOD_EXTRACTED" if overlap else "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    overlap_state = "ORIGINAL_NOTICE_OVERLAP_SIGNAL_REVIEW_REQUIRED" if overlap else "ORIGINAL_NOTICE_NO_MATCH_REVIEW"
    payload = {
        "manifest": {
            "original_notice_fetch_records": [
                {
                    "original_notice_task_id": "NOTICE-1",
                    "project_id": "PROJ-1",
                    "project_name": "项目一",
                    "candidate_company_name": "广东甲公司",
                    "responsible_person_names": ["张三"],
                    "original_notice_url": "https://example.gov.cn/original/1.html",
                    "source_url": "https://example.gov.cn/original/1.html",
                    "fetch_state": "ORIGINAL_NOTICE_FETCHED",
                    "blocker_taxonomy": [],
                },
                {
                    "original_notice_task_id": "NOTICE-2",
                    "project_id": "PROJ-2",
                    "project_name": "项目二",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "source_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "fetch_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
                    "blocker_taxonomy": ["ygp_original_readback_required"],
                },
            ],
            "original_notice_extraction_records": [
                {
                    "original_notice_task_id": "NOTICE-1",
                    "project_id": "PROJ-1",
                    "project_name": "项目一",
                    "candidate_company_name": "广东甲公司",
                    "responsible_person_names": ["张三"],
                    "original_notice_url": "https://example.gov.cn/original/1.html",
                    "source_url": "https://example.gov.cn/original/1.html",
                    "original_notice_extraction_state": extraction_state,
                    "extracted_responsible_person_names": ["张三"] if overlap else [],
                    "extracted_period_text": "365日历天" if overlap else "",
                },
                {
                    "original_notice_task_id": "NOTICE-2",
                    "project_id": "PROJ-2",
                    "project_name": "项目二",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "source_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "original_notice_extraction_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
                    "blocker_taxonomy": ["ygp_original_readback_required"],
                },
            ],
            "original_notice_overlap_signal_records": [
                {
                    "original_notice_task_id": "NOTICE-1",
                    "project_id": "PROJ-1",
                    "project_name": "项目一",
                    "candidate_company_name": "广东甲公司",
                    "responsible_person_names": ["张三"],
                    "matched_person_names": ["张三"] if overlap else [],
                    "source_url": "https://example.gov.cn/original/1.html",
                    "extracted_period_text": "365日历天" if overlap else "",
                    "extracted_award_date": "2025年10月1日",
                    "original_notice_overlap_signal_state": overlap_state,
                    "release_evidence_probe_triggered": overlap,
                }
            ],
            "summary": {"original_notice_overlap_signal_review_required_count": 1 if overlap else 0},
        }
    }
    _write_json(root / "original-notice-backtrace-v1.json", payload)


def _write_ygp_readback(root: Path) -> None:
    payload = {
        "manifest": {
            "ygp_original_readback_records": [
                {
                    "original_notice_task_id": "NOTICE-2",
                    "project_id": "PROJ-2",
                    "project_name": "项目二",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "source_url": "https://ygp.gdzwfw.gov.cn/detail/123",
                    "ygp_readback_state": "YGP_ORIGINAL_URL_UNSUPPORTED",
                    "blocker_taxonomy": ["ygp_original_detail_payload_not_discovered"],
                }
            ],
            "summary": {"ygp_readback_ready_count": 0},
        }
    }
    _write_json(root / "ygp-original-readback-v1.json", payload)


def _write_coverage(root: Path) -> None:
    payload = {
        "manifest": {
            "city_coverage_records": [
                {"project_id": "PROJ-1", "city_code": "440100", "city_coverage_state": "YGP_CITY_READY"},
                {"project_id": "PROJ-2", "city_code": "440200", "city_coverage_state": "YGP_CITY_READY"},
            ]
        }
    }
    _write_json(root / "guangdong-ygp-city-coverage-closeout-v1.json", payload)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
