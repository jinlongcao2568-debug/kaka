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

from storage.certificate_supplement_closeout import build_certificate_supplement_closeout  # noqa: E402


class CertificateSupplementCloseoutTests(unittest.TestCase):
    def test_gdcic_gap_is_compensated_by_stage4_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence")
            _write_stage4_execution(root / "stage4")
            _write_official_source(root / "official")

            result = build_certificate_supplement_closeout(
                evidence_report_root=root / "evidence",
                stage4_execution_root=root / "stage4",
                official_source_readback_root=root / "official",
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

        summary = result["summary"]
        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(summary["closeout_state"], "P6_CERTIFICATE_SUPPLEMENT_READY")
        self.assertEqual(summary["candidate_group_count"], 1)
        self.assertEqual(summary["certificate_resolved_group_count"], 1)
        self.assertEqual(summary["gdcic_certificate_field_gap_compensated_by_stage4_count"], 1)
        group = result["manifest"]["certificate_supplement_group_records"][0]
        self.assertEqual(group["certificate_supplement_state"], "CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4")
        self.assertEqual(group["certificate_no"], "粤1442020202104300")
        self.assertEqual(group["registered_unit_name"], "广州市第三建筑工程有限公司")
        self.assertFalse(group["flow_08_targeted_parse_required"])

    def test_any_consortium_member_resolution_closes_group_without_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", members=["广东主办公司", "广东成员公司"])
            _write_stage4_execution(
                root / "stage4",
                stage4_items=[
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11021",
                        "project_name": "测试项目",
                        "candidate_group_id": "G1",
                        "candidate_company_name": "广东主办公司",
                        "responsible_person_name": "张三",
                        "stage4_execution_state": "FAIL_CLOSED",
                        "supplement_after_execution_state": "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED",
                    },
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11021",
                        "project_name": "测试项目",
                        "candidate_group_id": "G1",
                        "candidate_company_name": "广东成员公司",
                        "responsible_person_name": "张三",
                        "stage4_execution_state": "READBACK_READY",
                        "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                        "resolved_certificate_no_optional": "粤2442020202104300",
                        "registered_unit_name_optional": "广东成员公司",
                    },
                ],
            )
            _write_official_source(root / "official")

            result = build_certificate_supplement_closeout(
                evidence_report_root=root / "evidence",
                stage4_execution_root=root / "stage4",
                official_source_readback_root=root / "official",
                output_root=root / "out",
            )

        group = result["manifest"]["certificate_supplement_group_records"][0]
        self.assertEqual(group["certificate_supplement_state"], "CERTIFICATE_SUPPLEMENT_RESOLVED_BY_STAGE4")
        self.assertEqual(group["matched_company_name"], "广东成员公司")
        self.assertNotIn("冲突成立", json.dumps(result, ensure_ascii=False))

    def test_unresolved_without_flow08_stays_review_and_does_not_auto_trigger_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", source_certificate_no="")
            _write_stage4_execution(root / "stage4", resolved=False)
            _write_official_source(root / "official")

            result = build_certificate_supplement_closeout(
                evidence_report_root=root / "evidence",
                stage4_execution_root=root / "stage4",
                official_source_readback_root=root / "official",
                output_root=root / "out",
            )

        summary = result["summary"]
        group = result["manifest"]["certificate_supplement_group_records"][0]
        self.assertEqual(summary["closeout_state"], "P6_CERTIFICATE_SUPPLEMENT_REVIEW_REQUIRED")
        self.assertEqual(group["certificate_supplement_state"], "CERTIFICATE_SUPPLEMENT_UNRESOLVED_REVIEW")
        self.assertFalse(group["flow_08_targeted_parse_required"])
        self.assertEqual(group["next_action"], "RETRY_PUBLIC_REGISTRATION_SOURCE_OR_NAME_ENUMERATION")

    def test_existing_flow08_trigger_blocks_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence", source_certificate_no="", flow08_required=True)
            _write_stage4_execution(root / "stage4", resolved=False, flow08_required=True)
            _write_official_source(root / "official")

            result = build_certificate_supplement_closeout(
                evidence_report_root=root / "evidence",
                stage4_execution_root=root / "stage4",
                official_source_readback_root=root / "official",
                output_root=root / "out",
            )

        group = result["manifest"]["certificate_supplement_group_records"][0]
        self.assertEqual(group["certificate_supplement_state"], "FLOW_08_TARGETED_PARSE_REQUIRED_AFTER_SUPPLEMENT")
        self.assertEqual(result["summary"]["flow_08_targeted_parse_required_count"], 1)
        self.assertEqual(result["summary"]["closeout_state"], "P6_CERTIFICATE_SUPPLEMENT_REVIEW_REQUIRED")

    def test_writes_manifest_and_avoids_forbidden_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report(root / "evidence")
            _write_stage4_execution(root / "stage4")
            _write_official_source(root / "official")

            result = build_certificate_supplement_closeout(
                evidence_report_root=root / "evidence",
                stage4_execution_root=root / "stage4",
                official_source_readback_root=root / "official",
                output_root=root / "out",
            )

            self.assertTrue((root / "out" / "certificate-supplement-closeout-v1.json").exists())
            text = json.dumps(result, ensure_ascii=False)
            for term in ("确认本人", "无风险", "无冲突", "冲突成立", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_evidence_report(
    root: Path,
    *,
    members: list[str] | None = None,
    source_certificate_no: str = "",
    flow08_required: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    group = {
        "candidate_group_id": "G1",
        "candidate_group_order": "1",
        "candidate_group_members": members or ["广州市第三建筑工程有限公司"],
        "responsible_person_name": "张三",
        "certificate_no": source_certificate_no,
        "matched_company_names": members or ["广州市第三建筑工程有限公司"],
        "group_resolution_state": "RESOLVED_BY_CONSORTIUM_MEMBER" if source_certificate_no else "PENDING_STAGE4_PUBLIC_REGISTRATION_MATCH",
        "flow_08_targeted_parse_required": flow08_required,
    }
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_evidence_report_v1_manifest",
            "project_reports": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-11021",
                    "project_name": "测试项目",
                    "verification_evidence": {
                        "project_id": "PROJ-CN-GD-JG2026-11021",
                        "project_name": "测试项目",
                        "candidate_group_records": [group],
                        "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
                    },
                }
            ],
            "summary": {"project_count": 1},
        }
    }
    (root / "guangzhou-evidence-report-v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_stage4_execution(
    root: Path,
    *,
    resolved: bool = True,
    flow08_required: bool = False,
    stage4_items: list[dict[str, object]] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    item = {
        "project_id": "PROJ-CN-GD-JG2026-11021",
        "project_name": "测试项目",
        "candidate_group_id": "G1",
        "candidate_company_name": "广州市第三建筑工程有限公司",
        "responsible_person_name": "张三",
        "stage4_execution_state": "READBACK_READY" if resolved else "FAIL_CLOSED",
        "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED" if resolved else "NAME_ENUMERATION_FALLBACK_REQUIRED",
        "resolved_certificate_no_optional": "粤1442020202104300" if resolved else "",
        "registered_unit_name_optional": "广州市第三建筑工程有限公司" if resolved else "",
        "required_registration_category_optional": "注册建造师" if resolved else "",
        "matched_company_name_optional": "广州市第三建筑工程有限公司" if resolved else "",
        "personnel_project_source_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=zhangsan" if resolved else "",
        "flow_08_targeted_parse_required": flow08_required,
    }
    payload = {
        "manifest": {
            "manifest_kind": "company_first_stage4_execution_manifest",
            "items": stage4_items if stage4_items is not None else [item],
        }
    }
    (root / "company-first-stage4-execution.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_official_source(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_official_source_readback_closeout_v1_manifest",
            "project_records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-11021",
                    "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
                }
            ],
            "summary": {
                "gdcic_certificate_field_availability_state": "GDCIC_CERTIFICATE_FIELDS_NOT_RETURNED_IN_CURRENT_READBACK",
            },
        }
    }
    (root / "guangdong-official-source-readback-closeout-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
