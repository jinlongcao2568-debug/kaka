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

from storage.stage6_review_action_result_routing import (  # noqa: E402
    build_stage6_review_action_result_routing,
)


class Stage6ReviewActionResultRoutingTests(unittest.TestCase):
    def test_routes_ready_results_to_rebuild_or_field_query_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_closeout(root / "closeout")
            _write_baseline_evidence_state(root / "state")

            result = build_stage6_review_action_result_routing(
                dispatch_closeout_root=root / "closeout",
                baseline_evidence_state_root=root / "state",
                evidence_state_rebuild_output_root=root / "state-rebuild",
                release_evidence_field_query_output_root=root / "field-query",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["result_routing_count"], 4)
            self.assertEqual(summary["evidence_state_rebuild_ready_count"], 2)
            self.assertEqual(summary["release_evidence_field_query_ready_count"], 1)
            self.assertEqual(summary["recommended_command_ready_count"], 3)
            self.assertEqual(summary["waiting_for_controlled_execution_count"], 1)
            records = _records_by_project(result["manifest"]["result_routing_table"]["records"])
            self.assertEqual(
                records["PROJ-ORIG"]["next_task_type"],
                "REBUILD_EVIDENCE_STATE_WITH_ORIGINAL_BACKTRACE_CONTINUATION",
            )
            self.assertEqual(records["PROJ-ORIG"]["input_arg_name_for_result_json"], "OriginalBacktraceContinuationJson")
            self.assertIn("stage16_storage_json", records["PROJ-ORIG"]["required_baseline_input_refs"])
            self.assertIn("Stage16StorageJson", records["PROJ-ORIG"]["resolved_baseline_input_refs"])
            self.assertIn("-Stage16StorageJson", records["PROJ-ORIG"]["recommended_command"])
            self.assertIn("-OriginalBacktraceContinuationJson", records["PROJ-ORIG"]["recommended_command"])
            self.assertIn("tmp/original-continuation.json", records["PROJ-ORIG"]["recommended_command"])
            self.assertEqual(
                records["PROJ-SURVEY"]["next_task_type"],
                "REBUILD_EVIDENCE_STATE_WITH_DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
            )
            self.assertEqual(
                records["PROJ-SURVEY"]["input_arg_name_for_result_json"],
                "DesignSurveyPublicRegistryReadbackJson",
            )
            self.assertIn("-DesignSurveyPublicRegistryReadbackJson", records["PROJ-SURVEY"]["recommended_command"])
            self.assertEqual(records["PROJ-REL"]["next_task_type"], "RUN_RELEASE_EVIDENCE_FIELD_QUERY_PROBE")
            self.assertEqual(records["PROJ-REL"]["input_arg_name_for_result_json"], "ReleaseEvidenceAdapterPlanJson")
            self.assertIn("-ReleaseEvidenceAdapterPlanJson", records["PROJ-REL"]["recommended_command"])
            self.assertEqual(
                records["PROJ-WAIT"]["result_routing_state"],
                "WAITING_FOR_CONTROLLED_EXECUTION",
            )
            self.assertTrue((root / "out" / "stage6-review-action-result-routing-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-result-routing-table.json").exists())

    def test_missing_closeout_blocks_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_stage6_review_action_result_routing(
                dispatch_closeout_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["stage6_review_action_result_routing_mode"], "INPUT_BLOCKED")
            self.assertIn("stage6_review_action_dispatch_closeout_missing_or_invalid", result["blocking_reasons"])

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_closeout(root / "closeout")

            result = build_stage6_review_action_result_routing(
                dispatch_closeout_root=root / "closeout",
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


def _write_closeout(root: Path) -> None:
    records = [
        _closeout_record(
            "PROJ-ORIG",
            dispatch_task_type="RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
            closeout_state="READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE",
            result_json_path="tmp/original-continuation.json",
            result_json_exists=True,
        ),
        _closeout_record(
            "PROJ-SURVEY",
            dispatch_task_type="RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW",
            closeout_state="READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE",
            result_json_path="tmp/design-survey-readback.json",
            result_json_exists=True,
        ),
        _closeout_record(
            "PROJ-REL",
            dispatch_task_type="BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
            closeout_state="READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY",
            result_json_path="tmp/release-adapter-plan.json",
            result_json_exists=True,
        ),
        _closeout_record(
            "PROJ-WAIT",
            dispatch_task_type="RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
            closeout_state="WAITING_FOR_CONTROLLED_EXECUTION",
            next_required_input_refs=["evidence_orchestration_state_root_or_json"],
        ),
    ]
    _write_json(
        root / "stage6-review-action-dispatch-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "DISPATCH-CLOSEOUT-1",
                "dispatch_closeout_table": {"records": records},
                "summary": {"dispatch_closeout_count": len(records)},
            },
            "summary": {"dispatch_closeout_count": len(records)},
        },
    )


def _write_baseline_evidence_state(root: Path) -> None:
    _write_json(
        root / "evidence-orchestration-state-v1.json",
        {
            "manifest": {
                "manifest_id": "EVIDENCE-STATE-BASELINE",
                "source_stage16_storage_json": "tmp/storage.json",
                "source_p13b_company_history_json": "tmp/p13b/company-history-overlap-triage-v1.json",
                "source_original_notice_backtrace_json": "tmp/original/original-notice-backtrace-v1.json",
                "source_design_survey_adapter_plan_json": "tmp/design/design-survey-responsible-adapter-plan-v1.json",
                "source_design_survey_public_registry_readback_json": "tmp/old-registry/design-survey-public-registry-readback-v1.json",
            },
            "summary": {},
        },
    )


def _closeout_record(
    project_id: str,
    *,
    dispatch_task_type: str,
    closeout_state: str,
    result_json_path: str = "",
    result_json_exists: bool = False,
    next_required_input_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "dispatch_closeout_id": f"CLOSEOUT-{project_id}",
        "dispatch_task_id": f"DISPATCH-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} 项目",
        "dispatch_task_type": dispatch_task_type,
        "dispatch_readback_state": "EXECUTION_OUTPUT_READY" if result_json_exists else "WAITING_FOR_CONTROLLED_EXECUTION",
        "dispatch_closeout_state": closeout_state,
        "result_json_path": result_json_path,
        "result_json_exists": result_json_exists,
        "result_manifest_id": f"RESULT-{project_id}" if result_json_exists else "",
        "next_required_input_refs": next_required_input_refs or [],
        "ready_to_feed_back_to_evidence_state": closeout_state == "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE",
        "ready_for_release_evidence_field_query": closeout_state == "READY_FOR_RELEASE_EVIDENCE_FIELD_QUERY",
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
