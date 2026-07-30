from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.runtime_closeout_precedence import (  # noqa: E402
    blocker_ledger_record,
    build_runtime_blocker_controller_dispatch_table,
    build_runtime_blocker_next_subqueue_table,
    build_runtime_blocker_subqueue_controller_table,
    closeout_precedence_decision,
    closeout_precedence_summary,
    runtime_blocker_record_subqueues,
)


class RuntimeCloseoutPrecedenceTests(unittest.TestCase):
    def test_terminal_marker_for_matching_family_suppresses_duplicate_dispatch(self) -> None:
        decision = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "MATCHED",
                        "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                    }
                ],
            }
        )

        self.assertTrue(decision["suppressed_dispatch"])
        self.assertEqual(decision["closeout_precedence_state"], "SUPPRESS_TERMINAL_CLOSEOUT")
        self.assertEqual(decision["matched_marker_count"], 1)
        self.assertEqual(
            decision["operator_next_action"],
            "project_to_review_ready_status_projection_without_duplicate_dispatch",
        )
        self.assertIn("terminal_closeout_or_backfill_marker_present", decision["blocker_taxonomy"])

    def test_unrelated_family_marker_does_not_suppress(self) -> None:
        decision = closeout_precedence_decision(
            {
                "action_family": "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "MATCHED",
                    }
                ],
            }
        )

        self.assertFalse(decision["suppressed_dispatch"])
        self.assertEqual(decision["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")

    def test_release_evidence_needs_browser_is_not_terminal_closeout(self) -> None:
        by_adapter_state = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "adapter_result_state": "NEEDS_BROWSER",
                "release_evidence_adapter_task_id": "REL-TASK-AUTH",
            }
        )
        by_marker_state = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "NEEDS_BROWSER",
                        "artifact_ref": "tmp/field-query/auth-hold.json",
                    }
                ],
            }
        )

        self.assertFalse(by_adapter_state["suppressed_dispatch"])
        self.assertEqual(by_adapter_state["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")
        self.assertFalse(by_marker_state["suppressed_dispatch"])
        self.assertEqual(by_marker_state["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")

    def test_release_evidence_non_terminal_explicit_states_do_not_suppress(self) -> None:
        non_terminal_states = [
            "NEEDS_BROWSER",
            "RELEASE_FIELD_QUERY_AUTHORIZATION_HOLD",
            "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
            "RELEASE_FIELD_QUERY_RESULT_MISSING",
            "RELEASE_FIELD_QUERY_NO_PROJECT_TASKS",
            "PENDING",
            "NO_PROJECT_TASKS",
        ]

        for state in non_terminal_states:
            with self.subTest(state=state):
                decision = closeout_precedence_decision(
                    {
                        "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                        "release_field_query_state": state,
                        "project_id": f"PROJ-{state}",
                    }
                )
                self.assertFalse(decision["suppressed_dispatch"])
                self.assertEqual(decision["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")

    def test_release_evidence_not_found_is_not_terminal_closeout(self) -> None:
        by_adapter_state = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "adapter_result_state": "NOT_FOUND",
                "release_evidence_adapter_task_id": "REL-TASK-NOTFOUND",
            }
        )
        by_marker_state = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_backfill_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "NOT_FOUND",
                        "artifact_ref": "tmp/field-query/not-found.json",
                    }
                ],
            }
        )

        self.assertFalse(by_adapter_state["suppressed_dispatch"])
        self.assertEqual(by_adapter_state["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")
        self.assertFalse(by_marker_state["suppressed_dispatch"])
        self.assertEqual(by_marker_state["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")

    def test_release_evidence_explicit_not_found_closeout_marker_suppresses_duplicate_dispatch(self) -> None:
        decision = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "NOT_FOUND",
                        "artifact_ref": "tmp/field-query/not-found.json",
                    }
                ],
            }
        )

        self.assertTrue(decision["suppressed_dispatch"])
        self.assertEqual(decision["closeout_precedence_state"], "SUPPRESS_TERMINAL_CLOSEOUT")
        self.assertEqual(
            decision["operator_next_action"],
            "record_not_found_status_projection_without_clearance_claim_or_duplicate_dispatch",
        )
        self.assertTrue(decision["query_miss_is_not_clearance"])

    def test_release_evidence_blocked_is_not_terminal_closeout(self) -> None:
        by_adapter_state = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "adapter_result_state": "BLOCKED",
                "release_evidence_adapter_task_id": "REL-TASK-BLOCKED",
            }
        )
        by_marker_state = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "closeout_backfill_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "BLOCKED",
                        "artifact_ref": "tmp/field-query/retry-suspend.json",
                    }
                ],
            }
        )

        self.assertFalse(by_adapter_state["suppressed_dispatch"])
        self.assertEqual(by_adapter_state["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")
        self.assertFalse(by_marker_state["suppressed_dispatch"])
        self.assertEqual(by_marker_state["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")

    def test_release_evidence_review_ready_terminal_does_not_route_to_suspend_dead_letter(self) -> None:
        decision = closeout_precedence_decision(
            {
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "MATCHED",
                        "artifact_ref": "tmp/field-query/review-ready.json",
                    }
                ],
                "project_id": "PROJ-REL-READY",
                "project_name": "Release ready project",
                "release_evidence_adapter_task_id": "REL-TASK-READY",
            }
        )
        blocker = blocker_ledger_record(
            {
                "project_id": "PROJ-REL-READY",
                "project_name": "Release ready project",
                "release_evidence_adapter_task_id": "REL-TASK-READY",
            },
            decision,
            ledger_scope="stage4_release_evidence_query",
        )

        self.assertTrue(decision["suppressed_dispatch"])
        self.assertEqual(
            runtime_blocker_record_subqueues(blocker),
            ["manual_hold", "operator_action"],
        )

    def test_p13b_terminal_state_takes_precedence_over_generic_stage6_action_family(self) -> None:
        decision = closeout_precedence_decision(
            {
                "project_id": "PROJ-P13B-HOLD",
                "action_family": "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
                "p13b_followup_terminal_state": "SOURCE_LIMIT_DEFERRED",
            }
        )

        self.assertTrue(decision["suppressed_dispatch"])
        self.assertEqual(decision["task_scope"], "p13b_follow_up")
        self.assertEqual(decision["terminal_marker"]["terminal_state"], "SOURCE_LIMIT_DEFERRED")
        self.assertEqual(decision["operator_next_action"], "operator_confirms_higher_budget_before_retry")
        self.assertEqual(decision["retry_policy"], "retry_only_after_budget_increase_or_new_source")

    def test_artifact_backed_batch_routes_terminal_and_open_work_without_duplicate_dispatch(self) -> None:
        records = [
            {
                "project_id": "PROJ-P13B-READY",
                "runtime_task_family": "p13b_followup",
                "artifact_ref": "tmp/p13b-controller/p13b-ready.json",
            },
            {
                "project_id": "PROJ-P13B-HOLD",
                "runtime_task_family": "p13b_followup",
                "terminal_closeout_markers": [
                    {
                        "task_family": "p13b_followup",
                        "marker_state": "SOURCE_LIMIT_DEFERRED",
                        "artifact_ref": "tmp/p13b-operational-closeout-v1/p13b-hold.json",
                    }
                ],
            },
            {
                "project_id": "PROJ-RELEASE-REVIEW",
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "MATCHED",
                        "artifact_ref": "tmp/field-query/review-ready.json",
                    }
                ],
            },
            {
                "project_id": "PROJ-AUTH-HOLD",
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_closeout_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "NEEDS_BROWSER",
                        "artifact_ref": "tmp/field-query/auth-hold.json",
                    }
                ],
            },
            {
                "project_id": "PROJ-NOT-FOUND",
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "terminal_backfill_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "NOT_FOUND",
                        "artifact_ref": "tmp/field-query/not-found.json",
                    }
                ],
            },
            {
                "project_id": "PROJ-RETRY-SUSPEND",
                "action_family": "P13B_RELEASE_EVIDENCE_TARGETED_REVIEW",
                "closeout_backfill_markers": [
                    {
                        "task_family": "release_evidence_query",
                        "marker_state": "BLOCKED",
                        "artifact_ref": "tmp/field-query/retry-suspend.json",
                    }
                ],
            },
        ]
        decisions = [closeout_precedence_decision(record) for record in records]
        summary = closeout_precedence_summary(decisions)

        self.assertFalse(decisions[0]["suppressed_dispatch"])
        self.assertEqual(summary["closeout_precedence_decision_count"], 6)
        self.assertEqual(summary["closeout_precedence_suppressed_count"], 2)
        self.assertFalse(decisions[3]["suppressed_dispatch"])
        self.assertEqual(decisions[3]["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")
        self.assertFalse(decisions[4]["suppressed_dispatch"])
        self.assertEqual(decisions[4]["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")
        self.assertFalse(decisions[5]["suppressed_dispatch"])
        self.assertEqual(decisions[5]["closeout_precedence_state"], "ALLOW_DISPATCH_NO_TERMINAL_MARKER")

    def test_runtime_blocker_next_subqueue_table_is_controller_consumable(self) -> None:
        table = build_runtime_blocker_next_subqueue_table(
            [
                {
                    "project_id": "PROJ-AUTH",
                    "project_name": "Auth project",
                    "assigned_owner": "卡卡罗特",
                    "assigned_owner_role": "single_operator",
                    "loop_terminal_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "next_recommended_action": "authorize_browser_or_keep_manual_hold",
                    "release_field_query_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                    "release_field_query_result_json": "tmp/field/guangdong-local-field-query-probe-v1.json",
                    "runtime_blocker_ledger_records": [
                        {
                            "blocker_ledger_id": "BLK-AUTH",
                            "ledger_scope": "stage4_release_evidence_query",
                            "task_id": "GD-FIELD-AUTH",
                            "task_scope": "release_evidence_query",
                            "task_type": "project_manager_change",
                            "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                            "blocker_reason": "LOGIN_OR_SSO_REQUIRED",
                            "runtime_layer": "browser worker",
                            "required_input": ["authorized_browser_storage_state_or_user_data_dir"],
                            "retry_policy": "retry_only_after_authorized_session_available",
                            "reopen_conditions": ["authorized_browser_storage_state_available"],
                            "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                            "artifact_ref": "tmp/field/guangdong-local-field-query-probe-v1.json",
                        }
                    ],
                }
            ],
            source_status_table_ref="tmp/out/stage6-review-loop-project-status-table.json",
        )

        self.assertEqual(table["summary"]["next_subqueue_record_count"], 3)
        self.assertEqual(
            table["summary"]["subqueue_route_counts"],
            {"browser_worker": 1, "operator_action": 1, "retry": 1},
        )
        self.assertEqual(
            [record["subqueue_route"] for record in table["records"]],
            ["browser_worker", "retry", "operator_action"],
        )
        browser_record = table["records"][0]
        self.assertTrue(browser_record["controller_consumable"])
        self.assertEqual(browser_record["subqueue_state"], "BROWSER_WORKER_WAITING_FOR_AUTHORIZED_SESSION")
        self.assertEqual(browser_record["required_input"], ["authorized_browser_storage_state_or_user_data_dir"])
        self.assertEqual(
            browser_record["input_artifact_refs"],
            ["tmp/field/guangdong-local-field-query-probe-v1.json"],
        )
        self.assertEqual(
            runtime_blocker_record_subqueues(
                {
                    "blocker_state": "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED",
                    "retry_policy": "retry_only_with_fallback_source_or_more_precise_identifiers",
                    "operator_next_action": "record_not_found_without_clearance_claim_or_try_project_local_authority",
                }
            ),
            ["fallback_source", "retry", "operator_action"],
        )

    def test_explicit_runtime_blocker_subqueue_routes_override_string_guessing(self) -> None:
        self.assertEqual(
            runtime_blocker_record_subqueues(
                {
                    "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                    "retry_policy": "retry_only_after_authorized_session_available",
                    "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                    "subqueue_routes": ["browser_worker"],
                }
            ),
            ["browser_worker"],
        )

    def test_runtime_blocker_subqueue_controller_table_consumes_next_subqueue_artifact(self) -> None:
        next_subqueue_table = {
            "records": [
                {
                    "next_subqueue_record_id": "RUNTIME-SUBQUEUE-AUTH",
                    "subqueue_route": "browser_worker",
                    "subqueue_state": "BROWSER_WORKER_WAITING_FOR_AUTHORIZED_SESSION",
                    "project_id": "PROJ-AUTH",
                    "project_name": "Auth project",
                    "blocker_ledger_id": "BLK-AUTH",
                    "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                    "runtime_layer": "browser worker",
                    "required_input": ["authorized_browser_storage_state_or_user_data_dir"],
                    "retry_policy": "retry_only_after_authorized_session_available",
                    "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                    "input_artifact_refs": ["tmp/field/guangdong-local-field-query-probe-v1.json"],
                },
                {
                    "next_subqueue_record_id": "RUNTIME-SUBQUEUE-HOLD",
                    "subqueue_route": "manual_hold",
                    "project_id": "PROJ-HOLD",
                    "blocker_ledger_id": "BLK-HOLD",
                    "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                    "runtime_layer": "controller decision",
                    "required_input": ["operator_override_reason_or_new_machine_readable_input"],
                },
            ]
        }

        controller_table = build_runtime_blocker_subqueue_controller_table(
            next_subqueue_table,
            source_next_subqueue_ref="tmp/out/stage6-review-loop-runtime-blocker-next-subqueues.json",
        )

        self.assertEqual(controller_table["summary"]["controller_queue_record_count"], 2)
        self.assertEqual(
            controller_table["summary"]["controller_route_state_counts"],
            {
                "MANUAL_HOLD_ROUTE_RECORDED": 1,
                "WAIT_FOR_BROWSER_WORKER_OR_AUTHORIZED_SESSION_INPUT": 1,
            },
        )
        self.assertEqual(controller_table["summary"]["automated_worker_dispatch_allowed_count"], 0)
        auth_queue = controller_table["records"][0]
        self.assertEqual(auth_queue["dispatch_worker_family"], "browser_worker")
        self.assertEqual(
            auth_queue["controller_next_action"],
            "route_to_browser_worker_when_authorized_session_or_same_session_input_available",
        )
        self.assertEqual(
            auth_queue["input_artifact_refs"],
            ["tmp/field/guangdong-local-field-query-probe-v1.json"],
        )
        self.assertTrue(auth_queue["controller_consumable"])

    def test_runtime_blocker_controller_dispatch_table_builds_allowlisted_browser_worker_plan(self) -> None:
        controller_table = {
            "source_next_subqueue_ref": "tmp/out/stage6-review-loop-runtime-blocker-next-subqueues.json",
            "records": [
                {
                    "controller_queue_record_id": "RUNTIME-CONTROLLER-QUEUE-READY",
                    "source_next_subqueue_record_id": "RUNTIME-SUBQUEUE-READY",
                    "subqueue_route": "browser_worker",
                    "subqueue_state": "BROWSER_WORKER_READY",
                    "controller_route_state": "WAIT_FOR_BROWSER_WORKER_OR_AUTHORIZED_SESSION_INPUT",
                    "dispatch_worker_family": "browser_worker",
                    "automated_worker_dispatch_allowed": True,
                    "project_id": "PROJ-READY",
                    "project_name": "Ready browser project",
                    "input_artifact_refs": ["tmp/plan/release-evidence-adapter-plan-v1.json"],
                    "required_input": [],
                    "operator_next_action": "run_authorized_browser_worker",
                },
                {
                    "controller_queue_record_id": "RUNTIME-CONTROLLER-QUEUE-HOLD",
                    "source_next_subqueue_record_id": "RUNTIME-SUBQUEUE-HOLD",
                    "subqueue_route": "manual_hold",
                    "dispatch_worker_family": "manual_hold",
                    "automated_worker_dispatch_allowed": False,
                    "project_id": "PROJ-HOLD",
                    "required_input": ["operator_override_reason_or_new_machine_readable_input"],
                },
            ],
        }

        dispatch_table = build_runtime_blocker_controller_dispatch_table(
            controller_table,
            output_root="tmp/out/controller-dispatch",
        )

        self.assertEqual(dispatch_table["summary"]["controller_dispatch_task_count"], 2)
        self.assertEqual(dispatch_table["summary"]["ready_for_controlled_worker_dispatch_count"], 1)
        self.assertEqual(
            dispatch_table["summary"]["dispatch_readiness_state_counts"],
            {
                "MANUAL_HOLD_RECORDED_NO_WORKER_DISPATCH": 1,
                "READY_FOR_CONTROLLED_INTERNAL_WORKER_DISPATCH": 1,
            },
        )
        ready = dispatch_table["records"][0]
        self.assertEqual(ready["recommended_script"], "scripts/build-gdcic-browser-authorized-readback-v1.ps1")
        self.assertEqual(
            ready["recommended_command_argv"][:6],
            ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/build-gdcic-browser-authorized-readback-v1.ps1"],
        )
        self.assertIn("-ReleaseEvidenceAdapterPlanJson", ready["recommended_command_argv"])
        self.assertEqual(ready["expected_output_artifact"], "gdcic-browser-authorized-readback-v1.json")
        self.assertTrue(ready["expected_output_artifact_path"].endswith("gdcic-browser-authorized-readback-v1.json"))
        hold = dispatch_table["records"][1]
        self.assertEqual(hold["recommended_command_argv"], [])
        self.assertEqual(hold["dispatch_readiness_state"], "MANUAL_HOLD_RECORDED_NO_WORKER_DISPATCH")


if __name__ == "__main__":
    unittest.main()
