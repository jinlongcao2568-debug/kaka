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

from storage.gdcic_browser_authorized_readback import (  # noqa: E402
    build_gdcic_browser_authorized_readback,
)
from storage.guangdong_local_field_query_probe import (  # noqa: E402
    build_guangdong_local_field_query_probe,
)


class GDCICBrowserAuthorizedReadbackTests(unittest.TestCase):
    def test_plan_only_builds_gdcic_contract_and_project_manager_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            out_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=out_root,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["gdcic_browser_readback_task_count"], 2)
            self.assertEqual(summary["gdcic_browser_readback_record_count"], 0)
            self.assertEqual(summary["gdcic_authorized_session_overall_state"], "NOT_ATTEMPTED_PLAN_ONLY")
            tasks = result["manifest"]["browser_readback_task_records"]
            self.assertEqual(
                {task["release_evidence_target_type"] for task in tasks},
                {"contract_performance", "project_manager_change_notice"},
            )
            self.assertTrue((out_root / "gdcic-browser-authorized-readback-v1.json").exists())

    def test_live_fake_runner_ready_artifact_flows_into_local_field_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            field_root = root / "field"
            _write_release_evidence_adapter_plan(plan_root)

            readback = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_contract_text_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(readback["safe_to_execute"])
            self.assertEqual(readback["summary"]["gdcic_browser_readback_ready_count"], 1)
            self.assertEqual(
                readback["summary"]["gdcic_authorized_session_overall_state"],
                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
            )
            readback_record = readback["manifest"]["browser_readback_records"][0]
            self.assertEqual(
                readback_record["authorization_readiness_state"],
                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
            )
            self.assertEqual(readback_record["field_surface_state"], "TARGET_FIELD_MATCHED_REVIEW_REQUIRED")
            field = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                gdcic_browser_readback_root=readback_root,
                output_root=field_root,
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=_gdcic_sso_empty_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(field["safe_to_execute"])
            task = field["manifest"]["field_task_records"][0]
            self.assertEqual(task["release_evidence_target_type"], "contract_performance")
            self.assertEqual(task["field_query_probe_state"], "FIELD_READBACK_READY_PUBLIC_SOURCE")
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "B_ENHANCEMENT_OFFICIAL_READBACK",
            )
            self.assertTrue(task["field_match_summary"]["browser_authorized_readback_consumed"])
            self.assertEqual(
                task["field_summary"]["authorization_readiness_state_counts"],
                {"FIELD_SURFACE_REACHED_REVIEW_REQUIRED": 1},
            )

    def test_login_or_sso_text_is_blocked_not_field_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_sso_text_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["browser_readback_records"][0]
            self.assertEqual(record["readback_state"], "LOGIN_OR_SSO_REQUIRED_BLOCKED")
            self.assertEqual(record["adapter_result_state"], "BLOCKED")
            self.assertEqual(record["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertEqual(record["field_surface_state"], "LOGIN_OR_SSO_BLOCKED_BEFORE_FIELD_SURFACE")
            self.assertIn(
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                record["operator_next_actions"],
            )
            self.assertEqual(result["summary"]["gdcic_authorized_session_overall_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertIn("gdcic_login_or_sso_required_for_authorized_readback", record["blocker_taxonomy"])
            self.assertTrue(record["query_miss_is_not_clearance"])

    def test_gdcic_contract_system_login_shell_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_contract_login_shell_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["browser_readback_records"][0]
            self.assertEqual(record["readback_state"], "LOGIN_OR_SSO_REQUIRED_BLOCKED")
            self.assertEqual(record["adapter_result_state"], "BLOCKED")
            self.assertEqual(record["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertEqual(result["summary"]["gdcic_authorized_session_overall_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertIn("gdcic_login_or_sso_required_for_authorized_readback", record["blocker_taxonomy"])

    def test_no_target_text_is_not_found_not_clearance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_no_target_text_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["browser_readback_records"][0]
            self.assertEqual(record["readback_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertEqual(record["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(record["authorization_readiness_state"], "FIELD_SURFACE_REACHED_REVIEW_REQUIRED")
            self.assertEqual(record["field_surface_state"], "TARGET_FIELD_NOT_FOUND_REVIEW_REQUIRED")
            self.assertIn(
                "review_gdcic_authorized_query_terms_or_capture_more_precise_field_page",
                record["operator_next_actions"],
            )
            self.assertEqual(record["record_count"], 0)
            self.assertTrue(record["query_miss_is_not_clearance"])


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
        "summary": {"adapter_task_count": len(tasks)},
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
        "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
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


def _contract_text_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": str(task.get("source_url") or ""),
        "body_text": (
            "广东建设信息网 合同 履约 工期 广州测试项目中标候选人公示 "
            "广州测试建设有限公司 项目经理 张三 合同开始 2025-08-01 合同结束 2026-08-01"
        ),
    }


def _sso_text_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": "http://210.76.80.152:8008/SSO/jrsso/auth",
        "body_text": "统一身份认证 用户登录 验证码",
    }


def _contract_login_shell_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": "http://210.76.80.152:8008/JG",
        "body_text": "登录 广东省建筑市场监管公共服务平台 招投标及合同履约监管系统 信息公示区",
    }


def _no_target_text_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": str(task.get("source_url") or ""),
        "body_text": "广东建设信息网 查询页面 广州测试建设有限公司 张三",
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


if __name__ == "__main__":
    unittest.main()
