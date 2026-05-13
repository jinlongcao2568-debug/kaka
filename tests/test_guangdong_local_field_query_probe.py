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

from storage.guangdong_local_field_query_probe import build_guangdong_local_field_query_probe  # noqa: E402


class GuangdongLocalFieldQueryProbeTests(unittest.TestCase):
    def test_plan_only_delegates_gdcic_and_builds_pending_field_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            output_root = root / "out"
            _write_local_verification(local_root)

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=output_root,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 6)
            self.assertEqual(summary["delegated_task_count"], 1)
            self.assertEqual(summary["field_query_probe_state_counts"]["PLAN_ONLY_NOT_EXECUTED"], 5)
            delegated = result["manifest"]["field_task_records"][0]
            self.assertEqual(delegated["field_query_probe_state"], "DELEGATED_TO_SEPARATE_FIELD_ADAPTER")
            self.assertEqual(delegated["delegated_adapter_id"], "guangdong_gdcic_query_probe_v1")
            pending = result["manifest"]["field_task_records"][1]
            self.assertTrue(pending["route_plan"])
            self.assertEqual(pending["field_readback_state"], "FIELD_READBACK_NOT_RUN")
            text = json.dumps(result, ensure_ascii=False)
            for term in ("在建冲突成立", "无在建", "无风险", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人"):
                self.assertNotIn(term, text)
            self.assertTrue((output_root / "guangdong-local-field-query-probe-v1.json").exists())

    def test_live_public_query_records_keyword_hit_without_final_conclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": f"<html><body>{url} 广州测试建设有限公司 张三 粤1442020202100001</body></html>",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 1)
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["keyword_hit_task_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE")
            self.assertEqual(task["field_readback_state"], "PUBLIC_SOURCE_KEYWORD_HIT_REVIEW_REQUIRED")
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])

    def test_guangzhou_zfcj_api_readback_records_source_specific_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "xyxxxxxx.ashx" in url:
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "status": 1,
                            "message": "ok",
                            "data": {
                                "wsh": "440100202605010101",
                                "xmmc": "广州测试项目",
                                "xknr": "房屋建筑工程和市政基础设施工程施工许可",
                                "xdrmc": "广州测试建设有限公司",
                                "jdrq": "2026/5/1 0:00:00",
                                "xkjg": "广州市住房和城乡建设局",
                            },
                        },
                        "text_probe": "",
                    }
                if "xyxxzhlb.ashx" in url and params.get("keywords") == "广州测试建设有限公司":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "currentPage": 1,
                            "totalNum": 1,
                            "data": [
                                {
                                    "infoId": "INFO-001",
                                    "infoDate": "2026/5/1 0:00:00",
                                    "subCategory": 1,
                                    "infoName": "房屋建筑工程和市政基础设施工程施工许可【广州测试建设有限公司】",
                                    "rowNum": "1",
                                }
                            ],
                            "status": 1,
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"currentPage": 1, "totalNum": 0, "data": [], "status": 1},
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["source_specific_readback_ready_count"], 1)
            self.assertEqual(summary["guangzhou_zfcj_api_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["field_readback_state"], "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED")
            self.assertEqual(task["field_summary"]["source_specific_adapter_id"], "guangzhou_zfcj_xyxx_api_query_v1")
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertIn("xyxxDetails", record["detail_url"])
            self.assertEqual(record["detail_readback"]["administrative_counterparty"], "广州测试建设有限公司")
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])

    def test_guangzhou_construction_permit_public_api_readback_records_permit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "jzgdsgxkxxlb.ashx" in url and "sgdw=" in url:
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "currentPage": 1,
                            "totalNum": 1,
                            "data": [
                                {
                                    "gcmc": "广州测试项目",
                                    "jsdd": "广州市天河区测试路1号",
                                    "jsdw": "广州测试建设单位",
                                    "sgdw": "广州测试建设有限公司",
                                    "jldw": "广州测试监理有限公司",
                                    "sgxkzh": "440106202605120101",
                                    "pzrq": "2026/5/12 0:00:00",
                                    "sgxkzt": "有效",
                                }
                            ],
                            "status": 1,
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"currentPage": 1, "totalNum": 0, "data": [], "status": 1},
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["guangzhou_zfcj_construction_permit_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangzhou_zfcj_construction_permit_public_api_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "construction_permit_public_record")
            self.assertEqual(record["construction_company_probe"], "广州测试建设有限公司")
            self.assertEqual(record["construction_permit_no"], "440106202605120101")
            self.assertEqual(record["permit_status"], "有效")
            self.assertTrue(record["query_miss_is_not_clearance"])

    def test_guangzhou_completion_acceptance_public_api_readback_records_filing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "gcjgysxxlb.ashx" in url and "sgdw=" in url:
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "currentPage": 1,
                            "totalNum": 1,
                            "data": [
                                {
                                    "pegcmc": "广州测试项目",
                                    "babh": "穗竣备2026-001",
                                    "pejsdd": "广州市天河区测试路1号",
                                    "jsdw": "广州测试建设单位",
                                    "sgdw": "广州测试建设有限公司",
                                    "spbm": "广州市住房和城乡建设局",
                                    "peblrq": "2026/5/13 0:00:00",
                                }
                            ],
                            "status": 1,
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"currentPage": 1, "totalNum": 0, "data": [], "status": 1},
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["guangzhou_zfcj_completion_acceptance_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangzhou_zfcj_completion_acceptance_public_api_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "completion_acceptance_public_record")
            self.assertEqual(record["construction_company_probe"], "广州测试建设有限公司")
            self.assertEqual(record["completion_filing_no"], "穗竣备2026-001")
            self.assertEqual(record["acceptance_date"], "2026/5/13 0:00:00")
            self.assertTrue(record["readback_is_line_clue_not_final_conclusion"])

    def test_gdcic_contract_performance_public_page_readback_records_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "PerformanceEvaluationProject/Indexgs" in url and params.get("search_name") == "广州测试建设有限公司":
                    return {
                        "http_status": 200,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": """
                        <table><tbody>
                        <tr>
                          <td>1</td><td>广州测试项目</td><td>广州建设单位</td>
                          <td>广州测试建设有限公司</td><td>广州勘察单位</td><td>广州设计单位</td>
                          <td>广州监理单位</td><td><a onclick="ppDetaill('DG-001')">查看</a></td>
                        </tr>
                        </tbody></table>
                        """,
                    }
                if "Indexht" in url:
                    return {
                        "http_status": 200,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "<script>top.window.location.href='http://210.76.80.152:8008/SSO/jrsso/auth'</script>",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<table><tbody></tbody></table>",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["source_specific_readback_ready_count"], 1)
            self.assertEqual(summary["guangdong_gdcic_contract_performance_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangdong_gdcic_contract_performance_public_page_v1",
            )
            self.assertIn("gd_gdcic_contract_system_sso_login_required", task["blocker_taxonomy"])
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["construction_company_probe"], "广州测试建设有限公司")
            self.assertIn("Detailgs", record["detail_url"])

    def test_zfcxjst_penalty_publicity_readback_records_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "post_4890001" in url:
                    return {
                        "http_status": 200,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": """
                        <meta name="ArticleTitle" content="关于广州测试建设有限公司的行政处罚决定书">
                        <meta name="PubDate" content="2026-04-30 09:00">
                        <div class="news-article">
                        <p>（法人）名称：广州测试建设有限公司</p>
                        <p>统一社会信用代码：91440101MA00000000</p>
                        <p>2026年1月1日，本机关发现你单位承建的广州测试项目存在质量安全问题。</p>
                        <p>文号：粤建质罚〔2026〕88号</p>
                        <p>本机关决定给予你单位暂扣建筑施工企业安全生产许可证30日的行政处罚。</p>
                        </div>
                        """,
                    }
                if "gsgg" in url:
                    return {
                        "http_status": 200,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": """
                        <ul>
                          <li><a href="http://zfcxjst.gd.gov.cn/xxgk/gsgg/content/post_4890001.html"
                                 title="关于广州测试建设有限公司的行政处罚决定书">关于广州测试建设有限公司的行政处罚决定书</a></li>
                        </ul>
                        """,
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<html></html>",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-ZFCXJST-PENALTY-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["source_specific_readback_ready_count"], 1)
            self.assertEqual(summary["guangdong_zfcxjst_penalty_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangdong_zfcxjst_penalty_publicity_page_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["administrative_counterparty"], "广州测试建设有限公司")
            self.assertEqual(record["document_no"], "粤建质罚〔2026〕88号")
            self.assertIn("暂扣建筑施工企业安全生产许可证30日", record["punishment_summary_probe"])

    def test_tzxm_project_approval_readback_records_filing_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "selectBaProjectInfo" in url:
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "code": "0",
                            "status": 200,
                            "data": {
                                "proofOrSerialCode": "2605-440100-04-01-000001",
                                "projectName": "广州测试项目",
                                "applyOrgan": "广州测试建设有限公司",
                                "place": "广州市天河区",
                                "scope": "建设一栋研发楼及配套设施。",
                                "finishDate": "2026-05-12",
                                "stateFlagName": "办结（通过）",
                                "fullName": "广州市发展和改革委员会",
                            },
                        },
                        "text_probe": "",
                    }
                if "selectByPageBA" in url and params.get("flag") == "1":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "code": "0",
                            "status": 200,
                            "data": {
                                "list": [
                                    {
                                        "baId": "BA-001",
                                        "projectCode": "2605-440100-04-01-000001",
                                        "projectName": "广州测试项目",
                                        "applyOrgan": "广州测试建设有限公司",
                                        "projectAddress": "广州市天河区",
                                        "stateFlagName": "办结（通过）",
                                        "finishDate": "2026-05-12",
                                    }
                                ]
                            },
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"code": "0", "status": 200, "data": {"list": []}},
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-TZXM-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["source_specific_readback_ready_count"], 1)
            self.assertEqual(summary["guangdong_tzxm_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangdong_tzxm_project_approval_publicity_api_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["project_code"], "2605-440100-04-01-000001")
            self.assertEqual(record["project_unit_probe"], "广州测试建设有限公司")
            self.assertEqual(record["detail_readback"]["approval_unit"], "广州市发展和改革委员会")
            self.assertIn("研发楼", record["detail_readback"]["project_scope_probe"])

    def test_credit_gd_public_credit_readback_records_penalty_and_license(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "booleanQueryListByPageSimple" not in url:
                    return {
                        "http_status": 200,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "信用广东公开查询入口",
                    }
                if params.get("jsonArgs"):
                    return {
                        "http_status": 403,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "Forbidden",
                    }
                table_name = str(params.get("tableName") or "")
                if "xzcf" in table_name:
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "code": 0,
                            "data": {
                                "rows": [
                                    {
                                        "ID": "CF-001",
                                        "CF_XDR_MC": "广州测试建设有限公司",
                                        "CF_WSH": "粤信罚〔2026〕1号",
                                        "CF_SY": "广州测试项目信用处罚事项",
                                        "CF_CFJG": "广东省发展和改革委员会",
                                        "CF_JDRQ": "2026-05-01",
                                        "CF_NR": "行政处罚公开记录",
                                    }
                                ],
                                "page": 1,
                                "totalPage": 1,
                            },
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {
                        "code": 0,
                        "data": {
                            "rows": [
                                {
                                    "ID": "XK-001",
                                    "XK_XDR_MC": "广州测试建设有限公司",
                                    "XK_WSH": "粤信许〔2026〕1号",
                                    "XK_XMMC": "广州测试项目行政许可事项",
                                    "XK_XKJG": "广东省发展和改革委员会",
                                    "XK_JDRQ": "2026-05-02",
                                    "XK_NR": "行政许可公开记录",
                                }
                            ],
                            "page": 1,
                            "totalPage": 1,
                        },
                    },
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                credit_gd_session_getter=_credit_gd_session_readback,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["readback_ready_count"], 1)
            self.assertEqual(summary["source_specific_readback_ready_count"], 1)
            self.assertEqual(summary["guangdong_credit_gd_readback_ready_count"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangdong_credit_gd_public_credit_query_v1",
            )
            self.assertEqual(task["field_summary"]["public_list_record_count"], 2)
            self.assertEqual(
                task["field_summary"]["public_list_record_type_counts"]["administrative_penalty_public_record"],
                1,
            )
            self.assertEqual(
                task["field_summary"]["public_list_record_type_counts"]["administrative_license_public_record"],
                1,
            )
            records = task["field_match_summary"]["source_specific_records"]
            self.assertGreaterEqual(len(records), 2)
            self.assertEqual(records[0]["administrative_counterparty"], "广州测试建设有限公司")
            self.assertIn(records[0]["record_type"], {"administrative_penalty_public_record", "administrative_license_public_record"})
            self.assertIn("creditPublic", records[0]["detail_url"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])
            self.assertIn("gd_credit_gd_public_list_readback_ready", task["blocker_taxonomy"])
            self.assertEqual(
                task["diagnostics"]["credit_gd_session_readback_v1"]["discovered_api_path"],
                "/gdcreditwebApi2//company/web/booleanQueryListByPageSimple",
            )
            self.assertEqual(
                task["route_attempts"][0]["credit_gd_cookie_session_state"],
                "SESSION_COOKIE_PRESENT",
            )
            list_urls = [
                route["url"]
                for route in task["route_plan"]
                if route["route_group"] == "gd_credit_gd_public_credit_list"
            ]
            self.assertTrue(list_urls)
            self.assertTrue(
                all("/gdcreditwebApi2//company/web/booleanQueryListByPageSimple" in url for url in list_urls)
            )
            targeted_attempts = [
                attempt
                for attempt in task["route_attempts"]
                if attempt["route_group"] == "gd_credit_gd_public_credit_targeted_query"
            ]
            self.assertTrue(targeted_attempts)
            self.assertTrue(all(attempt["deferred_reason"] == "public_list_match_ready" for attempt in targeted_attempts))

    def test_credit_gd_list_records_without_candidate_match_stay_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "booleanQueryListByPageSimple" not in url:
                    return {
                        "http_status": 200,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "信用广东公开查询入口",
                    }
                if params.get("jsonArgs"):
                    return {
                        "http_status": 403,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "Forbidden",
                    }
                table_name = str(params.get("tableName") or "")
                if "xzcf" in table_name:
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "code": 0,
                            "data": {
                                "rows": [
                                    {
                                        "ID": "CF-OTHER",
                                        "CF_XDR_MC": "其他建设有限公司",
                                        "CF_WSH": "粤信罚〔2026〕2号",
                                        "CF_SY": "其他项目处罚事项",
                                        "CF_CFJG": "广东省发展和改革委员会",
                                        "CF_JDRQ": "2026-05-01",
                                        "CF_NR": "行政处罚公开记录",
                                    }
                                ],
                            },
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {
                        "code": 0,
                        "data": {
                            "rows": [
                                {
                                    "ID": "XK-OTHER",
                                    "XK_XDR_MC": "其他建设有限公司",
                                    "XK_WSH": "粤信许〔2026〕2号",
                                    "XK_XMMC": "其他项目行政许可事项",
                                    "XK_XKJG": "广东省发展和改革委员会",
                                    "XK_JDRQ": "2026-05-02",
                                    "XK_NR": "行政许可公开记录",
                                }
                            ],
                        },
                    },
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                credit_gd_session_getter=_credit_gd_session_readback,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_credit_gd_readback_ready_count"], 0)
            self.assertEqual(summary["field_query_probe_state_counts"]["NO_FIELD_MATCH_REVIEW_REQUIRED"], 1)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertEqual(task["field_readback_state"], "PUBLIC_SOURCE_QUERIED_NO_FIELD_MATCH")
            self.assertFalse(task["readback_ready"])
            self.assertEqual(task["field_summary"]["public_list_record_count"], 2)
            self.assertEqual(
                task["field_summary"]["public_list_record_type_counts"]["administrative_penalty_public_record"],
                1,
            )
            self.assertEqual(
                task["field_summary"]["public_list_record_type_counts"]["administrative_license_public_record"],
                1,
            )
            samples = task["field_match_summary"]["public_list_sample_records_for_interface_diagnostics"]
            self.assertEqual({sample["record_type"] for sample in samples}, {
                "administrative_penalty_public_record",
                "administrative_license_public_record",
            })
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])
            self.assertIn("gd_credit_gd_targeted_query_forbidden_review", task["blocker_taxonomy"])
            self.assertIn("gd_credit_gd_targeted_query_deferred_by_site_guard", task["blocker_taxonomy"])

    def test_credit_gd_browser_session_readback_discovers_current_api_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)
            seen_urls: list[str] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                seen_urls.append(url)
                self.assertIn("/gdcreditwebApi2//company/web/booleanQueryListByPageSimple", url)
                self.assertEqual(params.get("_cookie_header"), "SESSIONID=abc")
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"data": {"rows": []}},
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                credit_gd_session_getter=_credit_gd_session_readback,
                credit_gd_max_requests_per_task=2,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertEqual(task["diagnostics"]["credit_gd_session_readback_v1"]["session_state"], "SESSION_READBACK_READY")
            self.assertEqual(task["diagnostics"]["credit_gd_session_readback_v1"]["cookie_count"], 1)
            self.assertTrue(seen_urls)
            self.assertTrue(all("/company/web/booleanQueryListByPageSimple" in url for url in seen_urls))
            self.assertTrue(all("/gdcreditwebApi2//company/web/" in url for url in seen_urls))

    def test_credit_gd_site_guard_does_not_mark_source_successful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if params.get("_route_group") == "gd_credit_gd_public_credit_list":
                    return {
                        "http_status": 503,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "Service Temporarily Unavailable",
                    }
                return {
                    "http_status": 403,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "验证码 校验失败",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                credit_gd_session_getter=_credit_gd_session_readback,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_credit_gd_readback_ready_count"], 0)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED")
            self.assertFalse(task["readback_ready"])
            self.assertIn("gd_credit_gd_rate_limited_or_temporary_unavailable", task["blocker_taxonomy"])
            self.assertIn("gd_credit_gd_targeted_query_deferred_by_site_guard", task["blocker_taxonomy"])
            self.assertNotIn("gd_credit_gd_public_list_readback_ready", task["blocker_taxonomy"])
            repair_attempts = task["diagnostics"]["credit_gd_session_repair_attempts"]
            self.assertEqual(repair_attempts[0]["repair_action"], "session_refresh_retry_public_list_once")
            self.assertTrue(
                any(
                    attempt.get("credit_gd_repair_action") == "session_refresh_retry_public_list_once"
                    for attempt in task["route_attempts"]
                )
            )

    def test_credit_gd_session_refresh_retry_can_recover_public_list_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)
            list_call_count = 0

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                nonlocal list_call_count
                if params.get("_route_group") == "gd_credit_gd_public_credit_list":
                    list_call_count += 1
                    if list_call_count == 1:
                        return {
                            "http_status": 503,
                            "content_type": "text/html; charset=utf-8",
                            "text_probe": "站点繁忙",
                        }
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "data": {
                                "rows": [
                                    {
                                        "ID": "CF-RECOVERED",
                                        "CF_XDR_MC": "广州测试建设有限公司",
                                        "CF_WSH": "粤信罚〔2026〕3号",
                                        "CF_SY": "广州测试项目行政处罚事项",
                                        "CF_CFJG": "广东省发展和改革委员会",
                                        "CF_JDRQ": "2026-05-03",
                                    }
                                ]
                            }
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 403,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "验证码 校验失败",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                credit_gd_session_getter=_credit_gd_session_readback,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertTrue(task["readback_ready"])
            self.assertIn("gd_credit_gd_public_list_readback_ready", task["blocker_taxonomy"])
            self.assertTrue(
                any(
                    attempt.get("credit_gd_repair_action") == "session_refresh_retry_public_list_once"
                    and attempt.get("json_record_count") == 1
                    for attempt in task["route_attempts"]
                )
            )

    def test_credit_gd_rendered_page_fallback_keeps_query_miss_in_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 503,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "Service Temporarily Unavailable",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                credit_gd_session_getter=_credit_gd_rendered_session_readback,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertFalse(task["readback_ready"])
            self.assertIn("gd_credit_gd_public_list_rendered_fallback_ready", task["blocker_taxonomy"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])
            self.assertTrue(
                any(
                    attempt["route_group"] == "gd_credit_gd_rendered_public_list_fallback"
                    for attempt in task["route_attempts"]
                )
            )

    def test_credit_gd_repeated_runs_never_reuse_legacy_404_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)
            seen_urls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                seen_urls.append(url)
                if "/gdcreditwebApi2//company/web/booleanQueryListByPageSimple" not in url:
                    return {
                        "http_status": 404,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "legacy 404",
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"data": {"rows": []}},
                    "text_probe": "",
                }

            for index in range(2):
                result = build_guangdong_local_field_query_probe(
                    local_verification_root=local_root,
                    output_root=root / f"out-{index}",
                    source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                    enable_live_public_query=True,
                    max_live_tasks=1,
                    http_getter=fake_getter,
                    credit_gd_session_getter=_credit_gd_session_readback,
                    credit_gd_max_requests_per_task=2,
                    created_at="2026-05-12T00:00:00+08:00",
                )
                self.assertTrue(result["safe_to_execute"])

            self.assertTrue(seen_urls)
            self.assertTrue(
                all("/gdcreditwebApi2//company/web/booleanQueryListByPageSimple" in url for url in seen_urls)
            )
            self.assertFalse(
                any(url.endswith("/company/web/booleanQueryListByPageSimple") and "/gdcreditwebApi2//" not in url for url in seen_urls)
            )

    def test_credit_gd_stale_or_blocked_interface_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if "booleanQueryListByPageSimple" in url and params.get("_route_group") == "gd_credit_gd_public_credit_list":
                    return {
                        "http_status": 404,
                        "content_type": "text/html; charset=utf-8",
                        "text_probe": "404 很抱歉，您查看的页面找不到了",
                    }
                return {
                    "http_status": 403,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "验证码 校验失败",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-CREDIT-GD-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED")
            self.assertIn("gd_credit_gd_interface_endpoint_not_found_or_stale", task["blocker_taxonomy"])
            self.assertIn("gd_credit_gd_waf_or_captcha_required", task["blocker_taxonomy"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])

    def test_live_public_query_miss_remains_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<html><body>公开查询入口</body></html>",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertFalse(task["readback_ready"])
            self.assertIn("guangzhou_zfcj_xyxx_api_no_record_review", task["blocker_taxonomy"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])

    def test_captcha_or_login_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<html><body>请登录后完成验证码</body></html>",
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED")
            self.assertIn("guangdong_local_field_query_captcha_or_login_required", task["blocker_taxonomy"])

    def test_missing_local_verification_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangdong_local_field_query_probe(
                local_verification_root=root / "missing",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("guangdong_local_verification_probe_missing", result["blocking_reasons"])
            self.assertEqual(result["summary"]["probe_state"], "INPUT_BLOCKED")


def _write_local_verification(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tasks = [
        _task("GUANGDONG-GDCIC-SKYPT-OPENPLATFORM", "https://skypt.gdcic.net/openplatform/"),
        _task("GUANGDONG-GDCIC-HOME", "http://210.76.80.152:8008"),
        _task("GUANGDONG-ZFCXJST-PENALTY-PUBLICITY", "https://zfcxjst.gd.gov.cn/xxgk/gsgg/"),
        _task("GUANGDONG-TZXM-HOME", "https://tzxm.gd.gov.cn/"),
        _task("GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY", "https://zfcj.gz.gov.cn/zfcj/xyxx/"),
        _task("GUANGDONG-CREDIT-GD-HOME", "https://credit.gd.gov.cn/"),
    ]
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_local_verification_probe_v1_manifest",
            "query_task_records": tasks,
            "project_task_records": [
                {
                    "project_id": "PROJ-CN-GD-TEST",
                    "project_name": "广州测试项目",
                    "query_task_ids": [task["query_task_id"] for task in tasks],
                    "query_task_count": len(tasks),
                }
            ],
        },
        "summary": {
            "guangdong_local_verification_task_count": len(tasks),
        },
    }
    (root / "guangdong-local-verification-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _task(source_profile_id: str, source_url: str) -> dict[str, Any]:
    return {
        "query_task_id": f"GD-LOCAL-VERIFY-{source_profile_id}",
        "active_conflict_task_id": "GZ-ACTIVE-CONFLICT-TASK-001",
        "project_id": "PROJ-CN-GD-TEST",
        "project_name": "广州测试项目中标候选人公示",
        "candidate_group_id": "G1",
        "candidate_group_order": "1",
        "responsible_person_name": "张三",
        "candidate_group_members": ["广州测试建设有限公司"],
        "matched_company_names": ["广州测试建设有限公司"],
        "company_query_variants": ["广州测试建设有限公司"],
        "certificate_no": "粤1442020202100001",
        "query_keywords": ["广州测试建设有限公司 张三"],
        "source_profile_id": source_profile_id,
        "source_family": "test_source_family",
        "source_url": source_url,
        "target_source_types": ["construction_permit", "contract_public_info"],
        "query_params": {
            "projectId": "PROJ-CN-GD-TEST",
            "projectName": "广州测试项目中标候选人公示",
            "companyName": "广州测试建设有限公司",
            "companyVariants": ["广州测试建设有限公司"],
            "personName": "张三",
            "certificateNo": "粤1442020202100001",
            "keywords": [
                "广州测试项目中标候选人公示",
                "广州测试建设有限公司",
                "张三",
                "粤1442020202100001",
            ],
        },
        "field_adapter_status": (
            "IMPLEMENTED_SEPARATE:guangdong_gdcic_query_probe_v1"
            if source_profile_id == "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"
            else "FIELD_ADAPTER_PENDING"
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _credit_gd_session_readback(_routes: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    return {
        "session_readback_adapter_id": "credit_gd_session_readback_v1",
        "session_state": "SESSION_READBACK_READY",
        "discovered_api_url": "https://credit.gd.gov.cn/gdcreditwebApi2//company/web/booleanQueryListByPageSimple",
        "captured_response_urls": [
            "https://credit.gd.gov.cn/gdcreditwebApi2//company/web/booleanQueryListByPageSimple?page=1",
        ],
        "prewarm_page_urls": [
            "https://credit.gd.gov.cn/page/creditPublic/xzcf.html",
            "https://credit.gd.gov.cn/page/creditPublic/xzxk.html",
        ],
        "cookie_header": "SESSIONID=abc",
        "cookie_session_state": "SESSION_COOKIE_PRESENT",
        "cookie_count": 1,
        "blocker_taxonomy": [],
    }


def _credit_gd_rendered_session_readback(routes: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    payload = dict(_credit_gd_session_readback(routes))
    payload["rendered_public_list_state"] = "RENDERED_TEXT_READY"
    payload["rendered_public_list_text_probe"] = "信用广东 行政处罚 行政许可 其他建设有限公司"
    return payload


if __name__ == "__main__":
    unittest.main()
