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
            self.assertEqual(summary["guangdong_local_field_query_task_count"], 3)
            self.assertEqual(summary["delegated_task_count"], 1)
            self.assertEqual(summary["field_query_probe_state_counts"]["PLAN_ONLY_NOT_EXECUTED"], 2)
            delegated = result["manifest"]["field_task_records"][0]
            self.assertEqual(delegated["field_query_probe_state"], "DELEGATED_TO_SEPARATE_FIELD_ADAPTER")
            self.assertEqual(delegated["delegated_adapter_id"], "guangdong_gdcic_query_probe_v1")
            pending = result["manifest"]["field_task_records"][1]
            self.assertTrue(pending["route_plan"])
            self.assertEqual(pending["field_readback_state"], "FIELD_READBACK_NOT_RUN")
            text = json.dumps(result, ensure_ascii=False)
            for term in ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人"):
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


if __name__ == "__main__":
    unittest.main()
