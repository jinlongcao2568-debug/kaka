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

from storage.guangdong_ygp_flow_matrix import build_guangdong_ygp_flow_matrix  # noqa: E402


YGP_URL_MAPPING = "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/dt2c/url-mapping/123-3C52"
YGP_HASH_URL = (
    "https://ygp.gdzwfw.gov.cn/ggzy-portal/#/44/new/jygg/v3/D?"
    "noticeId=n03&projectCode=441900029-2025-00741&bizCode=3871&siteCode=441900"
    "&publishDate=2025-11-21&source=1&titleDetails=%E9%87%87%E8%B4%AD%E5%85%AC%E5%91%8A"
)


class GuangdongYgpFlowMatrixTests(unittest.TestCase):
    def test_plan_only_generates_tasks_without_live_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_input(root)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(result["summary"]["ygp_flow_matrix_task_count"], 1)
            self.assertEqual(result["summary"]["ygp_flow_item_count"], 0)

    def test_live_readback_builds_full_01_to_12_matrix_from_node_list_and_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_input(root)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_source_urls=1,
                http_getter=_fake_ygp_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["ygp_project_readback_count"], 1)
            self.assertEqual(summary["ygp_flow_item_count"], 12)
            self.assertEqual(summary["ygp_detail_readback_ready_count"], 7)
            self.assertEqual(summary["present_flow_nos"], ["01", "02", "03", "04", "09", "11", "12"])
            matrix = result["manifest"]["ygp_flow_matrix_records"]
            self.assertEqual({row["flow_no"] for row in matrix}, {f"{idx:02d}" for idx in range(1, 13)})
            self.assertEqual(
                {row["flow_no"] for row in matrix if row["flow_item_state"] == "YGP_FLOW_ITEM_NOT_PRESENT"},
                {"05", "06", "07", "08", "10"},
            )
            detail = next(
                row for row in result["manifest"]["ygp_detail_readback_records"] if row["flow_no"] == "03"
            )
            self.assertEqual(detail["project_name"], "历史桥梁工程")
            self.assertIn("广东乙公司", detail["candidate_company_names"])
            self.assertEqual(detail["responsible_person_names"], ["李四"])
            self.assertIn("365日历天", detail["period_text"])
            self.assertEqual(detail["award_date"], "2025年10月15日")
            self.assertIn("采购文件.pdf", detail["attachment_names"])

    def test_hash_url_input_can_skip_url_mapping_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                source_urls=[YGP_HASH_URL],
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_source_urls=1,
                http_getter=_fake_ygp_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            project = result["manifest"]["ygp_project_records"][0]
            self.assertEqual(project["project_readback_state"], "YGP_FLOW_MATRIX_READY")
            self.assertEqual(project["resolved_project_route"]["projectCode"], "441900029-2025-00741")

    def test_empty_node_counts_as_flow_absent_without_duplicate_missing_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_input(root)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_source_urls=1,
                http_getter=_fake_ygp_http_getter_with_empty_candidate_node,
                created_at="2026-05-15T00:00:00+08:00",
            )

            matrix = result["manifest"]["ygp_flow_matrix_records"]
            self.assertEqual(len(matrix), 12)
            candidate_rows = [row for row in matrix if row["flow_no"] == "07"]
            self.assertEqual(len(candidate_rows), 1)
            self.assertEqual(candidate_rows[0]["flow_item_state"], "YGP_FLOW_ITEM_ABSENT")

    def test_dslist_items_are_mapped_by_specific_biz_code_and_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                source_urls=[YGP_HASH_URL],
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_source_urls=1,
                http_getter=_fake_ygp_engineering_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["ygp_flow_item_count"], 12)
            self.assertEqual(result["summary"]["present_flow_nos"], ["03", "04", "05", "06", "07", "12"])
            item_records = result["manifest"]["ygp_flow_item_records"]
            by_label = {record["notice_label"]: record["flow_no"] for record in item_records}
            self.assertEqual(by_label["招标公告、资格预审公告"], "03")
            self.assertEqual(by_label["招标文件、招标文件澄清与修改"], "04")
            self.assertEqual(by_label["开标记录"], "05")
            self.assertEqual(by_label["资格审查结果"], "06")
            self.assertEqual(by_label["评标报告"], "06")
            self.assertEqual(by_label["中标候选人公示"], "07")
            self.assertEqual(by_label["招标异常情况报告"], "12")

    def test_node_list_blocker_is_classified_without_fake_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_input(root)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_source_urls=1,
                http_getter=_fake_blocked_node_list_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            project = result["manifest"]["ygp_project_records"][0]
            self.assertEqual(project["project_readback_state"], "YGP_FLOW_MATRIX_BLOCKED")
            self.assertIn("ygp_node_list_temporary_unavailable_retry_required", project["blocker_taxonomy"])
            self.assertEqual(result["summary"]["ygp_detail_readback_ready_count"], 0)

    def test_output_does_not_contain_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_input(root)

            result = build_guangdong_ygp_flow_matrix(
                input_root=root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_source_urls=1,
                http_getter=_fake_ygp_http_getter,
                created_at="2026-05-15T00:00:00+08:00",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_input(root: Path) -> None:
    payload = {
        "manifest": {
            "original_notice_task_records": [
                {
                    "original_notice_task_id": "P13B-ORIGINAL-NOTICE-1",
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "candidate_company_name": "广东乙公司",
                    "responsible_person_names": ["李四"],
                    "original_notice_url": YGP_URL_MAPPING,
                    "ygp_original_url_pointer_only": True,
                }
            ],
        }
    }
    _write_json(root / "original-notice-backtrace-v1.json", payload)


def _fake_ygp_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "url-mapping" in url:
        return {
            "status_code": 302,
            "content_type": "application/json",
            "headers": {"Location": YGP_HASH_URL},
            "body": '{"success":true}',
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
        notice_id = params.get("noticeId", "")
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": _detail_payload(notice_id)}, ensure_ascii=False),
            "url": url,
        }
    return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}


def _fake_blocked_node_list_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "url-mapping" in url:
        return {
            "status_code": 302,
            "content_type": "application/json",
            "headers": {"Location": YGP_HASH_URL},
            "body": '{"success":true}',
            "url": url,
        }
    if "nodeList" in url:
        return {
            "status_code": 503,
            "content_type": "text/html",
            "body": "temporary unavailable",
            "url": url,
        }
    return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}


def _fake_ygp_http_getter_with_empty_candidate_node(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "nodeList" in url:
        payload = [
            *_node_list_payload(),
            {
                "nodeId": "n07",
                "nodeName": "中标候选人公示",
                "selectedBizCode": "3871",
                "dataCount": 0,
                "dsList": [],
            },
        ]
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": payload}, ensure_ascii=False),
            "url": url,
        }
    return _fake_ygp_http_getter(url, context)


def _fake_ygp_engineering_http_getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    if "nodeList" in url:
        return {
            "status_code": 200,
            "content_type": "application/json;charset=UTF-8",
            "body": json.dumps({"data": _engineering_node_list_payload()}, ensure_ascii=False),
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
    return _fake_ygp_http_getter(url, context)


def _node_list_payload() -> list[dict[str, Any]]:
    return [
        _node("n01", "采购意向公开", "3871@采购意向公开", "notice01"),
        _node("n02", "采购需求", "3871@采购需求", "notice02"),
        _node("n03", "采购公告", "3871@采购公告", "notice03"),
        _node("n04", "更正公告", "3871@更正公告", "notice04"),
        _node("n09", "结果公告", "3871@结果公告", "notice09"),
        _node("n11", "合同公告", "3871@合同公告", "notice11"),
        _node("n12", "终止公告", "3871@终止公告", "notice12"),
    ]


def _engineering_node_list_payload() -> list[dict[str, Any]]:
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
    ]


def _node(node_id: str, name: str, ds_key: str, notice_id: str) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "nodeName": name,
        "selectedBizCode": "3871",
        "dataCount": 1,
        "dsList": [{ds_key: [notice_id]}],
    }


def _detail_payload(notice_id: str) -> dict[str, Any]:
    return {
        "title": f"历史桥梁工程{notice_id}公告",
        "publishDate": "2025-10-15",
        "tradingNoticeColumnModelList": [
            {
                "name": "主要信息",
                "multiKeyValueTableList": [
                    [
                        {"key": "采购项目名称", "value": "历史桥梁工程"},
                        {"key": "中标人", "value": "广东乙公司"},
                        {"key": "项目负责人", "value": "李四"},
                        {"key": "服务期", "value": "365日历天"},
                        {"key": "中标日期", "value": "2025年10月15日"},
                    ]
                ],
                "richtext": "<p>中标单位：广东乙公司</p><p>项目负责人：李四</p>",
                "noticeFileBOList": [{"fileName": "采购文件.pdf"}],
            }
        ],
    }


def _query(url: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse

    return {key: values[-1] for key, values in parse_qs(urlparse(url).query).items() if values}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
