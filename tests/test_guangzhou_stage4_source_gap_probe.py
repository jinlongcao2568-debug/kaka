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

from storage.guangzhou_stage4_source_gap_probe import build_guangzhou_stage4_source_gap_probe  # noqa: E402


class GuangzhouStage4SourceGapProbeTests(unittest.TestCase):
    def test_classifies_covered_empty_and_query_error_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_run_result(root / "run-result.json")
            _write_candidate_pressure(root / "candidate-pressure-table.json")

            def fake_getter(url: str, params: dict[str, str]) -> dict[str, object]:
                if "project/list" in url:
                    return {"rows": [{"projectCode": "GC001", "projectName": "广州候选项目"}], "total": 1}
                if "constructionPermit" in url:
                    return {"rows": [], "total": 0}
                if "projectContract" in url:
                    return {"rows": [{"projectCode": "GC001", "projectName": "广州候选项目"}], "total": 1}
                if "projectAcceptanceArchive" in url:
                    return {"rows": [], "total": 0}
                if "finishCheck" in url:
                    return {"rows": [], "total": 0}
                if "memberInvolvedProject" in url:
                    return {"rows": [{"memberName": "张三", "postName": "项目经理", "orgName": "广州甲公司"}], "total": 1}
                if "performance/list" in url:
                    return {"rows": [], "total": 0}
                if "enterprisePunishment" in url:
                    raise RuntimeError("punishment query down")
                if "enterpriseBackpay" in url:
                    return {"rows": [], "total": 0}
                if "enterpriseBlacklist" in url:
                    return {"rows": [], "total": 0}
                if "personIntoGd" in url:
                    return {"rows": [{"name": "张三", "entName": "广州甲公司"}], "total": 1}
                if "personInGd" in url:
                    return {"rows": [{"name": "张三", "entName": "广州甲公司"}], "total": 1}
                return {"rows": [], "total": 0}

            result = build_guangzhou_stage4_source_gap_probe(
                run_result_json=root / "run-result.json",
                candidate_pressure_json=root / "candidate-pressure-table.json",
                output_root=root / "out",
                http_get_json=fake_getter,
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["candidate_records"][0]
            self.assertIn("contract_public_info", record["covered_source_types"])
            self.assertEqual(record["project_code_candidates"], ["GC001"])
            self.assertEqual(record["project_codes"], ["GC001"])
            self.assertIn("construction_permit", record["empty_result_source_types"])
            self.assertIn("administrative_penalty_public_record", record["query_error_source_types"])
            self.assertTrue(record["person_directory_same_company_candidate_found"])
            self.assertEqual(record["certificate_verification_state"], "NOT_VERIFIED_BY_GDCIC_PERSON_DIRECTORY")
            self.assertTrue(record["certificate_not_publicly_confirmed"])
            self.assertEqual(record["responsible_role_identity_completion_state"], "RESPONSIBLE_ROLE_CANDIDATE_FOUND")
            self.assertEqual(record["stage4_responsible_role_writeback_state"], "NOT_REQUIRED_STAGE3_ROLE_ALREADY_PRESENT")
            self.assertEqual(record["replay_identifier_hints"]["project_code_candidates"], ["GC001"])
            summary_rows = {row["source_type"]: row for row in result["manifest"]["source_type_summary_records"]}
            self.assertEqual(summary_rows["construction_permit"]["empty_result_candidate_count"], 1)
            self.assertEqual(summary_rows["contract_public_info"]["covered_candidate_count"], 1)
            self.assertEqual(summary_rows["administrative_penalty_public_record"]["query_error_candidate_count"], 1)
            self.assertTrue((root / "out" / "stage4-source-gap-probe-v1.json").exists())
            self.assertTrue((root / "out" / "candidate-source-gap-table.json").exists())
            self.assertTrue((root / "out" / "source-type-summary.json").exists())

    def test_classifies_person_directory_only_match_without_role_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(
                root / "run-result.json",
                {
                    "candidate_options": [
                        {
                            "project_id": "PROJ-2",
                            "project_name": "广州候选项目二",
                            "source_url": "https://example.invalid/2?projectCode=GC002",
                            "candidate_company": "广州乙公司",
                            "person_name": "王五",
                            "primary_responsible_role": "project_manager",
                            "region_code": "CN-GD",
                        }
                    ]
                },
            )
            _write_json(
                root / "candidate-pressure-table.json",
                {
                    "records": [
                        {
                            "project_id": "PROJ-2",
                            "project_name": "广州候选项目二",
                            "candidate_company": "广州乙公司",
                            "responsible_role_gap_code": "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
                            "jzsc_company_first_identity_resolution_required": False,
                        }
                    ]
                },
            )

            def fake_getter(url: str, params: dict[str, str]) -> dict[str, object]:
                if "memberInvolvedProject" in url:
                    return {"rows": [], "total": 0}
                if "performance/list" in url:
                    return {"rows": [], "total": 0}
                if "personIntoGd" in url:
                    return {"rows": [{"name": "王五", "entName": "广州乙公司", "certificate": None}], "total": 1}
                if "personInGd" in url:
                    return {"rows": [], "total": 0}
                return {"rows": [], "total": 0}

            result = build_guangzhou_stage4_source_gap_probe(
                run_result_json=root / "run-result.json",
                candidate_pressure_json=root / "candidate-pressure-table.json",
                output_root=root / "out",
                http_get_json=fake_getter,
            )

            record = result["manifest"]["candidate_records"][0]
            self.assertEqual(
                record["responsible_role_identity_completion_state"],
                "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH",
            )
            self.assertEqual(
                record["stage4_responsible_role_writeback_state"],
                "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH",
            )
            self.assertEqual(record["responsible_role_identity_candidates"], [])
            self.assertTrue(record["person_directory_same_company_candidate_found"])
            self.assertEqual(record["recommended_next_action"], "keep_company_first_and_review_certificate_visibility")
            self.assertEqual(
                result["summary"]["responsible_role_identity_completion_state_counts"][
                    "RESPONSIBLE_ROLE_PERSON_DIRECTORY_ONLY_MATCH"
                ],
                1,
            )


def _write_run_result(path: Path) -> None:
    payload = {
        "candidate_options": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目",
                "source_url": "https://example.invalid/1?projectCode=GC001",
                "candidate_company": "广州甲公司",
                "project_manager_name": "张三",
                "project_manager_certificate_no": "粤144202020202020",
                "primary_responsible_person_name": "张三",
                "primary_responsible_role": "project_manager",
                "region_code": "CN-GD",
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_candidate_pressure(path: Path) -> None:
    payload = {
        "records": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目",
                "candidate_company": "广州甲公司",
                "responsible_role_gap_code": "",
                "jzsc_company_first_identity_resolution_required": False,
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
