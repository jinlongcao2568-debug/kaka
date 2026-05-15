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

from storage.guangzhou_evidence_value_closeout import build_guangzhou_evidence_value_closeout  # noqa: E402


class GuangzhouEvidenceValueCloseoutTests(unittest.TestCase):
    def test_builds_four_internal_tables_from_p11_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_inputs(root, unfixable_count=0)

            result = build_guangzhou_evidence_value_closeout(
                batch_stability_root=root / "batch",
                evidence_report_root=root / "evidence",
                readable_report_root=root / "readable",
                internal_package_root=root / "internal",
                fixation_backfill_root=root / "backfill",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["value_closeout_state"], "P12_VALUE_CLOSEOUT_READY")
            self.assertEqual(summary["project_count"], 3)
            self.assertEqual(summary["candidate_group_count"], 3)
            self.assertEqual(summary["external_conflict_source_required_project_count"], 1)
            self.assertEqual(summary["low_value_or_not_applicable_project_count"], 1)
            self.assertEqual(summary["process_blocked_project_count"], 1)
            self.assertEqual(summary["flow_08_targeted_parse_required_count"], 1)
            self.assertEqual(summary["unfixable_with_current_artifacts_count"], 0)
            self.assertEqual(summary["forbidden_term_scan_state"], "PASS")
            self.assertFalse(summary["customer_delivery_ready"])

            self.assertTrue((root / "out" / "project-value-table.json").exists())
            self.assertTrue((root / "out" / "candidate-group-verification-table.json").exists())
            self.assertTrue((root / "out" / "delivery-gap-table.json").exists())
            self.assertTrue((root / "out" / "guangzhou-evidence-value-closeout-v1.json").exists())

            project_table = json.loads((root / "out" / "project-value-table.json").read_text(encoding="utf-8"))
            states = {record["project_id"]: record["value_closeout_state"] for record in project_table["records"]}
            self.assertEqual(states["PROJ-CN-GD-JG2026-10001"], "EXTERNAL_CONFLICT_SOURCE_REQUIRED")
            self.assertEqual(states["PROJ-CN-GD-JG2026-10002"], "LOW_VALUE_OR_NOT_APPLICABLE")
            self.assertEqual(states["PROJ-CN-GD-JG2026-10003"], "PROCESS_BLOCKED_REVIEW")

            candidate_table = json.loads((root / "out" / "candidate-group-verification-table.json").read_text(encoding="utf-8"))
            self.assertEqual(len(candidate_table["records"]), 3)
            self.assertEqual(candidate_table["records"][0]["public_registration_match_state"], "PUBLIC_REGISTRATION_MATCHED")

            delivery_table = json.loads((root / "out" / "delivery-gap-table.json").read_text(encoding="utf-8"))
            gap_types = {record["gap_type"] for record in delivery_table["records"]}
            self.assertIn("EXTERNAL_ACTIVE_CONFLICT_SOURCE_REQUIRED", gap_types)
            self.assertIn("FLOW_08_TARGETED_PARSE_REQUIRED", gap_types)
            self.assertIn("RECORD_HASH_ONLY_EXPLANATION_REQUIRED", gap_types)

    def test_unfixable_source_gap_blocks_value_closeout_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_inputs(root, unfixable_count=2, flow08_required=False)

            result = build_guangzhou_evidence_value_closeout(
                batch_stability_root=root / "batch",
                evidence_report_root=root / "evidence",
                readable_report_root=root / "readable",
                internal_package_root=root / "internal",
                fixation_backfill_root=root / "backfill",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
            )

            states = {record["project_id"]: record["value_closeout_state"] for record in result["manifest"]["project_value_records"]}
            self.assertEqual(states["PROJ-CN-GD-JG2026-10001"], "PROCESS_BLOCKED_REVIEW")
            self.assertEqual(result["summary"]["unfixable_with_current_artifacts_count"], 2)

    def test_report_never_contains_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_inputs(root, unfixable_count=0)

            result = build_guangzhou_evidence_value_closeout(
                batch_stability_root=root / "batch",
                evidence_report_root=root / "evidence",
                readable_report_root=root / "readable",
                internal_package_root=root / "internal",
                fixation_backfill_root=root / "backfill",
                stage4_execution_root=root / "stage4",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_p12_inputs(root: Path, *, unfixable_count: int, flow08_required: bool = True) -> None:
    for folder in ("batch", "evidence", "readable", "internal", "backfill", "stage4"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    _write_json(
        root / "batch" / "guangzhou-batch-stability-closeout-v1.json",
        {
            "summary": {
                "batch_closeout_state": "P11_STABILITY_READY",
                "entry_project_count": 3,
                "attachment_snapshot_success_rate": 1.0,
                "stage4_resolved_group_count": 2,
                "customer_delivery_ready": False,
            }
        },
    )
    projects = [
        _project("PROJ-CN-GD-JG2026-10001", "广州道路工程施工中标候选人公示", "CANDIDATE-GROUP-1", flow08=False),
        _project("PROJ-CN-GD-JG2026-10002", "车辆及半挂车购置项目中标候选人公示", "CANDIDATE-GROUP-2", flow08=False),
        _project("PROJ-CN-GD-JG2026-10003", "广州桥梁工程施工中标候选人公示", "CANDIDATE-GROUP-3", flow08=flow08_required),
    ]
    _write_json(
        root / "evidence" / "guangzhou-evidence-report-v1.json",
        {
            "manifest": {
                "project_reports": projects,
                "summary": {
                    "project_count": 3,
                    "candidate_group_count": 3,
                    "resolved_candidate_group_count": 2,
                    "flow_08_targeted_parse_required_project_count": 1 if flow08_required else 0,
                },
            }
        },
    )
    _write_json(root / "readable" / "guangzhou-evidence-readable-report-v1.json", {"summary": {"report_state": "READY", "project_count": 3}})
    _write_json(
        root / "internal" / "internal-evidence-package-manifest-v1.json",
        {
            "summary": {
                "source_fixation_record_count": 18,
                "trusted_timestamp_state": "RESERVED_NOT_IMPLEMENTED",
                "customer_delivery_ready": False,
            }
        },
    )
    _write_json(
        root / "backfill" / "evidence-fixation-backfill-v1.json",
        {
            "summary": {
                "backfilled_no_remaining_gap_count": 10,
                "classified_record_hash_only_count": 2,
                "unfixable_with_current_artifacts_count": unfixable_count,
            }
        },
    )
    _write_json(
        root / "stage4" / "company-first-stage4-execution.json",
        {
            "manifest": {
                "summary": {"job_count": 3},
                "items": [
                    {
                        "candidate_group_id": "CANDIDATE-GROUP-1",
                        "provider_id": "JZSC_PERSON_IDENTITY",
                        "readback_state": "READBACK_READY",
                        "registered_unit_name_optional": "广州道路公司",
                    },
                    {
                        "candidate_group_id": "CANDIDATE-GROUP-2",
                        "provider_id": "JZSC_PERSON_IDENTITY",
                        "readback_state": "READBACK_READY",
                        "registered_unit_name_optional": "广州车辆公司",
                    },
                    {
                        "candidate_group_id": "CANDIDATE-GROUP-3",
                        "provider_id": "JZSC_PERSON_IDENTITY",
                        "readback_state": "REVIEW_REQUIRED",
                    },
                ],
            }
        },
    )


def _project(project_id: str, name: str, group_id: str, *, flow08: bool) -> dict:
    return {
        "project_id": project_id,
        "project_name": name,
        "verification_evidence": {
            "project_id": project_id,
            "project_name": name,
            "candidate_notice_source_urls": [f"https://example.invalid/{project_id}.html"],
            "project_source_urls": [f"https://example.invalid/{project_id}.html"],
            "flow_08_targeted_parse_required": flow08,
            "flow_08_registry": {"flow_08_present": True, "source_urls": [f"https://example.invalid/{project_id}_tb.html"]},
            "official_source_readback_ready_count": 0,
            "guangdong_local_field_readback_ready_count": 0,
            "candidate_group_records": [
                {
                    "candidate_group_id": group_id,
                    "candidate_group_order": "1",
                    "candidate_group_members": [name[:6] + "公司"],
                    "responsible_person_name": "张三",
                    "certificate_no": "粤1442024202500001",
                    "matched_company_names": [name[:6] + "公司"],
                    "group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER",
                    "flow_08_targeted_parse_required": flow08,
                    "member_records": [
                        {
                            "candidate_company_name": name[:6] + "公司",
                            "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                            "registered_unit_name_optional": name[:6] + "公司",
                            "resolved_certificate_no_optional": "粤1442024202500001",
                        }
                    ],
                }
            ],
        },
        "process_stability": {
            "safe_to_closeout_evidence_report": not flow08,
            "closeout_blocking_reasons": [],
            "failure_taxonomy": [],
        },
        "optimization_recommendations": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
