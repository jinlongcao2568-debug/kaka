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
from storage.p13b_ygp_original_readback import build_p13b_ygp_original_readback  # noqa: E402


class P13BYgpOriginalReadbackTests(unittest.TestCase):
    def test_plan_only_generates_ygp_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_ygp_original_readback(
                input_root=root,
                output_root=root / "ygp",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(result["summary"]["ygp_original_readback_task_count"], 1)
            self.assertEqual(result["summary"]["ygp_original_readback_count"], 0)

    def test_spa_shell_discovers_detail_api_and_extracts_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_ygp_original_readback(
                input_root=root,
                output_root=root / "ygp",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_ygp_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["ygp_readback_ready_count"], 1)
            self.assertEqual(summary["ygp_person_period_extracted_count"], 1)
            record = result["manifest"]["ygp_original_readback_records"][0]
            self.assertEqual(record["ygp_api_discovery_state"], "YGP_DETAIL_API_DISCOVERED")
            self.assertEqual(record["extracted_responsible_person_names"], ["李四"])
            self.assertIn("365日历天", record["extracted_period_text"])
            self.assertEqual(record["extracted_award_date"], "2025年10月15日")

    def test_browser_network_fallback_can_supply_public_detail_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_ygp_original_readback(
                input_root=root,
                output_root=root / "ygp",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_ygp_http_getter_without_api,
                browser_readback_getter=_fake_browser_readback_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            record = result["manifest"]["ygp_original_readback_records"][0]
            self.assertEqual(record["ygp_readback_state"], "YGP_BROWSER_NETWORK_READBACK_READY")
            self.assertEqual(record["extracted_responsible_person_names"], ["李四"])

    def test_p13b_original_notice_backtrace_consumes_ygp_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            p13b_root = root / "p13b"
            original_root = root / "original"
            ygp_root = root / "ygp"
            _write_company_history_input(p13b_root)
            original = build_p13b_original_notice_backtrace(
                input_root=p13b_root,
                output_root=original_root,
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_spa_shell_original_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )
            self.assertEqual(original["summary"]["extraction_state_counts"]["ORIGINAL_NOTICE_SOURCE_UNSUPPORTED"], 1)
            build_p13b_ygp_original_readback(
                input_root=original_root,
                output_root=ygp_root,
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_ygp_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            repaired = build_p13b_original_notice_backtrace(
                input_root=p13b_root,
                ygp_readback_root=ygp_root,
                output_root=root / "repaired",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(repaired["summary"]["original_notice_person_period_extracted_count"], 1)
            self.assertEqual(repaired["summary"]["original_notice_overlap_signal_review_required_count"], 1)
            extraction = repaired["manifest"]["original_notice_extraction_records"][0]
            self.assertEqual(extraction["extraction_source"], "YGP_ORIGINAL_READBACK")
            self.assertEqual(extraction["extracted_responsible_person_names"], ["李四"])

    def test_p13b_original_notice_backtrace_treats_readback_without_person_as_review_not_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            p13b_root = root / "p13b"
            ygp_root = root / "ygp"
            _write_company_history_input(p13b_root)
            _write_json(
                ygp_root / "ygp-original-readback-v1.json",
                {
                    "manifest": {
                        "ygp_original_readback_records": [
                            {
                                "original_notice_task_id": "P13B-ORIGINAL-NOTICE-816af4e8012d",
                                "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                                "source_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/#/44/new/jygg/v3/D?noticeId=abc",
                                "ygp_readback_state": "YGP_BROWSER_NETWORK_READBACK_READY",
                                "text_probe": "采购项目名称 历史桥梁工程 中标（成交）结果公告 相关附件",
                                "record_payload_sha256": "recordhash",
                            }
                        ]
                    }
                },
            )

            repaired = build_p13b_original_notice_backtrace(
                input_root=p13b_root,
                ygp_readback_root=ygp_root,
                output_root=root / "repaired",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(repaired["summary"]["extraction_state_counts"]["ORIGINAL_NOTICE_NO_MATCH_REVIEW"], 1)
            self.assertEqual(repaired["summary"]["original_notice_overlap_signal_review_required_count"], 0)

    def test_report_never_contains_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_original_backtrace_input(root)

            result = build_p13b_ygp_original_readback(
                input_root=root,
                output_root=root / "ygp",
                enable_live_public_query=True,
                max_live_original_notices=1,
                http_getter=_fake_ygp_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_original_backtrace_input(root: Path) -> None:
    payload = {
        "manifest": {
            "original_notice_task_records": [
                {
                    "original_notice_task_id": "P13B-ORIGINAL-NOTICE-1",
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "ygp_original_url_pointer_only": True,
                }
            ],
            "original_notice_extraction_records": [
                {
                    "original_notice_task_id": "P13B-ORIGINAL-NOTICE-1",
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "original_notice_extraction_state": "ORIGINAL_NOTICE_SOURCE_UNSUPPORTED",
                }
            ],
        }
    }
    _write_json(root / "original-notice-backtrace-v1.json", payload)


def _write_company_history_input(root: Path) -> None:
    payload = {
        "manifest": {
            "manual_original_url_backtrace_table": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                    "backtrace_reason": "ORIGINAL_NOTICE_BACKTRACE_REQUIRED",
                }
            ],
            "bid_show_records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "bid_show_record_id": "BID-SHOW-2",
                    "bid_show_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=2",
                    "bid_project_name": "历史桥梁工程",
                    "original_notice_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52",
                }
            ],
        }
    }
    _write_json(root / "company-history-overlap-triage-v1.json", payload)


def _fake_ygp_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "url-mapping" in url:
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": '<html><head><script type="module" src="/ggzy-portal/assets/index.js"></script></head><body><div id="app"></div>广东省公共资源交易平台</body></html>',
            "url": url,
        }
    if url.endswith("/ggzy-portal/assets/index.js"):
        return {
            "status_code": 200,
            "content_type": "application/javascript",
            "body": 'const detail="./detail-v1.js";',
            "url": url,
        }
    if url.endswith("/ggzy-portal/assets/detail-v1.js"):
        return {
            "status_code": 200,
            "content_type": "application/javascript",
            "body": 'const api="/ggzy-portal/center/apis/notice/detail?id={notice_id}&type={notice_type}";',
            "url": url,
        }
    if "/ggzy-portal/center/apis/notice/detail" in url:
        return {
            "status_code": 200,
            "content_type": "application/json",
            "body": json.dumps(
                {
                    "content": "公告标题：历史桥梁工程中标公告。项目名称：历史桥梁工程。中标人：广东乙公司。项目负责人：李四。服务期：365日历天。中标日期：2025年10月15日"
                },
                ensure_ascii=False,
            ),
            "url": url,
        }
    return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}


def _fake_ygp_http_getter_without_api(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "url-mapping" in url:
        return {
            "status_code": 200,
            "content_type": "text/html",
            "body": '<html><head><script type="module" src="/ggzy-portal/assets/index.js"></script></head><body><div id="app"></div>广东省公共资源交易平台</body></html>',
            "url": url,
        }
    if url.endswith("/ggzy-portal/assets/index.js"):
        return {"status_code": 200, "content_type": "application/javascript", "body": "const noop=true;", "url": url}
    return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}


def _fake_browser_readback_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "application/json",
        "body": json.dumps(
            {
                "content": "中标人：广东乙公司。项目负责人：李四。工期：180日历天。公告日期：2025年10月16日"
            },
            ensure_ascii=False,
        ),
        "url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/browser/detail",
    }


def _fake_spa_shell_original_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "content_type": "text/html",
        "body": '<html><head><script type="module" src="/ggzy-portal/assets/index.js"></script></head><body><div id="app"></div>广东省公共资源交易平台</body></html>',
        "url": url,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
