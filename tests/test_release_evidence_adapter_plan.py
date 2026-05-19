from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.release_evidence_adapter_plan import build_release_evidence_adapter_plan  # noqa: E402


class ReleaseEvidenceAdapterPlanTests(unittest.TestCase):
    def test_normalizes_four_release_evidence_targets_into_b_c_adapter_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_plan_count"], 2)
            self.assertEqual(summary["adapter_task_count"], 4)
            self.assertEqual(
                summary["adapter_task_target_type_counts"],
                {
                    "completion_acceptance": 1,
                    "construction_permit": 1,
                    "contract_performance": 1,
                    "project_manager_change_notice": 1,
                },
            )
            self.assertEqual(
                summary["adapter_task_grade_on_match_counts"],
                {
                    "B_ENHANCEMENT_OFFICIAL_READBACK": 2,
                    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 2,
                },
            )
            task_by_type = {
                task["release_evidence_target_type"]: task
                for task in result["manifest"]["release_evidence_adapter_task_records"]
            }
            self.assertEqual(task_by_type["construction_permit"]["release_evidence_grade_on_match"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertEqual(task_by_type["contract_performance"]["release_evidence_grade_on_match"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertEqual(task_by_type["completion_acceptance"]["release_evidence_grade_on_match"], "C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
            self.assertEqual(task_by_type["project_manager_change_notice"]["release_evidence_grade_on_match"], "C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
            self.assertTrue(
                all(
                    task["allowed_adapter_result_states"] == ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"]
                    for task in task_by_type.values()
                )
            )
            self.assertTrue(all(task["query_miss_is_not_clearance"] for task in task_by_type.values()))
            self.assertTrue((root / "out" / "release-evidence-adapter-plan-v1.json").exists())
            self.assertTrue((root / "out" / "release-evidence-adapter-task-table.json").exists())

    def test_non_a_closeout_does_not_generate_release_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            plans = _records_by_project(result["manifest"]["project_release_evidence_plan_records"])
            self.assertEqual(plans["PROJ-D"]["release_evidence_project_plan_state"], "NO_A_SIGNAL_RELEASE_EVIDENCE_NOT_PLANNED")
            self.assertNotIn(
                "PROJ-D",
                {task["project_id"] for task in result["manifest"]["release_evidence_adapter_task_records"]},
            )

    def test_non_guangdong_region_and_local_housing_scope_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b", region_code="CN-ZJ")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            task = result["manifest"]["release_evidence_adapter_task_records"][0]
            self.assertEqual(task["local_housing_authority_adapter_scope"], "HISTORICAL_PROJECT_JURISDICTION")
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-ZJ")
            self.assertEqual(
                task["non_guangdong_release_adapter_rule"],
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER",
            )
            self.assertEqual(result["summary"]["local_housing_region_counts"]["CN-ZJ"], 4)

    def test_a_signal_without_source_tasks_is_explicitly_plan_required_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=None,
                output_root=root / "out",
            )

            plans = _records_by_project(result["manifest"]["project_release_evidence_plan_records"])
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(plans["PROJ-A"]["release_evidence_project_plan_state"], "RELEASE_EVIDENCE_SOURCE_PLAN_REQUIRED")
            self.assertEqual(result["summary"]["adapter_task_count"], 0)

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)
            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_sha256"], _fingerprint_without_manifest_sha(manifest))


def _write_batch_closeout(root: Path) -> None:
    records = [
        {
            "project_id": "PROJ-A",
            "project_name": "A 项目",
            "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
            "next_action_label": "build_release_evidence_regional_adapter_plan_and_stage6_fact_package",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
        {
            "project_id": "PROJ-D",
            "project_name": "D 项目",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "next_action_label": "park_or_manual_review_without_clearance_claim",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    ]
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "BATCH-1",
                "closeout_records": records,
                "summary": {"project_count": 2},
            }
        },
    )


def _write_p13b_operational(root: Path, *, region_code: str = "CN-GD") -> None:
    non_gd_rule = (
        "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
        if region_code != "CN-GD"
        else ""
    )
    plan = {
        "release_evidence_probe_plan_id": "PLAN-A",
        "project_id": "PROJ-A",
        "project_name": "A 项目",
        "release_evidence_query_region_code": region_code,
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "local_housing_authority_adapter_scope": "HISTORICAL_PROJECT_JURISDICTION",
        "local_housing_authority_adapter_region_code": region_code,
        "non_guangdong_release_adapter_rule": non_gd_rule,
    }
    tasks = [
        _task(
            task_id="TASK-A-BC",
            target_types=["construction_permit", "contract_public_info"],
            subsource_id="permit_contract_public",
            region_code=region_code,
            non_gd_rule=non_gd_rule,
        ),
        _task(
            task_id="TASK-A-CC",
            target_types=["completion_filing", "project_manager_change_notice"],
            subsource_id="completion_change_public",
            region_code=region_code,
            non_gd_rule=non_gd_rule,
        ),
    ]
    _write_json(
        root / "p13b-operational-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "P13B-OPERATIONAL-1",
                "release_evidence_probe_plan_records": [plan],
                "release_evidence_probe_task_records": tasks,
                "summary": {"release_evidence_probe_task_count": len(tasks)},
            }
        },
    )


def _task(
    *,
    task_id: str,
    target_types: list[str],
    subsource_id: str,
    region_code: str,
    non_gd_rule: str,
) -> dict[str, Any]:
    return {
        "release_evidence_probe_task_id": task_id,
        "release_evidence_probe_plan_id": "PLAN-A",
        "project_id": "PROJ-A",
        "project_name": "A 项目",
        "candidate_company_name": "A 公司",
        "matched_person_names": ["张三"],
        "matched_target_source_types": target_types,
        "canonical_release_evidence_source_targets": target_types,
        "initial_release_evidence_abcd_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
        "release_evidence_query_region_code": region_code,
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "local_housing_authority_adapter_scope": "HISTORICAL_PROJECT_JURISDICTION",
        "local_housing_authority_adapter_region_code": region_code,
        "non_guangdong_release_adapter_rule": non_gd_rule,
        "source_entry_id": "LOCAL-HOUSING",
        "subsource_id": subsource_id,
        "source_profile_id": "LOCAL-HOUSING-PROFILE",
        "source_name": "地方住建公开源",
        "source_url": "https://example.test/local-housing",
        "trigger_source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
        "query_params": {
            "projectName": "A 项目",
            "candidateCompanyName": "A 公司",
            "projectManagerName": "张三",
        },
        "next_adapter": "local_housing_authority_release_evidence_adapter_required",
        "runtime_status": "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED",
    }


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _fingerprint_without_manifest_sha(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
