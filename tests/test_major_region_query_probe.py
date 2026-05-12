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

from stage4_verification.regional_hard_defect_sources import MAJOR_TARGET_REGION_SOURCE_CATALOG  # noqa: E402
from storage.major_region_query_probe import build_major_region_query_probe  # noqa: E402


class MajorRegionQueryProbeTests(unittest.TestCase):
    def test_plan_only_builds_tasks_for_all_major_region_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=2)

            result = build_major_region_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(
                summary["major_region_query_probe_task_count"],
                2 * len(MAJOR_TARGET_REGION_SOURCE_CATALOG),
            )
            self.assertIn("CN-ZJ", summary["region_task_counts"])
            self.assertIn("CN-SD", summary["region_task_counts"])
            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(task["query_probe_state"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertTrue(task["source_profile_id"])
            self.assertTrue(task["region_code"])
            self.assertEqual(task["query_params"]["personName"], "张三01")
            self.assertTrue(result["manifest"]["manual_check_table"])
            text = json.dumps(result, ensure_ascii=False)
            for term in ("在建冲突成立", "无在建", "无冲突", "造假成立", "违法成立", "确认本人"):
                self.assertNotIn(term, text)
            self.assertTrue((root / "out" / "major-region-query-probe-v1.json").exists())

    def test_region_filter_can_run_zhejiang_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=3)

            result = build_major_region_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                region_codes=["CN-ZJ"],
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["major_region_query_probe_task_count"], 3)
            self.assertEqual(result["summary"]["region_task_counts"], {"CN-ZJ": 3})
            regions = {task["region_code"] for task in result["manifest"]["query_task_records"]}
            self.assertEqual(regions, {"CN-ZJ"})

    def test_live_fake_getter_marks_reachable_source_without_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=1)

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                return {
                    "http_status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "text_probe": "浙江省建筑市场监管公共服务系统",
                }

            result = build_major_region_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                region_codes=["CN-ZJ"],
                enable_live_reachability=True,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["execution_mode"], "LIVE_REACHABILITY_ATTEMPTED")
            self.assertEqual(result["summary"]["readback_ready_count"], 1)
            task = result["manifest"]["query_task_records"][0]
            self.assertEqual(task["query_probe_state"], "REACHABILITY_READY_PUBLIC_SOURCE")
            self.assertTrue(task["readback_ready"])
            self.assertEqual(task["field_summary"]["source_page_reachable"], True)

    def test_live_fake_getter_classifies_forbidden_and_captcha(self) -> None:
        cases = [
            (
                {"http_status": 403, "content_type": "text/html", "text_probe": ""},
                "major_region_http_forbidden_or_login_required",
            ),
            (
                {"http_status": 200, "content_type": "text/html", "text_probe": "请登录后完成验证码"},
                "major_region_captcha_or_login_required",
            ),
        ]
        for response, expected_taxonomy in cases:
            with self.subTest(expected_taxonomy=expected_taxonomy):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    root = Path(tmp_dir)
                    _write_active_conflict_probe(root / "active", task_count=1)

                    result = build_major_region_query_probe(
                        active_conflict_root=root / "active",
                        output_root=root / "out",
                        region_codes=["CN-ZJ"],
                        enable_live_reachability=True,
                        http_getter=lambda _url, _params, response=response: response,
                        created_at="2026-05-12T00:00:00+08:00",
                    )

                    task = result["manifest"]["query_task_records"][0]
                    self.assertEqual(task["query_probe_state"], "REVIEW_REQUIRED")
                    self.assertIn(expected_taxonomy, task["blocker_taxonomy"])

    def test_live_reachability_can_defer_by_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=1)

            result = build_major_region_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                enable_live_reachability=True,
                max_live_tasks=1,
                http_getter=lambda _url, _params: {
                    "http_status": 200,
                    "content_type": "text/html",
                    "text_probe": "ok",
                },
                created_at="2026-05-12T00:00:00+08:00",
            )

            tasks = result["manifest"]["query_task_records"]
            self.assertEqual(tasks[0]["query_probe_state"], "REACHABILITY_READY_PUBLIC_SOURCE")
            self.assertEqual(tasks[1]["query_probe_state"], "LIVE_REACHABILITY_DEFERRED_BY_LIMIT")

    def test_live_reachability_reuses_same_source_result_across_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_active_conflict_probe(root / "active", task_count=2)
            call_count = 0

            def fake_getter(_url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
                nonlocal call_count
                call_count += 1
                return {
                    "http_status": 200,
                    "content_type": "text/html",
                    "text_probe": "浙江省建筑市场监管公共服务系统",
                }

            result = build_major_region_query_probe(
                active_conflict_root=root / "active",
                output_root=root / "out",
                region_codes=["CN-ZJ"],
                enable_live_reachability=True,
                max_live_tasks=1,
                http_getter=fake_getter,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(call_count, 1)
            self.assertEqual(result["summary"]["major_region_query_probe_task_count"], 2)
            self.assertEqual(result["summary"]["readback_ready_count"], 2)
            self.assertTrue(result["manifest"]["query_task_records"][1]["reachability_cache_hit"])

    def test_missing_active_conflict_probe_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_major_region_query_probe(
                active_conflict_root=root / "missing",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("active_conflict_probe_missing", result["blocking_reasons"])
            self.assertEqual(result["summary"]["probe_state"], "INPUT_BLOCKED")


def _write_active_conflict_probe(root: Path, *, task_count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    source_entries = [
        {
            "entry_id": item["entry_id"],
            "region_code": item["region_code"],
            "region_name": item["region_name"],
            "source_profile_id": item["source_profile_id"],
            "source_name": item["source_name"],
            "source_url": item["source_url"],
            "official_reference_url": item["official_reference_url"],
            "target_source_types": [
                "construction_permit",
                "contract_public_info",
                "completion_filing",
                "project_manager_change_notice",
                "personnel_public_record",
                "performance_public_record",
            ],
            "query_keys": [
                "candidate_company",
                "project_manager_name",
                "project_manager_certificate_no",
            ],
            "runtime_status": item["runtime_status"],
            "next_adapter": item["next_adapter"],
        }
        for item in MAJOR_TARGET_REGION_SOURCE_CATALOG
    ]
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
                "candidate_group_members": [f"广州测试建设有限公司{index:02d}"],
                "matched_company_names": [f"广州测试建设有限公司{index:02d}"],
                "company_query_variants": [f"广州测试建设有限公司{index:02d}"],
                "certificate_no": f"粤14420202021{index:04d}",
                "query_keywords": [
                    f"广州测试建设有限公司{index:02d} 张三{index:02d}",
                    f"张三{index:02d}",
                    "广州测试项目",
                ],
                "source_entries": source_entries,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_active_conflict_probe_v1_manifest",
            "task_records": tasks,
            "summary": {"active_conflict_probe_task_count": len(tasks), "probe_state": "READY"},
        }
    }
    (root / "guangzhou-active-conflict-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
