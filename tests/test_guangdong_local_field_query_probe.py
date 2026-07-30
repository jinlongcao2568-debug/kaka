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

import storage.guangdong_local_field_query_probe as field_query_probe  # noqa: E402
from storage.guangdong_local_field_query_probe import build_guangdong_local_field_query_probe  # noqa: E402


class GuangdongLocalFieldQueryProbeTests(unittest.TestCase):
    def test_append_missing_query_params_does_not_duplicate_existing_ygp_detail_params(self) -> None:
        url = (
            "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/trading-notice/new/detail"
            "?nodeId=1942830178172833793&version=v3&noticeId=notice-1"
            "&bizCode=3C52&projectCode=E4401001123002315001&siteCode=440900"
        )

        request_url = field_query_probe._append_missing_query_params(
            url,
            {
                "nodeId": "1942830178172833793",
                "version": "v3",
                "noticeId": "notice-1",
                "bizCode": "3C52",
                "projectCode": "E4401001123002315001",
                "siteCode": "440900",
                "extra": "keep",
            },
        )

        self.assertEqual(request_url.count("?"), 1)
        self.assertEqual(request_url.count("nodeId="), 1)
        self.assertEqual(request_url.count("projectCode="), 1)
        self.assertIn("&extra=keep", request_url)

    def test_default_getter_uses_scrapling_bridge_for_get_readback(self) -> None:
        class FakeResponse:
            url = "https://example.test/query?a=1"
            final_url = "https://example.test/query?a=1"
            status_code = 200
            content_type = "text/html; charset=utf-8"
            content = "江苏测试建设有限公司".encode("utf-8")
            headers = {
                "x-ax9s-fetch-transport": "fake_primary",
                "x-ax9s-scrapling-escalation-target": "scrapling_dynamic",
                "x-ax9s-scrapling-escalation-trigger": "response",
                "x-ax9s-scrapling-escalation-reasons": "SPA_OR_JS_RENDERED_SHELL_DETECTED",
            }

        class FakeTransport:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def fetch(self, url: str, *, timeout_seconds: float, user_agent: str) -> FakeResponse:
                self.calls.append(
                    {
                        "url": url,
                        "timeout_seconds": timeout_seconds,
                        "user_agent": user_agent,
                    }
                )
                return FakeResponse()

        fake_transport = FakeTransport()
        original_transport = field_query_probe._STAGE4_SCRAPLING_GET_TRANSPORT
        try:
            field_query_probe._STAGE4_SCRAPLING_GET_TRANSPORT = fake_transport
            response = field_query_probe._default_http_getter("https://example.test/query", {"a": "1"})
            attempt = field_query_probe._route_attempt(
                {"route_id": "r1", "route_group": "g1", "url": "https://example.test/query"},
                response,
                ["江苏测试建设有限公司"],
            )
        finally:
            field_query_probe._STAGE4_SCRAPLING_GET_TRANSPORT = original_transport

        self.assertEqual(fake_transport.calls[0]["url"], "https://example.test/query?a=1")
        self.assertEqual(response["http_status"], 200)
        self.assertTrue(response["stage4_scrapling_get_bridge_used"])
        self.assertEqual(attempt["keyword_hit_count"], 1)
        self.assertTrue(attempt["stage4_scrapling_get_bridge_used"])
        self.assertEqual(attempt["scrapling_escalation_target"], "scrapling_dynamic")
        self.assertEqual(attempt["fetch_transport"], "fake_primary")

    def test_default_getter_skips_scrapling_bridge_for_post_api(self) -> None:
        self.assertFalse(
            field_query_probe._should_use_stage4_scrapling_get_bridge(
                "POST",
                {},
                json_body=True,
                form_body=False,
            )
        )

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
            self.assertEqual(summary["adapter_result_state_counts"]["NEEDS_BROWSER"], 6)
            delegated = result["manifest"]["field_task_records"][0]
            self.assertEqual(delegated["field_query_probe_state"], "DELEGATED_TO_SEPARATE_FIELD_ADAPTER")
            self.assertEqual(delegated["delegated_adapter_id"], "guangdong_gdcic_query_probe_v1")
            self.assertEqual(delegated["adapter_result_state"], "NEEDS_BROWSER")
            pending = result["manifest"]["field_task_records"][1]
            self.assertTrue(pending["route_plan"])
            self.assertEqual(pending["field_readback_state"], "FIELD_READBACK_NOT_RUN")
            self.assertEqual(pending["adapter_result_state"], "NEEDS_BROWSER")
            text = json.dumps(result, ensure_ascii=False)
            for term in ("在建冲突成立", "无在建", "无风险", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人"):
                self.assertNotIn(term, text)
            self.assertTrue((output_root / "guangdong-local-field-query-probe-v1.json").exists())

    def test_live_gdcic_openplatform_delegated_adapter_feeds_field_query_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            output_root = root / "out"
            _write_local_verification(local_root)
            requested: list[tuple[str, Mapping[str, Any]]] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested.append((url, dict(params)))
                if url.endswith("/openplatform/project/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "1573",
                                    "projectCode": "4401141512100101",
                                    "projectName": "广州测试项目",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/publicityPeriod/listApplyProjectPerson"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "1573",
                                    "name": "张三",
                                    "post": "项目经理",
                                    "orgName": "广州测试建设有限公司",
                                    "regCertNum": "粤1442020202100001",
                                    "certNum": "441900202206061001",
                                    "idNum": "44010119900101567X",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=output_root,
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 1)
            self.assertEqual(summary["delegated_task_count"], 0)
            self.assertEqual(summary["guangdong_gdcic_openplatform_readback_ready_count"], 1)
            self.assertEqual(summary["guangdong_gdcic_openplatform_publicity_period_readback_ready_count"], 1)
            self.assertEqual(summary["adapter_result_state_counts"], {"MATCHED": 1})
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["delegated_adapter_id"], "guangdong_gdcic_query_probe_v1")
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "guangdong_gdcic_openplatform_public_api_query_v1",
            )
            self.assertEqual(task["field_summary"]["sample_person_names"], ["张三"])
            self.assertEqual(task["field_summary"]["sample_certificate_nos"], ["粤1442020202100001"])
            source_records = task["field_match_summary"]["source_specific_records"]
            self.assertTrue(any(record["record_type"] == "personnel_public_record" for record in source_records))
            self.assertNotIn("44010119900101567X", json.dumps(task, ensure_ascii=False))
            self.assertTrue(any(record.get("id_card_redacted") is True for record in source_records))
            self.assertTrue(
                any(
                    url.endswith("/openplatform/publicityPeriod/getContract")
                    and params.get("_method") == "POST"
                    for url, params in requested
                )
            )

    def test_live_gdcic_openplatform_uses_project_title_variants_for_publicity_followup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            output_root = root / "out"
            _write_local_verification(local_root)
            local_path = local_root / "guangdong-local-verification-probe-v1.json"
            payload = json.loads(local_path.read_text(encoding="utf-8"))
            task = payload["manifest"]["query_task_records"][0]
            task["project_name"] = "广州科玛生物科技有限公司日用品、化妆品、药品及食品生产建设项目"
            task["query_params"]["projectName"] = task["project_name"]
            local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            requested: list[tuple[str, Mapping[str, Any]]] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested.append((url, dict(params)))
                if url.endswith("/openplatform/project/list") and params.get("projectName") == "广州科玛生物科技有限公司日用品":
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "1573",
                                    "projectCode": "4401141512100101",
                                    "projectName": "广州科玛生物科技有限公司日用品",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/publicityPeriod/listApplyProjectPerson"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "1573",
                                    "name": "王先耀",
                                    "post": "项目经理",
                                    "orgName": "东莞市建工集团有限公司",
                                    "regCertNum": "粤1332006200810171",
                                    "certNum": "441900202206061001",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=output_root,
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["adapter_result_state_counts"], {"MATCHED": 1})
            self.assertEqual(summary["guangdong_gdcic_openplatform_publicity_period_readback_ready_count"], 1)
            field_task = result["manifest"]["field_task_records"][0]
            self.assertEqual(field_task["field_summary"]["sample_person_names"], ["王先耀"])
            self.assertIn("粤1332006200810171", field_task["field_summary"]["sample_certificate_nos"])
            self.assertTrue(
                any(
                    url.endswith("/openplatform/project/list")
                    and params.get("projectName") == "广州科玛生物科技有限公司日用品"
                    for url, params in requested
                )
            )

    def test_live_gdcic_openplatform_uses_service_suffix_stripped_project_title_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            output_root = root / "out"
            _write_local_verification(local_root)
            local_path = local_root / "guangdong-local-verification-probe-v1.json"
            payload = json.loads(local_path.read_text(encoding="utf-8"))
            task = payload["manifest"]["query_task_records"][0]
            task["project_name"] = "珠海市-阳江市产业转移合作园区新材料厂房项目工程设计施工总承包"
            task["query_params"]["projectName"] = task["project_name"]
            local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            requested: list[tuple[str, Mapping[str, Any]]] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested.append((url, dict(params)))
                if (
                    url.endswith("/openplatform/project/list")
                    and params.get("projectName") == "珠海市-阳江市产业转移合作园区新材料厂房项目"
                ):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "8801",
                                    "projectCode": "441702202605200001",
                                    "projectName": "珠海市-阳江市产业转移合作园区新材料厂房项目",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/publicityPeriod/getContract"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "8801",
                                    "projectName": "珠海市-阳江市产业转移合作园区新材料厂房项目",
                                    "contractOrgName": "广州测试建设有限公司",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_local_field_query_probe(
                local_verification_root=local_root,
                output_root=output_root,
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            field_task = result["manifest"]["field_task_records"][0]
            self.assertEqual(field_task["adapter_result_state"], "MATCHED")
            self.assertTrue(
                any(
                    url.endswith("/openplatform/project/list")
                    and params.get("projectName") == "珠海市-阳江市产业转移合作园区新材料厂房项目"
                    for url, params in requested
                )
            )

    def test_p13b_release_evidence_tasks_feed_field_query_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            p13b_root = root / "p13b"
            output_root = root / "out"
            _write_p13b_operational_closeout(p13b_root)

            result = build_guangdong_local_field_query_probe(
                p13b_operational_closeout_root=p13b_root,
                output_root=output_root,
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["manifest"]["input_mode"], "P13B_RELEASE_EVIDENCE_TASKS")
            self.assertNotIn("guangdong_local_verification_probe_missing", result["blocking_reasons"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 3)
            self.assertEqual(summary["input_source_kind_counts"]["p13b_release_evidence_probe_task"], 3)
            self.assertEqual(summary["release_evidence_task_count"], 3)
            self.assertEqual(summary["release_evidence_initial_abcd_grade_counts"]["A_STRONG_TIME_OVERLAP_SIGNAL"], 3)
            self.assertEqual(summary["release_evidence_downstream_abcd_grade_counts"]["PENDING_NOT_EXECUTED"], 3)
            self.assertEqual(summary["release_evidence_terminal_downstream_grade_count"], 0)
            self.assertEqual(summary["field_query_probe_state_counts"]["PLAN_ONLY_NOT_EXECUTED"], 3)
            self.assertEqual(summary["adapter_result_state_counts"]["NEEDS_BROWSER"], 3)
            self.assertEqual(summary["p13b_initial_release_evidence_abcd_grade_counts"]["A_STRONG_TIME_OVERLAP_SIGNAL"], 3)
            self.assertEqual(summary["p13b_downstream_release_evidence_abcd_grade_counts"]["PENDING_NOT_EXECUTED"], 3)
            self.assertEqual(summary["source_profile_task_counts"]["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"], 3)

            tasks = result["manifest"]["field_task_records"]
            first = tasks[0]
            self.assertEqual(first["p13b_release_evidence_probe_task_id"], "P13B-RELEASE-PROBE-TASK-1")
            self.assertEqual(first["trigger_source_url"], "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1")
            self.assertEqual(first["query_params"]["companyName"], "广州测试建设有限公司")
            self.assertEqual(first["query_params"]["personName"], "张三")
            self.assertEqual(first["initial_release_evidence_abcd_grade"], "A_STRONG_TIME_OVERLAP_SIGNAL")
            self.assertEqual(first["downstream_release_evidence_abcd_grade"], "PENDING_NOT_EXECUTED")
            self.assertTrue(first["release_evidence_query_region_code"])
            self.assertTrue(first["route_plan"])
            self.assertIn("construction_permit", {source_type for task in tasks for source_type in task["target_source_types"]})
            self.assertIn("completion_filing", {source_type for task in tasks for source_type in task["target_source_types"]})
            self.assertIn("contract_public_info", {source_type for task in tasks for source_type in task["target_source_types"]})
            self.assertTrue((output_root / "guangdong-local-field-query-probe-v1.json").exists())

    def test_release_evidence_adapter_plan_tasks_feed_field_query_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            output_root = root / "out"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=output_root,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["manifest"]["input_mode"], "RELEASE_EVIDENCE_ADAPTER_PLAN_TASKS")
            summary = result["summary"]
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 4)
            self.assertEqual(summary["input_source_kind_counts"]["release_evidence_adapter_plan_task"], 4)
            self.assertEqual(summary["release_evidence_task_count"], 4)
            self.assertEqual(summary["release_evidence_initial_abcd_grade_counts"]["A_STRONG_TIME_OVERLAP_SIGNAL"], 4)
            self.assertEqual(summary["release_evidence_downstream_abcd_grade_counts"]["PENDING_NOT_EXECUTED"], 4)
            self.assertEqual(summary["adapter_result_state_counts"]["NEEDS_BROWSER"], 4)
            tasks = result["manifest"]["field_task_records"]
            self.assertEqual({task["adapter_result_state"] for task in tasks}, {"NEEDS_BROWSER"})
            self.assertIn("construction_permit", {source_type for task in tasks for source_type in task["target_source_types"]})
            self.assertIn("contract_public_info", {source_type for task in tasks for source_type in task["target_source_types"]})
            self.assertIn("completion_filing", {source_type for task in tasks for source_type in task["target_source_types"]})
            self.assertIn("project_manager_change_notice", {source_type for task in tasks for source_type in task["target_source_types"]})
            by_target = {task["release_evidence_target_type"]: task for task in tasks}
            self.assertEqual(by_target["construction_permit"]["source_profile_id"], "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY")
            self.assertEqual(by_target["completion_acceptance"]["source_profile_id"], "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY")
            self.assertEqual(by_target["contract_performance"]["source_profile_id"], "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM")
            self.assertEqual(by_target["project_manager_change_notice"]["source_profile_id"], "GUANGDONG-GDCIC-HOME")
            self.assertEqual(
                _route_adapter_ids(by_target["construction_permit"]),
                {
                    "guangzhou_zfcj_construction_permit_public_api_v1",
                    "guangzhou_zfcj_xyxx_api_query_v1",
                },
            )
            self.assertEqual(
                _route_adapter_ids(by_target["completion_acceptance"]),
                {"guangzhou_zfcj_completion_acceptance_public_api_v1"},
            )
            self.assertIn(
                "guangdong_gdcic_openplatform_public_api_query_v1",
                _route_adapter_ids(by_target["contract_performance"]),
            )
            self.assertIn(
                "guangdong_gdcic_project_manager_change_notice_browser_required_v1",
                _route_adapter_ids(by_target["project_manager_change_notice"]),
            )

    def test_release_evidence_adapter_plan_splits_joint_venture_company_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_release_evidence_adapter_plan(plan_root)
            path = plan_root / "release-evidence-adapter-plan-v1.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            task = payload["manifest"]["release_evidence_adapter_task_records"][1]
            task["candidate_company_name"] = "(主)广州测试建设有限公司;(成)广东联合设计有限公司"
            task["query_params"]["companyName"] = task["candidate_company_name"]
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(
                task["query_params"]["companyVariants"],
                [
                    "(主)广州测试建设有限公司;(成)广东联合设计有限公司",
                    "广州测试建设有限公司",
                    "广东联合设计有限公司",
                ],
            )
            route_company_values = [
                route["params"]["projectName"]
                for route in task["route_plan"]
                if str(route.get("route_id") or "").startswith("gd_gdcic_openplatform_project_by_company")
            ]
            self.assertIn("广州测试建设有限公司", route_company_values)
            self.assertIn("广东联合设计有限公司", route_company_values)

    def test_gdcic_openplatform_contract_release_requires_contract_specific_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_release_evidence_adapter_plan(plan_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                if url.endswith("/openplatform/project/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "1573",
                                    "projectCode": "440100202605190001",
                                    "projectName": "广州测试项目",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/publicityPeriod/listApplyProjectPerson"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "name": "张三",
                                    "post": "项目经理",
                                    "orgName": "广州测试建设有限公司",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["release_evidence_target_type"], "contract_performance")
            self.assertEqual(task["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertEqual(task["field_match_summary"]["source_specific_records"], [])
            self.assertTrue(task["field_match_summary"]["context_source_specific_records"])
            self.assertTrue(task["field_match_summary"]["target_specific_record_required"])

    def test_gdcic_openplatform_contract_release_requires_project_name_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_release_evidence_adapter_plan(plan_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                if url.endswith("/openplatform/projectContract/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "projectName": "广州其他项目",
                                    "contractOrgName": "广州测试建设有限公司",
                                    "contractBeginDate": "2025-08-01",
                                    "contractEndDate": "2026-08-01",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(task["field_match_summary"]["source_specific_records"], [])
            self.assertEqual(
                task["field_match_summary"]["context_source_specific_records"][0]["record_type"],
                "contract_public_record",
            )

    def test_gdcic_openplatform_contract_release_allows_project_code_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_release_evidence_adapter_plan(plan_root)
            path = plan_root / "release-evidence-adapter-plan-v1.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            task = payload["manifest"]["release_evidence_adapter_task_records"][1]
            task["project_id"] = "PROJ-CN-GD-JG2026-11337"
            task["source_profile_id"] = "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"
            task["source_url"] = "https://skypt.gdcic.net/openplatform/"
            task["query_params"]["projectId"] = task["project_id"]
            task["query_params"]["sourceProjectCode"] = (
                "E4401002701502243001 441900029-2025-00741 2605-440100-04-01-000001"
            )
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if url.endswith("/openplatform/projectContract/list") and params.get("projectCode") == "E4401002701502243001":
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "projectCode": "E4401002701502243001",
                                    "projectName": "GDCIC返回名称与公告标题不完全一致",
                                    "contractOrgName": "广州测试建设有限公司",
                                    "contractBeginDate": "2025-08-01",
                                    "contractEndDate": "2026-08-01",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(
                task["query_params"]["projectCodeVariants"],
                [
                    "E4401002701502243001",
                    "441900029-2025-00741",
                    "2605-440100-04-01-000001",
                    "JG2026-11337",
                ],
            )
            self.assertEqual(
                task["query_params"]["gdcicProjectCodeVariants"],
                ["E4401002701502243001", "441900029-2025-00741"],
            )
            self.assertEqual(task["query_params"]["projectCode"], "E4401002701502243001")
            self.assertEqual(task["query_params"]["tradeProjectCode"], "JG2026-11337")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "B_ENHANCEMENT_OFFICIAL_READBACK",
            )
            self.assertEqual(
                task["field_match_summary"]["source_specific_records"][0]["record_type"],
                "contract_public_record",
            )

    def test_release_plan_can_disable_gdcic_project_code_route_for_ygp_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            task = _release_plan_task(
                "REL-YGP-BACKFILL-1",
                "ygp_original_readback_backfill",
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            task.update(
                {
                    "source_profile_id": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                    "source_entry_id": "P13B-YGP-STAGE4-BACKFILL",
                    "local_housing_authority_adapter_region_code": "CN-GD-YGP",
                    "release_evidence_query_region_code": "CN-GD-YGP",
                    "gdcic_project_code_route_allowed": False,
                    "query_params": {
                        "projectId": "PROJ-CN-GD-JG2026-11366",
                        "projectName": "YGP 回灌候选",
                        "projectCodeVariants": ["E4420002712020339001"],
                        "gdcicProjectCodeVariants": [],
                        "ygpProjectCodeVariants": ["E4420002712020339001"],
                        "targetSourceTypes": ["ygp_original_readback_backfill"],
                    },
                }
            )
            _write_release_plan_payload(plan_root, [task])

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                created_at="2026-05-20T00:00:00+08:00",
            )

            field_task = result["manifest"]["field_task_records"][0]
            self.assertEqual(
                field_task["query_params"]["projectCodeVariants"],
                ["E4420002712020339001", "JG2026-11366"],
            )
            self.assertEqual(field_task["query_params"]["gdcicProjectCodeVariants"], [])
            self.assertEqual(field_task["query_params"]["tradeProjectCode"], "JG2026-11366")
            self.assertFalse(field_task["query_params"]["gdcicProjectCodeRouteAllowed"])
            self.assertEqual(field_task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(result["summary"]["adapter_result_state_counts"], {"NEEDS_BROWSER": 1})

    def test_ygp_backfill_live_readback_maps_official_notice_without_gdcic_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            task = _release_plan_task(
                "REL-YGP-BACKFILL-1",
                "ygp_original_readback_backfill",
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            task.update(
                {
                    "source_profile_id": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                    "source_entry_id": "P13B-YGP-STAGE4-BACKFILL",
                    "local_housing_authority_adapter_region_code": "CN-GD-YGP",
                    "release_evidence_query_region_code": "CN-GD-YGP",
                    "gdcic_project_code_route_allowed": False,
                    "source_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/trading-notice/new/detail",
                    "trigger_source_url": "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/trading-notice/new/detail",
                    "query_params": {
                        "projectId": "PROJ-CN-GD-JG2026-11366",
                        "projectName": "YGP 回灌候选",
                        "projectCodeVariants": ["E4420002712020339001", "JG2026-11366"],
                        "gdcicProjectCodeVariants": [],
                        "ygpProjectCodeVariants": ["E4420002712020339001"],
                        "ygpBizCode": "3C52",
                        "ygpSiteCode": "442000",
                        "ygpNoticeId": "notice-1",
                        "ygpNodeId": "node-1",
                        "companyName": "广州市建工设计院有限公司",
                        "targetSourceTypes": ["ygp_original_readback_backfill"],
                    },
                }
            )
            _write_release_plan_payload(plan_root, [task])

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                self.assertIn("ygp.gdzwfw.gov.cn", url)
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {
                        "projectName": "YGP 回灌候选",
                        "projectCode": "E4420002712020339001",
                        "bizCode": "3C52",
                        "siteCode": "442000",
                        "noticeId": "notice-1",
                        "candidate": "广州市建工设计院有限公司",
                    },
                    "text_probe": "YGP 回灌候选 E4420002712020339001 3C52 442000 notice-1 广州市建工设计院有限公司",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            field_task = result["manifest"]["field_task_records"][0]
            self.assertEqual(field_task["field_adapter_status"], "IMPLEMENTED_INLINE:guangdong_ygp_original_readback_backfill_adapter_v1")
            self.assertEqual(field_task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(field_task["field_readback_state"], "YGP_ORIGINAL_NOTICE_READBACK_READY_REVIEW_REQUIRED")
            self.assertEqual(field_task["adapter_result_state"], "MATCHED")
            self.assertEqual(field_task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(field_task["field_match_summary"]["not_gdcic_project_code_route"])
            self.assertEqual(field_task["query_params"]["gdcicProjectCodeVariants"], [])
            self.assertEqual(result["summary"]["adapter_result_state_counts"], {"MATCHED": 1})
            self.assertEqual(result["summary"]["readback_ready_count"], 1)

    def test_ygp_backfill_synthesizes_detail_route_from_runtime_bridge_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            task = _release_plan_task(
                "REL-YGP-BACKFILL-RUNTIME-1",
                "ygp_original_readback_backfill",
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            task.update(
                {
                    "source_profile_id": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                    "source_entry_id": "RUNTIME-BLOCKER-YGP-STAGE4-BACKFILL",
                    "local_housing_authority_adapter_region_code": "CN-GD-YGP",
                    "release_evidence_query_region_code": "CN-GD-YGP",
                    "gdcic_project_code_route_allowed": False,
                    "query_params": {
                        "projectId": "PROJ-CN-GD-JG2026-11111",
                        "projectName": "YGP 运行阻断回灌候选",
                        "projectCodeVariants": ["E4413000835979563001"],
                        "gdcicProjectCodeVariants": [],
                        "ygpProjectCodeVariants": ["E4413000835979563001"],
                        "ygpBizCodeVariants": ["3C52"],
                        "ygpSiteCodeVariants": ["441300"],
                        "ygpNoticeIdVariants": ["notice-runtime-1"],
                        "targetSourceTypes": ["ygp_original_readback_backfill"],
                    },
                }
            )
            _write_release_plan_payload(plan_root, [task])

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                self.assertIn("trading-notice/new/detail", url)
                self.assertEqual(params["projectCode"], "E4413000835979563001")
                self.assertEqual(params["bizCode"], "3C52")
                self.assertEqual(params["siteCode"], "441300")
                self.assertEqual(params["noticeId"], "notice-runtime-1")
                return {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "text_probe": "YGP 运行阻断回灌候选 E4413000835979563001 3C52 441300 notice-runtime-1",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-25T00:00:00+08:00",
            )

            field_task = result["manifest"]["field_task_records"][0]
            self.assertEqual(field_task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(field_task["adapter_result_state"], "MATCHED")
            route = field_task["route_plan"][0]
            self.assertEqual(route["route_id"], "ygp_original_readback_backfill_detail")
            self.assertEqual(route["params"]["projectCode"], "E4413000835979563001")
            self.assertFalse(field_task["query_params"]["gdcicProjectCodeRouteAllowed"])
            self.assertEqual(field_task["query_params"]["gdcicProjectCodeVariants"], [])
            self.assertTrue(field_task["field_match_summary"]["not_gdcic_project_code_route"])
            self.assertFalse(field_task["customer_visible_allowed"])
            self.assertTrue(field_task["field_match_summary"]["query_miss_is_not_clearance"])
            self.assertEqual(result["summary"]["readback_ready_count"], 1)

    def test_p13b_release_evidence_live_readback_grades_enhancement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            p13b_root = root / "p13b"
            _write_p13b_operational_closeout(p13b_root)

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
                                    "sgdw": "广州测试建设有限公司",
                                    "sgxkzh": "440106202605120101",
                                    "pzrq": "2026/5/12 0:00:00",
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
                p13b_operational_closeout_root=p13b_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["initial_release_evidence_abcd_grade"], "A_STRONG_TIME_OVERLAP_SIGNAL")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")

    def test_p13b_release_evidence_live_readback_grades_reverse_and_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            p13b_root = root / "p13b"
            _write_p13b_operational_closeout(p13b_root)

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
                                    "sgdw": "广州测试建设有限公司",
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
                p13b_operational_closeout_root=p13b_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=2,
                http_getter=fake_getter,
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            by_task_id = {
                task["p13b_release_evidence_probe_task_id"]: task
                for task in result["manifest"]["field_task_records"]
            }
            self.assertEqual(
                by_task_id["P13B-RELEASE-PROBE-TASK-2"]["downstream_release_evidence_abcd_grade"],
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            self.assertEqual(by_task_id["P13B-RELEASE-PROBE-TASK-2"]["adapter_result_state"], "MATCHED")

            miss_result = build_guangdong_local_field_query_probe(
                p13b_operational_closeout_root=p13b_root,
                output_root=root / "out-miss",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=lambda _url, _params: {
                    "http_status": 200,
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"currentPage": 1, "totalNum": 0, "data": [], "status": 1},
                    "text_probe": "",
                },
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(miss_result["safe_to_execute"])
            miss_task = miss_result["manifest"]["field_task_records"][0]
            self.assertEqual(miss_task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertEqual(miss_task["adapter_result_state"], "NOT_FOUND")
            self.assertTrue(miss_task["initial_signal_remains_valid_when_downstream_is_d"])

    def test_release_evidence_adapter_result_state_maps_blocked_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=lambda _url, _params: {
                    "http_status": 403,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "Forbidden",
                },
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            first = result["manifest"]["field_task_records"][0]
            self.assertEqual(first["adapter_result_state"], "BLOCKED")
            self.assertIn("guangdong_local_field_query_forbidden_or_login_required", first["blocker_taxonomy"])

    def test_release_evidence_adapter_plan_live_minimum_loop_grades_four_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_release_evidence_adapter_plan(plan_root)

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
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
                                    "sgdw": "广州测试建设有限公司",
                                    "sgxkzh": "440106202605120101",
                                    "pzrq": "2026/5/12 0:00:00",
                                }
                            ],
                            "status": 1,
                        },
                        "text_probe": "",
                    }
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
                                    "sgdw": "广州测试建设有限公司",
                                    "peblrq": "2026/5/13 0:00:00",
                                }
                            ],
                            "status": 1,
                        },
                        "text_probe": "",
                    }
                if url.endswith("/openplatform/project/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "payload": {
                            "rows": [
                                {
                                    "id": "1573",
                                    "projectCode": "440100202605190001",
                                    "projectName": "广州测试项目",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/publicityPeriod/getContract"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "payload": {
                            "rows": [
                                {
                                    "projectName": "广州测试项目",
                                    "contractOrgName": "广州测试建设有限公司",
                                    "contractBeginDate": "2025-08-01",
                                    "contractEndDate": "2026-08-01",
                                }
                            ]
                        },
                    }
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
                    "content_type": "application/json; charset=utf-8",
                    "json_payload": {"currentPage": 1, "totalNum": 0, "data": [], "status": 1},
                    "text_probe": "",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=4,
                http_getter=fake_getter,
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            by_target = {
                task["release_evidence_target_type"]: task
                for task in result["manifest"]["field_task_records"]
            }
            self.assertEqual(by_target["construction_permit"]["adapter_result_state"], "MATCHED")
            self.assertEqual(
                by_target["construction_permit"]["downstream_release_evidence_abcd_grade"],
                "B_ENHANCEMENT_OFFICIAL_READBACK",
            )
            self.assertEqual(by_target["contract_performance"]["adapter_result_state"], "MATCHED")
            self.assertEqual(
                by_target["contract_performance"]["downstream_release_evidence_abcd_grade"],
                "B_ENHANCEMENT_OFFICIAL_READBACK",
            )
            self.assertEqual(by_target["completion_acceptance"]["adapter_result_state"], "MATCHED")
            self.assertEqual(
                by_target["completion_acceptance"]["downstream_release_evidence_abcd_grade"],
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            self.assertEqual(by_target["project_manager_change_notice"]["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(
                by_target["project_manager_change_notice"]["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertIn(
                "guangdong_project_manager_change_notice_requires_browser_or_authorized_runtime",
                by_target["project_manager_change_notice"]["blocker_taxonomy"],
            )

    def test_zhejiang_release_plan_live_uses_structured_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_non_guangdong_release_evidence_adapter_plan(plan_root)
            live_calls: list[str] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                if params.get("_route_group") == "zj_jzsc_structured_public_api":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "code": 200,
                            "data": [
                                {
                                    "PRJNAME": "浙江测试项目中标候选人公示",
                                    "BUILDCORPNAME": "浙江测试建设有限公司",
                                    "BUILDERLICENCENUM": "浙建施许2026001",
                                }
                            ],
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "浙江省建筑市场监管公共服务系统 浙江测试建设有限公司",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-ZJ"], 1)
            self.assertEqual(
                summary["jurisdiction_adapter_resolution_state_counts"]["JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED"],
                1,
            )
            self.assertEqual(summary["no_fallback_to_guangdong_or_guangzhou_task_count"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["zhejiang_jzsc_readback_ready_count"], 1)
            self.assertTrue(any("ProjectInfo/re/GetProjectSGXK" in url for url in live_calls))
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "ZHEJIANG-JZSC-PUBLIC-SERVICE")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:zhejiang_construction_market_public_service_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-ZJ")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["field_readback_state"], "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "zhejiang_construction_market_public_service_query_adapter_v1",
            )

    def test_unsupported_non_guangdong_release_plan_live_requires_region_adapter_without_homepage_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_anhui_release_evidence_adapter_plan(plan_root)
            live_calls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "安徽省建筑市场监管公共服务平台 安徽测试建设有限公司",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["release_evidence_query_region_counts"]["CN-AH"], 1)
            self.assertEqual(result["summary"]["region_adapter_required_count"], 1)
            self.assertEqual(live_calls, [])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_REGION_ADAPTER")
            self.assertEqual(task["field_readback_state"], "FIELD_READBACK_REGION_ADAPTER_REQUIRED")
            self.assertEqual(task["adapter_result_state"], "BLOCKED")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertIn(
                "non_guangdong_release_evidence_requires_jurisdiction_adapter",
                task["blocker_taxonomy"],
            )
            sample = result["manifest"]["stage5_calibration_sample_records"][0]
            self.assertEqual(sample["stage5_calibration_review_family"], "region_source_adapter_required")
            self.assertEqual(
                sample["stage5_calibration_failure_route_targets"],
                ["operator_truth_label_review", "source_adapter"],
            )

    def test_hunan_release_plan_live_uses_public_service_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_hunan_release_evidence_adapter_plan(plan_root)
            live_route_groups: list[str] = []

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_route_groups.append(str(params.get("_route_group") or ""))
                if params.get("_route_group") == "hn_jzsc_public_service_structured_query":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "result": {
                                "records": [
                                    {
                                        "projectName": "湖南测试项目中标候选人公示",
                                        "companyName": "湖南测试建设有限公司",
                                        "projectManagerName": "张三",
                                        "permitNo": "湘建施许2026001",
                                        "permitDate": "2026-05-20",
                                    }
                                ]
                            },
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "湖南省智慧住建云 湖南省建筑市场监管公共服务平台",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-HN"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["hunan_jzsc_readback_ready_count"], 1)
            self.assertIn("hn_jzsc_public_service_structured_query", live_route_groups)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "HUNAN-JZSC-PUBLIC-SERVICE")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:hunan_construction_market_public_service_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-HN")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "hunan_construction_market_public_service_query_adapter_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "construction_permit_public_record")
            self.assertEqual(record["permit_or_record_no"], "湘建施许2026001")

    def test_hunan_project_manager_change_requires_browser_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_hunan_release_evidence_adapter_plan(
                plan_root,
                target_type="project_manager_change_notice",
                grade_on_match="C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            live_calls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                return {"http_status": 200, "content_type": "text/html", "text_probe": ""}

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(live_calls, [])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertIn(
                "hunan_project_manager_change_notice_requires_browser_or_authorized_runtime",
                task["blocker_taxonomy"],
            )
            self.assertIn(
                "hunan_project_manager_change_notice_browser_required_v1",
                _route_adapter_ids(task),
            )

    def test_hunan_homepage_shell_needs_browser_not_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_hunan_release_evidence_adapter_plan(plan_root)

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<html><body>湖南省数字城建档案馆 用户登录 智慧住建云</body></html>",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertTrue(task["field_match_summary"]["browser_or_authorized_runtime_required_before_readback"])
            self.assertIn(
                "hunan_jzsc_public_service_returned_html_shell_without_field_rows",
                task["blocker_taxonomy"],
            )

    def test_henan_release_plan_live_uses_public_service_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_henan_release_evidence_adapter_plan(plan_root)
            live_route_groups: list[str] = []

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_route_groups.append(str(params.get("_route_group") or ""))
                if params.get("_route_group") == "ha_jzsc_public_service_structured_query":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "data": {
                                "records": [
                                    {
                                        "projectName": "河南测试项目中标候选人公示",
                                        "companyName": "河南测试建设有限公司",
                                        "projectManagerName": "张三",
                                        "permitNo": "豫建施许2026001",
                                        "permitDate": "2026-05-20",
                                    }
                                ]
                            },
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "河南省建筑市场监管公共服务平台 建筑工程施工许可证电子证照查询",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-HA"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["henan_jzsc_readback_ready_count"], 1)
            self.assertIn("ha_jzsc_public_service_structured_query", live_route_groups)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "HENAN-JZSC-PUBLIC-SERVICE")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:henan_construction_market_public_service_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-HA")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "henan_construction_market_public_service_query_adapter_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "construction_permit_public_record")
            self.assertEqual(record["permit_or_record_no"], "豫建施许2026001")

    def test_henan_project_manager_change_requires_browser_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_henan_release_evidence_adapter_plan(
                plan_root,
                target_type="project_manager_change_notice",
                grade_on_match="C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            live_calls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                return {"http_status": 200, "content_type": "text/html", "text_probe": ""}

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(live_calls, [])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertIn(
                "henan_project_manager_change_notice_requires_browser_or_authorized_runtime",
                task["blocker_taxonomy"],
            )
            self.assertIn(
                "henan_project_manager_change_notice_browser_required_v1",
                _route_adapter_ids(task),
            )

    def test_henan_html_shell_needs_browser_not_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_henan_release_evidence_adapter_plan(plan_root)

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<html><body>河南省建筑市场监管公共服务平台 电子证照 工程项目数据</body></html>",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertTrue(task["field_match_summary"]["browser_or_authorized_runtime_required_before_readback"])
            self.assertIn(
                "henan_jzsc_public_service_returned_html_shell_without_field_rows",
                task["blocker_taxonomy"],
            )

    def test_sichuan_release_plan_live_uses_project_chain_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_sichuan_release_evidence_adapter_plan(plan_root)
            live_calls: list[str] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                route_group = str(params.get("_route_group") or "")
                if route_group == "sc_jzsc_project_search_api":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "Count": 1,
                            "Data": [
                                {
                                    "dxmbh": "SC-DX-TEST-1",
                                    "XMMC": "四川测试项目中标候选人公示",
                                    "PrjItemName": "四川测试项目中标候选人公示",
                                    "JSDW": "四川测试建设有限公司",
                                    "BH": "510000202605200001",
                                    "XMSDMC": "四川省成都市",
                                }
                            ],
                        },
                        "text_probe": "",
                    }
                if route_group == "sc_jzsc_construction_permit_api":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": [
                            {
                                "XMMC": "四川测试项目中标候选人公示",
                                "GCMC": "四川测试项目",
                                "ContractorCorpName": "四川测试建设有限公司",
                                "XKZBH": "川建施许2026001",
                                "FZRQ": "2026-05-20 00:00:00",
                                "DataLevel": "A",
                            }
                        ],
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "四川省建筑市场监管公共服务平台 四川测试建设有限公司",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-SC"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["sichuan_jzsc_readback_ready_count"], 1)
            self.assertTrue(any("GetPerjectList" in url for url in live_calls))
            self.assertTrue(any("GetProjSgxkzList" in url for url in live_calls))
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "SICHUAN-JZSC-PUBLIC-SERVICE")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:sichuan_construction_market_public_service_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-SC")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "sichuan_construction_market_public_service_query_adapter_v1",
            )

    def test_jiangsu_release_plan_live_uses_integrated_platform_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_jiangsu_release_evidence_adapter_plan(plan_root)
            live_route_groups: list[str] = []

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_route_groups.append(str(params.get("_route_group") or ""))
                if params.get("_route_group") == "js_jzsc_integrated_platform_structured_query":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "data": [
                                {
                                    "projectName": "江苏测试项目中标候选人公示",
                                    "companyName": "江苏测试建设有限公司",
                                    "projectManagerName": "张三",
                                    "permitNo": "苏建施许2026001",
                                    "permitDate": "2026-05-20",
                                }
                            ],
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "江苏省住房和城乡建设厅 江苏省建筑市场监管与诚信管理一体化平台",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-JS"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["jiangsu_jzsc_readback_ready_count"], 1)
            self.assertIn("js_jzsc_integrated_platform_structured_query", live_route_groups)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "JIANGSU-JZSC-INTEGRATED-PLATFORM")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:jiangsu_construction_market_integrated_platform_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-JS")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "jiangsu_construction_market_integrated_platform_query_adapter_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "construction_permit_public_record")
            self.assertEqual(record["permit_or_record_no"], "苏建施许2026001")

    def test_jiangsu_project_manager_change_requires_browser_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_jiangsu_release_evidence_adapter_plan(
                plan_root,
                target_type="project_manager_change_notice",
                grade_on_match="C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            live_calls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                return {"http_status": 200, "content_type": "text/html", "text_probe": ""}

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(live_calls, [])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertIn(
                "jiangsu_project_manager_change_notice_requires_browser_or_authorized_runtime",
                task["blocker_taxonomy"],
            )
            self.assertIn(
                "jiangsu_project_manager_change_notice_browser_required_v1",
                _route_adapter_ids(task),
            )

    def test_hubei_release_plan_live_uses_integrity_platform_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_hubei_release_evidence_adapter_plan(plan_root)
            live_route_groups: list[str] = []

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_route_groups.append(str(params.get("_route_group") or ""))
                if params.get("_route_group") == "hb_jzsc_integrity_platform_structured_query":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "rows": [
                                {
                                    "projectName": "湖北测试项目中标候选人公示",
                                    "companyName": "湖北测试建设有限公司",
                                    "projectManagerName": "张三",
                                    "permitNo": "鄂建施许2026001",
                                    "permitDate": "2026-05-20",
                                }
                            ],
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "湖北省建筑市场监督与诚信一体化平台",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-HB"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["hubei_jzsc_readback_ready_count"], 1)
            self.assertIn("hb_jzsc_integrity_platform_structured_query", live_route_groups)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "HUBEI-JZSC-INTEGRITY-PLATFORM")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:hubei_construction_market_integrity_platform_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-HB")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "hubei_construction_market_integrity_platform_query_adapter_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "construction_permit_public_record")
            self.assertEqual(record["permit_or_record_no"], "鄂建施许2026001")

    def test_hubei_project_manager_change_requires_browser_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_hubei_release_evidence_adapter_plan(
                plan_root,
                target_type="project_manager_change_notice",
                grade_on_match="C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            live_calls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                return {"http_status": 200, "content_type": "text/html", "text_probe": ""}

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(live_calls, [])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertIn(
                "hubei_project_manager_change_notice_requires_browser_or_authorized_runtime",
                task["blocker_taxonomy"],
            )
            self.assertIn(
                "hubei_project_manager_change_notice_browser_required_v1",
                _route_adapter_ids(task),
            )

    def test_shandong_release_plan_live_uses_credit_supervision_adapter_without_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_shandong_release_evidence_adapter_plan(plan_root)
            live_route_groups: list[str] = []

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_route_groups.append(str(params.get("_route_group") or ""))
                if params.get("_route_group") == "sd_jzsc_credit_supervision_structured_query":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {
                            "data": {
                                "records": [
                                    {
                                        "projectName": "山东测试项目中标候选人公示",
                                        "companyName": "山东测试建设有限公司",
                                        "projectManagerName": "张三",
                                        "permitNo": "鲁建施许2026001",
                                        "permitDate": "2026-05-20",
                                    }
                                ]
                            },
                        },
                        "text_probe": "",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "山东省住房城乡建设服务监管与信用信息综合平台",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["release_evidence_query_region_counts"]["CN-SD"], 1)
            self.assertEqual(summary.get("region_adapter_required_count", 0), 0)
            self.assertEqual(summary["shandong_jzsc_readback_ready_count"], 1)
            self.assertIn("sd_jzsc_credit_supervision_structured_query", live_route_groups)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["source_profile_id"], "SHANDONG-JZSC-CREDIT-SUPERVISION-PLATFORM")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_INLINE:shandong_construction_market_credit_supervision_query_adapter_v1",
            )
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-SD")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertEqual(
                task["field_summary"]["source_specific_adapter_id"],
                "shandong_construction_market_credit_supervision_query_adapter_v1",
            )
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "construction_permit_public_record")
            self.assertEqual(record["permit_or_record_no"], "鲁建施许2026001")

    def test_shandong_project_manager_change_requires_browser_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_shandong_release_evidence_adapter_plan(
                plan_root,
                target_type="project_manager_change_notice",
                grade_on_match="C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            live_calls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                live_calls.append(url)
                return {"http_status": 200, "content_type": "text/html", "text_probe": ""}

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(live_calls, [])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertIn(
                "shandong_project_manager_change_notice_requires_browser_or_authorized_runtime",
                task["blocker_taxonomy"],
            )
            self.assertIn(
                "shandong_project_manager_change_notice_browser_required_v1",
                _route_adapter_ids(task),
            )

    def test_shandong_https_blocked_http_homepage_shell_needs_browser_not_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_shandong_release_evidence_adapter_plan(plan_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                if url.startswith("https://zjt.shandong.gov.cn"):
                    raise OSError("certificate hostname mismatch")
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "<html><body>山东省住房和城乡建设厅 政务公开 首页</body></html>",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertTrue(task["field_match_summary"]["browser_or_authorized_runtime_required_before_readback"])
            self.assertIn(
                "shandong_jzsc_credit_supervision_returned_html_shell_without_field_rows",
                task["blocker_taxonomy"],
            )

    def test_zhejiang_empty_structured_readback_is_d_not_homepage_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            _write_non_guangdong_release_evidence_adapter_plan(plan_root)

            def fake_getter(_url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                if params.get("_route_group") == "zj_jzsc_structured_public_api":
                    return {
                        "http_status": 200,
                        "content_type": "application/json; charset=utf-8",
                        "json_payload": {"code": "204", "Message": "暂无数据！", "data": []},
                        "text_probe": "{\"code\":\"204\",\"Message\":\"暂无数据！\",\"data\":[]}",
                    }
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "浙江省建筑市场监管公共服务系统 浙江测试建设有限公司",
                }

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertEqual(task["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertTrue(task["field_match_summary"]["entry_portal_reachability_is_not_field_verification"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])

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
            self.assertEqual(task["adapter_result_state"], "MATCHED")
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

    def test_gdcic_contract_sso_without_public_rows_needs_browser_not_clearance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_root = root / "local"
            _write_local_verification(local_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
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
            self.assertEqual(
                result["summary"]["authorization_readiness_state_counts"],
                {"LOGIN_OR_SSO_REQUIRED": 1},
            )
            self.assertEqual(
                result["summary"]["operator_next_action_counts"],
                {
                    "do_not_treat_http_dynamic_stealthy_as_login_state_replacement": 1,
                    "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1,
                },
            )
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(task["field_summary"]["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertEqual(
                task["field_summary"]["required_runtime_capability"],
                "AUTHORIZED_SESSION_STORAGE_STATE_OR_USER_DATA_DIR",
            )
            self.assertFalse(
                task["field_summary"]["browser_capability_assessment"][
                    "http_dynamic_stealthy_can_replace_login_state"
                ]
            )
            self.assertFalse(task["field_match_summary"]["http_dynamic_stealthy_can_replace_login_state"])
            self.assertTrue(task["field_match_summary"]["login_or_sso_required_before_field_surface"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])
            self.assertIn("gd_gdcic_contract_system_sso_login_required", task["blocker_taxonomy"])
            project_record = result["manifest"]["project_task_records"][0]
            self.assertEqual(
                project_record["authorization_readiness_state_counts"],
                {"LOGIN_OR_SSO_REQUIRED": 1},
            )

    def test_gdcic_browser_authorized_readback_no_longer_required_for_contract_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)
            _write_gdcic_browser_authorized_readback(
                readback_root,
                task_id="REL-TASK-2",
                target_type="contract_performance",
                records=[
                    {
                        "project_name": "广州测试项目",
                        "company_name": "广州测试建设有限公司",
                        "project_manager_name": "张三",
                        "contract_start_date": "2025-08-01",
                        "contract_end_date": "2026-08-01",
                        "contract_status": "履约中",
                    }
                ],
            )

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                gdcic_browser_readback_root=readback_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=_gdcic_sso_empty_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_gdcic_browser_authorized_readback_ready_count"], 0)
            task = result["manifest"]["field_task_records"][0]
            self.assertEqual(task["release_evidence_target_type"], "project_manager_change_notice")
            self.assertNotIn(
                "contract_performance",
                {item["release_evidence_target_type"] for item in result["manifest"]["field_task_records"]},
            )
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertIn(
                "guangdong_project_manager_change_notice_requires_browser_or_authorized_runtime",
                task["blocker_taxonomy"],
            )

    def test_gdcic_browser_authorized_readback_consumes_project_manager_change_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)
            _write_gdcic_browser_authorized_readback(
                readback_root,
                task_id="REL-TASK-4",
                target_type="project_manager_change_notice",
                records=[
                    {
                        "project_name": "广州测试项目",
                        "company_name": "广州测试建设有限公司",
                        "original_project_manager_name": "张三",
                        "new_project_manager_name": "李四",
                        "change_date": "2026-01-15",
                    }
                ],
            )

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                gdcic_browser_readback_root=readback_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=2,
                http_getter=_gdcic_sso_empty_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            by_target = {
                task["release_evidence_target_type"]: task
                for task in result["manifest"]["field_task_records"]
            }
            task = by_target["project_manager_change_notice"]
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
            record = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(record["record_type"], "project_manager_change_browser_authorized_record")
            self.assertEqual(record["original_project_manager_name_probe"], "张三")
            self.assertEqual(record["new_project_manager_name_probe"], "李四")
            self.assertEqual(
                task["field_match_summary"]["authorization_readiness_state"],
                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
            )

    def test_gdcic_browser_authorized_no_record_is_d_not_clearance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)
            _write_gdcic_browser_authorized_readback(
                readback_root,
                task_id="REL-TASK-4",
                target_type="project_manager_change_notice",
                readback_state="NO_FIELD_MATCH_REVIEW_REQUIRED",
                records=[],
            )

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                gdcic_browser_readback_root=readback_root,
                output_root=root / "out",
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=2,
                http_getter=_gdcic_sso_empty_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            by_target = {
                task["release_evidence_target_type"]: task
                for task in result["manifest"]["field_task_records"]
            }
            task = by_target["project_manager_change_notice"]
            self.assertEqual(task["field_query_probe_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertEqual(task["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertTrue(task["initial_signal_remains_valid_when_downstream_is_d"])
            self.assertTrue(task["field_match_summary"]["query_miss_is_not_clearance"])
            self.assertEqual(
                task["field_summary"]["authorization_readiness_state_counts"],
                {"FIELD_SURFACE_REACHED_REVIEW_REQUIRED": 1},
            )

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

    def test_terminal_closeout_marker_suppresses_release_field_query_without_live_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            release_plan_root = root / "release-plan"
            release_plan_root.mkdir(parents=True, exist_ok=True)
            task = _release_plan_task("REL-TERMINAL-NOT-FOUND", "construction_permit", "B_ENHANCEMENT_OFFICIAL_READBACK")
            task["terminal_closeout_markers"] = [
                {
                    "task_family": "release_evidence_query",
                    "marker_state": "NOT_FOUND",
                    "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                }
            ]
            (release_plan_root / "release-evidence-adapter-plan-v1.json").write_text(
                json.dumps(
                    {
                        "manifest": {
                            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
                            "release_evidence_adapter_task_records": [task],
                        },
                        "summary": {"adapter_task_count": 1},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fail_if_called(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                raise AssertionError("terminal closeout marker should suppress live field query")

            result = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=release_plan_root,
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fail_if_called,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 1)
            self.assertEqual(summary["closeout_precedence_suppressed_count"], 1)
            self.assertEqual(summary["runtime_blocker_ledger_count"], 1)
            record = result["manifest"]["field_task_records"][0]
            self.assertTrue(record["closeout_precedence_suppressed"])
            self.assertEqual(record["execution_mode"], "TERMINAL_CLOSEOUT_SUPPRESSED_NO_WORKER_DISPATCH")
            self.assertEqual(record["field_readback_state"], "FIELD_READBACK_SUPPRESSED_BY_TERMINAL_CLOSEOUT")
            self.assertEqual(record["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(record["downstream_release_evidence_abcd_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertEqual(
                record["runtime_blocker_ledger_record"]["blocker_state"],
                "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
            )
            self.assertEqual(summary["stage5_calibration_sample_count"], 1)
            self.assertEqual(summary["stage5_calibration_truth_label_required_count"], 1)
            sample = result["manifest"]["stage5_calibration_sample_records"][0]
            self.assertEqual(sample["project_id"], "PROJ-P13B-1")
            self.assertEqual(sample["stage5_gate_result_state"], "STAGE5_GATE_NOT_RUN_FIELD_QUERY_OUTCOME_READY")
            self.assertEqual(sample["stage5_calibration_review_bucket"], "MISSING_RELEVANT_PUBLIC_READBACK")
            self.assertEqual(sample["stage5_abcd_calibration_bucket"], "C_MISSING_RELEVANT_PUBLIC_READBACK")
            self.assertEqual(
                sample["stage5_calibration_failure_route_targets"],
                ["operator_truth_label_review", "source_adapter"],
            )
            self.assertTrue((root / "out" / "stage5-calibration-sample-table.json").exists())

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


def _write_p13b_operational_closeout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tasks = [
        _p13b_release_task(
            task_id="P13B-RELEASE-PROBE-TASK-1",
            source_profile_id="GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
            source_url="https://zfcj.gz.gov.cn/zfcj/gczlaq/constructionPermitInformation/",
            target_source_types=["construction_permit"],
            subsource_id="gz_zfcj_construction_permit_public_api",
            next_adapter="guangzhou_zfcj_construction_permit_public_api_v1",
        ),
        _p13b_release_task(
            task_id="P13B-RELEASE-PROBE-TASK-2",
            source_profile_id="GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
            source_url="https://zfcj.gz.gov.cn/zfcj/gczlaq/completionAcceptance/",
            target_source_types=["completion_filing"],
            subsource_id="gz_zfcj_completion_acceptance_public_api",
            next_adapter="guangzhou_zfcj_completion_acceptance_public_api_v1",
        ),
        _p13b_release_task(
            task_id="P13B-RELEASE-PROBE-TASK-3",
            source_profile_id="GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
            source_url="https://113.108.173.251:8080/",
            target_source_types=["contract_public_info"],
            subsource_id="gz_zfcj_contract_credit_public_portal",
            next_adapter="guangzhou_zfcj_contract_credit_query_adapter",
        ),
    ]
    payload = {
        "manifest": {
            "manifest_kind": "p13b_operational_closeout_v1_manifest",
            "release_evidence_probe_task_records": tasks,
        },
        "summary": {
            "release_evidence_probe_task_count": len(tasks),
        },
    }
    (root / "p13b-operational-closeout-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_release_evidence_adapter_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tasks = [
        _release_plan_task("REL-TASK-1", "construction_permit", "B_ENHANCEMENT_OFFICIAL_READBACK"),
        _release_plan_task("REL-TASK-2", "contract_performance", "B_ENHANCEMENT_OFFICIAL_READBACK"),
        _release_plan_task("REL-TASK-3", "completion_acceptance", "C_REVERSE_EXPLANATION_OFFICIAL_READBACK"),
        _release_plan_task("REL-TASK-4", "project_manager_change_notice", "C_REVERSE_EXPLANATION_OFFICIAL_READBACK"),
    ]
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": tasks,
        },
        "summary": {
            "adapter_task_count": len(tasks),
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_release_plan_payload(root: Path, tasks: list[Mapping[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": list(tasks),
        },
        "summary": {"adapter_task_count": len(tasks)},
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_gdcic_browser_authorized_readback(
    root: Path,
    *,
    task_id: str,
    target_type: str,
    records: list[Mapping[str, Any]],
    readback_state: str = "BROWSER_AUTHORIZED_READBACK_READY",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    authorization_state = (
        "FIELD_SURFACE_REACHED_REVIEW_REQUIRED"
        if readback_state in {"BROWSER_AUTHORIZED_READBACK_READY", "NO_FIELD_MATCH_REVIEW_REQUIRED"}
        else "LOGIN_OR_SSO_REQUIRED"
        if "LOGIN" in readback_state or "SSO" in readback_state
        else "BROWSER_EXECUTION_BLOCKED_REVIEW_REQUIRED"
    )
    payload = {
        "manifest": {
            "manifest_kind": "gdcic_browser_authorized_readback_v1_manifest",
            "manifest_id": "GDCIC-BROWSER-READBACK-TEST",
            "browser_readback_records": [
                {
                    "release_evidence_adapter_task_id": task_id,
                    "project_id": "PROJ-P13B-1",
                    "project_name": "广州测试项目中标候选人公示",
                    "candidate_company_name": "广州测试建设有限公司",
                    "person_name": "张三",
                    "source_profile_id": "GUANGDONG-GDCIC-HOME",
                    "release_evidence_target_type": target_type,
                    "readback_state": readback_state,
                    "authorization_readiness_state": authorization_state,
                    "source_url": "http://210.76.80.152:8008/JG/home/Indexht",
                    "captured_at": "2026-05-20T00:00:00+08:00",
                    "records": records,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ],
        },
        "summary": {"browser_readback_count": 1},
    }
    (root / "gdcic-browser-authorized-readback-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_non_guangdong_release_evidence_adapter_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-ZJ-TASK-1", "construction_permit", "B_ENHANCEMENT_OFFICIAL_READBACK")
    task.update(
        {
            "project_id": "PROJ-ZJ-P13B-1",
            "project_name": "浙江测试项目中标候选人公示",
            "candidate_company_name": "浙江测试建设有限公司",
            "release_evidence_query_region_code": "CN-ZJ",
            "local_housing_authority_adapter_region_code": "CN-ZJ",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-ZJ",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "ZHEJIANG-JZSC-PUBLIC-SERVICE",
                "next_adapter": "zhejiang_construction_market_public_service_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "ZJ-JZSC-PUBLIC-SERVICE",
            "subsource_id": "",
            "source_profile_id": "ZHEJIANG-JZSC-PUBLIC-SERVICE",
            "source_name": "浙江省建筑市场监管公共服务系统",
            "source_url": "https://jzsc.jst.zj.gov.cn/webserver/app/index.html",
            "official_reference_url": "https://jst.zj.gov.cn/art/2021/9/14/art_1229159345_58927639.html",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "zhejiang_construction_market_public_service_query_adapter",
            "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
            "query_params": {
                "projectId": "PROJ-ZJ-P13B-1",
                "projectName": "浙江测试项目中标候选人公示",
                "companyName": "浙江测试建设有限公司",
                "personName": "张三",
                "keywords": ["浙江测试项目中标候选人公示", "浙江测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-ZJ": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_sichuan_release_evidence_adapter_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-SC-TASK-1", "construction_permit", "B_ENHANCEMENT_OFFICIAL_READBACK")
    task.update(
        {
            "project_id": "PROJ-SC-P13B-1",
            "project_name": "四川测试项目中标候选人公示",
            "candidate_company_name": "四川测试建设有限公司",
            "release_evidence_query_region_code": "CN-SC",
            "local_housing_authority_adapter_region_code": "CN-SC",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-SC",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "SICHUAN-JZSC-PUBLIC-SERVICE",
                "next_adapter": "sichuan_construction_market_public_service_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "SC-JZSC-PUBLIC-SERVICE",
            "subsource_id": "",
            "source_profile_id": "SICHUAN-JZSC-PUBLIC-SERVICE",
            "source_name": "四川省建筑市场监管公共服务平台",
            "source_url": "https://sjfw.scjs.net.cn:8801/xxgx/index.aspx",
            "official_reference_url": "https://jst.sc.gov.cn/scjst/c101428/2020/12/16/524a5e292df5461996313971cdf85f3f.shtml",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "sichuan_construction_market_public_service_query_adapter",
            "runtime_status": "PUBLIC_PROJECT_API_VERIFIED_ADAPTER_MINIMUM_LOOP",
            "query_params": {
                "projectId": "PROJ-SC-P13B-1",
                "projectName": "四川测试项目中标候选人公示",
                "companyName": "四川测试建设有限公司",
                "personName": "张三",
                "keywords": ["四川测试项目中标候选人公示", "四川测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-SC": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_jiangsu_release_evidence_adapter_plan(
    root: Path,
    *,
    target_type: str = "construction_permit",
    grade_on_match: str = "B_ENHANCEMENT_OFFICIAL_READBACK",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-JS-TASK-1", target_type, grade_on_match)
    task.update(
        {
            "project_id": "PROJ-JS-P13B-1",
            "project_name": "江苏测试项目中标候选人公示",
            "candidate_company_name": "江苏测试建设有限公司",
            "release_evidence_query_region_code": "CN-JS",
            "local_housing_authority_adapter_region_code": "CN-JS",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-JS",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "JIANGSU-JZSC-INTEGRATED-PLATFORM",
                "next_adapter": "jiangsu_construction_market_integrated_platform_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "JS-JZSC-INTEGRATED-PLATFORM",
            "subsource_id": "",
            "source_profile_id": "JIANGSU-JZSC-INTEGRATED-PLATFORM",
            "source_name": "江苏省建筑市场监管与诚信管理一体化平台",
            "source_url": "https://jsszfhcxjst.jiangsu.gov.cn/",
            "official_reference_url": "https://jsszfhcxjst.jiangsu.gov.cn/art/2025/2/20/art_49384_11496246.html",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "jiangsu_construction_market_integrated_platform_query_adapter",
            "runtime_status": "OFFICIAL_PLATFORM_REFERENCED_STRUCTURED_READBACK_MINIMUM_LOOP",
            "query_params": {
                "projectId": "PROJ-JS-P13B-1",
                "projectName": "江苏测试项目中标候选人公示",
                "companyName": "江苏测试建设有限公司",
                "personName": "张三",
                "keywords": ["江苏测试项目中标候选人公示", "江苏测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-JS": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_hubei_release_evidence_adapter_plan(
    root: Path,
    *,
    target_type: str = "construction_permit",
    grade_on_match: str = "B_ENHANCEMENT_OFFICIAL_READBACK",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-HB-TASK-1", target_type, grade_on_match)
    task.update(
        {
            "project_id": "PROJ-HB-P13B-1",
            "project_name": "湖北测试项目中标候选人公示",
            "candidate_company_name": "湖北测试建设有限公司",
            "release_evidence_query_region_code": "CN-HB",
            "local_housing_authority_adapter_region_code": "CN-HB",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-HB",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "HUBEI-JZSC-INTEGRITY-PLATFORM",
                "next_adapter": "hubei_construction_market_integrity_platform_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "HB-JZSC-INTEGRITY-PLATFORM",
            "subsource_id": "",
            "source_profile_id": "HUBEI-JZSC-INTEGRITY-PLATFORM",
            "source_name": "湖北省建筑市场监督与诚信一体化平台",
            "source_url": "https://hbjz.hbcic.net.cn/",
            "official_reference_url": "https://hbjz.hbcic.net.cn/",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "hubei_construction_market_integrity_platform_query_adapter",
            "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
            "query_params": {
                "projectId": "PROJ-HB-P13B-1",
                "projectName": "湖北测试项目中标候选人公示",
                "companyName": "湖北测试建设有限公司",
                "personName": "张三",
                "keywords": ["湖北测试项目中标候选人公示", "湖北测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-HB": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_shandong_release_evidence_adapter_plan(
    root: Path,
    *,
    target_type: str = "construction_permit",
    grade_on_match: str = "B_ENHANCEMENT_OFFICIAL_READBACK",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-SD-TASK-1", target_type, grade_on_match)
    task.update(
        {
            "project_id": "PROJ-SD-P13B-1",
            "project_name": "山东测试项目中标候选人公示",
            "candidate_company_name": "山东测试建设有限公司",
            "release_evidence_query_region_code": "CN-SD",
            "local_housing_authority_adapter_region_code": "CN-SD",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-SD",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "SHANDONG-JZSC-CREDIT-SUPERVISION-PLATFORM",
                "next_adapter": "shandong_construction_market_credit_supervision_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "SD-JZSC-CREDIT-SUPERVISION-PLATFORM",
            "subsource_id": "",
            "source_profile_id": "SHANDONG-JZSC-CREDIT-SUPERVISION-PLATFORM",
            "source_name": "山东省住房城乡建设服务监管与信用信息综合平台",
            "source_url": "https://zjt.shandong.gov.cn/",
            "official_reference_url": "https://zwfwzx.jining.gov.cn/art/2022/5/26/art_32745_2707826.html",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "shandong_construction_market_credit_supervision_query_adapter",
            "runtime_status": "SOURCE_ANALYSIS_REQUIRED_ADAPTER_PENDING",
            "query_params": {
                "projectId": "PROJ-SD-P13B-1",
                "projectName": "山东测试项目中标候选人公示",
                "companyName": "山东测试建设有限公司",
                "personName": "张三",
                "keywords": ["山东测试项目中标候选人公示", "山东测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-SD": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_hunan_release_evidence_adapter_plan(
    root: Path,
    *,
    target_type: str = "construction_permit",
    grade_on_match: str = "B_ENHANCEMENT_OFFICIAL_READBACK",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-HN-TASK-1", target_type, grade_on_match)
    task.update(
        {
            "project_id": "PROJ-HN-P13B-1",
            "project_name": "湖南测试项目中标候选人公示",
            "candidate_company_name": "湖南测试建设有限公司",
            "release_evidence_query_region_code": "CN-HN",
            "local_housing_authority_adapter_region_code": "CN-HN",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-HN",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "HUNAN-JZSC-PUBLIC-SERVICE",
                "next_adapter": "hunan_construction_market_public_service_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "HN-JZSC-PUBLIC-SERVICE",
            "subsource_id": "",
            "source_profile_id": "HUNAN-JZSC-PUBLIC-SERVICE",
            "source_name": "湖南省建筑市场监管公共服务平台 / 智慧住建云",
            "source_url": "https://www.hunanjs.gov.cn/",
            "official_reference_url": "https://zjt.hunan.gov.cn/xxgk/xinxigongkaimulu/tzgg/tzgg2jzgl/201906/t20190614_5357245.html",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "hunan_construction_market_public_service_query_adapter",
            "runtime_status": "OFFICIAL_PLATFORM_REFERENCED_STRUCTURED_READBACK_MINIMUM_LOOP",
            "query_params": {
                "projectId": "PROJ-HN-P13B-1",
                "projectName": "湖南测试项目中标候选人公示",
                "companyName": "湖南测试建设有限公司",
                "personName": "张三",
                "keywords": ["湖南测试项目中标候选人公示", "湖南测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-HN": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_henan_release_evidence_adapter_plan(
    root: Path,
    *,
    target_type: str = "construction_permit",
    grade_on_match: str = "B_ENHANCEMENT_OFFICIAL_READBACK",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-HA-TASK-1", target_type, grade_on_match)
    task.update(
        {
            "project_id": "PROJ-HA-P13B-1",
            "project_name": "河南测试项目中标候选人公示",
            "candidate_company_name": "河南测试建设有限公司",
            "release_evidence_query_region_code": "CN-HA",
            "local_housing_authority_adapter_region_code": "CN-HA",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-HA",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "HENAN-JZSC-PUBLIC-SERVICE",
                "next_adapter": "henan_construction_market_public_service_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "HA-JZSC-PUBLIC-SERVICE",
            "subsource_id": "",
            "source_profile_id": "HENAN-JZSC-PUBLIC-SERVICE",
            "source_name": "河南省建筑市场监管公共服务平台",
            "source_url": "https://hngcjs.hnjs.henan.gov.cn/site/",
            "official_reference_url": "https://hngcjs.hnjs.henan.gov.cn/site/",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "henan_construction_market_public_service_query_adapter",
            "runtime_status": "OFFICIAL_PLATFORM_REFERENCED_STRUCTURED_READBACK_MINIMUM_LOOP",
            "query_params": {
                "projectId": "PROJ-HA-P13B-1",
                "projectName": "河南测试项目中标候选人公示",
                "companyName": "河南测试建设有限公司",
                "personName": "张三",
                "keywords": ["河南测试项目中标候选人公示", "河南测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-HA": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_anhui_release_evidence_adapter_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = _release_plan_task("REL-AH-TASK-1", "construction_permit", "B_ENHANCEMENT_OFFICIAL_READBACK")
    task.update(
        {
            "project_id": "PROJ-AH-P13B-1",
            "project_name": "安徽测试项目中标候选人公示",
            "candidate_company_name": "安徽测试建设有限公司",
            "release_evidence_query_region_code": "CN-AH",
            "local_housing_authority_adapter_region_code": "CN-AH",
            "non_guangdong_release_adapter_rule": (
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
            ),
            "jurisdiction_adapter_resolution_state": "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED",
            "jurisdiction_local_housing_adapter": {
                "region_code": "CN-AH",
                "source_selection_scope": "HISTORICAL_PROJECT_JURISDICTION",
                "source_profile_id": "ANHUI-JZSC-PUBLIC-SERVICE",
                "next_adapter": "anhui_construction_market_public_service_query_adapter",
                "no_fallback_to_guangdong_or_guangzhou": True,
            },
            "no_fallback_to_guangdong_or_guangzhou": True,
            "source_entry_id": "AH-JZSC-PUBLIC-SERVICE",
            "subsource_id": "",
            "source_profile_id": "ANHUI-JZSC-PUBLIC-SERVICE",
            "source_name": "安徽省建筑市场监管公共服务平台",
            "source_url": "https://dohurd.ah.gov.cn/",
            "official_reference_url": "https://dohurd.ah.gov.cn/",
            "source_family": "regional_construction_market_public_service",
            "next_adapter": "anhui_construction_market_public_service_query_adapter",
            "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
            "query_params": {
                "projectId": "PROJ-AH-P13B-1",
                "projectName": "安徽测试项目中标候选人公示",
                "companyName": "安徽测试建设有限公司",
                "personName": "张三",
                "keywords": ["安徽测试项目中标候选人公示", "安徽测试建设有限公司", "张三"],
            },
        }
    )
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "release_evidence_adapter_task_records": [task],
        },
        "summary": {
            "adapter_task_count": 1,
            "local_housing_region_counts": {"CN-AH": 1},
        },
    }
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _release_plan_task(task_id: str, target_type: str, grade_on_match: str) -> dict[str, Any]:
    return {
        "release_evidence_adapter_task_id": task_id,
        "source_release_evidence_probe_task_id": "P13B-RELEASE-PROBE-TASK-1",
        "source_release_evidence_probe_plan_id": "P13B-RELEASE-PROBE-PLAN-1",
        "project_id": "PROJ-P13B-1",
        "project_name": "广州测试项目中标候选人公示",
        "candidate_company_name": "广州测试建设有限公司",
        "matched_person_names": ["张三"],
        "release_evidence_target_type": target_type,
        "release_evidence_grade_on_match": grade_on_match,
        "initial_release_evidence_abcd_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
        "release_evidence_query_region_code": "CN-GD",
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "local_housing_authority_adapter_scope": "HISTORICAL_PROJECT_JURISDICTION",
        "local_housing_authority_adapter_region_code": "CN-GD",
        "source_entry_id": "GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
        "subsource_id": "gz_zfcj_release_evidence_public_api",
        "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
        "source_name": "广州住建公开源",
        "source_url": "https://zfcj.gz.gov.cn/zfcj/xyxx/",
        "source_family": "guangzhou_local_housing_public_source",
        "trigger_source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
        "query_params": {
            "projectId": "PROJ-P13B-1",
            "projectName": "广州测试项目中标候选人公示",
            "companyName": "广州测试建设有限公司",
            "personName": "张三",
            "keywords": ["广州测试项目中标候选人公示", "广州测试建设有限公司", "张三"],
        },
        "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _route_adapter_ids(task: Mapping[str, Any]) -> set[str]:
    return {
        str(route.get("source_specific_adapter_id") or "")
        for route in task.get("route_plan", [])
        if str(route.get("source_specific_adapter_id") or "")
    }


def _gdcic_sso_empty_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
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


def _p13b_release_task(
    *,
    task_id: str,
    source_profile_id: str,
    source_url: str,
    target_source_types: list[str],
    subsource_id: str,
    next_adapter: str,
) -> dict[str, Any]:
    return {
        "release_evidence_probe_task_id": task_id,
        "release_evidence_probe_plan_id": "P13B-RELEASE-PROBE-PLAN-1",
        "release_evidence_trigger_id": "P13B-RELEASE-TRIGGER-1",
        "source_stage": "DATA_GGZY_BID_SHOW",
        "project_id": "PROJ-P13B-1",
        "project_name": "广州测试项目中标候选人公示",
        "city_code": "440100",
        "region_code": "CN-GD",
        "candidate_company_name": "广州测试建设有限公司",
        "matched_person_names": ["张三"],
        "trigger_source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
        "extracted_period_text": "365日历天",
        "extracted_award_date": "2026年05月01日",
        "time_window_review_state": "TIME_WINDOW_OVERLAP_REVIEW",
        "estimated_performance_end_date": "2027-05-01",
        "historical_project_area_code": "广州市",
        "historical_project_region_code": "CN-GD",
        "release_evidence_query_region_code": "CN-GD",
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "source_granularity": "verified_public_subsource" if subsource_id else "source_entry",
        "source_entry_id": "GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
        "subsource_id": subsource_id,
        "source_profile_id": source_profile_id,
        "source_name": "P13B测试源",
        "source_url": source_url,
        "source_family": "test_release_evidence_public_source",
        "matched_target_source_types": target_source_types,
        "source_target_source_types": target_source_types,
        "initial_release_evidence_abcd_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
        "initial_release_evidence_abcd_grade_basis": [
            "same_person_company_time_window_overlap_from_data_ggzy_or_targeted_original_notice"
        ],
        "downstream_probe_role": "enhancement_or_reverse_explanation_not_prerequisite_for_initial_signal",
        "downstream_possible_release_evidence_abcd_grades": [
            "B_ENHANCEMENT_OFFICIAL_READBACK",
            "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            "D_INSUFFICIENT_OR_BLOCKED_READBACK",
        ],
        "query_params": {
            "projectId": "PROJ-P13B-1",
            "projectName": "广州测试项目中标候选人公示",
            "candidateCompanyName": "广州测试建设有限公司",
            "projectManagerName": "张三",
            "targetSourceTypes": target_source_types,
            "triggerSourceUrl": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
            "keywords": ["广州测试项目中标候选人公示", "广州测试建设有限公司", "张三"],
        },
        "runtime_status": "PUBLIC_API_ENDPOINT_VERIFIED_PROJECT_QUERY_AVAILABLE",
        "next_adapter": next_adapter,
        "task_state": "PLAN_ONLY_NOT_EXECUTED",
        "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        "readback_ready": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


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
