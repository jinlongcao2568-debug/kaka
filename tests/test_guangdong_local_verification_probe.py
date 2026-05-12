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

from storage.guangdong_local_verification_probe import build_guangdong_local_verification_probe  # noqa: E402


class GuangdongLocalVerificationProbeTests(unittest.TestCase):
    def test_plan_only_builds_guangdong_and_guangzhou_source_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            active_root = root / "active"
            output_root = root / "out"
            _write_active_conflict_probe(active_root)

            result = build_guangdong_local_verification_probe(
                active_conflict_root=active_root,
                output_root=output_root,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["guangdong_local_verification_task_count"], 6)
            self.assertEqual(summary["project_count"], 1)
            self.assertEqual(summary["source_profile_task_counts"]["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"], 1)
            self.assertEqual(summary["source_profile_task_counts"]["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"], 1)
            self.assertIn("construction_permit", summary["target_source_type_counts"])
            self.assertIn("project_manager_change_notice", summary["target_source_type_counts"])
            self.assertIn("administrative_penalty_public_record", summary["target_source_type_counts"])
            self.assertIn(
                "guangzhou_housing_credit_double_publicity_query_adapter",
                summary["next_required_runtime_adapters"],
            )
            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(task["query_probe_state"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(
                task["field_adapter_status"],
                "IMPLEMENTED_SEPARATE:guangdong_gdcic_query_probe_v1",
            )
            self.assertTrue(result["manifest"]["manual_check_table"])
            text = json.dumps(result, ensure_ascii=False)
            for term in ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立", "确认本人", "是不是本人"):
                self.assertNotIn(term, text)
            self.assertTrue((output_root / "guangdong-local-verification-probe-v1.json").exists())

    def test_live_reachability_uses_public_source_without_field_conclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            active_root = root / "active"
            _write_active_conflict_probe(active_root)

            def fake_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": f"<html><title>{url}</title>公开查询入口</html>",
                }

            result = build_guangdong_local_verification_probe(
                active_conflict_root=active_root,
                output_root=root / "out",
                source_profile_ids=["GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"],
                enable_live_reachability=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["guangdong_local_verification_task_count"], 1)
            self.assertEqual(summary["readback_ready_count"], 1)
            record = result["manifest"]["query_task_records"][0]
            self.assertEqual(record["query_probe_state"], "REACHABILITY_READY_PUBLIC_SOURCE")
            self.assertEqual(record["reachability_diagnostic_state"], "PUBLIC_SOURCE_REACHABLE")
            self.assertTrue(record["readback_ready"])
            self.assertEqual(record["field_adapter_status"], "FIELD_ADAPTER_PENDING")

    def test_missing_active_conflict_probe_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangdong_local_verification_probe(
                active_conflict_root=root / "missing",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("active_conflict_probe_missing", result["blocking_reasons"])
            self.assertEqual(result["summary"]["probe_state"], "INPUT_BLOCKED")


def _write_active_conflict_probe(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    task = {
        "task_id": "GZ-ACTIVE-CONFLICT-TASK-001",
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "candidate_group_id": "G01",
        "candidate_group_order": "1",
        "responsible_person_name": "张三",
        "candidate_group_members": ["广州测试建设有限公司"],
        "matched_company_names": ["广州测试建设有限公司"],
        "company_query_variants": ["广州测试建设有限公司"],
        "certificate_no": "粤144202020210001",
        "query_keywords": ["广州测试建设有限公司 张三"],
        "source_entries": [
            _entry("GUANGDONG-GDCIC-SKYPT-OPENPLATFORM", "https://skypt.gdcic.net/openplatform/", ["construction_permit", "contract_public_info", "completion_filing"]),
            _entry("GUANGDONG-GDCIC-HOME", "http://210.76.80.152:8008", ["contract_public_info", "project_manager_change_notice"]),
            _entry("GUANGDONG-TZXM-HOME", "https://tzxm.gd.gov.cn/", ["construction_permit", "completion_filing"]),
            _entry("GUANGDONG-ZFCXJST-PENALTY-PUBLICITY", "https://zfcxjst.gd.gov.cn/xxgk/sgs/", ["administrative_penalty_public_record", "complaint_or_supervision_decision"]),
            _entry("GUANGDONG-CREDIT-GD-HOME", "https://credit.gd.gov.cn/", ["credit_penalty_blacklist"]),
            _entry("GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY", "https://zfcj.gz.gov.cn/zfcj/xyxx/", ["construction_permit", "contract_public_info", "administrative_penalty_public_record"]),
            _entry("ZHEJIANG-JZSC-PUBLIC-SERVICE", "https://jzsc.jst.zj.gov.cn/webserver/app/index.html", ["construction_permit"]),
        ],
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_active_conflict_probe_v1_manifest",
            "task_records": [task],
            "project_task_records": [
                {
                    "project_id": task["project_id"],
                    "project_name": task["project_name"],
                    "task_ids": [task["task_id"]],
                    "task_count": 1,
                }
            ],
            "summary": {"active_conflict_probe_task_count": 1},
        },
        "summary": {"active_conflict_probe_task_count": 1},
    }
    (root / "guangzhou-active-conflict-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _entry(source_profile_id: str, source_url: str, source_types: list[str]) -> dict[str, Any]:
    next_adapter = (
        "guangzhou_housing_credit_double_publicity_query_adapter"
        if source_profile_id == "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY"
        else f"{source_profile_id.lower().replace('-', '_')}_adapter"
    )
    return {
        "entry_id": f"ENTRY-{source_profile_id}",
        "source_profile_id": source_profile_id,
        "source_name": source_profile_id,
        "source_url": source_url,
        "source_family": "test_source_family",
        "target_source_types": source_types,
        "query_keys": ["candidate_company", "project_manager_name", "project_manager_certificate_no"],
        "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
        "next_adapter": next_adapter,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
