from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangzhou_active_conflict_probe import build_guangzhou_active_conflict_probe  # noqa: E402


class GuangzhouActiveConflictProbeTests(unittest.TestCase):
    def test_probe_builds_plan_only_tasks_from_evidence_report_candidate_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            evidence_root = root / "evidence"
            output_root = root / "out"
            _write_evidence_report(evidence_root, group_count=12)

            result = build_guangzhou_active_conflict_probe(
                evidence_report_root=evidence_root,
                output_root=output_root,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["active_conflict_probe_task_count"], 12)
            self.assertEqual(summary["project_count"], 1)
            self.assertEqual(summary["project_with_task_count"], 1)
            self.assertEqual(summary["project_without_task_count"], 0)
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertIn("construction_permit", summary["source_category_counts"])
            self.assertIn("contract_public_info", summary["source_category_counts"])
            self.assertIn("completion_filing", summary["source_category_counts"])
            self.assertIn("project_manager_change_notice", summary["source_category_counts"])
            self.assertIn("administrative_penalty_public_record", summary["source_category_counts"])
            self.assertIn("jzsc_company_first_project_manager_active_conflict_query", summary["next_required_runtime_adapters"])
            self.assertIn("zhejiang_construction_market_public_service_query_adapter", summary["next_required_runtime_adapters"])
            self.assertIn("sichuan_construction_market_public_service_query_adapter", summary["next_required_runtime_adapters"])
            self.assertIn("jiangsu_construction_market_integrated_platform_query_adapter", summary["next_required_runtime_adapters"])
            self.assertIn("shandong_construction_market_credit_supervision_query_adapter", summary["next_required_runtime_adapters"])
            task = result["manifest"]["task_records"][0]
            self.assertEqual(task["probe_state"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertTrue(task["company_query_variants"])
            self.assertTrue(task["query_keywords"])
            self.assertTrue(task["source_entries"])
            source_profile_ids = {entry["source_profile_id"] for entry in task["source_entries"]}
            self.assertIn("ZHEJIANG-JZSC-PUBLIC-SERVICE", source_profile_ids)
            self.assertIn("SICHUAN-JZSC-PUBLIC-SERVICE", source_profile_ids)
            self.assertIn("JIANGSU-JZSC-INTEGRATED-PLATFORM", source_profile_ids)
            self.assertIn("SHANDONG-JZSC-CREDIT-SUPERVISION-PLATFORM", source_profile_ids)
            source_region_codes = {entry["region_code"] for entry in task["source_entries"]}
            self.assertIn("CN-ZJ", source_region_codes)
            self.assertIn("CN-SD", source_region_codes)
            zhejiang_entry = next(
                entry for entry in task["source_entries"]
                if entry["source_profile_id"] == "ZHEJIANG-JZSC-PUBLIC-SERVICE"
            )
            self.assertTrue(zhejiang_entry["official_reference_url"])
            self.assertEqual(task["candidate_notice_source_urls"], ["https://example.test/07.html"])
            self.assertTrue(result["manifest"]["manual_check_table"])
            text = json.dumps(result, ensure_ascii=False)
            for term in ("冲突成立", "造假成立", "违法成立", "确认本人"):
                self.assertNotIn(term, text)
            self.assertTrue((output_root / "guangzhou-active-conflict-probe-v1.json").exists())

    def test_probe_fails_closed_when_evidence_report_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangzhou_active_conflict_probe(
                evidence_report_root=root / "missing",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("evidence_report_missing", result["blocking_reasons"])
            self.assertEqual(result["summary"]["probe_state"], "INPUT_BLOCKED")
            self.assertTrue((root / "out" / "guangzhou-active-conflict-probe-v1.json").exists())


def _write_evidence_report(root: Path, *, group_count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    groups = [
        {
            "candidate_group_id": f"G{i:02d}",
            "candidate_group_order": str(i),
            "candidate_group_members": [f"广州测试建设有限公司{i:02d}", f"广州联合成员有限公司{i:02d}"],
            "responsible_person_name": f"张三{i:02d}",
            "certificate_no": f"粤14420202021{i:04d}",
            "matched_company_names": [f"广州测试建设有限公司{i:02d}"],
            "group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER",
            "flow_08_targeted_parse_required": False,
            "member_records": [],
        }
        for i in range(1, group_count + 1)
    ]
    project = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "verification_evidence": {
            "project_id": "PROJ-CN-GD-JG2026-10815",
            "project_name": "广州测试项目",
            "candidate_group_records": groups,
            "candidate_notice_source_urls": ["https://example.test/07.html"],
            "project_source_urls": ["https://example.test/03.html", "https://example.test/07.html"],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_evidence_report_v1_manifest",
            "project_reports": [project],
            "summary": {"project_count": 1, "candidate_group_count": group_count},
        },
        "summary": {"project_count": 1, "candidate_group_count": group_count},
    }
    (root / "guangzhou-evidence-report-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
