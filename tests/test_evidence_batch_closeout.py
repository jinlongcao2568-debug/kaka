from __future__ import annotations

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

from storage.evidence_batch_closeout import build_evidence_batch_closeout  # noqa: E402


class EvidenceBatchCloseoutTests(unittest.TestCase):
    def test_builds_batch_closeout_for_promote_continue_and_park_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_state(root / "state")

            result = build_evidence_batch_closeout(
                evidence_state_root=root / "state",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_count"], 3)
            self.assertEqual(
                summary["closeout_state_counts"],
                {
                    "CONTINUE_EVIDENCE_RUN": 1,
                    "PARK_D_INSUFFICIENT_OR_BLOCKED": 1,
                    "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW": 1,
                },
            )
            self.assertEqual(summary["next_action_queue_count"], 2)
            by_project = _records_by_project(result["manifest"]["closeout_records"])
            self.assertEqual(
                by_project["PROJ-A"]["closeout_state"],
                "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            )
            self.assertEqual(
                by_project["PROJ-A"]["next_action_type"],
                "BUILD_STAGE6_FACT_PACKAGE_OR_STAGE7_GOVERNED_PREVIEW",
            )
            self.assertEqual(by_project["PROJ-B"]["closeout_state"], "CONTINUE_EVIDENCE_RUN")
            self.assertEqual(by_project["PROJ-B"]["next_action_type"], "RUN_ADAPTER_JOB")
            self.assertEqual(by_project["PROJ-B"]["pending_adapter_job_count"], 1)
            self.assertEqual(by_project["PROJ-D"]["closeout_state"], "PARK_D_INSUFFICIENT_OR_BLOCKED")
            self.assertEqual(
                by_project["PROJ-D"]["next_action_type"],
                "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM",
            )
            self.assertEqual(
                by_project["PROJ-D"]["evidence_artifacts"][0]["evidence_artifact_type"],
                "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
            )
            self.assertTrue((root / "out" / "evidence-batch-closeout-v1.json").exists())
            self.assertTrue((root / "out" / "next-action-queue.json").exists())
            self.assertTrue((root / "out" / "project-closeout-records.json").exists())

    def test_copies_continuation_lineage_without_recomputing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_state(root / "state")
            _write_continuation(root / "continuation")

            result = build_evidence_batch_closeout(
                evidence_state_root=root / "state",
                continuation_run_root=root / "continuation",
                output_root=root / "out",
            )

            record = _records_by_project(result["manifest"]["closeout_records"])["PROJ-D"]
            self.assertEqual(record["source_refs"]["continuation_manifest_id"], "CONTINUATION-1")
            self.assertEqual(record["source_refs"]["state_after_root"], "after-state-root")
            self.assertEqual(
                record["continuation_lineage"]["state_after_evidence_state_counts"],
                {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 1},
            )
            self.assertEqual(
                record["continuation_lineage"]["final_original_backtrace_continuation_recommended_next_action"],
                "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM",
            )

    def test_overlay_state_replaces_scoped_project_and_clears_stale_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_state(root / "state")
            _write_overlay_state(root / "overlay")

            result = build_evidence_batch_closeout(
                evidence_state_root=root / "state",
                evidence_state_overlay_root=root / "overlay",
                output_root=root / "out",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["project_count"], 3)
            by_project = _records_by_project(result["manifest"]["closeout_records"])
            self.assertEqual(by_project["PROJ-B"]["evidence_state"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
            self.assertEqual(by_project["PROJ-B"]["closeout_state"], "PARK_D_INSUFFICIENT_OR_BLOCKED")
            self.assertEqual(by_project["PROJ-B"]["pending_adapter_job_count"], 0)
            self.assertEqual(
                by_project["PROJ-B"]["source_refs"]["evidence_state_overlay_jsons"],
                [str(root / "overlay" / "evidence-orchestration-state-v1.json")],
            )

    def test_missing_state_input_blocks_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_evidence_batch_closeout(
                evidence_state_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["evidence_batch_closeout_mode"], "INPUT_BLOCKED")
            self.assertIn("evidence_orchestration_state_missing_or_invalid", result["blocking_reasons"])
            self.assertEqual(result["summary"]["closeout_state"], "EVIDENCE_BATCH_CLOSEOUT_INPUT_BLOCKED")

    def test_missing_explicit_overlay_blocks_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_state(root / "state")

            result = build_evidence_batch_closeout(
                evidence_state_root=root / "state",
                evidence_state_overlay_root=root / "missing-overlay",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("evidence_orchestration_state_overlay_missing_or_invalid", result["blocking_reasons"])

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_evidence_state(root / "state")

            result = build_evidence_batch_closeout(evidence_state_root=root / "state", output_root=root / "out")

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)


def _write_evidence_state(root: Path) -> None:
    evidence_records = [
        {
            "project_id": "PROJ-A",
            "project_name": "A 项目",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
            "evidence_signal_source": "data_ggzy_bid_show",
            "recommended_next_action": "build_release_evidence_regional_adapter_plan_and_stage6_fact_package",
            "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY",
            "signal_counts": {"p13b_a_strong_direct_signal_count": 1},
        },
        {
            "project_id": "PROJ-B",
            "project_name": "B 项目",
            "evidence_state": "P13B_ORIGINAL_BACKTRACE_REQUIRED",
            "evidence_grade": "PENDING_ORIGINAL_BACKTRACE",
            "evidence_signal_source": "p13b_company_history",
            "recommended_next_action": "continue_p13b_original_notice_backtrace",
            "stage6_fact_package_state": "NOT_READY",
            "review_reasons": ["original_notice_person_period_not_extracted_review"],
        },
        {
            "project_id": "PROJ-D",
            "project_name": "D 项目",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_signal_source": "original_notice_readback",
            "recommended_next_action": "manual_review_or_retry_blocked_original_notice_backtrace_without_clearance_claim",
            "stage6_fact_package_state": "NOT_READY",
            "review_reasons": ["source_blocked_or_fields_missing"],
            "evidence_artifacts": [
                {
                    "evidence_artifact_type": "DESIGN_SURVEY_PUBLIC_REGISTRY_READBACK",
                    "verification_result": "MATCHED",
                    "identity_fields": {
                        "person_name": "胡昌华",
                        "registered_unit_name": "广州市城市规划勘测设计研究院有限公司",
                    },
                    "source_snapshot_sha256": "snapshot-sha256",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ],
        },
    ]
    batch_records = [
        {
            "project_id": "PROJ-A",
            "batch_triage_bucket": "A_STRONG_SIGNAL_READY_FOR_RELEASE_EVIDENCE",
            "commercial_decision_state": "PROMOTE_TO_STAGE6_FACT_PACKAGE_AND_STAGE7_GOVERNED_PREVIEW",
            "recommended_next_action": "build_release_evidence_regional_adapter_plan_and_stage6_fact_package",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": True,
        },
        {
            "project_id": "PROJ-B",
            "batch_triage_bucket": "CONTINUE_ORIGINAL_BACKTRACE",
            "commercial_decision_state": "CONTINUE_INTERNAL_EVIDENCE_RUN",
            "recommended_next_action": "continue_p13b_original_notice_backtrace",
            "stage6_ready": False,
            "stage7_commercial_input_allowed": False,
        },
        {
            "project_id": "PROJ-D",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "commercial_decision_state": "KEEP_INTERNAL_REVIEW_OR_MANUAL_RESOLVE",
            "recommended_next_action": "manual_review_or_retry_blocked_original_notice_backtrace_without_clearance_claim",
            "stop_reason": "release_evidence_or_original_readback_insufficient_or_blocked",
            "stage6_ready": False,
            "stage7_commercial_input_allowed": False,
        },
    ]
    adapter_jobs = [
        {
            "adapter_job_id": "JOB-B-1",
            "project_id": "PROJ-B",
            "job_type": "p13b_original_notice_backtrace",
            "recommended_script": "scripts/build-p13b-original-notice-backtrace-v1.ps1",
            "recommended_next_action": "continue_p13b_original_notice_backtrace",
            "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
        }
    ]
    stage6_records = [
        {"project_id": "PROJ-A", "stage6_fact_package_state": "A_SIGNAL_FACT_PACKAGE_READY"},
        {"project_id": "PROJ-B", "stage6_fact_package_state": "NOT_READY"},
        {"project_id": "PROJ-D", "stage6_fact_package_state": "NOT_READY"},
    ]
    _write_json(
        root / "evidence-orchestration-state-v1.json",
        {
            "manifest": {
                "manifest_id": "STATE-1",
                "evidence_state_table": {"records": evidence_records},
                "adapter_job_table": {"records": adapter_jobs},
                "stage6_fact_package_readiness_table": {"records": stage6_records},
                "batch_triage_table": {"records": batch_records},
                "summary": {"project_count": 3},
            },
            "summary": {"project_count": 3},
        },
    )


def _write_continuation(root: Path) -> None:
    _write_json(
        root / "evidence-orchestration-continuation-run-v1.json",
        {
            "manifest": {
                "manifest_id": "CONTINUATION-1",
                "state_after_root": "after-state-root",
                "summary": {
                    "original_action_state": "EXISTING_ORIGINAL_BACKTRACE_CONSUMED_NO_DELTA_TASKS",
                    "targeted_person_action_state": "SKIPPED_NO_TARGETED_PERSON_READBACK_REQUIRED",
                    "state_after_evidence_state_counts": {"D_INSUFFICIENT_OR_BLOCKED_READBACK": 1},
                    "state_after_adapter_job_count": 0,
                    "final_original_backtrace_continuation_recommended_next_action": (
                        "PARK_OR_MANUAL_REVIEW_WITHOUT_CLEARANCE_CLAIM"
                    ),
                },
            },
            "summary": {"state_after_adapter_job_count": 0},
        },
    )


def _write_overlay_state(root: Path) -> None:
    evidence_records = [
        {
            "project_id": "PROJ-B",
            "project_name": "B 项目",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "evidence_signal_source": "original_backtrace_continuation",
            "recommended_next_action": "manual_review_or_retry_blocked_original_notice_backtrace",
            "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
            "review_reasons": ["original_backtrace_continuation_closed_without_signal"],
        }
    ]
    batch_records = [
        {
            "project_id": "PROJ-B",
            "batch_triage_bucket": "D_BLOCKED_OR_INSUFFICIENT_REVIEW",
            "commercial_decision_state": "KEEP_INTERNAL_REVIEW_OR_MANUAL_RESOLVE",
            "recommended_next_action": "manual_review_or_retry_blocked_original_notice_backtrace_without_clearance_claim",
            "stop_reason": "release_evidence_or_original_readback_insufficient_or_blocked",
            "stage6_ready": True,
            "stage7_commercial_input_allowed": False,
        }
    ]
    stage6_records = [{"project_id": "PROJ-B", "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY"}]
    _write_json(
        root / "evidence-orchestration-state-v1.json",
        {
            "manifest": {
                "manifest_id": "STATE-OVERLAY",
                "evidence_state_table": {"records": evidence_records},
                "adapter_job_table": {"records": []},
                "stage6_fact_package_readiness_table": {"records": stage6_records},
                "batch_triage_table": {"records": batch_records},
                "summary": {"project_count": 1},
            },
            "summary": {"project_count": 1},
        },
    )


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
