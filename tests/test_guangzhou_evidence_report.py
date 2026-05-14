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
            chain = project["verification_evidence"]["responsible_person_verification_chain"]
            self.assertEqual(chain["source_07_certificate_ready_count"], 1)
            self.assertEqual(chain["stage4_public_registration_input_count"], 1)
            self.assertEqual(chain["company_first_supplement_required_count"], 0)
            flow08 = project["verification_evidence"]["flow_08_registry"]
            self.assertTrue(flow08["flow_08_present"])
            self.assertEqual(flow08["default_parse_depth"], "LIST_ONLY")
            self.assertFalse(flow08["default_parse_required"])
            self.assertEqual(project["process_stability"]["flow_08_default_parse_state"], "REGISTER_ONLY_NO_DEFAULT_PARSE")
            self.assertEqual(project["process_stability"]["evidence_report_closeout_state"], "EVIDENCE_REPORT_CLOSEOUT_READY")
            self.assertTrue(project["process_stability"]["safe_to_closeout_evidence_report"])
            self.assertIn(
                "parse_probe_manifest_missing_deferred_by_candidate_group_resolution",
                project["process_stability"]["closeout_deferred_reasons"],
            )
            self.assertEqual(summary["safe_to_closeout_evidence_report_project_count"], 1)
            self.assertTrue(summary["safe_to_closeout_evidence_report"])
            self.assertEqual(summary["evidence_report_closeout_overall_state"], "EVIDENCE_REPORT_CLOSEOUT_READY")
            self.assertIn(
                "parse_probe_manifest_missing_deferred_by_candidate_group_resolution",
                summary["overall_closeout_deferred_reasons"],
            )
            self.assertEqual(
                summary["closeout_deferred_reason_counts"],
                {"parse_probe_manifest_missing_deferred_by_candidate_group_resolution": 1},
            )
            self.assertIn(
                "READY_FOR_INTERNAL_EVIDENCE_PACKAGE_REVIEW",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            self.assertIn(
                "CLOSEOUT_EVIDENCE_REPORT_READY",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            self.assertIn(
                "PARSE_PROBE_DEFERRED_NO_FLOW08_TRIGGER",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            self.assertIn(
                "run_stage4_registration_probe",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            report_text = json.dumps(result, ensure_ascii=False)
            for term in ("是不是本人", "确认本人", "无风险", "无冲突", "冲突成立", "造假成立", "违法成立"):
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
            chain = project["verification_evidence"]["responsible_person_verification_chain"]
            self.assertEqual(chain["source_07_certificate_missing_count"], 1)
            self.assertEqual(chain["company_first_supplement_required_count"], 1)
            self.assertIn(
                "RUN_FLOW_08_TARGETED_PARSE",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            self.assertIn(
                "company_first_certificate_supplement",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            self.assertIn(
                "flow_08_targeted_parse_if_stage4_unmatched",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )
            tasks = project["verification_evidence"]["active_conflict_probe_tasks"]
            self.assertEqual(tasks[0]["probe_state"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertIn("construction_permit", tasks[0]["source_categories"])
            release_matrix = project["verification_evidence"]["release_evidence_matrix"]
            self.assertEqual(release_matrix[0]["matrix_state"], "RELEASE_READBACK_REQUIRED")
            self.assertIn("completion_acceptance_or_completion_filing", release_matrix[0]["release_evidence_targets"])
            self.assertIn("project_manager_change_notice_or_permit_change", release_matrix[0]["release_evidence_targets"])
            self.assertEqual(
                tasks[0]["release_evidence_matrix"]["evidence_strength_state"],
                "INSUFFICIENT_EVIDENCE_PENDING_EXTERNAL_READBACK",
            )

    def test_report_consumes_active_conflict_probe_summary_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible")
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False)
            _write_active_conflict_root(root / "active-conflict")

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                active_conflict_probe_root=root / "active-conflict",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["active_conflict_external_probe_state"], "TASKS_READY")
            self.assertEqual(result["summary"]["active_conflict_external_probe_task_count"], 1)
            project = result["manifest"]["project_reports"][0]
            self.assertEqual(project["verification_evidence"]["active_conflict_probe_state"], "TASKS_READY")
            self.assertIn(
                "ACTIVE_CONFLICT_EXTERNAL_SOURCE_TASKS_READY",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )

    def test_not_applicable_responsible_person_project_can_closeout_without_candidate_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible", not_applicable=True)
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False, include_group=False)

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            project = result["manifest"]["project_reports"][0]
            self.assertEqual(project["verification_evidence"]["public_registration_match_state"], "NO_CANDIDATE_GROUPS")
            self.assertEqual(project["responsible_person_verification_chain"]["chain_state"], "RESPONSIBLE_PERSON_NOT_APPLICABLE")
            self.assertEqual(project["process_stability"]["evidence_report_closeout_state"], "EVIDENCE_REPORT_CLOSEOUT_NOT_APPLICABLE")
            self.assertTrue(project["process_stability"]["safe_to_closeout_evidence_report"])
            self.assertEqual(project["process_stability"]["closeout_blocking_reasons"], [])

    def test_report_consumes_gdcic_query_probe_summary_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible")
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False)
            _write_active_conflict_root(root / "active-conflict")
            _write_gdcic_query_root(root / "gdcic")

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                active_conflict_probe_root=root / "active-conflict",
                gdcic_query_probe_root=root / "gdcic",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["gdcic_probe_state"], "READY")
            self.assertEqual(result["summary"]["gdcic_query_probe_task_count"], 1)
            self.assertEqual(result["summary"]["gdcic_readback_ready_count"], 1)
            self.assertEqual(result["summary"]["gdcic_blocker_taxonomy_counts"], {"gdcic_public_query_empty_review": 1})
            project = result["manifest"]["project_reports"][0]
            evidence = project["verification_evidence"]
            self.assertEqual(evidence["gdcic_probe_state"], "READY")
            self.assertEqual(evidence["gdcic_readback_ready_count"], 1)
            self.assertIn(
                "GDCIC_PUBLIC_SOURCE_READBACK_READY",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )

    def test_report_consumes_official_source_readback_closeout_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible")
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False)
            _write_official_source_readback_root(root / "official-source")

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                official_source_readback_root=root / "official-source",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["official_source_readback_closeout_state"], "P2_OFFICIAL_READBACK_READY")
            self.assertEqual(result["summary"]["official_source_readback_ready_count"], 12)
            project = result["manifest"]["project_reports"][0]
            evidence = project["verification_evidence"]
            self.assertEqual(evidence["official_source_readback_closeout_state"], "P2_OFFICIAL_READBACK_READY")
            self.assertEqual(evidence["official_source_readback_state"], "OFFICIAL_SOURCE_READBACK_READY")
            self.assertEqual(evidence["official_source_readback_ready_count"], 3)
            self.assertIn(
                "OFFICIAL_SOURCE_READBACK_READY",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )

    def test_report_consumes_guangdong_local_verification_probe_summary_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible")
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False)
            _write_guangdong_local_verification_root(root / "gd-local")

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                guangdong_local_verification_root=root / "gd-local",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["guangdong_local_verification_probe_state"], "READY")
            self.assertEqual(result["summary"]["guangdong_local_verification_task_count"], 6)
            self.assertEqual(result["summary"]["guangdong_local_readback_ready_count"], 2)
            project = result["manifest"]["project_reports"][0]
            evidence = project["verification_evidence"]
            self.assertEqual(evidence["guangdong_local_verification_probe_state"], "READY")
            self.assertEqual(evidence["guangdong_local_readback_ready_count"], 2)
            self.assertIn("GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY", evidence["guangdong_local_source_profile_ids"])
            self.assertIn(
                "GUANGDONG_LOCAL_VERIFICATION_PROBE_READY",
                [item["recommended_action"] for item in project["optimization_recommendations"]],
            )

    def test_report_consumes_guangdong_local_field_query_probe_summary_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_flow_root(root / "flow")
            _write_download_root(root / "download")
            _write_responsible_root(root / "responsible")
            _write_stage4_root(root / "stage4")
            _write_readiness_root(root / "readiness", flow_08_required=False)
            _write_guangdong_local_field_query_root(root / "gd-local-field")

            result = build_guangzhou_evidence_report(
                flow_root=root / "flow",
                download_root=root / "download",
                responsible_person_root=root / "responsible",
                stage4_execution_root=root / "stage4",
                readiness_root=root / "readiness",
                guangdong_local_field_query_root=root / "gd-local-field",
                output_root=root / "out",
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["guangdong_local_field_query_probe_state"], "READY")
            self.assertEqual(result["summary"]["guangdong_local_field_query_task_count"], 6)
            self.assertEqual(result["summary"]["guangdong_local_field_keyword_hit_task_count"], 1)
            field_summary = result["summary"]["guangdong_local_field_query_summary"]
            self.assertEqual(field_summary["task_count"], 2)
            self.assertEqual(field_summary["readback_ready_count"], 1)
            self.assertEqual(field_summary["keyword_hit_count"], 1)
            self.assertTrue(field_summary["no_legal_conclusion"])
            self.assertTrue(field_summary["query_miss_is_not_clearance"])
            failure_review = result["manifest"]["guangdong_local_field_query_failure_review"]
            self.assertEqual(failure_review["review_purpose"], "REFOCUS_ON_RESPONSIBLE_PERSON_PUBLIC_REGISTRATION_CHAIN")
            self.assertIn("GUANGDONG-CREDIT-GD-HOME", failure_review["not_primary_source_profile_ids"])
            project = result["manifest"]["project_reports"][0]
            evidence = project["verification_evidence"]
            self.assertEqual(evidence["guangdong_local_field_query_probe_state"], "READY")
            self.assertEqual(evidence["guangdong_local_field_keyword_hit_count"], 1)
            self.assertEqual(
                evidence["release_evidence_matrix"][0]["project_level_readback_counts"][
                    "completion_acceptance_public_record"
                ],
                1,
            )
            self.assertEqual(
                evidence["release_evidence_matrix"][0]["matrix_state"],
                "RELEASE_SOURCE_READBACK_PRESENT_REVIEW_REQUIRED",
            )
            self.assertIn("GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY", evidence["guangdong_local_field_source_profile_ids"])
            self.assertEqual(
                evidence["local_credit_source_context"]["source_role"],
                "SUPPLEMENTARY_ONLY_NOT_PRIMARY_RESPONSIBLE_PERSON_CHAIN",
            )
            self.assertEqual(project["local_field_probe_state"]["task_count"], 2)
            self.assertEqual(project["local_field_probe_state"]["readback_ready_count"], 1)
            self.assertEqual(project["local_field_probe_state"]["no_match_review_required_count"], 1)
            self.assertTrue(project["local_field_probe_state"]["query_miss_is_not_clearance"])
            actions = [item["recommended_action"] for item in project["optimization_recommendations"]]
            for action in (
                "run_stage4_registration_probe",
                "flow_08_targeted_parse_if_stage4_unmatched",
                "retry_creditgd_later_only",
            ):
                self.assertIn(action, actions)
            for action in ("targeted_adapter_needed", "no_match_review_required"):
                self.assertNotIn(action, actions)
            report_text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "违法成立", "造假成立", "确认本人"):
                self.assertNotIn(term, report_text)
            self.assertTrue((root / "out" / "guangdong-local-field-query-failure-review.json").exists())


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


def _write_responsible_root(root: Path, *, flow_08_required: bool = False, not_applicable: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    item = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "early_probe_state": "RESPONSIBLE_PERSON_NOT_APPLICABLE"
        if not_applicable
        else "CERTIFICATE_READY_FROM_07"
        if not flow_08_required
        else "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
        "stage4_readiness_state": "STAGE4_NOT_APPLICABLE" if not_applicable else "READY_FOR_STAGE4_INPUT",
        "responsible_role": "not_applicable" if not_applicable else "project_manager",
        "flow_08_targeted_parse_required": flow_08_required,
        "candidate_groups": []
        if not_applicable
        else [
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


def _write_readiness_root(root: Path, *, flow_08_required: bool, resolved: bool = True, include_group: bool = True) -> None:
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
        "candidate_group_verification_records": [group] if include_group else [],
        "safe_to_closeout_evidence_report": resolved and not flow_08_required,
        "closeout_readiness_state": "EVIDENCE_REPORT_CLOSEOUT_READY" if resolved and not flow_08_required else "EVIDENCE_REPORT_CLOSEOUT_BLOCKED",
        "closeout_blocking_reasons": []
        if resolved and not flow_08_required and include_group
        else ["candidate_evidence_certificate_input_missing_parse_required"],
        "closeout_deferred_reasons": (
            ["parse_probe_manifest_missing_deferred_by_candidate_group_resolution"]
            if resolved and not flow_08_required
            else []
        ),
    }
    (root / "guangzhou-upstream-readiness-report.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "project_records": [project],
                    "summary": {
                        "safe_to_closeout_evidence_report": resolved and not flow_08_required,
                        "closeout_readiness_state": "EVIDENCE_REPORT_CLOSEOUT_READY"
                        if resolved and not flow_08_required
                        else "EVIDENCE_REPORT_CLOSEOUT_BLOCKED",
                        "closeout_deferred_reasons": (
                            ["parse_probe_manifest_missing_deferred_by_candidate_group_resolution"]
                            if resolved and not flow_08_required
                            else []
                        ),
                        "closeout_blocking_reasons": []
                        if resolved and not flow_08_required
                        else ["candidate_group_unresolved_flow08_required"],
                    },
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_active_conflict_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_record = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "task_ids": ["GZ-ACTIVE-CONFLICT-TASK-1"],
        "task_count": 1,
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_active_conflict_probe_v1_manifest",
            "project_task_records": [project_record],
            "summary": {
                "active_conflict_probe_task_count": 1,
                "probe_state": "READY",
            },
        }
    }
    (root / "guangzhou-active-conflict-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_gdcic_query_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_record = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "query_task_ids": ["GD-GDCIC-QUERY-1"],
        "query_task_count": 1,
        "readback_ready_count": 1,
        "blocker_taxonomy_counts": {"gdcic_public_query_empty_review": 1},
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_gdcic_query_probe_v1_manifest",
            "project_task_records": [project_record],
            "summary": {
                "probe_state": "READY",
                "gdcic_query_probe_task_count": 1,
                "gdcic_readback_ready_count": 1,
                "gdcic_blocker_taxonomy_counts": {"gdcic_public_query_empty_review": 1},
            },
        }
    }
    (root / "guangdong-gdcic-query-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_official_source_readback_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_record = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "official_source_readback_state": "OFFICIAL_SOURCE_READBACK_READY",
        "official_source_readback_ready_count": 3,
        "official_source_task_count": 3,
        "source_profile_ids": ["GUANGDONG-GDCIC-SKYPT-OPENPLATFORM"],
        "blocker_taxonomy_counts": {"gdcic_public_query_empty_review": 1},
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_official_source_readback_closeout_v1_manifest",
            "project_records": [project_record],
            "summary": {
                "closeout_state": "P2_OFFICIAL_READBACK_READY",
                "p2_closeout_state": "P2_OFFICIAL_READBACK_READY",
                "p2_ready": True,
                "official_source_readback_ready_count": 12,
                "official_source_project_ready_count": 1,
                "source_profile_readback_ready_counts": {
                    "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM": 12,
                },
                "blocker_taxonomy_counts": {"gdcic_public_query_empty_review": 1},
            },
        }
    }
    (root / "guangdong-official-source-readback-closeout-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_guangdong_local_verification_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_record = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "query_task_ids": ["GD-LOCAL-VERIFY-1", "GD-LOCAL-VERIFY-2"],
        "query_task_count": 6,
        "source_profile_ids": [
            "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
            "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
        ],
        "readback_ready_count": 2,
        "blocker_taxonomy_counts": {"guangdong_local_source_reachability_not_verified": 1},
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_local_verification_probe_v1_manifest",
            "project_task_records": [project_record],
            "summary": {
                "probe_state": "READY",
                "guangdong_local_verification_task_count": 6,
                "readback_ready_count": 2,
                "source_profile_task_counts": {
                    "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM": 1,
                    "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY": 1,
                },
                "blocker_taxonomy_counts": {"guangdong_local_source_reachability_not_verified": 1},
            },
        }
    }
    (root / "guangdong-local-verification-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_guangdong_local_field_query_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    field_tasks = [
        {
            "field_query_task_id": "GD-LOCAL-FIELD-1",
            "project_id": "PROJ-CN-GD-JG2026-10815",
            "project_name": "广州测试项目",
            "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
            "field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE",
            "field_readback_state": "PUBLIC_SOURCE_FIELD_READBACK_READY_REVIEW_REQUIRED",
            "readback_ready": True,
            "field_summary": {
                "matched_keyword_count": 1,
                "source_specific_adapter_id": "guangzhou_zfcj_multi_public_api_query_v1",
            },
            "field_match_summary": {
                "source_specific_records": [
                    {"administrative_counterparty": "广州测试建设有限公司"},
                    {
                        "source_specific_adapter_id": "guangzhou_zfcj_completion_acceptance_public_api_v1",
                        "record_type": "completion_acceptance_public_record",
                        "completion_filing_no": "穗竣备2026-001",
                    },
                ],
                "query_miss_is_not_clearance": True,
            },
            "blocker_taxonomy": [],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        {
            "field_query_task_id": "GD-LOCAL-FIELD-2",
            "project_id": "PROJ-CN-GD-JG2026-10815",
            "project_name": "广州测试项目",
            "source_profile_id": "GUANGDONG-CREDIT-GD-HOME",
            "field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED",
            "field_readback_state": "PUBLIC_SOURCE_QUERIED_NO_FIELD_MATCH",
            "readback_ready": False,
            "field_summary": {
                "public_list_record_count": 2,
                "source_specific_adapter_id": "guangdong_credit_gd_public_credit_query_v1",
            },
            "field_match_summary": {"query_miss_is_not_clearance": True},
            "blocker_taxonomy": [
                "gd_credit_gd_targeted_query_deferred_by_site_guard",
                "gd_credit_gd_rate_limited_or_temporary_unavailable",
                "gd_credit_gd_public_list_rendered_fallback_ready",
            ],
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    ]
    project_record = {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "field_query_task_ids": ["GD-LOCAL-FIELD-1", "GD-LOCAL-FIELD-2"],
        "field_query_task_count": 6,
        "source_profile_ids": [
            "GUANGDONG-CREDIT-GD-HOME",
            "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
        ],
        "readback_ready_count": 1,
        "keyword_hit_count": 1,
        "source_profile_task_counts": {
            "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY": 1,
            "GUANGDONG-CREDIT-GD-HOME": 1,
        },
        "field_query_probe_state_counts": {
            "FIELD_READBACK_READY_PUBLIC_SOURCE": 1,
            "NO_FIELD_MATCH_REVIEW_REQUIRED": 1,
        },
        "blocker_taxonomy_counts": {
            "gd_credit_gd_targeted_query_deferred_by_site_guard": 1,
            "gd_credit_gd_rate_limited_or_temporary_unavailable": 1,
            "gd_credit_gd_public_list_rendered_fallback_ready": 1,
        },
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_local_field_query_probe_v1_manifest",
            "project_task_records": [project_record],
            "field_task_records": field_tasks,
            "summary": {
                "probe_state": "READY",
                "guangdong_local_field_query_task_count": 6,
                "readback_ready_count": 1,
                "keyword_hit_task_count": 1,
                "source_profile_task_counts": {
                    "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY": 1,
                    "GUANGDONG-CREDIT-GD-HOME": 1,
                },
                "field_query_probe_state_counts": {
                    "FIELD_READBACK_KEYWORD_HIT_PUBLIC_SOURCE": 1,
                    "NO_FIELD_MATCH_REVIEW_REQUIRED": 5,
                },
                "blocker_taxonomy_counts": {
                    "gd_credit_gd_targeted_query_deferred_by_site_guard": 1,
                    "gd_credit_gd_rate_limited_or_temporary_unavailable": 1,
                    "gd_credit_gd_public_list_rendered_fallback_ready": 1,
                },
            },
        }
    }
    (root / "guangdong-local-field-query-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
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
