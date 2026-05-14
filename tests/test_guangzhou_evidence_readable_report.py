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

from storage.guangzhou_evidence_readable_report import build_guangzhou_evidence_readable_report  # noqa: E402


class GuangzhouEvidenceReadableReportTests(unittest.TestCase):
    def test_builds_json_and_markdown_from_p3_evidence_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", project_count=5)

            result = build_guangzhou_evidence_readable_report(
                evidence_report_root=root / "evidence",
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_count"], 5)
            self.assertEqual(summary["candidate_group_count"], 12)
            self.assertEqual(summary["resolved_candidate_group_count"], 12)
            self.assertEqual(summary["not_applicable_project_count"], 1)
            self.assertEqual(summary["flow_08_targeted_parse_required_project_count"], 0)
            self.assertEqual(summary["official_source_readback_ready_count"], 12)
            self.assertEqual(summary["gdcic_readback_classification_counts"]["PERSON_REGISTRATION_READBACK"], 12)
            self.assertTrue((root / "out" / "guangzhou-evidence-readable-report-v1.json").exists())
            md_path = root / "out" / "guangzhou-evidence-readable-report-v1.md"
            self.assertTrue(md_path.exists())
            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("PROJ-CN-GD-JG2026-10001", markdown)
            self.assertIn("REGISTER_ONLY_BACKUP", markdown)
            self.assertIn("NOT_APPLICABLE", markdown)
            self.assertIn("GDCIC_BLOCKED_OR_CAPTCHA_REVIEW_REQUIRED", markdown)
            report_text = json.dumps(result, ensure_ascii=False) + markdown
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, report_text)

    def test_flow08_trigger_is_visible_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", project_count=2, flow08_required=True)

            result = build_guangzhou_evidence_readable_report(
                evidence_report_root=root / "evidence",
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            project = [
                item
                for item in result["manifest"]["project_cards"]
                if item["project_status"] == "FLOW_08_TARGETED_PARSE_REQUIRED"
            ][0]
            self.assertEqual(project["project_status"], "FLOW_08_TARGETED_PARSE_REQUIRED")
            self.assertEqual(project["flow_08_state"]["default_state"], "TARGETED_PARSE_REQUIRED")
            self.assertEqual(result["summary"]["flow_08_targeted_parse_required_project_count"], 1)


def _write_evidence_report(root: Path, *, project_count: int, flow08_required: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    projects = [_project_payload("PROJ-CN-GD-JG2026-11283", "保险项目", [], {}, not_applicable=True)]
    for idx in range(1, project_count):
        groups = [_group(idx, sub) for sub in range(3)]
        projects.append(
            _project_payload(
                f"PROJ-CN-GD-JG2026-10{idx:03d}",
                f"广州测试项目 {idx}",
                groups,
                {
                    "PERSON_REGISTRATION_READBACK": 3,
                    "COMPANY_PROJECT_READBACK": 2,
                    "EMPTY_PUBLIC_RESULT_REVIEW": 3,
                    "BLOCKED_OR_CAPTCHA_REVIEW": 2,
                },
                flow08_required=flow08_required,
            )
        )
    candidate_count = sum(len((p["verification_evidence"]).get("candidate_group_records") or []) for p in projects)
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_evidence_report_v1_manifest",
            "project_reports": projects,
            "summary": {
                "report_state": "READY",
                "project_count": len(projects),
                "candidate_group_count": candidate_count,
                "resolved_candidate_group_count": candidate_count,
                "flow_08_targeted_parse_required_project_count": 1 if flow08_required else 0,
                "official_source_readback_ready_count": 12,
                "official_source_project_ready_count": 4,
                "gdcic_readback_classification_counts": {
                    "PERSON_REGISTRATION_READBACK": 12,
                    "COMPANY_PROJECT_READBACK": 10,
                    "EMPTY_PUBLIC_RESULT_REVIEW": 12,
                    "BLOCKED_OR_CAPTCHA_REVIEW": 11,
                },
                "evidence_report_closeout_overall_state": "EVIDENCE_REPORT_CLOSEOUT_READY",
            },
        }
    }
    (root / "guangzhou-evidence-report-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _project_payload(
    project_id: str,
    name: str,
    groups: list[dict[str, object]],
    gdcic_counts: dict[str, int],
    *,
    not_applicable: bool = False,
    flow08_required: bool = False,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": name,
        "verification_evidence": {
            "candidate_group_records": groups,
            "candidate_notice_source_urls": [f"https://example.test/{project_id}/07.html"],
            "project_source_urls": [f"https://example.test/{project_id}/{flow}.html" for flow in ("03", "07", "08")],
            "flow_08_targeted_parse_required": flow08_required,
            "flow_08_registry": {
                "flow_08_present": True,
                "source_urls": [f"https://example.test/{project_id}/08.html"],
                "attachment_count": 2,
            },
            "official_source_readback_state": "OFFICIAL_SOURCE_READBACK_READY" if gdcic_counts else "NOT_BUILT",
            "official_source_readback_ready_count": sum(gdcic_counts.values()),
            "gdcic_readback_classification_counts": gdcic_counts,
        },
        "process_stability": {
            "evidence_report_closeout_state": (
                "EVIDENCE_REPORT_CLOSEOUT_NOT_APPLICABLE" if not_applicable else "EVIDENCE_REPORT_CLOSEOUT_READY"
            ),
            "safe_to_closeout_evidence_report": True,
            "download_probe_flow_count": 4,
            "attachment_snapshot_count": 11,
            "stage4_readback_ready_count": 3,
            "closeout_deferred_reasons": ["parse_probe_manifest_missing_deferred_by_candidate_group_resolution"],
            "closeout_blocking_reasons": [],
            "failure_taxonomy": ["source_readback_deferred"],
        },
        "optimization_recommendations": [
            {"recommended_action": "CLOSEOUT_EVIDENCE_REPORT_READY", "reason": "ready"},
            {"recommended_action": "GDCIC_PERSON_REGISTRATION_READBACK_REVIEW", "reason": "person"},
            {"recommended_action": "GDCIC_COMPANY_PROJECT_READBACK_REVIEW", "reason": "project"},
            {"recommended_action": "GDCIC_EMPTY_PUBLIC_RESULT_REVIEW_REQUIRED", "reason": "empty"},
            {"recommended_action": "GDCIC_BLOCKED_OR_CAPTCHA_REVIEW_REQUIRED", "reason": "blocked"},
            *([{"recommended_action": "RUN_FLOW_08_TARGETED_PARSE", "reason": "flow08"}] if flow08_required else []),
        ],
    }


def _group(project_idx: int, group_idx: int) -> dict[str, object]:
    return {
        "candidate_group_id": f"G-{project_idx}-{group_idx}",
        "candidate_group_order": str(group_idx + 1),
        "candidate_group_members": [f"候选公司{project_idx}-{group_idx}"],
        "responsible_person_name": f"负责人{project_idx}-{group_idx}",
        "certificate_no": f"粤1442026{project_idx:02d}{group_idx:02d}",
        "bid_price": "1000.00",
        "group_resolution_state": "RESOLVED_PUBLIC_REGISTRATION_MATCHED",
    }


if __name__ == "__main__":
    unittest.main()
