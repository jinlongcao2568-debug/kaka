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

from storage.stage6_review_action_dispatch_readback import (  # noqa: E402
    build_stage6_review_action_dispatch_readback,
)


class Stage6ReviewActionDispatchReadbackTests(unittest.TestCase):
    def test_reads_back_ready_skipped_and_blocked_dispatch_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_dispatch(root / "dispatch")
            _write_result(
                root / "release" / "release-evidence-adapter-plan-v1.json",
                manifest_id="REL-READY",
                safe_to_execute=True,
            )
            _write_result(
                root / "registry" / "design-survey-public-registry-readback-v1.json",
                manifest_id="REG-BLOCKED",
                safe_to_execute=False,
                blocking_reasons=["public_registry_provider_jobs_missing"],
            )
            _write_decisions(root / "decisions.json", project_id="PROJ-D", decision="SKIPPED")

            result = build_stage6_review_action_dispatch_readback(
                dispatch_root=root / "dispatch",
                release_evidence_adapter_plan_root=root / "release",
                evidence_orchestration_continuation_root=root / "continuation",
                design_survey_public_registry_readback_root=root / "registry",
                dispatch_decision_json=root / "decisions.json",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["dispatch_readback_count"], 3)
            self.assertEqual(summary["execution_output_ready_count"], 1)
            self.assertEqual(summary["operator_skipped_count"], 1)
            self.assertEqual(summary["blocked_or_review_count"], 1)
            records = _records_by_project(result["manifest"]["dispatch_readback_table"]["records"])
            self.assertEqual(records["PROJ-A"]["dispatch_readback_state"], "EXECUTION_OUTPUT_READY")
            self.assertEqual(records["PROJ-A"]["result_manifest_id"], "REL-READY")
            self.assertEqual(records["PROJ-D"]["dispatch_readback_state"], "SKIPPED_BY_OPERATOR")
            self.assertEqual(
                records["PROJ-SURVEY"]["dispatch_readback_state"],
                "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED",
            )
            self.assertIn(
                "public_registry_provider_jobs_missing",
                records["PROJ-SURVEY"]["result_blocking_reasons"],
            )
            self.assertTrue((root / "out" / "stage6-review-action-dispatch-readback-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-dispatch-readback-table.json").exists())

    def test_missing_result_artifacts_wait_for_controlled_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_dispatch(root / "dispatch")

            result = build_stage6_review_action_dispatch_readback(
                dispatch_root=root / "dispatch",
                release_evidence_adapter_plan_root=root / "missing-release",
                evidence_orchestration_continuation_root=root / "missing-continuation",
                design_survey_public_registry_readback_root=root / "missing-registry",
                output_root=root / "out",
            )

            records = _records_by_project(result["manifest"]["dispatch_readback_table"]["records"])
            self.assertEqual(
                result["summary"]["dispatch_readback_state_counts"],
                {"WAITING_FOR_CONTROLLED_EXECUTION": 3},
            )
            self.assertEqual(
                records["PROJ-D"]["next_recommended_action"],
                "run_recommended_script_in_controlled_internal_mode_or_record_skip_decision",
            )
            self.assertIn("evidence_orchestration_state_root_or_json", records["PROJ-D"]["next_required_input_refs"])

    def test_missing_dispatch_blocks_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_stage6_review_action_dispatch_readback(
                dispatch_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["stage6_review_action_dispatch_readback_mode"], "INPUT_BLOCKED")
            self.assertIn("stage6_review_action_dispatch_missing_or_invalid", result["blocking_reasons"])

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_dispatch(root / "dispatch")

            result = build_stage6_review_action_dispatch_readback(
                dispatch_root=root / "dispatch",
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


def _write_dispatch(root: Path) -> None:
    records = [
        _dispatch_task(
            project_id="PROJ-A",
            dispatch_task_type="BUILD_RELEASE_EVIDENCE_ADAPTER_PLAN",
            expected_output_artifact="release-evidence-adapter-plan-v1.json",
            required_input_refs=["evidence_batch_closeout_root"],
        ),
        _dispatch_task(
            project_id="PROJ-D",
            dispatch_task_type="RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
            expected_output_artifact="evidence-orchestration-continuation-run-v1.json",
            required_input_refs=["evidence_orchestration_state_root_or_json"],
        ),
        _dispatch_task(
            project_id="PROJ-SURVEY",
            dispatch_task_type="RUN_DESIGN_SURVEY_QUALIFICATION_SERVICE_CLOCK_REVIEW",
            expected_output_artifact="design-survey-public-registry-readback-v1.json",
            required_input_refs=["design_survey_public_registry_fallback_root_or_provider_jobs_json"],
        ),
    ]
    _write_json(
        root / "stage6-review-action-dispatch-v1.json",
        {
            "manifest": {
                "manifest_id": "DISPATCH-1",
                "dispatch_task_table": {"records": records},
                "summary": {"dispatch_task_count": len(records)},
            },
            "summary": {"dispatch_task_count": len(records)},
        },
    )


def _dispatch_task(
    *,
    project_id: str,
    dispatch_task_type: str,
    expected_output_artifact: str,
    required_input_refs: list[str],
) -> dict[str, Any]:
    return {
        "dispatch_task_id": f"DISPATCH-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} 项目",
        "review_lane": "GENERAL_STAGE6_REVIEW",
        "dispatch_task_type": dispatch_task_type,
        "action_family": dispatch_task_type,
        "dispatch_readiness_state": "READY_FOR_CONTROLLED_INTERNAL_DISPATCH_PLAN",
        "dispatch_status": "OPEN",
        "recommended_script": "scripts/example.ps1",
        "expected_output_artifact": expected_output_artifact,
        "required_input_refs": required_input_refs,
        "live_execution_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _write_result(
    path: Path,
    *,
    manifest_id: str,
    safe_to_execute: bool,
    blocking_reasons: list[str] | None = None,
) -> None:
    _write_json(
        path,
        {
            "safe_to_execute": safe_to_execute,
            "blocking_reasons": blocking_reasons or [],
            "manifest": {
                "manifest_id": manifest_id,
                "summary": {"blocking_reasons": blocking_reasons or []},
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            "summary": {"blocking_reasons": blocking_reasons or []},
        },
    )


def _write_decisions(path: Path, *, project_id: str, decision: str) -> None:
    _write_json(
        path,
        {
            "manifest": {
                "dispatch_decision_records": [
                    {
                        "project_id": project_id,
                        "dispatch_decision": decision,
                        "reason": "operator_deferred_this_round",
                    }
                ]
            }
        },
    )


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
