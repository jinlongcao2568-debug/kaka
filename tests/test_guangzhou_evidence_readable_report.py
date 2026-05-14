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
                internal_evidence_package_root=root / "package",
                fixation_backfill_root=root / "backfill",
                recapture_root=root / "recapture",
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
            self.assertEqual(summary["gdcic_field_availability_counts"]["person_name"], 12)
            self.assertEqual(summary["gdcic_certificate_field_availability_state"], "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK")
            self.assertEqual(summary["certificate_supplement_summary"]["certificate_resolved_group_count"], 12)
            self.assertEqual(summary["evidence_fixation_summary"]["backfilled_no_remaining_gap_count"], 70)
            self.assertEqual(summary["source_fixation_backfill_summary"]["classified_record_hash_only_count"], 12)
            self.assertEqual(summary["source_fixation_backfill_summary"]["unfixable_with_current_artifacts_count"], 0)
            self.assertEqual(summary["recapture_summary"]["recapture_task_count"], 38)
            self.assertEqual(summary["forbidden_term_scan_state"], "PASS")
            self.assertTrue((root / "out" / "guangzhou-evidence-readable-report-v1.json").exists())
            md_path = root / "out" / "guangzhou-evidence-readable-report-v1.md"
            self.assertTrue(md_path.exists())
            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("PROJ-CN-GD-JG2026-10001", markdown)
            self.assertIn("REGISTER_ONLY_BACKUP", markdown)
            self.assertIn("NOT_APPLICABLE", markdown)
            self.assertIn("GDCIC_BLOCKED_OR_CAPTCHA_REVIEW_REQUIRED", markdown)
            self.assertIn("GDCIC 当前 readback 未返回证书字段", markdown)
            self.assertIn("证书字段已由 Stage4 公司优先链路补强", markdown)
            self.assertIn("CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4", markdown)
            self.assertIn("证据固化状态", markdown)
            self.assertIn("backfilled=70", markdown)
            self.assertIn("record_hash_only=12", markdown)
            self.assertIn("unfixable=0", markdown)
            self.assertIn("tasks=38", markdown)
            self.assertIn("不等同于源网页或源文件完整内容 hash", markdown)
            report_text = json.dumps(result, ensure_ascii=False) + markdown
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, report_text)

    def test_flow08_trigger_is_visible_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", project_count=2, flow08_required=True)

            result = build_guangzhou_evidence_readable_report(
                evidence_report_root=root / "evidence",
                internal_evidence_package_root=None,
                fixation_backfill_root=None,
                recapture_root=None,
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
                "gdcic_field_availability_counts": {
                    "person_name": 12,
                    "company_name": 12,
                    "project_name": 10,
                    "id_card_hash": 12,
                },
                "gdcic_missing_field_counts": {
                    "certificate_no": 12,
                    "registration_category": 12,
                    "registration_profession": 12,
                    "effective_status": 12,
                },
                "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
                "certificate_supplement_summary": {
                    "candidate_group_count": candidate_count,
                    "certificate_resolved_group_count": candidate_count,
                    "certificate_unresolved_group_count": 0,
                    "flow_08_targeted_parse_required_count": 0,
                    "gdcic_certificate_field_gap_compensated_by_stage4_count": candidate_count,
                },
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
    if root.parent.exists():
        _write_p9_inputs(root.parent)


def _write_p9_inputs(root: Path) -> None:
    package = root / "package"
    package.mkdir(parents=True, exist_ok=True)
    (package / "internal-evidence-package-manifest-v1.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "summary": {
                        "internal_package_state": "P7_INTERNAL_EVIDENCE_PACKAGE_READY",
                        "source_fixation_record_count": 173,
                        "fixation_complete_count": 91,
                        "fixation_gap_count": 82,
                        "fixation_completeness_state": "SOURCE_FIXATION_PARTIAL_REVIEW",
                        "source_fixation_backfill_state": "P8_FIXATION_BACKFILL_READY",
                        "strict_fixation_gap_count": 82,
                        "classified_fixation_gap_count": 12,
                        "backfilled_no_remaining_gap_count": 70,
                        "backfill_unfixable_with_current_artifacts_count": 0,
                        "forbidden_term_scan_state": "PASS",
                        "customer_delivery_ready": False,
                        "approval_required_before_customer_delivery": True,
                        "trusted_timestamp_state": "RESERVED_NOT_IMPLEMENTED",
                        "notary_state": "RESERVED_NOT_IMPLEMENTED",
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    backfill = root / "backfill"
    backfill.mkdir(parents=True, exist_ok=True)
    (backfill / "evidence-fixation-backfill-v1.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "summary": {
                        "backfill_state": "P8_FIXATION_BACKFILL_READY",
                        "source_gap_record_count": 82,
                        "backfilled_record_count": 70,
                        "classified_record_hash_only_count": 12,
                        "unfixable_with_current_artifacts_count": 0,
                        "backfill_state_counts": {
                            "BACKFILLED_FROM_RECAPTURED_DETAIL_SNAPSHOT": 8,
                            "BACKFILLED_FROM_RECAPTURED_STAGE4_READBACK": 30,
                        },
                        "backfill_classification_counts": {
                            "CONTENT_SNAPSHOT_HASH_BACKFILLED": 28,
                            "READBACK_RECORD_HASH_ONLY": 12,
                        },
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    recapture = root / "recapture"
    recapture.mkdir(parents=True, exist_ok=True)
    (recapture / "evidence-fixation-recapture-v1.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "summary": {
                        "recapture_state": "P9_RECAPTURE_EXECUTED",
                        "recapture_task_count": 38,
                        "flow_detail_recapture_task_count": 8,
                        "stage4_readback_recapture_task_count": 30,
                        "recapture_state_counts": {
                            "FLOW_DETAIL_RECAPTURED": 8,
                            "STAGE4_READBACK_RECAPTURED": 30,
                        },
                        "failure_taxonomy_counts": {},
                        "execute_enabled": True,
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
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
            "gdcic_field_availability_counts": {
                "person_name": gdcic_counts.get("PERSON_REGISTRATION_READBACK", 0),
                "company_name": gdcic_counts.get("PERSON_REGISTRATION_READBACK", 0),
                "project_name": gdcic_counts.get("COMPANY_PROJECT_READBACK", 0),
                "id_card_hash": gdcic_counts.get("PERSON_REGISTRATION_READBACK", 0),
            },
            "gdcic_missing_field_counts": {
                "certificate_no": 1,
                "registration_category": 1,
                "registration_profession": 1,
                "effective_status": 1,
            },
            "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK" if gdcic_counts else "",
            "certificate_supplement_summary": {
                "candidate_group_count": len(groups),
                "certificate_resolved_group_count": len(groups),
                "certificate_unresolved_group_count": 0,
                "flow_08_targeted_parse_required_count": 0,
                "gdcic_certificate_field_gap_compensated_by_stage4_count": len(groups),
            },
            "certificate_supplement_group_records": [
                {
                    "candidate_group_id": group["candidate_group_id"],
                    "certificate_supplement_state": "CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4",
                    "registered_unit_name": group["candidate_group_members"][0],
                    "registration_category": "注册建造师",
                    "personnel_public_source_url": "https://example.test/person",
                }
                for group in groups
            ],
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
            {"recommended_action": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_REVIEW", "reason": "cert"},
            {"recommended_action": "CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4", "reason": "stage4 cert"},
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
