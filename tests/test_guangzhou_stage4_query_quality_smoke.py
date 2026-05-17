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

from storage.guangzhou_stage4_query_quality_smoke import (  # noqa: E402
    build_guangzhou_stage4_query_quality_smoke,
)


class GuangzhouStage4QueryQualitySmokeTests(unittest.TestCase):
    def test_builds_query_quality_summary_with_before_after_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_json(root / "baseline-run.json", _baseline_run_result())
            _write_json(root / "baseline-candidate-table.json", _baseline_candidate_table())
            _write_json(root / "company-first-remediation.json", _company_first_remediation())
            _write_json(root / "before-source-gap.json", _before_source_gap())

            def fake_getter(url: str, params: dict[str, str]) -> dict[str, object]:
                if "personIntoGd" in url:
                    return {"rows": [{"name": "张三", "entName": "广州甲公司"}], "total": 1}
                if "personInGd" in url:
                    return {"rows": [], "total": 0}
                return {"rows": [], "total": 0}

            result = build_guangzhou_stage4_query_quality_smoke(
                baseline_run_result_json=root / "baseline-run.json",
                baseline_candidate_pressure_json=root / "baseline-candidate-table.json",
                company_first_remediation_json=root / "company-first-remediation.json",
                before_source_gap_probe_json=root / "before-source-gap.json",
                output_root=root / "out",
                http_get_json=fake_getter,
                search_runner=lambda payload: _replay_run_result(),
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(
                summary["project_code_resolution_failure_counts_before"],
                {"gdcic_project_code_candidate_missing": 1},
            )
            self.assertEqual(
                summary["project_code_resolution_failure_counts_after"],
                {"gdcic_project_code_candidates_present_but_not_matched": 1},
            )
            self.assertEqual(summary["same_company_person_directory_found_count"], 1)
            self.assertEqual(
                summary["company_first_identity_resolution_required_count_before_after"],
                {"before": 1, "after": 0},
            )
            self.assertEqual(
                summary["stage5_evidence_gate_status_counts_before_after"],
                {"before": {"REVIEW": 1}, "after": {"PASS": 1}},
            )
            self.assertEqual(
                summary["empty_result_source_type_counts_before_after"]["after"]["construction_permit"],
                1,
            )
            self.assertTrue((root / "out" / "query-quality-smoke-summary.json").exists())


def _baseline_run_result() -> dict:
    return {
        "candidate_options": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目",
                "source_url": "https://example.invalid/1?projectCode=GC001",
                "candidate_company": "广州甲公司",
                "project_manager_name": "张三",
                "project_manager_certificate_no": "",
                "primary_responsible_person_name": "张三",
                "primary_responsible_role": "project_manager",
                "region_code": "CN-GD",
            }
        ],
        "search_scope": {"candidate_count": 1, "selected_candidate_count": 1},
        "closed_loop_results": [
            {
                "project_id": "PROJ-1",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "REVIEW",
                    "jzsc_company_first_identity_resolution_required": True,
                    "remaining_real_world_gaps": ["missing_stage4_5_source_type:construction_permit"],
                    "fail_closed_reasons": ["source_gap_review_required"],
                    "customer_sellable_evidence_ready": False,
                },
            }
        ],
    }


def _replay_run_result() -> dict:
    return {
        "candidate_options": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目",
                "source_url": "https://example.invalid/1?projectCode=GC001",
                "notice_stage": "candidate_notice",
                "candidate_company": "广州甲公司",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "jzsc_company_first_identity_resolution_required": False,
                "responsible_role_gap_code": "",
            }
        ],
        "search_scope": {"candidate_count": 1, "selected_candidate_count": 1},
        "closed_loop_results": [
            {
                "project_id": "PROJ-1",
                "real_public_stage4_9_chain_state": "REVIEW_REQUIRED",
                "real_public_stage1_6_chain_state": "REVIEW_REQUIRED",
                "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
                "real_public_stage4_9_readback": {
                    "stage5_rule_gate_status": "REVIEW",
                    "stage5_evidence_gate_status": "PASS",
                    "jzsc_company_first_identity_resolution_required": False,
                    "remaining_real_world_gaps": [],
                    "fail_closed_reasons": ["source_gap_review_required"],
                    "customer_sellable_evidence_ready": False,
                },
            }
        ],
    }


def _baseline_candidate_table() -> dict:
    return {
        "records": [
            {
                "project_id": "PROJ-1",
                "project_name": "广州候选项目",
                "stage5_evidence_gate_status": "REVIEW",
                "jzsc_company_first_identity_resolution_required": True,
                "responsible_role_gap_code": "",
                "remaining_real_world_gaps": ["missing_stage4_5_source_type:construction_permit"],
                "fail_closed_reasons": ["source_gap_review_required"],
            }
        ]
    }


def _company_first_remediation() -> dict:
    return {
        "records": [
            {
                "project_id": "PROJ-1",
                "remediation_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                "replay_field_writeback": {"project_manager_certificate_no": "粤1442020202100011"},
            }
        ],
        "summary": {"candidate_count": 1},
    }


def _before_source_gap() -> dict:
    return {
        "summary": {
            "candidate_count": 1,
            "project_code_resolution_failure_counts": {"gdcic_project_code_candidate_missing": 1},
        },
        "source_type_summary_records": [
            {
                "source_type": "construction_permit",
                "empty_result_candidate_count": 1,
                "query_error_candidate_count": 0,
            }
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
