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

from storage.guangzhou_evidence_report import build_guangzhou_evidence_report  # noqa: E402


class GuangzhouEvidenceReportTests(unittest.TestCase):
    def test_report_has_three_sections_and_keeps_flow08_register_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible")
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False)

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(
                summary["section_names"],
                ["verification_evidence", "process_stability", "optimization_recommendations"],
            )
            self.assertEqual(summary["flow_08_present_project_count"], 1)
            self.assertEqual(summary["flow_08_targeted_parse_required_project_count"], 0)
            project = result["manifest"]["project_reports"][0]
            self.assertIn("verification_evidence", project)
            self.assertIn("process_stability", project)
            self.assertIn("optimization_recommendations", project)
            flow08 = project["verification_evidence"]["flow_08_registry"]
            self.assertTrue(flow08["flow_08_present"])
            self.assertEqual(flow08["default_parse_depth"], "LIST_ONLY")
            self.assertFalse(flow08["default_parse_required"])
            self.assertEqual(project["process_stability"]["flow_08_default_parse_state"], "REGISTER_ONLY_NO_DEFAULT_PARSE")
            self.assertIn(
                "READY_FOR_INTERNAL_EVIDENCE_PACKAGE_REVIEW",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            report_text = json.dumps(result, ensure_ascii=False)
            for term in ("是不是本人", "确认本人", "冲突成立", "造假成立", "违法成立"):
                self.assertNotIn(term, report_text)
            self.assertTrue((root / "out" / "guangzhou-evidence-report-v1.json").exists())

    def test_flow08_required_when_candidate_group_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible", flow_08_required=True)
            _write_stage4_root(root / "stage4", resolved=False)
            _write_readiness_root(root / "readiness", flow_08_required=True, resolved=False)

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["flow_08_targeted_parse_required_project_count"], 1)
            project = result["manifest"]["project_reports"][0]
            self.assertIn(
                "RUN_FLOW_08_TARGETED_PARSE",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            tasks = project["verification_evidence"]["active_conflict_probe_tasks"]
            self.assertEqual(tasks[0]["probe_state"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertIn("construction_permit", tasks[0]["source_categories"])


def _write_flow_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    samples = [
        _sample("07", "中标候选人公示"),
        _sample("08", "投标(资格预审申请)文件公开"),
    ]
    (root / "run-manifest.json").write_text(
        json.dumps({"manifest": {"project_sample_items": samples}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    analysis_items = [
        {**_sample("07", "中标候选人公示"), "download_policy": "DOWNLOAD_REQUIRED_IF_ATTACHMENT_PRESENT", "parse_depth": "TEXT_PROBE"},
        {**_sample("08", "投标(资格预审申请)文件公开"), "download_policy": "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED", "parse_depth": "LIST_ONLY"},
    ]
    (root / "analysis-plan.json").write_text(
        json.dumps({"manifest": {"items": analysis_items}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_download_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    samples = [
        {
            **_sample("07", "中标候选人公示"),
            "download_attempted_count": 1,
            "attachment_snapshot_count": 1,
            "listed_attachment_count": 1,
            "attachment_snapshot_refs": [{"snapshot_id": "ATT-07", "attachment_url": "https://example.test/07.pdf", "attachment_link_text": "候选公示.pdf"}],
        },
        {
            **_sample("08", "投标(资格预审申请)文件公开"),
            "download_attempted_count": 0,
            "attachment_snapshot_count": 0,
            "listed_attachment_count": 2,
            "attachment_snapshot_refs": [
                {"snapshot_id": "ATT-08-A", "attachment_url": "https://example.test/a.zip", "attachment_link_text": "投标文件A.zip"},
                {"snapshot_id": "ATT-08-B", "attachment_url": "https://example.test/b.zip", "attachment_link_text": "投标文件B.zip"},
            ],
        },
    ]
    (root / "download-probe-manifest.json").write_text(
        json.dumps({"manifest": {"project_sample_items": samples}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_responsible_root(root: Path, *, flow_08_required: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    item = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "early_probe_state": "CERTIFICATE_READY_FROM_07" if not flow_08_required else "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
        "stage4_readiness_state": "READY_FOR_STAGE4_INPUT",
        "flow_08_targeted_parse_required": flow_08_required,
        "candidate_groups": [
            {
                "candidate_group_id": "G1",
                "candidate_group_order": "1",
                "candidate_group_members": ["广州测试建设有限公司"],
                "responsible_person_name": "张三",
                "certificate_no": "粤1442020202100001",
            }
        ],
    }
    (root / "responsible-person-early-probe.json").write_text(
        json.dumps({"manifest": {"items": [item]}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_stage4_root(root: Path, *, resolved: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    item = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "stage4_execution_state": "READBACK_READY" if resolved else "FAIL_CLOSED",
        "candidate_group_id": "G1",
        "candidate_company_name": "广州测试建设有限公司",
        "responsible_person_name": "张三",
    }
    (root / "company-first-stage4-execution.json").write_text(
        json.dumps({"manifest": {"items": [item]}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_readiness_root(root: Path, *, flow_08_required: bool, resolved: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    group = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "candidate_group_id": "G1",
        "candidate_group_order": "1",
        "responsible_person_name": "张三",
        "certificate_no": "粤1442020202100001",
        "candidate_group_members": ["广州测试建设有限公司"],
        "matched_company_names": ["广州测试建设有限公司"] if resolved else [],
        "group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER" if resolved else "UNRESOLVED_NO_MEMBER_MATCHED",
        "flow_08_targeted_parse_required": flow_08_required,
        "member_records": [],
    }
    project = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "candidate_group_verification_records": [group],
    }
    (root / "guangzhou-upstream-readiness-report.json").write_text(
        json.dumps({"manifest": {"project_records": [project]}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sample(flow_no: str, title: str) -> dict[str, object]:
    return {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "flow_no": flow_no,
        "guangzhou_flow_no": flow_no,
        "flow_title": title,
        "source_url": f"https://example.test/{flow_no}.html",
        "published_date": "2026-05-10",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
