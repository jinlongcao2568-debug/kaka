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

from storage.guangdong_official_source_readback_closeout import (  # noqa: E402
    build_guangdong_official_source_readback_closeout,
)


class GuangdongOfficialSourceReadbackCloseoutTests(unittest.TestCase):
    def test_gdcic_readback_ready_outputs_p2_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_gdcic_root(root / "gdcic", readback_ready_count=12)
            _write_evidence_report_root(root / "evidence")

            result = build_guangdong_official_source_readback_closeout(
                gdcic_query_probe_root=root / "gdcic",
                evidence_report_root=root / "evidence",
                guangdong_local_field_query_root=None,
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["p2_closeout_state"], "P2_OFFICIAL_READBACK_READY")
            self.assertEqual(summary["closeout_state"], "P2_OFFICIAL_READBACK_READY")
            self.assertTrue(summary["p2_ready"])
            self.assertEqual(summary["official_source_readback_ready_count"], 12)
            self.assertEqual(
                summary["source_profile_readback_ready_counts"],
                {"GUANGDONG-GDCIC-SKYPT-OPENPLATFORM": 12},
            )
            self.assertEqual(
                summary["gdcic_readback_classification_counts"],
                {
                    "BLOCKED_OR_CAPTCHA_REVIEW": 1,
                    "CERTIFICATE_FIELD_READBACK": 1,
                    "COMPANY_PROJECT_READBACK": 1,
                    "EMPTY_PUBLIC_RESULT_REVIEW": 1,
                    "PERSON_REGISTRATION_READBACK": 1,
                },
            )
            project = result["manifest"]["project_records"][0]
            self.assertEqual(project["official_source_readback_state"], "OFFICIAL_SOURCE_READBACK_READY")
            self.assertEqual(len(project["gdcic_readback_classification_records"]), 1)
            self.assertIn("PERSON_REGISTRATION_READBACK", project["gdcic_readback_classification_records"][0]["classification_tags"])
            report_text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立"):
                self.assertNotIn(term, report_text)
            self.assertTrue((root / "out" / "guangdong-official-source-readback-closeout-v1.json").exists())

    def test_empty_or_blocked_gdcic_does_not_clear_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_gdcic_root(root / "gdcic", readback_ready_count=0)
            _write_evidence_report_root(root / "evidence")

            result = build_guangdong_official_source_readback_closeout(
                gdcic_query_probe_root=root / "gdcic",
                evidence_report_root=root / "evidence",
                guangdong_local_field_query_root=None,
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["p2_closeout_state"], "P2_OFFICIAL_READBACK_REVIEW_REQUIRED")
            self.assertFalse(summary["p2_ready"])
            self.assertEqual(summary["official_source_readback_ready_count"], 0)
            self.assertEqual(summary["blocker_taxonomy_counts"], {"gdcic_captcha_required": 1})
            self.assertEqual(summary["gdcic_readback_classification_counts"], {"BLOCKED_OR_CAPTCHA_REVIEW": 1})
            self.assertNotIn("无风险", json.dumps(result, ensure_ascii=False))
            self.assertNotIn("无冲突", json.dumps(result, ensure_ascii=False))

    def test_missing_gdcic_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_report_root(root / "evidence")

            result = build_guangdong_official_source_readback_closeout(
                gdcic_query_probe_root=root / "missing-gdcic",
                evidence_report_root=root / "evidence",
                guangdong_local_field_query_root=None,
                output_root=root / "out",
                created_at="2026-05-14T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["p2_closeout_state"], "INPUT_BLOCKED")
            self.assertIn("gdcic_query_probe_missing", result["blocking_reasons"])


def _write_gdcic_root(root: Path, *, readback_ready_count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    project_readback = min(readback_ready_count, 3)
    blocker_counts = {"gdcic_captcha_required": 1} if readback_ready_count == 0 else {"gdcic_public_query_empty_review": 1}
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_gdcic_query_probe_v1_manifest",
            "project_task_records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "广州测试项目",
                    "query_task_ids": ["GD-GDCIC-QUERY-1"],
                    "query_task_count": 3,
                    "readback_ready_count": project_readback,
                    "blocker_taxonomy_counts": blocker_counts,
                }
            ],
            "query_task_records": [
                _gdcic_task_payload(readback_ready_count=readback_ready_count, blocker_counts=blocker_counts)
            ],
            "summary": {
                "probe_state": "READY",
                "gdcic_query_probe_task_count": 12,
                "gdcic_readback_ready_count": readback_ready_count,
                "query_probe_state_counts": {
                    "READBACK_READY_PUBLIC_SOURCE": readback_ready_count,
                    "REVIEW_REQUIRED": 0 if readback_ready_count else 12,
                },
                "gdcic_blocker_taxonomy_counts": blocker_counts,
            },
        }
    }
    (root / "guangdong-gdcic-query-probe-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _gdcic_task_payload(*, readback_ready_count: int, blocker_counts: dict[str, int]) -> dict[str, object]:
    if readback_ready_count:
        return {
            "query_task_id": "GD-GDCIC-QUERY-1",
            "project_id": "PROJ-CN-GD-JG2026-10815",
            "project_name": "广州测试项目",
            "candidate_group_id": "GROUP-1",
            "responsible_person_name": "张三",
            "certificate_no": "粤144202600001",
            "readback_ready": True,
            "query_probe_state": "READBACK_READY_PUBLIC_SOURCE",
            "field_summary": {
                "record_count": 3,
                "sample_project_names": ["广州历史项目"],
                "sample_company_names": ["广州测试建设有限公司"],
                "sample_person_names": ["*三"],
                "sample_certificate_nos": ["粤144202600001"],
                "sample_id_card_hashes": ["hash-1"],
            },
            "blocker_taxonomy": list(blocker_counts.keys()),
            "route_attempts": [
                {
                    "route_id": "person_in_gd_by_name",
                    "route_state": "READBACK_READY_PUBLIC_SOURCE",
                    "field_summary": {
                        "record_count": 1,
                        "sample_person_names": ["*三"],
                        "sample_id_card_hashes": ["hash-1"],
                    },
                    "blocker_taxonomy": [],
                },
                {
                    "route_id": "project_bidding_by_company",
                    "route_state": "READBACK_READY_PUBLIC_SOURCE",
                    "field_summary": {
                        "record_count": 1,
                        "sample_project_names": ["广州历史项目"],
                        "sample_company_names": ["广州测试建设有限公司"],
                        "sample_certificate_nos": ["粤144202600001"],
                    },
                    "blocker_taxonomy": [],
                },
                {
                    "route_id": "person_into_gd_by_name_company",
                    "route_state": "REVIEW_REQUIRED",
                    "field_summary": {},
                    "blocker_taxonomy": ["gdcic_public_query_empty_review"],
                },
                {
                    "route_id": "person_in_gd_by_name",
                    "route_state": "FAIL_CLOSED_CAPTCHA_REQUIRED",
                    "field_summary": {},
                    "blocker_taxonomy": ["gdcic_captcha_required"],
                },
            ],
        }
    return {
        "query_task_id": "GD-GDCIC-QUERY-1",
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "广州测试项目",
        "candidate_group_id": "GROUP-1",
        "responsible_person_name": "张三",
        "certificate_no": "",
        "readback_ready": False,
        "query_probe_state": "FAIL_CLOSED_CAPTCHA_REQUIRED",
        "field_summary": {},
        "blocker_taxonomy": list(blocker_counts.keys()),
        "route_attempts": [
            {
                "route_id": "person_in_gd_by_name",
                "route_state": "FAIL_CLOSED_CAPTCHA_REQUIRED",
                "field_summary": {},
                "blocker_taxonomy": ["gdcic_captcha_required"],
            }
        ],
    }


def _write_evidence_report_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "manifest_kind": "guangzhou_evidence_report_v1_manifest",
            "project_reports": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "广州测试项目",
                    "verification_evidence": {},
                    "process_stability": {},
                }
            ],
            "summary": {
                "project_count": 1,
                "candidate_group_count": 3,
            },
        }
    }
    (root / "guangzhou-evidence-report-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
