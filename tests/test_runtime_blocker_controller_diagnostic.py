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

from storage.runtime_blocker_controller_diagnostic import (  # noqa: E402
    build_runtime_blocker_controller_diagnostic,
)


class RuntimeBlockerControllerDiagnosticTests(unittest.TestCase):
    def test_diagnostic_compacts_controller_dispatch_and_safety_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cycle_json = root / "stage6-review-cycle-runner-v1.json"
            out = root / "out"
            _write_cycle(cycle_json)

            result = build_runtime_blocker_controller_diagnostic(
                stage6_review_cycle_json=cycle_json,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )
            json_exists = (out / "runtime-blocker-controller-diagnostic-v1.json").exists()
            markdown_exists = (out / "runtime-blocker-controller-diagnostic-v1.md").exists()

        self.assertEqual(result["controller_state"]["runtime_blocker_next_subqueue_record_count"], 4)
        self.assertEqual(result["route_diagnosis"]["subqueue_route_counts"]["fallback_source"], 1)
        self.assertEqual(result["dispatch_diagnosis"]["dispatch_readiness_state_counts"]["FALLBACK_SOURCE_PLAN_REQUIRED"], 1)
        self.assertEqual(result["followup_diagnosis"]["summary_followup_task_count"], 2)
        self.assertEqual(
            result["operator_projection_diagnosis"]["gdcic_authorization_readiness_state_counts"],
            {"LOGIN_OR_SSO_REQUIRED": 1},
        )
        self.assertEqual(result["operator_projection_diagnosis"]["alternative_public_source_route_total"], 3)
        self.assertTrue(result["p0_gap_summary"]["stage4_followup_queue_entered_controller"])
        self.assertEqual(result["p0_gap_summary"]["fallback_source_plan_required_count"], 1)
        self.assertEqual(result["priority_work_queues"]["fallback_source_plan_required"]["record_count"], 1)
        self.assertEqual(result["priority_work_queues"]["authorized_browser_input_required"]["record_count"], 1)
        self.assertIn(
            "build_fallback_source_adapter_plan_for_local_authority_or_bid_show_routes",
            result["recommended_next_actions"],
        )
        self.assertFalse(result["safety"]["customer_visible_allowed"])
        self.assertFalse(result["safety"]["runtime_blocker_dispatch_execution_enabled"])
        self.assertTrue(result["safety"]["not_found_blocked_needs_browser_are_not_clearance"])
        self.assertTrue(json_exists)
        self.assertTrue(markdown_exists)


def _write_cycle(path: Path) -> None:
    payload = {
        "summary": {
            "stage6_review_cycle_runner_state": "STAGE6_REVIEW_CYCLE_READY",
            "stage6_review_cycle_input_mode": "RUNTIME_BLOCKER_SUBQUEUE_ONLY",
            "execution_mode": "DRY_RUN_DISPATCH_NOT_EXECUTED",
            "runtime_blocker_next_subqueue_input_state": "DERIVED_FROM_STAGE6_LOOP_RUNNER",
            "runtime_blocker_next_subqueue_record_count": 4,
            "runtime_blocker_next_subqueue_route_counts": {
                "browser_worker": 1,
                "fallback_source": 1,
                "operator_action": 1,
                "retry": 1,
            },
            "runtime_blocker_controller_queue_record_count": 4,
            "runtime_blocker_controller_route_state_counts": {
                "WAIT_FOR_BROWSER_WORKER_OR_AUTHORIZED_SESSION_INPUT": 1,
                "WAIT_FOR_FALLBACK_SOURCE_ADAPTER_PLAN": 1,
                "OPERATOR_ACTION_ROUTE_RECORDED": 1,
                "WAIT_FOR_RETRY_REOPEN_INPUT_OR_BUDGET": 1,
            },
            "runtime_blocker_controller_next_action_counts": {
                "route_to_browser_worker_when_authorized_session_or_same_session_input_available": 1,
                "route_to_fallback_source_planning_before_retry": 1,
            },
            "runtime_blocker_controller_dispatch_worker_family_counts": {
                "browser_worker": 1,
                "source_adapter": 1,
                "operator_action": 1,
                "retry_policy": 1,
            },
            "runtime_blocker_controller_automated_worker_dispatch_allowed_count": 0,
            "runtime_blocker_controller_dispatch_task_count": 4,
            "runtime_blocker_controller_dispatch_ready_count": 0,
            "runtime_blocker_controller_dispatch_readiness_state_counts": {
                "BLOCKED_REQUIRED_INPUT_OR_WORKER_SPEC_MISSING": 1,
                "FALLBACK_SOURCE_PLAN_REQUIRED": 1,
                "OPERATOR_ACTION_RECORDED_NO_WORKER_DISPATCH": 1,
                "RETRY_REOPEN_INPUT_REQUIRED": 1,
            },
            "runtime_blocker_controller_dispatch_route_counts": {
                "browser_worker": 1,
                "fallback_source": 1,
                "operator_action": 1,
                "retry": 1,
            },
            "runtime_blocker_controller_dispatch_blocking_reason_counts": {
                "required_input_missing_or_operator_action_pending": 2
            },
            "runtime_blocker_dispatch_runner_execution_state_counts": {
                "WORKER_DISPATCH_NOT_READY_RECORDED": 4
            },
            "runtime_blocker_dispatch_runner_readback_state_counts": {
                "WORKER_DISPATCH_NOT_READY_OPERATOR_OR_INPUT_REQUIRED": 4
            },
            "runtime_blocker_dispatch_runner_closeout_state_counts": {
                "KEPT_IN_RUNTIME_BLOCKER_SUBQUEUE": 4
            },
            "runtime_blocker_dispatch_runner_ready_for_field_query_backfill_count": 0,
            "runtime_blocker_dispatch_runner_followup_task_count": 2,
            "runtime_blocker_dispatch_runner_followup_task_type_counts": {
                "BUILD_FALLBACK_SOURCE_ADAPTER_PLAN": 1,
                "RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT": 1,
            },
            "live_execution_enabled": False,
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "forbidden_term_scan_state": "PASS",
        },
        "manifest": {
            "source_stage6_review_loop_status_json": "tmp/status.json",
            "runtime_blocker_subqueue_controller_table": {
                "records": [
                    {
                        "project_id": "PROJ-AUTH",
                        "task_id": "TASK-AUTH",
                        "task_type": "completion_acceptance",
                        "subqueue_route": "browser_worker",
                        "controller_route_state": "WAIT_FOR_BROWSER_WORKER_OR_AUTHORIZED_SESSION_INPUT",
                        "blocker_state": "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED",
                        "required_input": "browser_worker_session_or_same_session_retry_budget",
                    },
                    {
                        "project_id": "PROJ-FALLBACK",
                        "task_id": "TASK-FALLBACK",
                        "task_type": "contract_performance",
                        "subqueue_route": "fallback_source",
                        "controller_route_state": "WAIT_FOR_FALLBACK_SOURCE_ADAPTER_PLAN",
                        "blocker_state": "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED",
                        "operator_next_action": "route_to_fallback_source_planning_before_retry",
                    },
                    {
                        "project_id": "PROJ-OP",
                        "task_id": "TASK-OP",
                        "task_type": "project_manager_change_notice",
                        "subqueue_route": "operator_action",
                        "controller_route_state": "OPERATOR_ACTION_ROUTE_RECORDED",
                    },
                ]
            },
            "runtime_blocker_controller_dispatch_table": {
                "records": [
                    {
                        "project_id": "PROJ-RETRY",
                        "task_id": "TASK-RETRY",
                        "task_type": "completion_acceptance",
                        "dispatch_route": "retry",
                        "dispatch_readiness_state": "RETRY_REOPEN_INPUT_REQUIRED",
                        "blocking_reason": "required_input_missing_or_operator_action_pending",
                    }
                ]
            },
            "runtime_blocker_controller_dispatch_runner": {
                "manifest": {
                    "records": [
                        {"execution_state": "WORKER_DISPATCH_NOT_READY_RECORDED"}
                    ]
                }
            },
            "runtime_blocker_worker_followup_queue": {
                "records": [
                    {"followup_task_type": "BUILD_FALLBACK_SOURCE_ADAPTER_PLAN"},
                    {"followup_task_type": "RETRY_RUNTIME_BLOCKER_AFTER_REOPEN_INPUT"},
                ]
            },
            "operator_projection_status_table": {
                "summary": {
                    "project_status_record_count": 1,
                    "limited_sellable_review_candidate_count": 1,
                    "limited_sellable_review_candidate_state_counts": {"REVIEW_CANDIDATE": 1},
                    "commercialization_boundary_state_counts": {
                        "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE": 1
                    },
                },
                "records": [
                    {
                        "project_id": "PROJ-AUTH",
                        "project_name": "样本项目",
                        "limited_sellable_review_candidate_state": "REVIEW_CANDIDATE",
                        "strong_lead_candidate_state": "STRONG_LEAD_REVIEW_CANDIDATE",
                        "commercialization_boundary_state": "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
                        "limited_sellable_review_evidence_grade_counts": {
                            "B_ENHANCEMENT_OFFICIAL_READBACK": 1
                        },
                        "customer_visible_allowed": False,
                        "gdcic_authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                        "gdcic_alternative_public_source_route_count": 3,
                    }
                ],
            },
            "safety": {
                "dispatch_execution_enabled": False,
                "runtime_blocker_dispatch_execution_enabled": False,
            },
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
