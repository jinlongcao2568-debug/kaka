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

from storage.stage6_review_action_dispatch import build_stage6_review_action_dispatch  # noqa: E402


class Stage6ReviewActionDispatchTests(unittest.TestCase):
    def test_maps_stage6_action_plans_to_controlled_dispatch_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_stage6_fact_package(root / "stage6")

            result = build_stage6_review_action_dispatch(
                stage6_fact_package_root=root / "stage6",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["dispatch_task_count"], 3)
            self.assertFalse(summary["live_execution_enabled"])
            self.assertEqual(
                summary["dispatch_task_type_counts"],
                {
                    "BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN": 1,
                    "RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW": 1,
                    "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW": 1,
                },
            )
            tasks = _records_by_project(result["manifest"]["dispatch_task_table"]["records"])
            self.assertEqual(
                tasks["PROJ-A"]["recommended_script"],
                "scripts/build-release-evidence-adapter-plan-v1.ps1",
            )
            self.assertEqual(
                tasks["PROJ-D"]["recommended_script"],
                "scripts/run-evidence-orchestration-continuation-v1.ps1",
            )
            self.assertEqual(
                tasks["PROJ-D"]["expected_output_artifact"],
                "evidence-orchestration-continuation-run-v1.json",
            )
            self.assertEqual(
                tasks["PROJ-SURVEY"]["recommended_script"],
                "scripts/build-design-survey-public-registry-readback-v1.ps1",
            )
            self.assertTrue(all(not task["live_execution_enabled"] for task in tasks.values()))
            self.assertTrue(all(task["requires_operator_action_before_live"] for task in tasks.values()))
            self.assertTrue(all(task["query_miss_is_not_clearance"] for task in tasks.values()))
            self.assertTrue((root / "out" / "stage6-review-action-dispatch-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-dispatch-task-table.json").exists())

    def test_missing_stage6_fact_package_blocks_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_stage6_review_action_dispatch(
                stage6_fact_package_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["stage6_review_action_dispatch_mode"], "INPUT_BLOCKED")
            self.assertIn("stage6_fact_package_missing_or_invalid", result["blocking_reasons"])
            self.assertEqual(
                result["summary"]["stage6_review_action_dispatch_state"],
                "STAGE6_REVIEW_ACTION_DISPATCH_INPUT_BLOCKED",
            )

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_stage6_fact_package(root / "stage6")

            result = build_stage6_review_action_dispatch(
                stage6_fact_package_root=root / "stage6",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            self.assertFalse(result["manifest"]["safety"]["stage7_to_stage9_live_execution_enabled"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)
            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_sha256"], _fingerprint_without_manifest_sha(manifest))


def _write_stage6_fact_package(root: Path) -> None:
    records = [
        _action_plan(
            project_id="PROJ-A",
            action_family="P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
            target_adapter_scope="ReleaseEvidenceAdapterPlanV1 + jurisdiction_release_adapter_registry",
            action_label="query_release_evidence_only_in_historical_overlap_project_local_public_source",
        ),
        _action_plan(
            project_id="PROJ-D",
            action_family="SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
            target_adapter_scope="OriginalNoticeTaskTriageV1 + official_direct_html_or_attachment_readback",
            action_label="retry_official_direct_html_or_attachment_readback_with_small_budget",
        ),
        _action_plan(
            project_id="PROJ-SURVEY",
            action_family="DESIGN_SURVEY_QUALIFICATION_AND_SERVICE_CLOCK_REVIEW",
            target_adapter_scope="DesignSurveyPublicRegistryReadback + natural_resources_public_registry_adapter",
            action_label="plan_qualification_service_clock_and_current_assignment_review",
        ),
    ]
    _write_json(
        root / "stage6-fact-package-v1.json",
        {
            "manifest": {
                "manifest_id": "STAGE6-FACT-PACKAGE-1",
                "stage6_review_action_plan_table": {"records": records},
                "summary": {"review_action_plan_count": len(records)},
            },
            "summary": {"review_action_plan_count": len(records)},
        },
    )


def _action_plan(
    *,
    project_id: str,
    action_family: str,
    target_adapter_scope: str,
    action_label: str,
) -> dict[str, Any]:
    return {
        "review_action_plan_id": f"PLAN-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} 项目",
        "review_lane": "GENERAL_STAGE6_REVIEW",
        "review_queue_bucket": "INTERNAL_FACT_REVIEW",
        "review_priority_score": 55,
        "primary_evidence_topic_code": "P13B_RESPONSIBLE_PERSON_RELEASE",
        "action_family": action_family,
        "target_adapter_scope": target_adapter_scope,
        "target_source_scope": ["public_source"],
        "regional_routing_policy": "route_by_project_region_or_manual_review",
        "action_items": [
            {
                "action_item_id": f"ITEM-{project_id}",
                "order": 1,
                "action_label": action_label,
                "manual_review_required": True,
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
                "query_miss_is_not_clearance": True,
            }
        ],
        "source_refs": {"stage6": "stage6-fact-package-v1.json"},
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fingerprint_without_manifest_sha(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
