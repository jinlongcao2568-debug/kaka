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

from storage.guangdong_gdcic_query_probe import build_guangdong_gdcic_query_probe  # noqa: E402


class GuangdongGdcicQueryProbeTests(unittest.TestCase):
    def test_plan_only_builds_gdcic_tasks_from_active_conflict_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=12)

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["source_profile_id"], "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM")
            self.assertEqual(summary["gdcic_query_probe_task_count"], 12)
            self.assertEqual(summary["gdcic_readback_ready_count"], 0)
            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(task["query_probe_state"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(task["source_profile_id"], "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM")
            self.assertEqual(task["source_url"], "https://skypt.gdcic.net/openplatform/")
            self.assertEqual(task["query_params"]["personName"], "张三01")
            self.assertIn("construction_permit", task["target_source_types"])
            self.assertTrue(result["manifest"]["manual_check_table"])
            text = json.dumps(result, ensure_ascii=False)
            for term in ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立"):
                self.assertNotIn(term, text)
            self.assertTrue((root / "out" / "guangdong-gdcic-query-probe-v1.json").exists())

    def test_live_fake_getter_can_generate_public_source_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=1)
            requested_urls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested_urls.append(url)
                if url.endswith("/openplatform/personIntoGd/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "projectName": "广州测试项目",
                                    "entName": "广州测试建设有限公司01",
                                    "name": "张三01",
                                    "idCard": "HASH-ZHANGSAN-01",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/personCertReg/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "name": "张三01",
                                    "entName": "广州测试建设有限公司01",
                                    "certNum": "粤144202020210001",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                enable_live_public_query=True,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "LIVE_PUBLIC_QUERY_ATTEMPTED")
            self.assertEqual(result["summary"]["gdcic_readback_ready_count"], 1)
            self.assertEqual(result["summary"]["gdcic_person_directory_readback_ready_count"], 1)
            self.assertEqual(result["summary"]["gdcic_certificate_route_readback_ready_count"], 1)
            self.assertEqual(result["summary"]["gdcic_certificate_field_candidate_count"], 1)
            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(task["query_probe_state"], "READBACK_READY_PUBLIC_SOURCE")
            self.assertGreaterEqual(task["field_summary"]["record_count"], 2)
            self.assertEqual(task["limited_readback"]["sample_person_names"], ["张三01"])
            self.assertIn("person_into_gd_by_name_company", task["limited_readback"]["readback_route_ids"])
            self.assertIn("person_cert_reg_by_id_card", task["limited_readback"]["readback_route_ids"])
            self.assertTrue(any(url.endswith("/openplatform/personInGd/list") for url in requested_urls))
            self.assertTrue(any(url.endswith("/openplatform/personIntoGd/list") for url in requested_urls))
            self.assertTrue(any(url.endswith("/openplatform/personCertReg/list") for url in requested_urls))

    def test_live_fake_getter_classifies_blockers_and_review_states(self) -> None:
        cases = [
            (
                {"http_status": 403, "content_type": "text/html", "payload": {}},
                "FAIL_CLOSED_FORBIDDEN",
                "gdcic_http_403",
            ),
            (
                {"http_status": 200, "content_type": "text/html", "text_probe": "请完成验证码验证"},
                "FAIL_CLOSED_CAPTCHA_REQUIRED",
                "gdcic_captcha_required",
            ),
            (
                {"http_status": 200, "content_type": "application/json", "payload": {"records": []}},
                "REVIEW_REQUIRED",
                "gdcic_public_query_empty_review",
            ),
            (
                {"http_status": 200, "content_type": "application/json", "payload": {"records": [{"unknown": "x"}]}},
                "REVIEW_REQUIRED",
                "gdcic_field_summary_missing",
            ),
        ]
        for response, expected_state, expected_taxonomy in cases:
            with self.subTest(expected_state=expected_state):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    root = Path(tmp_dir)
                    _write_active_conflict_probe(root / "active", task_count=1)

                    result = build_guangdong_gdcic_query_probe(
                        active_conflict_root=root / "active",
                        output_root=root / "out",
                        enable_live_public_query=True,
                        http_getter=lambda _url, _params, response=response: response,
                        created_at="2026-05-12T00:00:00+08:00",
                    )

                    task = result["manifest"]["query_task_records"][0]
                    self.assertEqual(task["query_probe_state"], expected_state)
                    self.assertIn(expected_taxonomy, task["blocker_taxonomy"])
                    text = json.dumps(result, ensure_ascii=False)
                    for term in ("无在建", "无冲突"):
                        self.assertNotIn(term, text)

    def test_project_lookup_triggers_publicity_period_followups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=1)
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
                                    "projectName": "广州测试项目",
                                    "certNum": "441900202206061001",
                                    "name": "张三01",
                                    "post": "项目经理",
                                    "regCertNum": "粤144202020210001",
                                    "orgName": "广州测试建设有限公司01",
                                    "idNum": "44010119900101567X",
                                }
                            ]
                        },
                    }
                if url.endswith("/openplatform/publicityPeriod/getConstructPermitInfo"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "data": {
                                "projectName": "广州测试项目",
                                "permitCode": "441900202206061001",
                                "contractBeginDate": "2025-01-01",
                                "contractEndDate": "2026-01-01",
                            }
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                enable_live_public_query=True,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(task["query_probe_state"], "READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(result["summary"]["gdcic_publicity_period_readback_ready_count"], 1)
            self.assertIn("441900202206061001", task["field_summary"]["sample_permit_codes"])
            self.assertIn("粤144202020210001", task["field_summary"]["sample_certificate_nos"])
            self.assertTrue(
                any(
                    str(record.get("id_card_sha256_probe") or "").startswith("sha256:")
                    and record.get("id_card_redacted") is True
                    for attempt in task["route_attempts"]
                    for record in attempt.get("sample_records", [])
                )
            )
            self.assertNotIn("44010119900101567X", json.dumps(task, ensure_ascii=False))
            attempts = task["route_attempts"]
            self.assertTrue(
                any(
                    attempt["route_id"] == "publicity_period_contract_by_project_id"
                    and attempt["method"] == "POST"
                    and attempt["params"] == {"id": "1573"}
                    for attempt in attempts
                )
            )
            self.assertTrue(
                any(
                    url.endswith("/openplatform/publicityPeriod/listApplyProjectPerson")
                    and params.get("id") == "1573"
                    for url, params in requested
                )
            )

    def test_project_title_variants_can_trigger_publicity_period_followups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            active_root = root / "active"
            _write_active_conflict_probe(active_root, task_count=1)
            active_path = active_root / "guangzhou-active-conflict-probe-v1.json"
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            payload["manifest"]["task_records"][0]["project_name"] = (
                "广州科玛生物科技有限公司日用品、化妆品、药品及食品生产建设项目"
            )
            active_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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
                                    "regCertNum": "粤1332006200810171",
                                    "certNum": "441900202206061001",
                                    "orgName": "东莞市建工集团有限公司",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=active_root,
                output_root=root / "out",
                enable_live_public_query=True,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            task = result["manifest"]["query_task_records"][0]
            self.assertIn("广州科玛生物科技有限公司日用品", task["query_params"]["projectNameVariants"])
            self.assertEqual(result["summary"]["gdcic_publicity_period_readback_ready_count"], 1)
            self.assertIn("王先耀", task["field_summary"]["sample_person_names"])
            self.assertIn("粤1332006200810171", task["field_summary"]["sample_certificate_nos"])
            self.assertTrue(
                any(
                    url.endswith("/openplatform/project/list")
                    and params.get("projectName") == "广州科玛生物科技有限公司日用品"
                    for url, params in requested
                )
            )

    def test_project_title_variants_strip_service_suffix_for_project_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            active_root = root / "active"
            _write_active_conflict_probe(active_root, task_count=1)
            active_path = active_root / "guangzhou-active-conflict-probe-v1.json"
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            payload["manifest"]["task_records"][0]["project_name"] = (
                "白云湖街城市更新片区周边基础设施配套建设工程监理"
            )
            active_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            requested: list[tuple[str, Mapping[str, Any]]] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested.append((url, dict(params)))
                if (
                    url.endswith("/openplatform/project/list")
                    and params.get("projectName") == "白云湖街城市更新片区周边基础设施配套建设工程"
                ):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "id": "9917",
                                    "projectCode": "440100202605200001",
                                    "projectName": "白云湖街城市更新片区周边基础设施配套建设工程",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=active_root,
                output_root=root / "out",
                enable_live_public_query=True,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            task = result["manifest"]["query_task_records"][0]
            self.assertIn("白云湖街城市更新片区周边基础设施配套建设工程", task["query_params"]["projectNameVariants"])
            self.assertTrue(
                any(
                    url.endswith("/openplatform/project/list")
                    and params.get("projectName") == "白云湖街城市更新片区周边基础设施配套建设工程"
                    for url, params in requested
                )
            )

    def test_project_code_variants_trigger_project_code_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            active_root = root / "active"
            _write_active_conflict_probe(active_root, task_count=1)
            active_path = active_root / "guangzhou-active-conflict-probe-v1.json"
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            payload["manifest"]["task_records"][0]["source_project_code"] = (
                "JG2026-10815 E4401002701502243001 441900029-2025-00741 "
                "2605-440100-04-01-000001"
            )
            active_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            requested: list[tuple[str, Mapping[str, Any]]] = []

            def fake_getter(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested.append((url, dict(params)))
                if url.endswith("/openplatform/projectContract/list") and params.get("projectCode") == "E4401002701502243001":
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "projectCode": "E4401002701502243001",
                                    "projectName": "广州测试项目合同",
                                    "contractOrgName": "广州测试建设有限公司01",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=active_root,
                output_root=root / "out",
                enable_live_public_query=True,
                http_getter=fake_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(
                task["query_params"]["projectCodeVariants"],
                [
                    "JG2026-10815",
                    "E4401002701502243001",
                    "441900029-2025-00741",
                    "2605-440100-04-01-000001",
                ],
            )
            self.assertEqual(
                task["query_params"]["gdcicProjectCodeVariants"],
                ["E4401002701502243001", "441900029-2025-00741"],
            )
            self.assertEqual(task["query_params"]["projectCode"], "E4401002701502243001")
            self.assertEqual(task["query_params"]["tradeProjectCode"], "JG2026-10815")
            self.assertTrue(
                any(
                    url.endswith("/openplatform/project/list")
                    and params.get("projectCode") == "E4401002701502243001"
                    for url, params in requested
                )
            )
            self.assertTrue(
                any(
                    url.endswith("/openplatform/projectContract/list")
                    and params.get("projectCode") == "E4401002701502243001"
                    for url, params in requested
                )
            )
            self.assertFalse(
                any(params.get("projectCode") == "JG2026-10815" for _url, params in requested)
            )
            self.assertFalse(
                any(params.get("projectCode") == "2605-440100-04-01-000001" for _url, params in requested)
            )

    def test_masked_id_card_values_do_not_trigger_followup_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=1)
            requested_urls: list[str] = []

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                requested_urls.append(url)
                if url.endswith("/openplatform/personIntoGd/list"):
                    return {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload": {
                            "rows": [
                                {
                                    "projectName": "广州测试项目",
                                    "entName": "广州测试建设有限公司01",
                                    "name": "张三01",
                                    "idNum": "**190019**********",
                                }
                            ]
                        },
                    }
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": []},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                enable_live_public_query=True,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["gdcic_readback_ready_count"], 1)
            self.assertFalse(any("getByIdNum" in url for url in requested_urls))
            self.assertFalse(any("personCertReg/list" in url for url in requested_urls))

    def test_live_query_can_defer_tasks_by_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=3)
            call_count = 0

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                nonlocal call_count
                call_count += 1
                return {
                    "http_status": 200,
                    "content_type": "application/json",
                    "payload": {"rows": [{"name": "张三01", "entName": "广州测试建设有限公司01"}]},
                }

            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            tasks = result["manifest"]["query_task_records"]
            self.assertGreater(call_count, 0)
            self.assertEqual(tasks[0]["query_probe_state"], "READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(tasks[1]["query_probe_state"], "LIVE_PUBLIC_QUERY_DEFERRED_BY_LIMIT")
            self.assertIn("gdcic_live_query_deferred_by_limit", tasks[1]["blocker_taxonomy"])

    def test_missing_active_conflict_probe_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangdong_gdcic_query_probe(
                active_conflict_root=root / "missing",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("active_conflict_probe_missing", result["blocking_reasons"])
            self.assertEqual(result["summary"]["probe_state"], "INPUT_BLOCKED")


def _write_active_conflict_probe(root: Path, *, task_count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tasks = []
    for index in range(1, task_count + 1):
        tasks.append(
            {
                "task_id": f"GZ-ACTIVE-CONFLICT-TASK-{index:02d}",
                "project_id": "PROJ-CN-GD-JG2026-10815",
                "project_name": "广州测试项目",
                "candidate_group_id": f"G{index:02d}",
                "candidate_group_order": str(index),
                "responsible_person_name": f"张三{index:02d}",
                "candidate_group_members": [f"广州测试建设有限公司{index:02d}", f"广州联合成员有限公司{index:02d}"],
                "matched_company_names": [f"广州测试建设有限公司{index:02d}"],
                "company_query_variants": [f"广州测试建设有限公司{index:02d}", f"广州联合成员有限公司{index:02d}"],
                "certificate_no": f"粤14420202021{index:04d}",
                "query_keywords": [
                    f"广州测试建设有限公司{index:02d} 张三{index:02d}",
                    f"张三{index:02d}",
                    "广州测试项目",
                ],
                "source_entries": [
                    {
                        "entry_id": "GD-GDCIC-SKYPT-PROJECT",
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "source_name": "广东建设信息网 / 三库一平台项目信息",
                        "source_url": "https://skypt.gdcic.net/openplatform/",
                        "target_source_types": [
                            "construction_permit",
                            "contract_public_info",
                            "completion_filing",
                            "personnel_public_record",
                        ],
                        "query_keys": [
                            "project_name",
                            "candidate_company",
                            "project_manager_name",
                            "project_manager_certificate_no",
                        ],
                        "runtime_status": "PUBLIC_API_ENDPOINT_VERIFIED_PROJECT_QUERY_AVAILABLE",
                        "next_adapter": "guangdong_gdcic_openplatform_public_api_query",
                    },
                    {
                        "entry_id": "GD-CREDIT-GD",
                        "source_profile_id": "GUANGDONG-CREDIT-GD-HOME",
                        "source_name": "信用广东",
                        "source_url": "https://credit.gd.gov.cn/",
                    },
                ],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_active_conflict_probe_v1_manifest",
            "task_records": tasks,
            "project_task_records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "广州测试项目",
                    "task_ids": [task["task_id"] for task in tasks],
                    "task_count": len(tasks),
                }
            ],
            "summary": {"active_conflict_probe_task_count": len(tasks), "probe_state": "READY"},
        }
    }
    (root / "guangzhou-active-conflict-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
