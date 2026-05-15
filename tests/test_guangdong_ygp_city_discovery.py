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

from storage.guangdong_ygp_city_discovery import build_guangdong_ygp_city_discovery  # noqa: E402


class GuangdongYgpCityDiscoveryTests(unittest.TestCase):
    def test_plan_only_generates_city_tasks_without_live_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_guangdong_ygp_city_discovery(
                output_root=Path(tmp_dir) / "out",
                city_codes=["440400", "440500"],
                per_city_candidate_limit=2,
                max_pages_per_city=1,
                build_flow_matrix=True,
                enable_live_public_query=False,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(result["summary"]["city_task_count"], 2)
            self.assertEqual(result["summary"]["candidate_project_count"], 0)
            self.assertEqual(result["summary"]["flow_matrix_state"], "NOT_RUN")

    def test_live_city_search_filters_recent_candidate_notices_and_builds_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_guangdong_ygp_city_discovery(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=2,
                max_pages_per_city=1,
                build_flow_matrix=True,
                enable_live_public_query=True,
                http_getter=_fake_ygp_city_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            candidates = result["manifest"]["ygp_candidate_project_records"]
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate["city_code"], "440400")
            self.assertEqual(candidate["notice_id"], "notice07")
            self.assertEqual(candidate["notice_second_type"], "A")
            self.assertEqual(candidate["trading_process"], "3C51")
            self.assertIn("/v3/A?", candidate["ygp_project_url"])
            self.assertIn("bizCode=3C51", candidate["ygp_project_url"])
            self.assertIn("siteCode=440400", candidate["ygp_project_url"])

            flow_summary = result["manifest"]["flow_matrix_summary"]
            self.assertEqual(flow_summary["ygp_project_readback_count"], 1)
            self.assertEqual(flow_summary["ygp_flow_item_count"], 12)
            self.assertEqual(flow_summary["present_flow_nos"], ["03", "04", "05", "06", "07", "12"])

            flow_matrix_path = root / "out" / "flow-matrix" / "guangdong-ygp-flow-matrix-v1.json"
            flow_matrix = json.loads(flow_matrix_path.read_text(encoding="utf-8"))
            item_records = flow_matrix["manifest"]["ygp_flow_item_records"]
            by_label = {record["notice_label"]: record["flow_no"] for record in item_records}
            self.assertEqual(by_label["招标公告、资格预审公告"], "03")
            self.assertEqual(by_label["招标文件、招标文件澄清与修改"], "04")
            self.assertEqual(by_label["开标记录"], "05")
            self.assertEqual(by_label["资格审查结果"], "06")
            self.assertEqual(by_label["评标报告"], "06")
            self.assertEqual(by_label["中标候选人公示"], "07")
            self.assertEqual(by_label["招标异常情况报告"], "12")

            manual_table = json.loads((root / "out" / "manual-url-check-table.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manual_table), 1)
            self.assertEqual(len(manual_table[0]["flow_summary"]), 12)

    def test_result_or_procurement_notice_is_not_accepted_as_flow_07_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_guangdong_ygp_city_discovery(
                output_root=Path(tmp_dir) / "out",
                city_codes=["440500"],
                per_city_candidate_limit=2,
                max_pages_per_city=1,
                enable_live_public_query=True,
                http_getter=_fake_result_only_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["candidate_project_count"], 0)
            self.assertEqual(result["manifest"]["ygp_city_search_records"][0]["rejected_record_count"], 2)

    def test_output_does_not_contain_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_guangdong_ygp_city_discovery(
                output_root=Path(tmp_dir) / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                build_flow_matrix=True,
                enable_live_public_query=True,
                http_getter=_fake_ygp_city_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _fake_ygp_city_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "search/v2/items" in url:
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": {"pageData": [_valid_candidate_item(), _result_notice_item(), _procurement_notice_item()]}}, ensure_ascii=False),
            "url": url,
        }
    if "nodeList" in url:
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": _node_list_payload()}, ensure_ascii=False),
            "url": url,
        }
    if "detail" in url:
        params = _query(url)
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": _detail_payload(params.get("noticeId", ""))}, ensure_ascii=False),
            "url": url,
        }
    return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}


def _fake_result_only_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "search/v2/items" in url:
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": {"pageData": [_result_notice_item(), _procurement_notice_item()]}}, ensure_ascii=False),
            "url": url,
        }
    return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}


def _valid_candidate_item() -> dict[str, Any]:
    return {
        "noticeId": "notice07",
        "projectCode": "E4404000001005932001",
        "noticeTitle": "珠海市海水淡化一期工程第二标段施工中标公示",
        "noticeSecondType": "A",
        "noticeSecondTypeDesc": "工程建设",
        "noticeThirdTypeDesc": "中标候选人公示",
        "datasetName": "中标候选人公示",
        "tradingProcess": "3C51",
        "regionCode": "440400",
        "siteCode": "440400",
        "publishDate": "20260515171800",
        "edition": "v3",
        "projectType": "A02",
        "projectTypeName": "市政",
        "pubServicePlat": "珠海市公共资源交易中心一体化平台",
    }


def _result_notice_item() -> dict[str, Any]:
    return {
        **_valid_candidate_item(),
        "noticeId": "notice09",
        "noticeTitle": "珠海市海水淡化一期工程中标结果公告",
        "datasetName": "中标结果公告",
        "noticeThirdTypeDesc": "中标结果公告",
        "tradingProcess": "3C52",
    }


def _procurement_notice_item() -> dict[str, Any]:
    return {
        **_valid_candidate_item(),
        "noticeId": "notice03",
        "noticeTitle": "珠海市海水淡化一期工程招标公告",
        "datasetName": "招标公告",
        "noticeThirdTypeDesc": "招标公告",
        "tradingProcess": "3C14",
    }


def _node_list_payload() -> list[dict[str, Any]]:
    return [
        {
            "nodeId": "n03",
            "nodeName": "招标公告及资格预审",
            "selectedBizCode": "3C14",
            "dataCount": 3,
            "dsList": [
                {"3C81@招标异常情况报告": ["notice12"]},
                {"3C14@招标公告、资格预审公告": ["notice03"]},
                {"3C16@招标文件、招标文件澄清与修改": ["notice04"]},
            ],
        },
        {
            "nodeId": "n07",
            "nodeName": "中标候选人公示",
            "selectedBizCode": "3C51",
            "dataCount": 4,
            "dsList": [
                {"3C73@资格审查结果": ["notice06"]},
                {"3C51@中标候选人公示": ["notice07"]},
                {"3C31@开标记录": ["notice05"]},
                {"3C42@评标报告": ["notice06b"]},
            ],
        },
        {
            "nodeId": "n09",
            "nodeName": "中标结果",
            "selectedBizCode": "3C52",
            "dataCount": 0,
            "dsList": [],
        },
        {
            "nodeId": "n11",
            "nodeName": "合同订立及履约",
            "selectedBizCode": "3C53",
            "dataCount": 0,
            "dsList": [],
        },
    ]


def _detail_payload(notice_id: str) -> dict[str, Any]:
    return {
        "title": f"珠海市海水淡化一期工程{notice_id}",
        "publishDate": "2026-05-15",
        "tradingNoticeColumnModelList": [
            {
                "name": "主要信息",
                "multiKeyValueTableList": [
                    [
                        {"key": "项目名称", "value": "珠海市海水淡化一期工程"},
                        {"key": "中标候选人", "value": "珠海测试建设有限公司"},
                        {"key": "项目负责人", "value": "张三"},
                        {"key": "服务期", "value": "365日历天"},
                    ]
                ],
                "richtext": "<p>中标候选人：珠海测试建设有限公司</p><p>项目负责人：张三</p>",
                "noticeFileBOList": [{"fileName": f"{notice_id}.pdf"}],
            }
        ],
    }


def _query(url: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse

    return {key: values[-1] for key, values in parse_qs(urlparse(url).query).items() if values}


if __name__ == "__main__":
    unittest.main()
