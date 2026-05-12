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
