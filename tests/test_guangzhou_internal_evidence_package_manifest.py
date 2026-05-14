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

from storage.guangzhou_internal_evidence_package_manifest import (  # noqa: E402
    build_guangzhou_internal_evidence_package_manifest,
)


class GuangzhouInternalEvidencePackageManifestTests(unittest.TestCase):
    def test_builds_internal_manifest_for_five_projects_and_twelve_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence")
            _write_certificate_supplement(root / "certificate")
            _write_official_source(root / "official")
            _write_stage4(root / "stage4")
            _write_download(root / "download")
            _write_flow(root / "flow")

            result = build_guangzhou_internal_evidence_package_manifest(
                evidence_report_root=root / "evidence",
                certificate_supplement_root=root / "certificate",
                official_source_readback_root=root / "official",
                stage4_execution_root=root / "stage4",
                download_root=root / "download",
                flow_root=root / "flow",
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["internal_package_state"], "P7_INTERNAL_EVIDENCE_PACKAGE_READY")
            self.assertEqual(summary["project_count"], 5)
            self.assertEqual(summary["candidate_group_count"], 12)
            self.assertEqual(summary["certificate_resolved_group_count"], 12)
            self.assertEqual(summary["flow_08_targeted_parse_required_count"], 0)
            self.assertEqual(summary["forbidden_term_scan_state"], "PASS")
            self.assertFalse(summary["customer_delivery_ready"])
            self.assertEqual(summary["trusted_timestamp_state"], "RESERVED_NOT_IMPLEMENTED")
            self.assertEqual(summary["notary_state"], "RESERVED_NOT_IMPLEMENTED")
            manifest = result["manifest"]
            self.assertFalse(manifest["customer_delivery_ready"])
            self.assertTrue(manifest["approval_required_before_customer_delivery"])
            self.assertFalse(manifest["customer_visible_allowed"])
            self.assertTrue(manifest["no_legal_conclusion"])
            self.assertEqual(manifest["forbidden_term_scan"]["scan_state"], "PASS")
            self.assertEqual(len(manifest["project_records"]), 5)
            self.assertEqual(len(manifest["candidate_group_records"]), 12)
            self.assertGreater(len(manifest["source_fixation_records"]), 0)
            self.assertGreater(len(manifest["field_lineage_records"]), 0)
            self.assertGreater(len(manifest["reverse_explanation_records"]), 0)
            self.assertTrue((root / "out" / "internal-evidence-package-manifest-v1.json").exists())

    def test_missing_snapshot_or_hash_is_fixation_gap_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", project_count=1, groups_per_project=[1])
            _write_certificate_supplement(root / "certificate", project_count=1, groups_per_project=[1])
            _write_official_source(root / "official", project_count=1, groups_per_project=[1])
            _write_stage4(root / "stage4", project_count=1, groups_per_project=[1])
            _write_download(root / "download", project_count=1, groups_per_project=[1], include_snapshot=False)
            _write_flow(root / "flow", project_count=1)

            result = build_guangzhou_internal_evidence_package_manifest(
                evidence_report_root=root / "evidence",
                certificate_supplement_root=root / "certificate",
                official_source_readback_root=root / "official",
                stage4_execution_root=root / "stage4",
                download_root=root / "download",
                flow_root=root / "flow",
                output_root=root / "out",
            )

            self.assertTrue(result["safe_to_execute"])
            gap_records = [
                record
                for record in result["manifest"]["source_fixation_records"]
                if record["fixation_state"] == "FIXATION_GAP_REVIEW"
            ]
            self.assertGreater(len(gap_records), 0)
            self.assertEqual(result["summary"]["fixation_completeness_state"], "SOURCE_FIXATION_PARTIAL_REVIEW")
            self.assertGreater(result["summary"]["fixation_gap_count"], 0)
            self.assertTrue(any("snapshot_or_readback_ref_missing" in record["fixation_gap_reasons"] for record in gap_records))

    def test_internal_manifest_does_not_export_raw_blobs_or_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence")
            _write_certificate_supplement(root / "certificate")
            _write_official_source(root / "official")
            _write_stage4(root / "stage4")
            _write_download(root / "download")
            _write_flow(root / "flow")

            result = build_guangzhou_internal_evidence_package_manifest(
                evidence_report_root=root / "evidence",
                certificate_supplement_root=root / "certificate",
                official_source_readback_root=root / "official",
                stage4_execution_root=root / "stage4",
                download_root=root / "download",
                flow_root=root / "flow",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["safety"]["manifest_stores_raw_html_or_blob"])
            self.assertFalse(result["manifest"]["redaction_log"]["raw_html_blob_exported"])
            self.assertFalse(result["manifest"]["redaction_log"]["raw_pdf_or_office_blob_exported"])
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _project_ids(project_count: int) -> list[str]:
    return [f"PROJ-CN-GD-JG2026-{10000 + idx}" for idx in range(project_count)]


def _groups_per_project(project_count: int, groups_per_project: list[int] | None = None) -> list[int]:
    if groups_per_project is not None:
        return groups_per_project
    if project_count == 5:
        return [3, 3, 3, 2, 1]
    return [1 for _ in range(project_count)]


def _write_evidence_report(root: Path, *, project_count: int = 5, groups_per_project: list[int] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    projects = []
    total_groups = 0
    for idx, project_id in enumerate(_project_ids(project_count)):
        groups = [_group(project_id, group_idx) for group_idx in range(_groups_per_project(project_count, groups_per_project)[idx])]
        total_groups += len(groups)
        projects.append(
            {
                "project_id": project_id,
                "project_name": f"广州测试项目 {idx}",
                "verification_evidence": {
                    "project_id": project_id,
                    "project_name": f"广州测试项目 {idx}",
                    "candidate_group_records": groups,
                    "candidate_group_count": len(groups),
                    "resolved_candidate_group_count": len(groups),
                    "public_registration_match_state": "PUBLIC_REGISTRATION_MATCHED",
                    "flow_08_targeted_parse_required": False,
                    "flow_08_registry": {
                        "flow_08_present": True,
                        "source_urls": [f"https://example.test/{project_id}/08.html"],
                        "attachment_count": 2,
                    },
                    "candidate_notice_source_urls": [f"https://example.test/{project_id}/07.html"],
                    "project_source_urls": [f"https://example.test/{project_id}/{flow}.html" for flow in ("03", "07", "08")],
                    "official_source_readback_state": "OFFICIAL_SOURCE_READBACK_READY",
                    "official_source_readback_ready_count": len(groups),
                    "gdcic_readback_classification_counts": {
                        "PERSON_REGISTRATION_READBACK": len(groups),
                        "COMPANY_PROJECT_READBACK": len(groups),
                    },
                    "gdcic_field_availability_counts": {"person_name": len(groups), "company_name": len(groups)},
                    "gdcic_missing_field_counts": {"certificate_no": len(groups)},
                    "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
                },
                "process_stability": {
                    "evidence_report_closeout_state": "EVIDENCE_REPORT_CLOSEOUT_READY",
                    "safe_to_closeout_evidence_report": True,
                },
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_evidence_report_v1_manifest",
            "adapter_id": "guangzhou-evidence-report-v1-builder",
            "manifest_id": "EVIDENCE-FAKE",
            "created_at": "2026-05-14T00:00:00+08:00",
            "project_reports": projects,
            "summary": {
                "project_count": project_count,
                "candidate_group_count": total_groups,
                "resolved_candidate_group_count": total_groups,
                "flow_08_targeted_parse_required_project_count": 0,
            },
        }
    }
    (root / "guangzhou-evidence-report-v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _group(project_id: str, group_idx: int) -> dict[str, object]:
    return {
        "candidate_group_id": f"{project_id}-G{group_idx}",
        "candidate_group_order": str(group_idx + 1),
        "candidate_group_members": [f"广州候选公司 {project_id}-{group_idx}"],
        "matched_company_names": [f"广州候选公司 {project_id}-{group_idx}"],
        "responsible_person_name": f"负责人{group_idx}",
        "responsible_role": "project_manager",
        "certificate_no": "",
        "bid_price": f"{1000 + group_idx}.00",
        "rank": str(group_idx + 1),
        "group_resolution_state": "PUBLIC_REGISTRATION_MATCHED",
        "flow_08_targeted_parse_required": False,
    }


def _write_certificate_supplement(root: Path, *, project_count: int = 5, groups_per_project: list[int] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_records = []
    group_records = []
    for idx, project_id in enumerate(_project_ids(project_count)):
        groups = []
        for group_idx in range(_groups_per_project(project_count, groups_per_project)[idx]):
            group = {
                "project_id": project_id,
                "project_name": f"广州测试项目 {idx}",
                "candidate_group_id": f"{project_id}-G{group_idx}",
                "candidate_group_order": str(group_idx + 1),
                "candidate_group_members": [f"广州候选公司 {project_id}-{group_idx}"],
                "responsible_person_name": f"负责人{group_idx}",
                "certificate_supplement_state": "CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4",
                "certificate_no": f"粤14420202021{group_idx:04d}",
                "registered_unit_name": f"广州候选公司 {project_id}-{group_idx}",
                "registration_category": "注册建造师",
                "matched_company_name": f"广州候选公司 {project_id}-{group_idx}",
                "personnel_public_source_url": f"https://jzsc.example.test/person/{project_id}-{group_idx}",
                "flow_08_targeted_parse_required": False,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
            groups.append(group)
            group_records.append(group)
        project_records.append(
            {
                "project_id": project_id,
                "project_name": f"广州测试项目 {idx}",
                "candidate_group_count": len(groups),
                "certificate_resolved_group_count": len(groups),
                "certificate_unresolved_group_count": 0,
                "flow_08_targeted_parse_required_count": 0,
                "gdcic_certificate_field_gap_compensated_by_stage4_count": len(groups),
                "certificate_supplement_group_records": groups,
            }
        )
    payload = {
        "manifest": {
            "manifest_kind": "certificate_supplement_closeout_v1_manifest",
            "adapter_id": "certificate-supplement-closeout-v1",
            "created_at": "2026-05-14T00:00:00+08:00",
            "project_records": project_records,
            "certificate_supplement_group_records": group_records,
            "summary": {
                "closeout_state": "P6_CERTIFICATE_SUPPLEMENT_READY",
                "project_count": project_count,
                "candidate_group_count": len(group_records),
                "certificate_resolved_group_count": len(group_records),
                "certificate_unresolved_group_count": 0,
                "flow_08_targeted_parse_required_count": 0,
                "gdcic_certificate_field_gap_compensated_by_stage4_count": len(group_records),
            },
        }
    }
    (root / "certificate-supplement-closeout-v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_official_source(root: Path, *, project_count: int = 5, groups_per_project: list[int] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_records = []
    classification_records = []
    total = 0
    for idx, project_id in enumerate(_project_ids(project_count)):
        group_count = _groups_per_project(project_count, groups_per_project)[idx]
        total += group_count
        project_records.append(
            {
                "project_id": project_id,
                "project_name": f"广州测试项目 {idx}",
                "official_source_readback_state": "OFFICIAL_SOURCE_READBACK_READY",
                "official_source_readback_ready_count": group_count,
                "gdcic_readback_classification_counts": {"PERSON_REGISTRATION_READBACK": group_count},
                "gdcic_field_availability_counts": {"person_name": group_count, "company_name": group_count},
                "gdcic_missing_field_counts": {"certificate_no": group_count},
                "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
                "blocker_taxonomy_counts": {"gdcic_public_query_empty_review": 1},
            }
        )
        for group_idx in range(group_count):
            classification_records.append(
                {
                    "query_task_id": f"GDCIC-{project_id}-{group_idx}",
                    "project_id": project_id,
                    "project_name": f"广州测试项目 {idx}",
                    "candidate_group_id": f"{project_id}-G{group_idx}",
                    "responsible_person_name": f"负责人{group_idx}",
                    "certificate_no": f"粤14420202021{group_idx:04d}",
                    "readback_ready": True,
                    "query_probe_state": "READBACK_READY_PUBLIC_SOURCE",
                    "classification_tags": ["PERSON_REGISTRATION_READBACK"],
                    "field_summary_probe": {"record_count": 1, "sample_person_names": [f"*责人{group_idx}"]},
                    "query_miss_is_not_clearance": True,
                }
            )
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_official_source_readback_closeout_v1_manifest",
            "adapter_id": "guangdong-official-source-readback-closeout-v1",
            "created_at": "2026-05-14T00:00:00+08:00",
            "project_records": project_records,
            "project_gdcic_classification_records": classification_records,
            "summary": {
                "closeout_state": "P2_OFFICIAL_READBACK_READY",
                "official_source_readback_ready_count": total,
                "project_count": project_count,
                "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
                "query_miss_is_not_clearance": True,
            },
        }
    }
    (root / "guangdong-official-source-readback-closeout-v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_stage4(root: Path, *, project_count: int = 5, groups_per_project: list[int] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for idx, project_id in enumerate(_project_ids(project_count)):
        for group_idx in range(_groups_per_project(project_count, groups_per_project)[idx]):
            items.append(
                {
                    "job_id": f"JOB-{project_id}-{group_idx}",
                    "project_id": project_id,
                    "project_name": f"广州测试项目 {idx}",
                    "flow_no": "07",
                    "flow_title": "中标候选人公示",
                    "candidate_group_id": f"{project_id}-G{group_idx}",
                    "candidate_company_name": f"广州候选公司 {project_id}-{group_idx}",
                    "responsible_person_name": f"负责人{group_idx}",
                    "stage4_execution_state": "READBACK_READY",
                    "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                    "resolved_certificate_no_optional": f"粤14420202021{group_idx:04d}",
                    "registered_unit_name_optional": f"广州候选公司 {project_id}-{group_idx}",
                    "required_registration_category_optional": "注册建造师",
                    "matched_company_name_optional": f"广州候选公司 {project_id}-{group_idx}",
                    "company_personnel_source_url": f"https://jzsc.example.test/company/{project_id}-{group_idx}",
                    "company_personnel_source_snapshot_id": f"SNAP-COMPANY-{project_id}-{group_idx}",
                    "personnel_project_source_url": f"https://jzsc.example.test/person/{project_id}-{group_idx}",
                    "personnel_project_source_snapshot_id": f"SNAP-PERSON-{project_id}-{group_idx}",
                    "created_at": "2026-05-14T00:00:00+08:00",
                }
            )
    payload = {
        "manifest": {
            "manifest_kind": "company_first_stage4_execution_manifest",
            "adapter_id": "company-first-stage4-execution",
            "created_at": "2026-05-14T00:00:00+08:00",
            "items": items,
            "summary": {"job_count": len(items), "project_count": project_count},
        }
    }
    (root / "company-first-stage4-execution.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_download(
    root: Path,
    *,
    project_count: int = 5,
    groups_per_project: list[int] | None = None,
    include_snapshot: bool = True,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for project_id in _project_ids(project_count):
        refs = []
        if include_snapshot:
            refs.append(
                {
                    "snapshot_id": f"DETAIL-{project_id}",
                    "source_url": f"https://example.test/{project_id}/07.html",
                    "parse_state": "NOT_RUN_DOWNLOAD_PROBE",
                    "guangzhou_flow_no": "07",
                    "guangzhou_flow_title": "中标候选人公示",
                    "content_type": "text/html",
                    "byte_size": 1200,
                    "sha256": "a" * 64,
                    "readback_state": "READBACK_READY",
                    "human_readable_path": f"projects/{project_id}/07/detail.html",
                }
            )
        items.append(
            {
                "project_id": project_id,
                "project_name": f"广州测试项目 {project_id}",
                "source_url": f"https://example.test/{project_id}/07.html",
                "guangzhou_flow_no": "07",
                "guangzhou_flow_title": "中标候选人公示",
                "published_at_optional": "2026-05-10",
                "created_at": "2026-05-14T00:00:00+08:00",
                "detail_snapshot_refs": refs,
                "attachment_snapshot_refs": [],
            }
        )
    payload = {
        "manifest": {
            "manifest_kind": "download_probe_manifest",
            "adapter_id": "guangzhou-download-probe",
            "created_at": "2026-05-14T00:00:00+08:00",
            "project_sample_items": items,
            "summary": {"project_sample_count": len(items), "attachment_snapshot_count": len(items) if include_snapshot else 0},
        }
    }
    (root / "download-probe-manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_flow(root: Path, *, project_count: int = 5) -> None:
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for project_id in _project_ids(project_count):
        for flow in ("03", "07", "08"):
            items.append(
                {
                    "project_id": project_id,
                    "project_name": f"广州测试项目 {project_id}",
                    "source_url": f"https://example.test/{project_id}/{flow}.html",
                    "guangzhou_flow_no": flow,
                    "guangzhou_flow_title": {"03": "招标公告/关联公告", "07": "中标候选人公示", "08": "投标文件公开"}[flow],
                    "published_at_optional": "2026-05-10",
                    "guangzhou_flow_folder": f"projects/{project_id}/{flow}",
                }
            )
    payload = {
        "manifest": {
            "manifest_kind": "real_sample_execution_manifest",
            "adapter_id": "guangzhou-flowurl-runner",
            "created_at": "2026-05-14T00:00:00+08:00",
            "project_sample_items": items,
            "summary": {"unique_project_count": project_count, "project_sample_count": len(items)},
        }
    }
    (root / "run-manifest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
