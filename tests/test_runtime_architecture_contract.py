from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from storage_test_support import IsolatedStorageTestMixin


class RuntimeArchitectureContractTests(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="runtime-architecture-contract.json")

    def tearDown(self) -> None:
        self.tearDown_storage_test_env()

    def test_runtime_architecture_contract_defines_target_brain_and_script_boundary(self) -> None:
        contract_path = ROOT / "control" / "runtime_architecture_contract.yaml"
        self.assertTrue(contract_path.exists(), "runtime architecture contract must be machine-readable")

        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["contract_id"], "RUNTIME_ARCHITECTURE_CONTRACT_V1")
        self.assertEqual(contract["status"], "ACTIVE")

        components = {component["component_id"]: component for component in contract["system_brain_components"]}
        for component_id in (
            "run_controller",
            "stage_state_machine",
            "work_queue_dispatcher",
            "transition_guard",
            "audit_replay_ledger",
            "runtime_state_repository",
            "stage123_front_chain",
            "operator_runtime_projection",
            "stage1_3_repair_worker",
            "gdcic_browser_authorized_readback_worker",
        ):
            self.assertIn(component_id, components)
            self.assertTrue(components[component_id]["runtime_responsibility"])

        stage_ids = [stage["stage_id"] for stage in contract["stage_graph"]]
        self.assertEqual(
            stage_ids,
            [
                "stage1_tasking",
                "stage2_ingestion",
                "stage3_parsing",
                "stage4_verification",
                "stage5_rules_evidence",
                "stage6_fact_review",
                "stage7_sales",
                "stage8_outreach",
                "stage9_delivery",
            ],
        )
        self.assertEqual(contract["stage_graph"][0]["next_stage_id"], "stage2_ingestion")
        self.assertEqual(contract["stage_graph"][-1]["next_stage_id"], "DONE")

        self.assertTrue(contract["script_boundary"]["scripts_are_transport_only"])
        self.assertTrue(contract["script_boundary"]["formal_continuation_uses_entrypoint_id"])
        self.assertIn("recommended_script_as_state_truth", contract["script_boundary"]["forbidden_patterns"])
        migration = contract["current_migration_slice"]
        self.assertTrue(migration["controller_consumes_stage123_front_chain"])
        self.assertTrue(migration["controller_consumes_stage1_6_batch_readiness_ledger"])
        self.assertTrue(migration["controller_consumes_stage4_release_field_query_ledger"])
        self.assertTrue(migration["controller_consumes_stage4_release_chain_bootstrap_ledger"])
        self.assertTrue(migration["controller_consumes_stage5_calibration_ledger"])
        self.assertTrue(migration["controller_derives_stage1_3_repair_worker_dispatch"])
        self.assertTrue(migration["gdcic_authorized_readback_persisted_as_runtime_worker_result"])
        self.assertTrue(migration["gdcic_authorized_readback_emits_stage5_calibration_samples"])
        self.assertTrue(migration["runtime_operator_projection_merges_worker_stage5_calibration_ledger"])
        self.assertTrue(migration["controller_records_stage8_stage9_controlled_boundary"])
        self.assertTrue(migration["runtime_entrypoint_transport_accepts_controller_consumed_artifact_refs"])
        self.assertTrue(migration["runtime_state_persisted_by_repository"])
        self.assertTrue(migration["operator_frontend_reads_runtime_projection"])
        self.assertTrue(migration["operator_frontend_reads_controller_dispatch_queue_records"])
        self.assertEqual(
            migration["formal_storage_object_types"],
            ["runtime_run_state", "runtime_audit_event", "runtime_operator_projection", "runtime_worker_result"],
        )

        live_boundary = contract["live_boundary"]
        self.assertFalse(live_boundary["external_customer_action_enabled"])
        self.assertFalse(live_boundary["real_payment_enabled"])
        self.assertFalse(live_boundary["real_delivery_enabled"])
        self.assertFalse(live_boundary["automatic_refund_enabled"])

    def test_run_controller_records_run_state_and_audit_without_live_execution(self) -> None:
        spec = importlib.util.find_spec("runtime.run_controller")
        self.assertIsNotNone(spec, "runtime.run_controller module must exist")

        from runtime.run_controller import RunController

        def stage6_preview_executor(payload: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "stage_id": "stage6_fact_review",
                "stage_state": "REVIEW_REQUIRED",
                "project_id": payload["project_id"],
                "output_artifact_refs": ["memory://stage6-preview/PROJ-RUNTIME-1"],
                "blocking_reasons": ["stage4_release_evidence_missing"],
                "next_action": "run_stage4_release_evidence_bridge_builder",
            }

        controller = RunController(stage6_preview_executor=stage6_preview_executor)
        result = controller.start_stage1_6_preview_run(
            {
                "project_id": "PROJ-RUNTIME-1",
                "entrypoint_id": "stage1_6_internal_http_orchestration_preview",
                "source_mode": "SANITIZED_OFFLINE_INTERNAL",
            },
            created_at="2026-05-24T00:00:00+08:00",
        )

        self.assertEqual(result["run_state"]["run_id"], "RUN-PROJ-RUNTIME-1-stage1-6-preview")
        self.assertEqual(result["run_state"]["entrypoint_id"], "stage1_6_internal_http_orchestration_preview")
        self.assertEqual(result["run_state"]["current_stage_id"], "stage6_fact_review")
        self.assertEqual(result["run_state"]["run_state"], "REVIEW_REQUIRED")
        self.assertEqual(result["run_state"]["next_action"]["action_type"], "ENTRYPOINT")
        self.assertEqual(
            result["run_state"]["next_action"]["entrypoint_id"],
            "stage4_release_evidence_bridge_builder",
        )
        self.assertEqual(result["run_state"]["blocking_reasons"], ["stage4_release_evidence_missing"])
        self.assertEqual(result["run_state"]["output_artifact_refs"], ["memory://stage6-preview/PROJ-RUNTIME-1"])

        safety = result["run_state"]["safety"]
        self.assertFalse(safety["external_customer_action_enabled"])
        self.assertFalse(safety["real_payment_enabled"])
        self.assertFalse(safety["real_delivery_enabled"])
        self.assertFalse(safety["automatic_refund_enabled"])
        controlled_boundary = result["run_state"]["controlled_boundary"]
        self.assertEqual(
            controlled_boundary["stage8_outreach_boundary_state"],
            "CONTROLLED_OPENING_PREREQUISITES_ONLY",
        )
        self.assertEqual(
            controlled_boundary["stage9_payment_delivery_refund_boundary_state"],
            "CONTROLLED_OPENING_PREREQUISITES_ONLY",
        )
        self.assertEqual(controlled_boundary["automatic_refund_policy_state"], "EXCLUDED")
        self.assertEqual(
            controlled_boundary["required_before_live_execution"],
            [
                "release_checklist_passed",
                "approval_chain_passed",
                "audit_chain_ready",
                "operator_action_confirmed",
            ],
        )
        self.assertIn("real_payment", controlled_boundary["blocked_action_families"])
        self.assertFalse(controlled_boundary["real_payment_enabled"])
        self.assertFalse(controlled_boundary["automatic_refund_enabled"])

        audit = result["audit_ledger"]["events"]
        self.assertEqual(
            [event["event_type"] for event in audit],
            [
                "RUN_STARTED",
                "STAGE_RESULT_RECORDED",
                "DISPATCH_TASK_ENQUEUED",
                "RUNTIME_CONTROLLED_BOUNDARY_RECORDED",
            ],
        )
        self.assertEqual(audit[0]["run_id"], result["run_state"]["run_id"])
        self.assertEqual(audit[1]["stage_id"], "stage6_fact_review")

        dispatch_records = result["dispatch_queue"]["records"]
        self.assertEqual(len(dispatch_records), 1)
        self.assertEqual(dispatch_records[0]["entrypoint_id"], "stage4_release_evidence_bridge_builder")
        self.assertEqual(dispatch_records[0]["dispatch_state"], "READY_FOR_INTERNAL_DISPATCH")
        self.assertFalse(dispatch_records[0]["external_customer_action_enabled"])

    def test_transition_guard_blocks_live_external_action_from_dispatch(self) -> None:
        from runtime.run_controller import RunController

        def stage6_preview_executor(payload: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "stage_id": "stage7_sales",
                "stage_state": "BLOCKED",
                "project_id": payload["project_id"],
                "output_artifact_refs": ["memory://stage7/PROJ-LIVE-GUARD"],
                "blocking_reasons": ["release_approval_audit_missing"],
                "next_action": "run_stage8_real_outreach_sender",
            }

        controller = RunController(stage6_preview_executor=stage6_preview_executor)
        result = controller.start_stage1_6_preview_run(
            {
                "project_id": "PROJ-LIVE-GUARD",
                "entrypoint_id": "stage1_6_internal_http_orchestration_preview",
                "source_mode": "SANITIZED_OFFLINE_INTERNAL",
            },
            created_at="2026-05-24T00:00:00+08:00",
        )

        next_action = result["run_state"]["next_action"]
        self.assertEqual(next_action["action_type"], "OPERATOR_ACTION")
        self.assertEqual(next_action["entrypoint_id"], "")
        self.assertEqual(next_action["review_family"], "controlled_live_boundary_review")
        self.assertEqual(
            next_action["review_state"],
            "BLOCKED_UNTIL_RELEASE_APPROVAL_AUDIT_AND_OPERATOR_ACTION",
        )
        self.assertIn("live_external_action_not_gated", next_action["blocking_reasons"])
        self.assertFalse(next_action["external_customer_action_enabled"])

        dispatch_records = result["dispatch_queue"]["records"]
        self.assertEqual(len(dispatch_records), 1)
        self.assertEqual(dispatch_records[0]["dispatch_state"], "WAITING_FOR_REVIEW")
        self.assertEqual(dispatch_records[0]["entrypoint_id"], "")
        self.assertEqual(dispatch_records[0]["blocking_reasons"], ["live_external_action_not_gated"])
        self.assertFalse(dispatch_records[0]["external_customer_action_enabled"])
        self.assertFalse(result["run_state"]["safety"]["real_outreach_enabled"])

        from storage.repositories.runtime_state_repo import RuntimeStateRepository

        projection = RuntimeStateRepository().latest_operator_projection()
        self.assertTrue(projection["operator_action_required"])
        self.assertEqual(projection["next_action_blocking_reasons"], ["live_external_action_not_gated"])
        self.assertEqual(
            projection["trace_refs"]["next_action_blocking_reasons_json"],
            '["live_external_action_not_gated"]',
        )

    def test_run_controller_consumes_current_focus_and_stage6_runtime_blocker_queue(self) -> None:
        spec = importlib.util.find_spec("runtime.run_controller")
        self.assertIsNotNone(spec, "runtime.run_controller module must exist")

        from runtime.run_controller import RunController

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            release_plan = root / "plan" / "release-evidence-adapter-plan-v1.json"
            release_plan.parent.mkdir(parents=True, exist_ok=True)
            release_plan.write_text(json.dumps({"manifest": {"manifest_id": "REL-PLAN-RUNTIME"}}), encoding="utf-8")
            next_subqueue = root / "runtime-blocker-next-subqueues.json"
            next_subqueue.write_text(
                json.dumps(
                    {
                        "table_kind": "runtime_blocker_next_subqueue_table_v1",
                        "summary": {
                            "next_subqueue_record_count": 1,
                            "subqueue_route_counts": {"browser_worker": 1},
                        },
                        "records": [
                            {
                                "next_subqueue_record_id": "RUNTIME-SUBQUEUE-RUN-CONTROLLER",
                                "subqueue_route": "browser_worker",
                                "subqueue_state": "READY_FOR_BROWSER_WORKER_DISPATCH",
                                "project_id": "PROJ-RUNTIME-CYCLE",
                                "project_name": "Runtime cycle project",
                                "assigned_owner": "卡卡罗特",
                                "assigned_owner_role": "single_operator",
                                "blocker_ledger_id": "BLK-RUNTIME-CYCLE",
                                "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                                "blocker_reason": "LOGIN_OR_SSO_REQUIRED",
                                "runtime_layer": "browser worker",
                                "task_id": "GD-FIELD-RUNTIME-CYCLE",
                                "task_scope": "release_evidence_query",
                                "task_type": "project_manager_change",
                                "required_input": [],
                                "input_artifact_refs": [str(release_plan)],
                                "operator_next_action": "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                                "controller_consumable": True,
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                        "customer_visible_allowed": False,
                        "no_legal_conclusion": True,
                        "query_miss_is_not_clearance": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            controller = RunController(stage6_preview_executor=lambda payload: {})
            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-RUNTIME-CYCLE",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "runtime_blocker_next_subqueue_json": str(next_subqueue),
                    "stage45_replay_samples": {
                        "stage4_probe_results": [
                            {
                                "project_id": "PROJ-RUNTIME-CYCLE-NOT-FOUND",
                                "probe_status": "NOT_FOUND",
                                "source_url": "https://example.test/not-found",
                            },
                            {
                                "project_id": "PROJ-RUNTIME-CYCLE-LOGIN",
                                "probe_status": "LOGIN_OR_SSO_REQUIRED",
                                "source_url": "https://example.test/login",
                            },
                        ],
                        "stage5_rule_codes": ["CREDIT-001"],
                    },
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        self.assertEqual(result["runtime_controller_mode"], "STAGE1_6_RUNTIME_CYCLE")
        run_state = result["run_state"]
        self.assertEqual(run_state["entrypoint_id"], "stage6_review_cycle_runner")
        self.assertEqual(run_state["current_stage_id"], "stage6_fact_review")
        self.assertEqual(run_state["current_focus"]["priority_id"], "P0_STAGE4_RELEASE_EVIDENCE_CHAIN")
        self.assertEqual(run_state["next_action"]["entrypoint_id"], "stage6_review_cycle_runner")
        self.assertEqual(
            run_state["runtime_blocker_controller_summary"]["next_subqueue_input_state"],
            "READY",
        )
        self.assertEqual(run_state["runtime_blocker_controller_summary"]["controller_dispatch_task_count"], 1)
        self.assertEqual(run_state["runtime_blocker_controller_summary"]["dispatch_ready_count"], 1)
        self.assertEqual(run_state["runtime_blocker_controller_summary"]["controller_derived_dispatch_task_count"], 1)
        self.assertEqual(run_state["runtime_blocker_controller_summary"]["controller_derived_dispatch_ready_count"], 1)
        self.assertEqual(
            run_state["runtime_blocker_controller_summary"]["controller_derived_dispatch_entrypoint_counts"],
            {"stage6_review_cycle_runner": 1},
        )
        self.assertEqual(result["dispatch_queue"]["records"][0]["entrypoint_id"], "stage6_review_cycle_runner")
        self.assertEqual(result["dispatch_queue"]["records"][0]["dispatch_state"], "READY_FOR_INTERNAL_DISPATCH")
        self.assertFalse(result["dispatch_queue"]["records"][0]["external_customer_action_enabled"])
        self.assertEqual(run_state["stage45_replay_summary"]["stage4_blocker_ledger_count"], 2)
        self.assertEqual(
            run_state["stage45_replay_summary"]["runtime_blocker_subqueue_route_counts"]["browser_worker"],
            1,
        )
        self.assertEqual(
            run_state["stage45_replay_summary"]["runtime_blocker_subqueue_route_counts"]["fallback_source"],
            1,
        )
        self.assertFalse(run_state["safety"]["external_customer_action_enabled"])
        self.assertEqual(
            run_state["controlled_boundary"]["stage8_outreach_boundary_state"],
            "CONTROLLED_OPENING_PREREQUISITES_ONLY",
        )
        self.assertEqual(run_state["controlled_boundary"]["automatic_refund_policy_state"], "EXCLUDED")
        self.assertFalse(result["customer_visible_allowed"])
        self.assertEqual(
            [event["event_type"] for event in result["audit_ledger"]["events"]],
            [
                "RUN_STARTED",
                "CONTROL_FOCUS_LOADED",
                "STAGE6_RUNTIME_CYCLE_RECORDED",
                "RUNTIME_BLOCKER_QUEUE_RECORDED",
                "RUNTIME_CONTROLLER_DISPATCH_TASK_DERIVED",
                "STAGE45_RUNTIME_REPLAY_RECORDED",
                "RUNTIME_CONTROLLED_BOUNDARY_RECORDED",
            ],
        )

    def test_run_controller_records_stage5_calibration_ledger_from_runtime_cycle(self) -> None:
        from runtime.run_controller import RunController

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stage5_json = root / "stage5" / "stage5-calibration-sample-table.json"
            stage5_json.parent.mkdir(parents=True, exist_ok=True)
            stage5_json.write_text(
                json.dumps(
                    {
                        "summary": {"stage5_calibration_sample_count": 1},
                        "records": [
                            {
                                "stage5_calibration_sample_id": "STAGE5-CAL-RUNTIME-1",
                                "project_id": "PROJ-STAGE5-RUNTIME",
                                "project_name": "Stage5 runtime calibration project",
                                "stage5_rule_gate_status": "PASS",
                                "stage5_evidence_gate_status": "PASS",
                                "stage5_calibration_review_bucket": "POTENTIAL_FALSE_POSITIVE_REVIEW",
                                "stage5_abcd_calibration_bucket": "B_PUBLIC_READBACK_REVIEW_REQUIRED",
                                "stage5_calibration_evidence_strength": "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED",
                                "stage5_calibration_review_family": "manual_public_readback_review",
                                "stage5_calibration_review_reasons": [
                                    "STAGE5_PASS_WITH_ACTIVE_STAGE4_GAP"
                                ],
                                "calibration_truth_label_required": True,
                                "suggested_calibration_action": (
                                    "review_truth_label_before_rule_relaxation_or_tightening"
                                ),
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            controller = RunController(stage6_preview_executor=lambda payload: {})
            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-STAGE5-RUNTIME",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "stage5_calibration_sample_json": str(stage5_json),
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        self.assertEqual(result["runtime_controller_mode"], "STAGE1_6_RUNTIME_CYCLE")
        run_state = result["run_state"]
        self.assertEqual(run_state["stage6_cycle_summary"]["stage5_calibration_sample_count"], 1)
        self.assertEqual(run_state["stage6_cycle_summary"]["stage5_calibration_truth_label_required_count"], 1)
        self.assertEqual(
            run_state["stage6_cycle_summary"]["stage5_abcd_calibration_counts"],
            {"B_PUBLIC_READBACK_REVIEW_REQUIRED": 1},
        )
        self.assertEqual(
            run_state["stage6_cycle_summary"]["stage5_calibration_evidence_strength_counts"],
            {"PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED": 1},
        )
        self.assertEqual(
            run_state["stage6_cycle_summary"]["stage5_calibration_review_family_counts"],
            {"manual_public_readback_review": 1},
        )
        stage5_review_tasks = [
            task
            for task in result["dispatch_queue"]["records"]
            if task["dispatch_task_id"].endswith("stage5-calibration-truth-label-review")
        ]
        self.assertEqual(len(stage5_review_tasks), 1)
        self.assertEqual(stage5_review_tasks[0]["action_type"], "REVIEW")
        self.assertEqual(stage5_review_tasks[0]["dispatch_state"], "WAITING_FOR_REVIEW")
        self.assertEqual(stage5_review_tasks[0]["review_family"], "manual_public_readback_review")
        self.assertEqual(stage5_review_tasks[0]["review_state"], "WAITING_FOR_STAGE5_TRUTH_LABEL_REVIEW")
        self.assertEqual(stage5_review_tasks[0]["input_refs"], [str(stage5_json)])
        self.assertFalse(stage5_review_tasks[0]["external_customer_action_enabled"])
        self.assertEqual(
            run_state["runtime_blocker_controller_summary"]["controller_derived_dispatch_review_family_counts"],
            {"manual_public_readback_review": 1},
        )
        self.assertIn(str(stage5_json), run_state["input_refs"])
        events = result["audit_ledger"]["events"]
        event_types = [event["event_type"] for event in events]
        self.assertIn("STAGE5_CALIBRATION_LEDGER_RECORDED", event_types)
        self.assertIn("STAGE5_CALIBRATION_REVIEW_TASK_DERIVED", event_types)
        calibration_event = next(
            event for event in events if event["event_type"] == "STAGE5_CALIBRATION_LEDGER_RECORDED"
        )
        self.assertEqual(calibration_event["stage_id"], "stage5_rules_evidence")
        self.assertEqual(calibration_event["details"]["stage5_calibration_sample_count"], 1)
        self.assertEqual(
            calibration_event["details"]["stage5_calibration_review_bucket_counts"],
            {"POTENTIAL_FALSE_POSITIVE_REVIEW": 1},
        )
        self.assertEqual(
            calibration_event["details"]["stage5_abcd_calibration_counts"],
            {"B_PUBLIC_READBACK_REVIEW_REQUIRED": 1},
        )
        self.assertEqual(
            calibration_event["details"]["stage5_calibration_evidence_strength_counts"],
            {"PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED": 1},
        )
        self.assertEqual(
            calibration_event["details"]["stage5_calibration_review_family_counts"],
            {"manual_public_readback_review": 1},
        )
        self.assertEqual(
            calibration_event["details"]["stage5_calibration_suggested_action_counts"],
            {"review_truth_label_before_rule_relaxation_or_tightening": 1},
        )
        review_event = next(
            event for event in events if event["event_type"] == "STAGE5_CALIBRATION_REVIEW_TASK_DERIVED"
        )
        self.assertEqual(review_event["stage_id"], "stage5_rules_evidence")
        self.assertEqual(review_event["details"]["dispatch_state"], "WAITING_FOR_REVIEW")
        self.assertEqual(review_event["details"]["review_family"], "manual_public_readback_review")
        self.assertFalse(review_event["details"]["external_customer_action_enabled"])
        status_rows = result["stage6_cycle_result"]["manifest"]["operator_projection_status_table"]["records"]
        self.assertEqual(status_rows[0]["loop_terminal_state"], "STAGE5_CALIBRATION_REVIEW_READY")
        self.assertFalse(result["customer_visible_allowed"])

    def test_run_controller_records_stage4_release_field_query_ledger_from_runtime_cycle(self) -> None:
        from runtime.run_controller import RunController
        from tests.test_stage6_review_cycle_runner import _write_batch_closeout, _write_evidence_state

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_json = _write_evidence_state(root / "state")
            _write_batch_closeout(root / "closeout", evidence_state_json=state_json)
            field_query_json = root / "guangdong-local-field-query-probe-v1.json"
            field_query_json.write_text(
                json.dumps(
                    {
                        "safe_to_execute": True,
                        "blocking_reasons": [],
                        "manifest": {
                            "manifest_id": "GD-FIELD-RUNTIME-CONTROLLER-1",
                            "field_task_records": [
                                {
                                    "field_query_task_id": "GD-FIELD-RUNTIME-AUTH",
                                    "project_id": "PROJ-STAGE4-FIELD-RUNTIME",
                                    "project_name": "Stage4 field runtime project",
                                    "source_profile_id": "GUANGDONG-GDCIC-HOME",
                                    "adapter_result_state": "NEEDS_BROWSER",
                                    "downstream_release_evidence_abcd_grade": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
                                    "field_summary": {
                                        "authorized_session_input_state": "NO_AUTHORIZED_SESSION_INPUT",
                                        "authorized_session_input_ready": False,
                                        "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
                                        "operator_next_actions": [
                                            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"
                                        ],
                                    },
                                    "customer_visible_allowed": False,
                                    "no_legal_conclusion": True,
                                }
                            ],
                        },
                        "summary": {"guangdong_local_field_query_task_count": 1},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            controller = RunController(stage6_preview_executor=lambda payload: {})
            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-STAGE4-FIELD-RUNTIME",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "closeout"),
                    "release_field_query_json": str(field_query_json),
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        stage4_summary = result["run_state"]["stage4_release_field_query_summary"]
        self.assertEqual(stage4_summary["release_field_query_project_count"], 1)
        self.assertEqual(
            stage4_summary["release_field_query_authorization_state_counts"],
            {"LOGIN_OR_SSO_REQUIRED": 1},
        )
        self.assertEqual(
            stage4_summary["release_field_query_operator_next_action_counts"],
            {"provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1},
        )
        self.assertEqual(result["run_state"]["next_action"]["entrypoint_id"], "guangdong_local_field_query_probe")
        self.assertEqual(
            result["run_state"]["next_action"]["reason"],
            "stage4_release_field_query_authorized_readback_required",
        )
        self.assertEqual(result["dispatch_queue"]["records"][0]["entrypoint_id"], "guangdong_local_field_query_probe")
        self.assertEqual(result["dispatch_queue"]["records"][0]["dispatch_state"], "READY_FOR_INTERNAL_DISPATCH")
        self.assertFalse(result["dispatch_queue"]["records"][0]["external_customer_action_enabled"])
        self.assertEqual(
            result["run_state"]["runtime_blocker_controller_summary"]["controller_derived_dispatch_entrypoint_counts"],
            {"guangdong_local_field_query_probe": 1},
        )
        self.assertTrue(stage4_summary["query_miss_is_not_clearance"])
        self.assertIn(str(field_query_json), result["run_state"]["input_refs"])
        events = result["audit_ledger"]["events"]
        event_types = [event["event_type"] for event in events]
        self.assertIn("STAGE4_RELEASE_FIELD_QUERY_LEDGER_RECORDED", event_types)
        field_query_event = next(
            event for event in events if event["event_type"] == "STAGE4_RELEASE_FIELD_QUERY_LEDGER_RECORDED"
        )
        self.assertEqual(field_query_event["stage_id"], "stage4_verification")
        self.assertEqual(field_query_event["details"]["release_field_query_project_count"], 1)
        self.assertEqual(
            field_query_event["details"]["release_field_query_authorized_session_input_state_counts"],
            {"NO_AUTHORIZED_SESSION_INPUT": 1},
        )
        self.assertEqual(
            field_query_event["details"]["release_field_query_operator_next_action_counts"],
            {"provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1},
        )
        self.assertTrue(field_query_event["details"]["query_miss_is_not_clearance"])
        self.assertFalse(result["customer_visible_allowed"])
        self.assertNotIn("无风险", str(result))

    def test_run_controller_records_stage4_release_chain_bootstrap_ledger_from_p13b_continuation(self) -> None:
        from runtime.run_controller import RunController
        from tests.test_stage6_review_cycle_runner import _write_standalone_stage16_p13b_continuation

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stage16_json = _write_standalone_stage16_p13b_continuation(root / "stage16")

            controller = RunController(stage6_preview_executor=lambda payload: {})
            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-P13B-HOLD",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "stage16_p13b_continuation_json": str(stage16_json),
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        summary = result["run_state"]["stage4_release_chain_bootstrap_summary"]
        self.assertEqual(summary["stage4_release_chain_bootstrap_source_kind"], "STAGE16_P13B_CONTINUATION_JSON")
        self.assertEqual(summary["stage4_release_chain_project_count"], 1)
        self.assertEqual(
            summary["stage4_release_chain_runtime_blocker_state_counts"],
            {"TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1},
        )
        self.assertEqual(
            summary["stage4_release_chain_manual_action_family_counts"],
            {"P13B_RELEASE_EVIDENCE_TARGETED_REVIEW": 1},
        )
        self.assertEqual(
            summary["stage4_release_chain_next_action_counts"],
            {"rerun_stage6_review_cycle_after_reopen_input_is_recorded": 1},
        )
        self.assertEqual(
            summary["stage4_release_chain_input_refs"]["source_stage16_p13b_continuation_json"],
            str(stage16_json),
        )
        self.assertTrue(summary["query_miss_is_not_clearance"])
        self.assertIn(str(stage16_json), result["run_state"]["input_refs"])

        event_types = [event["event_type"] for event in result["audit_ledger"]["events"]]
        self.assertIn("STAGE4_RELEASE_CHAIN_BOOTSTRAP_LEDGER_RECORDED", event_types)
        event = next(
            event for event in result["audit_ledger"]["events"]
            if event["event_type"] == "STAGE4_RELEASE_CHAIN_BOOTSTRAP_LEDGER_RECORDED"
        )
        self.assertEqual(event["stage_id"], "stage4_verification")
        self.assertEqual(event["details"]["stage4_release_chain_runtime_blocker_ledger_count"], 1)
        self.assertEqual(
            event["details"]["stage4_release_chain_manual_action_family_counts"],
            {"P13B_RELEASE_EVIDENCE_TARGETED_REVIEW": 1},
        )
        self.assertTrue(event["details"]["query_miss_is_not_clearance"])
        self.assertFalse(result["customer_visible_allowed"])
        self.assertNotIn("无风险", str(result))

    def test_run_controller_records_stage1_6_batch_readiness_ledger(self) -> None:
        from runtime.run_controller import RunController

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readiness_json = root / "stage1-6-readiness-table.json"
            gap_json = root / "stage1-6-gap-summary-table.json"
            readiness_json.write_text(
                json.dumps(
                    {
                        "summary": {
                            "stage1_6_readiness_record_count": 3,
                            "stage4_release_adapter_bridge_project_code_recall_summary": {
                                "bridge_task_count": 1,
                                "with_gdcic_project_code_variant_task_count": 1,
                                "missing_gdcic_project_code_variant_task_count": 0,
                                "project_code_recall_state": "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
                            },
                            "stage1_3_stability_summary": {
                                "stage2_attachment_capture_attempted_count": 2,
                                "stage2_attachment_snapshot_count": 1,
                                "stage2_attachment_snapshot_missing_count": 1,
                                "attachment_snapshot_readback_missing_count": 1,
                                "stage3_attachment_ocr_required_count": 2,
                                "stage3_attachment_ocr_extracted_count": 1,
                                "stage3_attachment_ocr_pending_count": 1,
                                "attachment_text_cache_hit_count": 1,
                                "stage3_responsible_role_gap_count": 1,
                                "stage3_parse_blocker_count": 0,
                            },
                        },
                        "records": [
                            {
                                "project_id": "PROJ-READY",
                                "stage1_6_readiness_state": "STAGE1_6_INTERNAL_READY",
                                "bottleneck_stage": "Stage6",
                                "recommended_next_action": "advance_to_stage7_9_internal_review",
                                "customer_visible_allowed": False,
                            },
                            {
                                "project_id": "PROJ-STAGE3-GAP",
                                "stage1_6_readiness_state": "STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED",
                                "bottleneck_stage": "Stage3",
                                "next_recommended_action": "run_company_first_identifier_resolution_before_stage4_or_stage6",
                                "customer_visible_allowed": False,
                            },
                            {
                                "project_id": "PROJ-STAGE4-GAP",
                                "stage1_6_readiness_state": "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED",
                                "bottleneck_stage": "Stage4",
                                "recommended_next_action": "run_stage4_release_evidence_bridge_builder",
                                "customer_visible_allowed": False,
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            gap_json.write_text(
                json.dumps(
                    {
                        "summary": {"stage1_6_gap_summary_record_count": 2},
                        "records": [
                            {
                                "gap_family": "stage1_6_readiness_state",
                                "gap_state": "STAGE3_FIELD_OR_ROLE_REVIEW_REQUIRED",
                                "next_action": "review_stage3_parse_fields",
                            },
                            {
                                "gap_family": "stage1_6_readiness_state",
                                "gap_state": "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED",
                                "next_action": "run_stage4_release_evidence_bridge_builder",
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            controller = RunController(stage6_preview_executor=lambda payload: {})
            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-STAGE1-6-READINESS",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "stage1_6_readiness_json": str(readiness_json),
                    "stage1_6_gap_summary_json": str(gap_json),
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        summary = result["run_state"]["stage1_6_readiness_summary"]
        self.assertEqual(summary["stage1_6_batch_regression_ledger_state"], "READY")
        self.assertEqual(summary["stage1_6_readiness_record_count"], 3)
        self.assertEqual(summary["stage1_6_gap_summary_record_count"], 2)
        self.assertEqual(summary["stage1_6_internal_ready_count"], 1)
        self.assertEqual(summary["stage1_6_review_or_blocked_count"], 2)
        self.assertEqual(
            summary["stage1_6_bottleneck_stage_counts"],
            {"Stage6": 1, "Stage3": 1, "Stage4": 1},
        )
        self.assertEqual(
            summary["stage1_6_next_action_counts"],
            {
                "advance_to_stage7_9_internal_review": 1,
                "run_company_first_identifier_resolution_before_stage4_or_stage6": 1,
                "run_stage4_release_evidence_bridge_builder": 1,
            },
        )
        self.assertEqual(
            summary["stage1_6_gap_next_action_counts"],
            {
                "review_stage3_parse_fields": 1,
                "run_stage4_release_evidence_bridge_builder": 1,
            },
        )
        self.assertEqual(summary["stage1_3_stability_summary"]["stage2_attachment_snapshot_missing_count"], 1)
        self.assertEqual(summary["stage1_3_stability_summary"]["stage3_attachment_ocr_pending_count"], 1)
        self.assertEqual(summary["stage1_3_stability_summary"]["stage3_responsible_role_gap_count"], 1)
        self.assertEqual(
            summary["stage4_release_adapter_bridge_project_code_recall_summary"]["project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertEqual(
            summary["stage4_release_adapter_bridge_project_code_recall_summary"][
                "with_gdcic_project_code_variant_task_count"
            ],
            1,
        )
        stability_tasks = [
            task
            for task in result["dispatch_queue"]["records"]
            if str(task.get("review_family") or "").startswith("stage1_3_")
        ]
        self.assertEqual(
            {task["review_family"] for task in stability_tasks},
            {
                "stage1_3_attachment_snapshot_repair",
                "stage1_3_attachment_snapshot_readback_repair",
                "stage1_3_attachment_ocr_repair",
                "stage1_3_responsible_role_review",
            },
        )
        self.assertTrue(all(task["entrypoint_id"] == "stage1_3_repair_worker" for task in stability_tasks))
        self.assertTrue(all(task["dispatch_state"] == "READY_FOR_INTERNAL_DISPATCH" for task in stability_tasks))
        self.assertTrue(all(task["action_type"] == "REVIEW" for task in stability_tasks))
        self.assertTrue(all(not task["external_customer_action_enabled"] for task in stability_tasks))
        self.assertTrue(all(str(readiness_json) in task["input_refs"] for task in stability_tasks))
        self.assertEqual(
            {
                task["source_metric"]: task["metric_count"]
                for task in stability_tasks
            },
            {
                "stage2_attachment_snapshot_missing_count": 1,
                "attachment_snapshot_readback_missing_count": 1,
                "stage3_attachment_ocr_pending_count": 1,
                "stage3_responsible_role_gap_count": 1,
            },
        )
        self.assertTrue(all(task["operator_next_action"] for task in stability_tasks))
        self.assertEqual(
            result["run_state"]["runtime_blocker_controller_summary"]["controller_derived_dispatch_entrypoint_counts"],
            {"stage4_release_evidence_bridge_builder": 1, "stage1_3_repair_worker": 4},
        )
        self.assertEqual(
            result["run_state"]["runtime_blocker_controller_summary"]["controller_derived_dispatch_ready_count"],
            5,
        )
        self.assertEqual(
            result["run_state"]["runtime_blocker_controller_summary"]["controller_derived_dispatch_review_family_counts"],
            {
                "stage1_3_attachment_snapshot_repair": 1,
                "stage1_3_attachment_snapshot_readback_repair": 1,
                "stage1_3_attachment_ocr_repair": 1,
                "stage1_3_responsible_role_review": 1,
            },
        )
        self.assertEqual(result["run_state"]["runtime_blocker_controller_summary"]["stage1_3_repair_task_count"], 4)
        self.assertEqual(
            result["run_state"]["runtime_blocker_controller_summary"]["stage1_3_repair_metric_counts"],
            {
                "stage2_attachment_snapshot_missing_count": 1,
                "attachment_snapshot_readback_missing_count": 1,
                "stage3_attachment_ocr_pending_count": 1,
                "stage3_responsible_role_gap_count": 1,
            },
        )
        self.assertIn(str(readiness_json), result["run_state"]["input_refs"])
        self.assertIn(str(gap_json), result["run_state"]["input_refs"])

        events = result["audit_ledger"]["events"]
        event_types = [event["event_type"] for event in events]
        self.assertIn("STAGE1_6_BATCH_READINESS_LEDGER_RECORDED", event_types)
        self.assertEqual(event_types.count("STAGE1_3_STABILITY_REPAIR_TASK_DERIVED"), 4)
        repair_event = next(
            event for event in events if event["event_type"] == "STAGE1_3_STABILITY_REPAIR_TASK_DERIVED"
        )
        self.assertIn("source_metric", repair_event["details"])
        self.assertEqual(repair_event["details"]["metric_count"], 1)
        self.assertEqual(repair_event["details"]["dispatch_state"], "READY_FOR_INTERNAL_DISPATCH")
        readiness_event = next(
            event for event in events if event["event_type"] == "STAGE1_6_BATCH_READINESS_LEDGER_RECORDED"
        )
        self.assertEqual(readiness_event["stage_id"], "stage1_tasking")
        self.assertEqual(readiness_event["details"]["stage1_6_review_or_blocked_count"], 2)
        self.assertEqual(
            readiness_event["details"]["stage1_3_stability_summary"]["attachment_snapshot_readback_missing_count"],
            1,
        )
        self.assertTrue(readiness_event["details"]["query_miss_is_not_clearance"])
        self.assertFalse(result["customer_visible_allowed"])
        self.assertNotIn("无风险", str(result))

    def test_run_controller_consumes_stage123_front_chain_and_persists_runtime_state(self) -> None:
        from runtime.run_controller import RunController
        from storage.db import DatabaseSession
        from storage.repositories.runtime_state_repo import (
            RUNTIME_AUDIT_EVENT_OBJECT_TYPE,
            RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE,
            RUNTIME_RUN_STATE_OBJECT_TYPE,
            RUNTIME_WORKER_RESULT_OBJECT_TYPE,
            RuntimeStateRepository,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            session = DatabaseSession(storage_path=root / "runtime-state.json")
            repository = RuntimeStateRepository(session=session)
            controller = RunController(
                stage6_preview_executor=lambda payload: {},
                runtime_state_repository=repository,
            )

            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-STAGE123-RUNTIME",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "output_root": str(root / "stage6-out"),
                    "stage123_front_chain_output_root": str(root / "stage123-out"),
                    "stage1_market_scan_payload": {
                        "task_id": "TASK-STAGE123-RUNTIME",
                        "source_selection_mode": "AUTOMATED_POLICY",
                        "notice_candidates": [
                            {
                                "notice_id": "NOTICE-STAGE123",
                                "project_id": "PROJ-STAGE123-RUNTIME",
                                "project_name": "Stage123 runtime candidate",
                                "region_code": "CN-GD",
                                "project_type": "municipal",
                                "notice_stage": "candidate_notice",
                                "amount": 12000000,
                                "candidate_count": 4,
                                "candidate_company": "示例公司",
                                "source_url": "https://example.test/notice",
                                "source_family": "guangzhou_public_resource_trading",
                                "source_registry_id": "SRC-REG-PROC-GZ-CANDIDATE",
                                "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                                "objection_deadline_at_optional": "2026-05-30T00:00:00+08:00",
                                "key_fields_present": ["project_name", "candidate_company", "notice_stage"],
                            }
                        ],
                    },
                    "stage2_capture_records": [
                        {
                            "project_id": "PROJ-STAGE123-RUNTIME",
                            "stage2_capture_state": "CAPTURED",
                            "attachment_capture_attempted_count": 2,
                            "attachment_snapshot_count": 1,
                            "degraded_reasons": ["attachment_snapshot_readback_missing"],
                            "output_artifact_refs": ["memory://stage2/PROJ-STAGE123-RUNTIME/detail"],
                            "customer_visible_allowed": False,
                        }
                    ],
                    "stage3_parse_records": [
                        {
                            "project_id": "PROJ-STAGE123-RUNTIME",
                            "stage3_parse_state": "PARSED",
                            "input_artifact_refs": ["memory://stage2/PROJ-STAGE123-RUNTIME/detail"],
                            "output_artifact_refs": ["memory://stage3/PROJ-STAGE123-RUNTIME/parsed"],
                            "attachment_ocr_required_count": 2,
                            "attachment_ocr_extracted_count": 1,
                            "attachment_text_cache_hit_count": 1,
                            "responsible_role_gap_review_required": True,
                            "responsible_role_gap_code": "B_CLASS_DIRECTOR_CERTIFICATE_MISSING",
                            "customer_visible_allowed": False,
                        }
                    ],
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        run_state = result["run_state"]
        self.assertEqual(run_state["stage123_front_chain_summary"]["stage123_front_chain_state"], "READY")
        self.assertEqual(run_state["stage123_front_chain_summary"]["stage1_selected_candidate_count"], 1)
        self.assertEqual(run_state["stage123_front_chain_summary"]["stage2_capture_record_count"], 1)
        self.assertEqual(run_state["stage123_front_chain_summary"]["stage3_parse_record_count"], 1)
        stability = run_state["stage123_front_chain_summary"]["stage123_stability_summary"]
        self.assertEqual(stability["stage2_attachment_snapshot_missing_count"], 1)
        self.assertEqual(stability["attachment_snapshot_readback_missing_count"], 1)
        self.assertEqual(stability["stage3_attachment_ocr_pending_count"], 1)
        self.assertEqual(stability["attachment_text_cache_hit_count"], 1)
        self.assertEqual(stability["stage3_responsible_role_gap_count"], 1)
        self.assertIn("memory://stage3/PROJ-STAGE123-RUNTIME/parsed", run_state["output_artifact_refs"])
        self.assertIn("STAGE123_FRONT_CHAIN_RECORDED", [event["event_type"] for event in result["audit_ledger"]["events"]])
        self.assertEqual(result["runtime_persistence"]["runtime_persistence_state"], "PERSISTED")
        self.assertEqual(result["runtime_persistence"]["audit_event_count"], len(result["audit_ledger"]["events"]))

        persisted = repository.get_run(run_state["run_id"])
        self.assertEqual(persisted["run_state"]["run_id"], run_state["run_id"])
        self.assertEqual(
            repository.list_by_project("PROJ-STAGE123-RUNTIME")[0]["run_state"]["project_id"],
            "PROJ-STAGE123-RUNTIME",
        )
        self.assertEqual(
            repository.list_by_entrypoint("stage6_review_cycle_runner")[0]["run_state"]["entrypoint_id"],
            "stage6_review_cycle_runner",
        )
        self.assertFalse(persisted["run_state"]["safety"]["external_customer_action_enabled"])
        record = session.get_record(RUNTIME_RUN_STATE_OBJECT_TYPE, run_state["run_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.trace_refs["stage123_front_chain_state"], "READY")
        self.assertEqual(record.trace_refs["output_artifact_ref_count"], str(len(run_state["output_artifact_refs"])))
        self.assertEqual(record.trace_refs["stage123_attachment_snapshot_missing_count"], "1")
        self.assertEqual(record.trace_refs["stage123_attachment_snapshot_readback_missing_count"], "1")
        self.assertEqual(record.trace_refs["stage123_attachment_ocr_pending_count"], "1")
        self.assertEqual(record.trace_refs["stage123_responsible_role_gap_count"], "1")
        self.assertIn("memory://stage3/PROJ-STAGE123-RUNTIME/parsed", record.trace_refs["output_artifact_refs_json"])

    def test_runtime_cycle_records_explicit_stage123_input_artifact_failures_as_blockers(self) -> None:
        from runtime.run_controller import RunController

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            controller = RunController(
                stage6_preview_executor=lambda payload: {},
                stage6_cycle_runner=lambda **kwargs: {
                    "safe_to_execute": True,
                    "summary": {},
                    "manifest": {},
                    "blocking_reasons": [],
                },
            )

            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-STAGE123-BAD-INPUT",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "stage123_front_chain_output_root": str(root / "stage123-out"),
                    "stage1_market_scan_json": str(root / "missing-market-scan.json"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        summary = result["run_state"]["stage123_front_chain_summary"]
        self.assertIn("BLOCKED_INPUT_MISSING:stage1_market_scan_json", summary["blocking_reasons"])
        self.assertIn("BLOCKED_INPUT_MISSING:stage1_market_scan_json", result["run_state"]["blocking_reasons"])
        diagnostic = summary["input_artifact_diagnostics"][0]
        self.assertEqual(diagnostic["blocker_code"], "BLOCKED_INPUT_MISSING")
        self.assertEqual(diagnostic["input_field"], "stage1_market_scan_json")
        event = next(event for event in result["audit_ledger"]["events"] if event["event_type"] == "STAGE123_FRONT_CHAIN_RECORDED")
        self.assertIn("BLOCKED_INPUT_MISSING:stage1_market_scan_json", event["details"]["summary"]["blocking_reasons"])

    def test_runtime_cycle_records_explicit_controller_json_failures_as_blockers(self) -> None:
        from runtime.run_controller import RunController

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bad_json = root / "bad-readiness.json"
            bad_json.write_text("{not-json", encoding="utf-8")
            non_object_json = root / "non-object-gap.json"
            non_object_json.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            controller = RunController(
                stage6_preview_executor=lambda payload: {},
                stage6_cycle_runner=lambda **kwargs: {
                    "safe_to_execute": True,
                    "summary": {},
                    "manifest": {},
                    "blocking_reasons": [],
                },
            )

            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-RUNTIME-BAD-INPUT",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "stage1_6_readiness_json": str(bad_json),
                    "stage1_6_gap_summary_json": str(non_object_json),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        self.assertIn("BLOCKED_INPUT_INVALID_JSON:stage1_6_readiness_json", result["run_state"]["blocking_reasons"])
        self.assertIn("BLOCKED_INPUT_NOT_OBJECT:stage1_6_gap_summary_json", result["run_state"]["blocking_reasons"])
        self.assertEqual(
            result["run_state"]["input_artifact_diagnostics"][0]["blocker_code"],
            "BLOCKED_INPUT_INVALID_JSON",
        )
        self.assertEqual(
            result["run_state"]["input_artifact_diagnostics"][1]["blocker_code"],
            "BLOCKED_INPUT_NOT_OBJECT",
        )
        event = next(
            event
            for event in result["audit_ledger"]["events"]
            if event["event_type"] == "RUNTIME_INPUT_ARTIFACT_BLOCKER_RECORDED"
        )
        self.assertIn("BLOCKED_INPUT_INVALID_JSON:stage1_6_readiness_json", event["details"]["blocking_reasons"])
        self.assertIn("BLOCKED_INPUT_NOT_OBJECT:stage1_6_gap_summary_json", event["details"]["blocking_reasons"])

    def test_runtime_state_repository_indexes_controller_consumed_artifact_trace_refs(self) -> None:
        from runtime.run_controller import RunController
        from storage.db import DatabaseSession
        from storage.repositories.runtime_state_repo import (
            RUNTIME_AUDIT_EVENT_OBJECT_TYPE,
            RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE,
            RUNTIME_RUN_STATE_OBJECT_TYPE,
            RuntimeStateRepository,
        )

        def stage6_cycle_runner(**kwargs: Any) -> Mapping[str, Any]:
            return {
                "safe_to_execute": False,
                "blocking_reasons": ["stage4_release_evidence_requires_authorized_readback"],
                "summary": {
                    "release_field_query_project_count": 1,
                    "release_field_query_state_counts": {"NEEDS_BROWSER": 1},
                    "release_field_query_authorization_state_counts": {"LOGIN_OR_SSO_REQUIRED": 1},
                    "release_field_query_authorized_session_input_state_counts": {
                        "NO_AUTHORIZED_SESSION_INPUT": 1,
                    },
                    "release_field_query_operator_next_action_counts": {
                        "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1
                    },
                    "release_field_query_project_manager_change_ready_count": 1,
                    "release_field_query_project_manager_change_interpretation_counts": {
                        "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1,
                    },
                    "stage6_review_cycle_bootstrap_source_kind": "STAGE16_P13B_CONTINUATION_JSON",
                    "stage6_review_cycle_bootstrap_selected_handler_kind": "stage16_p13b_continuation",
                    "stage5_calibration_sample_count": 1,
                    "stage5_calibration_truth_label_required_count": 1,
                    "stage5_abcd_calibration_counts": {"D_BLOCKED_OR_AUTHORIZATION_REQUIRED": 1},
                    "stage5_calibration_evidence_strength_counts": {
                        "BLOCKED_BY_AUTHORIZATION_OR_SOURCE": 1,
                    },
                    "stage5_calibration_review_bucket_counts": {
                        "POTENTIAL_FALSE_NEGATIVE_REVIEW": 1,
                    },
                    "stage5_calibration_review_family_counts": {
                        "manual_authorized_browser_review": 1,
                    },
                    "stage5_calibration_suggested_action_counts": {
                        "collect_authorized_readback_before_rule_change": 1,
                    },
                    "runtime_blocker_next_subqueue_input_state": "READY",
                    "runtime_blocker_controller_dispatch_task_count": 1,
                    "runtime_blocker_controller_dispatch_ready_count": 1,
                },
                "manifest": {
                    "source_release_evidence_adapter_plan_json": kwargs["release_evidence_adapter_plan_json"],
                    "source_stage16_p13b_continuation_json": kwargs["stage16_p13b_continuation_json"],
                    "operator_projection_status_table": {
                        "records": [
                            {
                                "project_id": "PROJ-RUNTIME-TRACE",
                                "dispatch_task_type": "P13B_RELEASE_EVIDENCE_FIELD_QUERY",
                                "next_cycle_manual_only_action_family": "P13B_RELEASE_CHAIN",
                                "loop_terminal_state": "AUTHORIZATION_HOLD",
                                "runtime_blocker_ledger_records": [
                                    {
                                        "ledger_scope": "p13b_continuation",
                                        "blocker_state": "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
                                    }
                                ],
                            }
                        ]
                    },
                    "stage6_fact_package_json": "memory://stage6/PROJ-RUNTIME-TRACE/fact-package",
                    "operator_projection_status_table_json": "memory://stage6/PROJ-RUNTIME-TRACE/operator-projection",
                },
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            session = DatabaseSession(storage_path=root / "runtime-state.json")
            repository = RuntimeStateRepository(session=session)
            readiness_json = root / "stage1-6-readiness-table.json"
            gap_json = root / "stage1-6-gap-summary-table.json"
            stage5_json = root / "stage5-calibration-sample-table.json"
            release_plan_json = root / "release-evidence-adapter-plan-v1.json"
            stage16_json = root / "stage16-p13b-continuation.json"
            readiness_json.write_text(
                json.dumps(
                    {
                        "summary": {
                            "stage4_release_adapter_bridge_project_code_recall_summary": {
                                "bridge_task_count": 2,
                                "with_gdcic_project_code_variant_task_count": 1,
                                "missing_gdcic_project_code_variant_task_count": 1,
                                "project_code_recall_state": "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
                                "query_miss_is_not_clearance": True,
                            },
                            "stage1_3_stability_summary": {
                                "stage2_attachment_snapshot_missing_count": 1,
                                "attachment_snapshot_readback_missing_count": 1,
                                "stage3_attachment_ocr_pending_count": 1,
                                "stage3_responsible_role_gap_count": 1,
                            }
                        },
                        "records": [
                            {
                                "project_id": "PROJ-RUNTIME-TRACE",
                                "stage1_6_readiness_state": "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED",
                                "bottleneck_stage": "Stage4",
                                "recommended_next_action": "run_stage4_release_evidence_bridge_builder",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            gap_json.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "gap_family": "stage4",
                                "gap_state": "release_evidence_missing",
                                "next_action": "release_evidence_missing",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stage5_json.write_text(
                json.dumps({"records": [{"stage5_calibration_sample_id": "STAGE5-CAL-TRACE"}]}),
                encoding="utf-8",
            )
            release_plan_json.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "summary": {
                                "stage4_release_adapter_plan_project_code_recall_summary": {
                                    "project_code_recall_state": "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
                                    "adapter_task_count": 2,
                                    "with_gdcic_project_code_variant_task_count": 1,
                                    "missing_gdcic_project_code_variant_task_count": 1,
                                    "with_trade_project_code_task_count": 1,
                                    "trade_project_code_only_task_count": 0,
                                    "sample_gdcic_project_code_variants": ["440100202605190001"],
                                    "sample_trade_project_codes": ["JG2026-11337"],
                                    "gdcic_project_code_route_ready": True,
                                    "jg_trade_code_not_sent_to_gdcic_project_code": True,
                                    "query_miss_is_not_clearance": True,
                                    "customer_visible_allowed": False,
                                    "no_legal_conclusion": True,
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stage16_json.write_text(json.dumps({"records": [{"project_id": "PROJ-RUNTIME-TRACE"}]}), encoding="utf-8")

            controller = RunController(
                stage6_preview_executor=lambda payload: {},
                stage6_cycle_runner=stage6_cycle_runner,
                runtime_state_repository=repository,
            )
            result = controller.start_stage1_6_runtime_cycle(
                {
                    "project_id": "PROJ-RUNTIME-TRACE",
                    "entrypoint_id": "stage6_review_cycle_runner",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "stage1_6_readiness_json": str(readiness_json),
                    "stage1_6_gap_summary_json": str(gap_json),
                    "stage5_calibration_sample_json": str(stage5_json),
                    "release_evidence_adapter_plan_json": str(release_plan_json),
                    "stage16_p13b_continuation_json": str(stage16_json),
                    "stage45_replay_samples": {
                        "stage4_probe_results": [
                            {
                                "project_id": "PROJ-RUNTIME-TRACE-NOT-FOUND",
                                "probe_status": "NOT_FOUND",
                                "source_url": "https://example.test/stage4/not-found",
                            },
                            {
                                "project_id": "PROJ-RUNTIME-TRACE-LOGIN",
                                "probe_status": "LOGIN_OR_SSO_REQUIRED",
                                "source_url": "https://example.test/stage4/login",
                            },
                        ],
                        "stage4_public_evidence_readbacks": [
                            {
                                "readback_id": "RB-CREDIT-RUNTIME-TRACE",
                                "verification_target_type": "credit_penalty_blacklist",
                                "source_family": "credit_china",
                                "source_url": "https://example.test/credit/readback",
                                "source_snapshot_id": "SNAP-CREDIT-RUNTIME-TRACE",
                                "snapshot_hash": "sha256-credit-runtime-trace",
                                "official_source": True,
                                "subject_identifier": "91440000MA-RUNTIME-TRACE",
                                "field_extracts": {"source_slice_sha256": "sha256-credit-slice"},
                                "validity_or_status": "ACTIVE",
                                "repair_or_release_state": "UNREPAIRED",
                                "data_grade_or_audit_state": "AUDITED",
                                "public_only": True,
                                "customer_visible": False,
                                "no_legal_conclusion": True,
                            }
                        ],
                        "stage5_rule_codes": ["CREDIT-001", "UNSUPPORTED-001"],
                    },
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

            record = session.get_record(RUNTIME_RUN_STATE_OBJECT_TYPE, result["run_state"]["run_id"])
            projection_record = session.get_record(
                RUNTIME_OPERATOR_PROJECTION_OBJECT_TYPE,
                result["run_state"]["run_id"],
            )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertIsNotNone(projection_record)
        assert projection_record is not None
        projection_payload = dict(projection_record.payload)
        projection_dispatch_records = projection_payload["controller_dispatch_queue"]["records"]
        self.assertGreaterEqual(len(projection_dispatch_records), 1)
        self.assertIn(
            "guangdong_local_field_query_probe",
            {str(record.get("entrypoint_id") or "") for record in projection_dispatch_records},
        )
        self.assertIn(
            "stage1_3_attachment_snapshot_repair",
            {str(record.get("review_family") or "") for record in projection_dispatch_records},
        )
        repair_projection_record = next(
            record
            for record in projection_dispatch_records
            if str(record.get("review_family") or "") == "stage1_3_attachment_snapshot_repair"
        )
        self.assertEqual(repair_projection_record["source_metric"], "stage2_attachment_snapshot_missing_count")
        self.assertEqual(repair_projection_record["metric_count"], 1)
        self.assertEqual(repair_projection_record["entrypoint_id"], "stage1_3_repair_worker")
        self.assertEqual(repair_projection_record["dispatch_state"], "READY_FOR_INTERNAL_DISPATCH")
        self.assertTrue(
            all(not bool(record.get("external_customer_action_enabled")) for record in projection_dispatch_records)
        )
        self.assertFalse(projection_payload["controller_dispatch_queue"]["external_customer_action_enabled"])
        self.assertEqual(
            projection_payload["controller_dispatch_queue"]["summary"]["stage1_3_repair_metric_counts"],
            {
                "stage2_attachment_snapshot_missing_count": 1,
                "attachment_snapshot_readback_missing_count": 1,
                "stage3_attachment_ocr_pending_count": 1,
                "stage3_responsible_role_gap_count": 1,
            },
        )
        trace_refs = record.trace_refs
        self.assertEqual(trace_refs["stage1_6_readiness_record_count"], "1")
        self.assertEqual(trace_refs["stage1_6_gap_summary_record_count"], "1")
        self.assertIn(
            "run_stage4_release_evidence_bridge_builder",
            trace_refs["stage1_6_next_action_counts_json"],
        )
        self.assertIn(
            "release_evidence_missing",
            trace_refs["stage1_6_gap_next_action_counts_json"],
        )
        self.assertEqual(trace_refs["stage1_6_attachment_snapshot_missing_count"], "1")
        self.assertEqual(trace_refs["stage1_6_attachment_snapshot_readback_missing_count"], "1")
        self.assertEqual(trace_refs["stage1_6_attachment_ocr_pending_count"], "1")
        self.assertEqual(trace_refs["stage1_6_responsible_role_gap_count"], "1")
        self.assertEqual(trace_refs["stage1_3_repair_task_count"], "4")
        self.assertIn(
            "stage2_attachment_snapshot_missing_count",
            trace_refs["stage1_3_repair_metric_counts_json"],
        )
        self.assertEqual(
            trace_refs["stage4_release_adapter_bridge_project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertEqual(
            trace_refs["stage4_release_adapter_bridge_gdcic_project_code_variant_task_count"],
            "1",
        )
        self.assertEqual(
            trace_refs["stage4_release_adapter_bridge_missing_gdcic_project_code_variant_task_count"],
            "1",
        )
        self.assertEqual(trace_refs["stage4_release_field_query_project_count"], "1")
        self.assertIn("LOGIN_OR_SSO_REQUIRED", trace_refs["stage4_release_field_query_authorization_state_counts_json"])
        self.assertIn(
            "NO_AUTHORIZED_SESSION_INPUT",
            trace_refs["stage4_release_field_query_authorized_session_input_state_counts_json"],
        )
        self.assertIn(
            "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            trace_refs["stage4_release_field_query_operator_next_action_counts_json"],
        )
        self.assertEqual(trace_refs["stage4_release_field_query_project_manager_change_ready_count"], "1")
        self.assertIn(
            "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
            trace_refs["stage4_release_field_query_project_manager_change_interpretation_counts_json"],
        )
        self.assertEqual(trace_refs["stage4_release_chain_source_kind"], "STAGE16_P13B_CONTINUATION_JSON")
        release_chain_input_refs = json.loads(trace_refs["stage4_release_chain_input_refs_json"])
        self.assertEqual(
            release_chain_input_refs["source_release_evidence_adapter_plan_json"],
            str(release_plan_json),
        )
        self.assertEqual(release_chain_input_refs["source_stage16_p13b_continuation_json"], str(stage16_json))
        self.assertEqual(
            trace_refs["stage4_release_adapter_plan_project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertEqual(
            trace_refs["stage4_release_adapter_plan_gdcic_project_code_variant_task_count"],
            "1",
        )
        self.assertEqual(
            trace_refs["stage4_release_adapter_plan_missing_gdcic_project_code_variant_task_count"],
            "1",
        )
        self.assertIn(
            "440100202605190001",
            trace_refs["stage4_release_adapter_plan_project_code_recall_summary_json"],
        )
        self.assertEqual(trace_refs["stage4_release_chain_project_count"], "1")
        self.assertEqual(trace_refs["stage4_release_chain_runtime_blocker_ledger_count"], "1")
        self.assertIn(
            "P13B_RELEASE_CHAIN",
            trace_refs["stage4_release_chain_manual_action_family_counts_json"],
        )
        self.assertIn(
            "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
            trace_refs["stage4_release_chain_runtime_blocker_state_counts_json"],
        )
        self.assertEqual(trace_refs["stage5_calibration_sample_count"], "1")
        self.assertEqual(trace_refs["stage5_calibration_truth_label_required_count"], "1")
        self.assertIn("D_BLOCKED_OR_AUTHORIZATION_REQUIRED", trace_refs["stage5_abcd_calibration_counts_json"])
        self.assertIn(
            "POTENTIAL_FALSE_NEGATIVE_REVIEW",
            trace_refs["stage5_calibration_review_bucket_counts_json"],
        )
        self.assertIn(
            "collect_authorized_readback_before_rule_change",
            trace_refs["stage5_calibration_suggested_action_counts_json"],
        )
        self.assertEqual(trace_refs["stage45_replay_stage4_probe_replay_count"], "2")
        self.assertEqual(trace_refs["stage45_replay_stage4_blocker_ledger_count"], "2")
        self.assertEqual(trace_refs["stage45_replay_operator_action_count"], "2")
        stage45_route_counts = json.loads(trace_refs["stage45_replay_runtime_blocker_subqueue_route_counts_json"])
        self.assertEqual(stage45_route_counts["browser_worker"], 1)
        self.assertEqual(stage45_route_counts["fallback_source"], 1)
        self.assertIn("CREDIT-001", trace_refs["stage45_replay_stage5_executed_rule_codes_json"])
        self.assertIn("UNSUPPORTED-001", trace_refs["stage45_replay_stage5_skipped_rule_codes_json"])
        self.assertEqual(trace_refs["stage45_replay_stage5_missing_readback_count"], "1")
        self.assertEqual(trace_refs["stage45_replay_stage5_calibration_sample_count"], "2")
        self.assertEqual(trace_refs["stage45_replay_stage5_calibration_truth_label_required_count"], "1")
        self.assertIn(
            "D_UNSUPPORTED_RULE_OR_RUNTIME_BLOCKED",
            trace_refs["stage45_replay_stage5_abcd_calibration_counts_json"],
        )
        self.assertEqual(trace_refs["runtime_blocker_next_subqueue_input_state"], "READY")
        self.assertEqual(trace_refs["runtime_blocker_controller_dispatch_task_count"], "1")
        self.assertEqual(trace_refs["stage8_outreach_boundary_state"], "CONTROLLED_OPENING_PREREQUISITES_ONLY")
        self.assertEqual(
            trace_refs["stage9_payment_delivery_refund_boundary_state"],
            "CONTROLLED_OPENING_PREREQUISITES_ONLY",
        )
        self.assertEqual(trace_refs["automatic_refund_policy_state"], "EXCLUDED")
        self.assertIn("automatic_refund", trace_refs["controlled_boundary_blocked_action_families_json"])
        self.assertIn("approval_chain_passed", trace_refs["controlled_boundary_required_before_live_execution_json"])
        self.assertEqual(trace_refs["controlled_boundary_required_before_live_execution_count"], "4")
        input_refs = json.loads(trace_refs["input_refs_json"])
        self.assertIn(str(readiness_json), input_refs)
        self.assertIn("memory://stage6/PROJ-RUNTIME-TRACE/fact-package", trace_refs["output_artifact_refs_json"])
        projection_trace_refs = projection_record.trace_refs
        self.assertEqual(projection_record.object_refs["entrypoint_id"], "stage6_review_cycle_runner")
        self.assertIn(
            "run_stage4_release_evidence_bridge_builder",
            projection_trace_refs["stage1_6_next_action_counts_json"],
        )
        self.assertIn(
            "release_evidence_missing",
            projection_trace_refs["stage1_6_gap_next_action_counts_json"],
        )
        self.assertEqual(projection_trace_refs["stage1_6_attachment_snapshot_missing_count"], "1")
        self.assertEqual(projection_trace_refs["stage1_6_attachment_snapshot_readback_missing_count"], "1")
        self.assertEqual(projection_trace_refs["stage1_6_attachment_ocr_pending_count"], "1")
        self.assertEqual(projection_trace_refs["stage1_6_responsible_role_gap_count"], "1")
        self.assertEqual(
            projection_trace_refs["stage4_release_adapter_bridge_project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertEqual(
            projection_trace_refs["stage4_release_adapter_bridge_gdcic_project_code_variant_task_count"],
            "1",
        )
        self.assertEqual(
            projection_trace_refs["stage4_release_field_query_project_manager_change_ready_count"],
            "1",
        )
        self.assertIn(
            "NO_AUTHORIZED_SESSION_INPUT",
            projection_trace_refs["stage4_release_field_query_authorized_session_input_state_counts_json"],
        )
        self.assertIn(
            "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
            projection_trace_refs[
                "stage4_release_field_query_project_manager_change_interpretation_counts_json"
            ],
        )
        self.assertEqual(projection_trace_refs["stage4_release_chain_project_count"], "1")
        self.assertEqual(
            projection_trace_refs["stage4_release_adapter_plan_project_code_recall_state"],
            "GDCIC_PROJECT_CODE_VARIANTS_PRESENT",
        )
        self.assertEqual(
            projection_trace_refs["stage4_release_adapter_plan_gdcic_project_code_variant_task_count"],
            "1",
        )
        self.assertIn(
            "JG2026-11337",
            projection_trace_refs["stage4_release_adapter_plan_project_code_recall_summary_json"],
        )
        self.assertIn(
            "P13B_RELEASE_CHAIN",
            projection_trace_refs["stage4_release_chain_manual_action_family_counts_json"],
        )
        self.assertIn(
            "AUTHORIZATION_HOLD_NEEDS_BROWSER_WORKER_OR_OPERATOR_SESSION",
            projection_trace_refs["stage4_release_chain_runtime_blocker_state_counts_json"],
        )
        self.assertEqual(projection_trace_refs["stage5_calibration_sample_count"], "1")
        self.assertEqual(projection_trace_refs["stage5_calibration_truth_label_required_count"], "1")
        self.assertIn(
            "D_BLOCKED_OR_AUTHORIZATION_REQUIRED",
            projection_trace_refs["stage5_abcd_calibration_counts_json"],
        )
        self.assertIn(
            "BLOCKED_BY_AUTHORIZATION_OR_SOURCE",
            projection_trace_refs["stage5_calibration_evidence_strength_counts_json"],
        )
        self.assertIn(
            "manual_authorized_browser_review",
            projection_trace_refs["stage5_calibration_review_family_counts_json"],
        )
        self.assertIn(
            "POTENTIAL_FALSE_NEGATIVE_REVIEW",
            projection_trace_refs["stage5_calibration_review_bucket_counts_json"],
        )
        self.assertIn(
            "collect_authorized_readback_before_rule_change",
            projection_trace_refs["stage5_calibration_suggested_action_counts_json"],
        )
        self.assertEqual(projection_trace_refs["stage45_replay_stage4_probe_replay_count"], "2")
        self.assertEqual(projection_trace_refs["stage45_replay_stage4_blocker_ledger_count"], "2")
        self.assertEqual(projection_trace_refs["stage45_replay_operator_action_count"], "2")
        projection_stage45_route_counts = json.loads(
            projection_trace_refs["stage45_replay_runtime_blocker_subqueue_route_counts_json"]
        )
        self.assertEqual(projection_stage45_route_counts["browser_worker"], 1)
        self.assertEqual(projection_stage45_route_counts["fallback_source"], 1)
        self.assertIn("CREDIT-001", projection_trace_refs["stage45_replay_stage5_executed_rule_codes_json"])
        self.assertIn("UNSUPPORTED-001", projection_trace_refs["stage45_replay_stage5_skipped_rule_codes_json"])
        self.assertEqual(projection_trace_refs["stage45_replay_stage5_missing_readback_count"], "1")
        self.assertEqual(projection_trace_refs["stage45_replay_stage5_calibration_sample_count"], "2")
        self.assertEqual(
            projection_trace_refs["stage45_replay_stage5_calibration_truth_label_required_count"],
            "1",
        )
        self.assertIn(
            "D_UNSUPPORTED_RULE_OR_RUNTIME_BLOCKED",
            projection_trace_refs["stage45_replay_stage5_abcd_calibration_counts_json"],
        )
        self.assertEqual(
            projection_trace_refs["stage8_outreach_boundary_state"],
            "CONTROLLED_OPENING_PREREQUISITES_ONLY",
        )
        self.assertEqual(projection_trace_refs["automatic_refund_policy_state"], "EXCLUDED")
        self.assertIn(
            "operator_action_confirmed",
            projection_trace_refs["controlled_boundary_required_before_live_execution_json"],
        )
        self.assertEqual(
            projection_trace_refs["controlled_boundary_required_before_live_execution_count"],
            "4",
        )
        self.assertIn(
            "real_delivery",
            projection_trace_refs["controlled_boundary_blocked_action_families_json"],
        )
        self.assertEqual(projection_trace_refs["next_action_entrypoint_id"], "guangdong_local_field_query_probe")
        self.assertIn(
            "guangdong_local_field_query_probe",
            projection_trace_refs["runtime_controller_derived_dispatch_entrypoint_counts_json"],
        )
        self.assertIn(
            "manual_authorized_browser_review",
            projection_trace_refs["runtime_controller_derived_dispatch_review_family_counts_json"],
        )
        self.assertIn(
            "stage1_3_attachment_snapshot_repair",
            projection_trace_refs["runtime_controller_derived_dispatch_review_family_counts_json"],
        )
        projection_rows = repository.list_operator_projections_by_trace(
            stage4_release_chain_source_kind="STAGE16_P13B_CONTINUATION_JSON"
        )
        self.assertEqual(projection_rows[0]["run_id"], result["run_state"]["run_id"])
        self.assertEqual(projection_rows[0]["trace_refs"]["stage5_calibration_sample_count"], "1")
        stage4_audit_records = session.find_records(
            RUNTIME_AUDIT_EVENT_OBJECT_TYPE,
            event_type="STAGE4_RELEASE_FIELD_QUERY_LEDGER_RECORDED",
        )
        self.assertEqual(len(stage4_audit_records), 1)
        self.assertEqual(stage4_audit_records[0].trace_refs["release_field_query_project_count"], "1")
        self.assertIn(
            "NO_AUTHORIZED_SESSION_INPUT",
            stage4_audit_records[0].trace_refs[
                "release_field_query_authorized_session_input_state_counts_json"
            ],
        )
        stage5_audit_records = session.find_records(
            RUNTIME_AUDIT_EVENT_OBJECT_TYPE,
            event_type="STAGE5_CALIBRATION_LEDGER_RECORDED",
        )
        self.assertEqual(len(stage5_audit_records), 1)
        self.assertEqual(stage5_audit_records[0].trace_refs["stage5_calibration_sample_count"], "1")
        self.assertEqual(stage5_audit_records[0].trace_refs["stage5_calibration_truth_label_required_count"], "1")
        self.assertIn(
            "D_BLOCKED_OR_AUTHORIZATION_REQUIRED",
            stage5_audit_records[0].trace_refs["stage5_abcd_calibration_counts_json"],
        )
        audit_replay = repository.audit_replay(result["run_state"]["run_id"])
        self.assertEqual(audit_replay["replay_state"], "REPLAY_READY")
        self.assertEqual(audit_replay["event_count"], len(result["audit_ledger"]["events"]))
        self.assertEqual(audit_replay["event_type_counts"]["STAGE5_CALIBRATION_LEDGER_RECORDED"], 1)
        self.assertEqual(audit_replay["event_type_counts"]["STAGE4_RELEASE_FIELD_QUERY_LEDGER_RECORDED"], 1)
        self.assertEqual(audit_replay["stage_id_counts"]["stage4_verification"], 3)
        self.assertFalse(audit_replay["external_customer_action_enabled"])
        self.assertFalse(audit_replay["automatic_refund_enabled"])
        self.assertTrue(audit_replay["query_miss_is_not_clearance"])
        self.assertNotIn("无风险", str(result))

    def test_runtime_projection_merges_gdcic_worker_stage5_calibration_into_persisted_trace_refs(self) -> None:
        from storage.db import DatabaseSession
        from storage.repositories.runtime_state_repo import RuntimeStateRepository

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            session = DatabaseSession(storage_path=root / "runtime-state.json")
            repository = RuntimeStateRepository(session=session)
            repository.save_controller_result(
                {
                    "runtime_controller_mode": "STATE_MACHINE",
                    "customer_visible_allowed": False,
                    "run_state": {
                        "run_id": "RUN-STAGE5-MERGE",
                        "project_id": "PROJ-STAGE5-MERGE",
                        "entrypoint_id": "stage6_review_cycle_runner",
                        "current_stage_id": "stage6_fact_review",
                        "run_state": "BLOCKED",
                        "next_action": {
                            "action_type": "REVIEW",
                            "entrypoint_id": "guangdong_local_field_query_probe",
                        },
                        "stage6_cycle_summary": {
                            "stage5_calibration_sample_count": 1,
                            "stage5_calibration_truth_label_required_count": 1,
                            "stage5_abcd_calibration_counts": {"B_OFFICIAL_READBACK_REVIEW_REQUIRED": 1},
                            "stage5_calibration_review_bucket_counts": {
                                "POTENTIAL_FALSE_POSITIVE_REVIEW": 1,
                            },
                            "stage5_calibration_evidence_strength_counts": {
                                "PUBLIC_READBACK_PRESENT_REVIEW_REQUIRED": 1,
                            },
                            "stage5_calibration_review_family_counts": {
                                "manual_public_readback_review": 1,
                            },
                            "stage5_calibration_suggested_action_counts": {
                                "manual_review_before_rule_change": 1,
                            },
                        },
                        "safety": {
                            "external_customer_action_enabled": False,
                            "real_payment_enabled": False,
                            "real_delivery_enabled": False,
                            "automatic_refund_enabled": False,
                        },
                    },
                    "audit_ledger": {"events": []},
                    "dispatch_queue": {"records": [], "summary": {"dispatch_record_count": 0}},
                }
            )
            repository.save_worker_result(
                {
                    "worker_id": "gdcic_browser_authorized_readback_worker",
                    "worker_result_id": "GDCIC-WORKER-STAGE5-MERGE",
                    "project_id": "PROJ-STAGE5-MERGE",
                    "worker_result_state": "READY",
                    "worker_mode": "PLAN_ONLY_AUTHORIZED_READBACK_SUMMARY",
                    "stage5_calibration_sample_count": 1,
                    "stage5_calibration_truth_label_required_count": 1,
                    "stage5_abcd_calibration_counts": {
                        "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                    },
                    "stage5_calibration_evidence_strength_counts": {
                        "OFFICIAL_READBACK_PRESENT_REVIEW_REQUIRED": 1,
                    },
                    "stage5_calibration_review_family_counts": {
                        "manual_gdcic_project_manager_change_readback_review": 1,
                    },
                    "stage5_calibration_suggested_action_counts": {
                        "manual_review_gdcic_project_manager_change_readback_before_stage5_rule_change": 1,
                    },
                    "customer_visible_allowed": False,
                    "external_customer_action_enabled": False,
                    "live_execution_enabled": False,
                    "real_payment_enabled": False,
                    "real_delivery_enabled": False,
                    "automatic_refund_enabled": False,
                }
            )

            projection = repository.latest_operator_projection()
            calibration = projection["stage5_calibration_summary"]
            self.assertEqual(calibration["stage5_calibration_sample_count"], 2)
            self.assertEqual(calibration["stage5_calibration_truth_label_required_count"], 2)
            self.assertEqual(calibration["stage5_abcd_calibration_counts"]["B_OFFICIAL_READBACK_REVIEW_REQUIRED"], 1)
            self.assertEqual(
                calibration["stage5_abcd_calibration_counts"]["C_REVERSE_EXPLANATION_OFFICIAL_READBACK"],
                1,
            )
            self.assertEqual(calibration["merged_source_count"], 2)
            self.assertEqual(
                projection["stage5_calibration_source_summaries"]["gdcic_authorized_readback_worker"][
                    "stage5_calibration_sample_count"
                ],
                1,
            )
            self.assertEqual(projection["trace_refs"]["stage5_calibration_sample_count"], "2")
            self.assertEqual(projection["trace_refs"]["stage5_calibration_truth_label_required_count"], "2")
            self.assertEqual(projection["trace_refs"]["stage5_calibration_merged_source_count"], "2")
            self.assertIn(
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
                projection["trace_refs"]["stage5_abcd_calibration_counts_json"],
            )
            self.assertIn(
                "gdcic_authorized_readback_worker",
                projection["trace_refs"]["stage5_calibration_source_summaries_json"],
            )
            rows = repository.list_operator_projections_by_trace(stage5_calibration_sample_count="2")
            self.assertEqual(rows[0]["run_id"], "RUN-STAGE5-MERGE")
            self.assertFalse(projection["customer_visible_allowed"])
            self.assertTrue(projection["query_miss_is_not_clearance"])

    def test_runtime_projection_merges_existing_gdcic_worker_when_controller_persists_later(self) -> None:
        from storage.db import DatabaseSession
        from storage.repositories.runtime_state_repo import RuntimeStateRepository

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            session = DatabaseSession(storage_path=root / "runtime-state.json")
            repository = RuntimeStateRepository(session=session)
            repository.save_worker_result(
                {
                    "worker_id": "gdcic_browser_authorized_readback_worker",
                    "worker_result_id": "GDCIC-WORKER-BEFORE-CONTROLLER",
                    "project_id": "PROJ-STAGE5-WORKER-FIRST",
                    "worker_result_state": "READY",
                    "worker_mode": "PLAN_ONLY_AUTHORIZED_READBACK_SUMMARY",
                    "stage5_calibration_sample_count": 1,
                    "stage5_calibration_truth_label_required_count": 1,
                    "stage5_abcd_calibration_counts": {
                        "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1,
                    },
                    "stage5_calibration_review_bucket_counts": {
                        "PROJECT_MANAGER_CHANGED_OUT_REVIEW": 1,
                    },
                    "stage5_calibration_evidence_strength_counts": {
                        "OFFICIAL_READBACK_PRESENT_REVIEW_REQUIRED": 1,
                    },
                    "stage5_calibration_review_family_counts": {
                        "manual_gdcic_project_manager_change_readback_review": 1,
                    },
                    "stage5_calibration_suggested_action_counts": {
                        "manual_review_gdcic_project_manager_change_readback_before_stage5_rule_change": 1,
                    },
                    "customer_visible_allowed": False,
                    "external_customer_action_enabled": False,
                    "live_execution_enabled": False,
                    "real_payment_enabled": False,
                    "real_delivery_enabled": False,
                    "automatic_refund_enabled": False,
                }
            )
            repository.save_controller_result(
                {
                    "runtime_controller_mode": "STATE_MACHINE",
                    "customer_visible_allowed": False,
                    "run_state": {
                        "run_id": "RUN-STAGE5-WORKER-FIRST",
                        "project_id": "PROJ-STAGE5-WORKER-FIRST",
                        "entrypoint_id": "stage6_review_cycle_runner",
                        "current_stage_id": "stage6_fact_review",
                        "run_state": "REVIEW_REQUIRED",
                        "next_action": {"action_type": "REVIEW"},
                        "stage6_cycle_summary": {
                            "stage5_calibration_sample_count": 1,
                            "stage5_calibration_truth_label_required_count": 1,
                            "stage5_abcd_calibration_counts": {"B_PUBLIC_READBACK_REVIEW_REQUIRED": 1},
                            "stage5_calibration_review_bucket_counts": {
                                "POTENTIAL_FALSE_POSITIVE_REVIEW": 1,
                            },
                        },
                        "safety": {
                            "external_customer_action_enabled": False,
                            "real_payment_enabled": False,
                            "real_delivery_enabled": False,
                            "automatic_refund_enabled": False,
                        },
                    },
                    "audit_ledger": {"events": []},
                    "dispatch_queue": {"records": [], "summary": {"dispatch_record_count": 0}},
                }
            )

            projection = repository.latest_operator_projection()
            calibration = projection["stage5_calibration_summary"]
            self.assertEqual(calibration["stage5_calibration_sample_count"], 2)
            self.assertEqual(calibration["merged_source_count"], 2)
            self.assertEqual(
                calibration["stage5_calibration_review_bucket_counts"],
                {
                    "POTENTIAL_FALSE_POSITIVE_REVIEW": 1,
                    "PROJECT_MANAGER_CHANGED_OUT_REVIEW": 1,
                },
            )
            self.assertEqual(projection["trace_refs"]["stage5_calibration_sample_count"], "2")
            self.assertIn(
                "PROJECT_MANAGER_CHANGED_OUT_REVIEW",
                projection["trace_refs"]["stage5_calibration_review_bucket_counts_json"],
            )

    def test_stage_state_machine_reads_contract_graph(self) -> None:
        spec = importlib.util.find_spec("runtime.stage_state_machine")
        self.assertIsNotNone(spec, "runtime.stage_state_machine module must exist")

        from runtime.stage_state_machine import StageStateMachine

        machine = StageStateMachine.from_contract_path(ROOT / "control" / "runtime_architecture_contract.yaml")

        self.assertEqual(machine.next_stage_id("stage1_tasking"), "stage2_ingestion")
        self.assertEqual(machine.next_stage_id("stage6_fact_review"), "stage7_sales")
        self.assertEqual(machine.next_stage_id("stage9_delivery"), "DONE")
        self.assertEqual(
            machine.stage_order_until("stage6_fact_review"),
            [
                "stage1_tasking",
                "stage2_ingestion",
                "stage3_parsing",
                "stage4_verification",
                "stage5_rules_evidence",
                "stage6_fact_review",
            ],
        )

    def test_work_queue_dispatcher_turns_entrypoint_next_action_into_internal_task(self) -> None:
        spec = importlib.util.find_spec("runtime.dispatcher")
        self.assertIsNotNone(spec, "runtime.dispatcher module must exist")

        from runtime.dispatcher import WorkQueueDispatcher

        dispatcher = WorkQueueDispatcher(created_at="2026-05-24T00:00:00+08:00")
        task = dispatcher.enqueue_next_action(
            run_id="RUN-PROJ-RUNTIME-1-stage1-6-preview",
            project_id="PROJ-RUNTIME-1",
            current_stage_id="stage6_fact_review",
            next_action={
                "action_type": "ENTRYPOINT",
                "entrypoint_id": "stage4_release_evidence_bridge_builder",
                "reason": "stage4_release_evidence_missing",
            },
            input_refs=["memory://stage6-preview/PROJ-RUNTIME-1"],
        )

        self.assertEqual(task["dispatch_task_id"], "DISPATCH-RUN-PROJ-RUNTIME-1-stage1-6-preview-stage4-release-evidence-bridge-builder")
        self.assertEqual(task["entrypoint_id"], "stage4_release_evidence_bridge_builder")
        self.assertEqual(task["dispatch_state"], "READY_FOR_INTERNAL_DISPATCH")
        self.assertEqual(task["execution_mode"], "INTERNAL_ONLY")
        self.assertFalse(task["external_customer_action_enabled"])
        self.assertEqual(task["input_refs"], ["memory://stage6-preview/PROJ-RUNTIME-1"])
        self.assertEqual(dispatcher.pending_tasks(), [task])

    def test_stage1_3_repair_worker_builds_internal_plan_from_controller_dispatch(self) -> None:
        spec = importlib.util.find_spec("runtime.stage13_repair_worker")
        self.assertIsNotNone(spec, "runtime.stage13_repair_worker module must exist")

        from runtime.stage13_repair_worker import build_stage1_3_repair_worker_plan

        result = build_stage1_3_repair_worker_plan(
            {
                "controller_dispatch_queue": {
                    "records": [
                        {
                            "dispatch_task_id": "DISPATCH-RUN-1-stage3-attachment-ocr-repair",
                            "run_id": "RUN-1",
                            "project_id": "PROJ-1",
                            "current_stage_id": "stage3_parsing",
                            "review_family": "stage1_3_attachment_ocr_repair",
                            "review_state": "WAITING_FOR_STAGE3_ATTACHMENT_OCR_REPAIR",
                            "source_metric": "stage3_attachment_ocr_pending_count",
                            "metric_count": 2,
                            "operator_next_action": "prepare OCR repair",
                            "input_refs": ["memory://stage1-6/readiness"],
                            "external_customer_action_enabled": False,
                        },
                        {
                            "dispatch_task_id": "DISPATCH-RUN-1-stage4-field-query",
                            "entrypoint_id": "guangdong_local_field_query_probe",
                            "external_customer_action_enabled": False,
                        },
                    ]
                }
            },
            created_at="2026-05-24T00:00:00+08:00",
        )

        self.assertEqual(result["worker_id"], "stage1_3_repair_worker")
        self.assertEqual(result["worker_mode"], "INTERNAL_REPAIR_PLAN_ONLY")
        self.assertEqual(result["repair_worker_state"], "REPAIR_PLAN_READY")
        self.assertEqual(result["repair_task_count"], 1)
        self.assertEqual(result["repair_metric_counts"], {"stage3_attachment_ocr_pending_count": 2})
        task = result["repair_tasks"][0]
        self.assertEqual(task["worker_family"], "stage3_attachment_ocr_repair_worker")
        self.assertEqual(task["execution_state"], "PLAN_READY_INTERNAL_REPAIR_NOT_EXECUTED")
        self.assertEqual(task["input_refs"], ["memory://stage1-6/readiness"])
        self.assertFalse(task["external_customer_action_enabled"])
        self.assertFalse(result["live_execution_enabled"])
        self.assertTrue(result["query_miss_is_not_clearance"])

    def test_entrypoint_transport_invokes_stage1_3_repair_worker(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import run_runtime_entrypoint
        from storage.repositories.runtime_state_repo import (
            RUNTIME_WORKER_RESULT_OBJECT_TYPE,
            RuntimeStateRepository,
        )

        result = run_runtime_entrypoint(
            entrypoint_id="stage1_3_repair_worker",
            payload={
                "controller_dispatch_queue": {
                    "records": [
                        {
                            "dispatch_task_id": "DISPATCH-RUN-1-stage2-snapshot-repair",
                            "review_family": "stage1_3_attachment_snapshot_repair",
                            "source_metric": "stage2_attachment_snapshot_missing_count",
                            "metric_count": 1,
                            "external_customer_action_enabled": False,
                        }
                    ]
                }
            },
            created_at="2026-05-24T00:00:00+08:00",
        )

        self.assertEqual(result["entrypoint_id"], "stage1_3_repair_worker")
        self.assertEqual(result["worker_result"]["repair_task_count"], 1)
        self.assertEqual(result["worker_persistence"]["worker_result_object_type"], RUNTIME_WORKER_RESULT_OBJECT_TYPE)
        self.assertEqual(
            result["worker_result"]["repair_worker_family_counts"],
            {"stage2_attachment_snapshot_repair_worker": 1},
        )
        self.assertFalse(result["safety"]["external_customer_action_enabled"])
        self.assertFalse(result["worker_result"]["external_customer_action_enabled"])
        persisted = RuntimeStateRepository().latest_worker_result(worker_id="stage1_3_repair_worker")
        self.assertEqual(persisted["worker_id"], "stage1_3_repair_worker")
        self.assertEqual(persisted["repair_task_count"], 1)
        self.assertEqual(persisted["trace_refs"]["repair_task_count"], "1")
        self.assertIn(
            "stage2_attachment_snapshot_missing_count",
            persisted["trace_refs"]["repair_metric_counts_json"],
        )
        self.assertFalse(persisted["governed_state"]["external_customer_action_enabled"])

    def test_work_queue_dispatcher_blocks_unregistered_entrypoint(self) -> None:
        spec = importlib.util.find_spec("runtime.dispatcher")
        self.assertIsNotNone(spec, "runtime.dispatcher module must exist")

        from runtime.dispatcher import WorkQueueDispatcher
        from runtime.entrypoint_registry import RuntimeEntrypointRegistry

        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "automation_entrypoint_registry.yaml"
            registry_path.write_text(
                yaml.safe_dump(
                    {
                        "formal_entrypoints": [
                            {
                                "entrypoint_id": "runtime_controller_entrypoint_transport",
                                "kind": "script",
                                "script": "scripts/run-runtime-entrypoint.ps1",
                                "entrypoint_role": "orchestrator",
                                "status": "SUPPORTING_TOOL",
                                "automation_layer": "runtime_controller_entrypoint_transport",
                                "module_or_command": "runtime.entrypoint_cli",
                                "state_inputs": ["entrypoint_id", "payload"],
                                "state_outputs": ["run state"],
                                "manual_gate_required": False,
                                "external_customer_action_enabled": False,
                                "replaces_human_memory": True,
                            }
                        ]
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            registry = RuntimeEntrypointRegistry.from_path(registry_path)
            dispatcher = WorkQueueDispatcher(
                created_at="2026-05-24T00:00:00+08:00",
                entrypoint_registry=registry,
            )

            task = dispatcher.enqueue_next_action(
                run_id="RUN-PROJ-RUNTIME-1-stage1-6-preview",
                project_id="PROJ-RUNTIME-1",
                current_stage_id="stage6_fact_review",
                next_action={
                    "action_type": "ENTRYPOINT",
                    "entrypoint_id": "unregistered_followup_entrypoint",
                    "reason": "test_unregistered",
                },
            )

        self.assertEqual(task["dispatch_state"], "BLOCKED_UNREGISTERED_ENTRYPOINT")
        self.assertIn("unregistered_runtime_entrypoint_id", task["blocking_reasons"][0])
        self.assertFalse(task["external_customer_action_enabled"])

    def test_entrypoint_transport_invokes_runtime_controller_by_entrypoint_id(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import run_runtime_entrypoint

        result = run_runtime_entrypoint(
            entrypoint_id="stage1_6_internal_http_orchestration_preview",
            payload={
                "project_id": "PROJ-RUNTIME-CLI",
                "source_mode": "SANITIZED_OFFLINE_INTERNAL",
                "stage6_preview_result": {
                    "stage_id": "stage6_fact_review",
                    "stage_state": "REVIEW_REQUIRED",
                    "output_artifact_refs": ["memory://stage6-preview/PROJ-RUNTIME-CLI"],
                    "blocking_reasons": ["release_evidence_chain_missing"],
                    "next_action": "run_stage4_release_evidence_bridge_builder",
                },
            },
            created_at="2026-05-24T00:00:00+08:00",
        )

        self.assertEqual(result["entrypoint_transport_mode"], "RUNTIME_CONTROLLER_ENTRYPOINT")
        self.assertEqual(result["entrypoint_id"], "stage1_6_internal_http_orchestration_preview")
        self.assertEqual(result["controller_result"]["run_state"]["project_id"], "PROJ-RUNTIME-CLI")
        self.assertEqual(
            result["controller_result"]["dispatch_queue"]["records"][0]["entrypoint_id"],
            "stage4_release_evidence_bridge_builder",
        )
        self.assertFalse(result["safety"]["external_customer_action_enabled"])
        self.assertFalse(result["safety"]["automatic_refund_enabled"])

    def test_entrypoint_transport_can_route_stage6_cycle_through_runtime_controller(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import run_runtime_entrypoint

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            next_subqueue = root / "runtime-blocker-next-subqueues.json"
            next_subqueue.write_text(
                json.dumps(
                    {
                        "table_kind": "runtime_blocker_next_subqueue_table_v1",
                        "summary": {"next_subqueue_record_count": 1},
                        "records": [
                            {
                                "next_subqueue_record_id": "RUNTIME-SUBQUEUE-MANUAL",
                                "subqueue_route": "manual_hold",
                                "subqueue_state": "MANUAL_HOLD_RECORDED",
                                "project_id": "PROJ-RUNTIME-CLI-CYCLE",
                                "project_name": "Runtime CLI cycle project",
                                "blocker_ledger_id": "BLK-RUNTIME-CLI",
                                "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                                "blocker_reason": "terminal_closeout_or_backfill_marker_present",
                                "runtime_layer": "controller decision",
                                "task_id": "TASK-RUNTIME-CLI",
                                "required_input": ["operator_override_reason_or_new_machine_readable_input"],
                                "operator_next_action": "operator_reviews_terminal_projection_before_reopen",
                                "input_artifact_refs": [],
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = run_runtime_entrypoint(
                entrypoint_id="stage6_review_cycle_runner",
                payload={
                    "project_id": "PROJ-RUNTIME-CLI-CYCLE",
                    "batch_closeout_root": str(root / "missing-closeout"),
                    "runtime_blocker_next_subqueue_json": str(next_subqueue),
                    "output_root": str(root / "out"),
                },
                created_at="2026-05-24T00:00:00+08:00",
            )

        self.assertEqual(result["entrypoint_transport_mode"], "RUNTIME_CONTROLLER_ENTRYPOINT")
        self.assertEqual(result["entrypoint_id"], "stage6_review_cycle_runner")
        controller_result = result["controller_result"]
        self.assertEqual(controller_result["runtime_controller_mode"], "STAGE1_6_RUNTIME_CYCLE")
        self.assertEqual(
            controller_result["run_state"]["runtime_blocker_controller_summary"]["controller_queue_record_count"],
            1,
        )
        self.assertFalse(result["safety"]["external_customer_action_enabled"])

    def test_entrypoint_cli_accepts_controller_consumed_runtime_artifact_refs(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload_path = root / "payload.json"
            readiness_json = root / "stage1-6-readiness-table.json"
            gap_json = root / "stage1-6-gap-summary-table.json"
            market_scan_json = root / "stage1-market-scan.json"
            source_blueprint_json = root / "stage1-source-blueprint.json"
            stage2_capture_json = root / "stage2-capture.json"
            stage3_parse_json = root / "stage3-parse.json"
            stage123_output_root = root / "stage123-out"
            calibration_json = root / "stage5-calibration-sample-table.json"
            stage45_replay_json = root / "stage45-replay-samples.json"
            stage45_replay_output_root = root / "stage45-replay-out"
            output_path = root / "runtime-cycle-result.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                        "batch_closeout_root": str(root / "missing-closeout"),
                        "output_root": str(root / "out"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            readiness_json.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                                "stage1_6_readiness_state": "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED",
                                "bottleneck_stage": "Stage4",
                                "customer_visible_allowed": False,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            gap_json.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "gap_family": "stage1_6_readiness_state",
                                "gap_state": "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            market_scan_json.write_text(
                json.dumps(
                    {
                        "summary": {
                            "selected_candidate_count": 1,
                            "opportunity_candidates": [
                                {
                                    "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                                    "project_name": "Runtime CLI artifacts project",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source_blueprint_json.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "source_blueprint_plan_state": "READY",
                            "stage2_capture_plan": {
                                "capture_plan_id": "CAPTURE-RUNTIME-CLI-ARTIFACTS",
                                "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                                "project_name": "Runtime CLI artifacts project",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stage2_capture_json.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "stage2_capture_records": [
                                {
                                    "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                                    "stage2_capture_state": "CAPTURED",
                                    "attachment_snapshot_count": 1,
                                    "attachment_capture_attempted_count": 1,
                                    "customer_visible_allowed": False,
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stage3_parse_json.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "application_records": [
                                {
                                    "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                                    "stage3_parse_state": "PARSED",
                                    "attachment_ocr_required_count": 1,
                                    "attachment_ocr_extracted_count": 1,
                                    "responsible_role_gap_count": 0,
                                    "customer_visible_allowed": False,
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            calibration_json.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "stage5_calibration_sample_id": "STAGE5-CAL-CLI-1",
                                "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS",
                                "stage5_calibration_review_bucket": "POTENTIAL_FALSE_POSITIVE_REVIEW",
                                "calibration_truth_label_required": True,
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stage45_replay_json.write_text(
                json.dumps(
                    {
                        "stage4_probe_results": [
                            {
                                "project_id": "PROJ-RUNTIME-CLI-ARTIFACTS-NOT-FOUND",
                                "probe_status": "NOT_FOUND",
                                "source_url": "https://example.test/runtime-cli/not-found",
                            }
                        ],
                        "stage5_rule_codes": ["UNSUPPORTED-CLI-001"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--entrypoint-id",
                    "stage6_review_cycle_runner",
                    "--payload-json",
                    str(payload_path),
                    "--stage1-6-readiness-json",
                    str(readiness_json),
                    "--stage1-6-gap-summary-json",
                    str(gap_json),
                    "--stage1-market-scan-json",
                    str(market_scan_json),
                    "--stage1-source-blueprint-json",
                    str(source_blueprint_json),
                    "--stage2-capture-json",
                    str(stage2_capture_json),
                    "--stage3-parse-json",
                    str(stage3_parse_json),
                    "--stage123-front-chain-output-root",
                    str(stage123_output_root),
                    "--stage5-calibration-sample-json",
                    str(calibration_json),
                    "--stage45-replay-samples-json",
                    str(stage45_replay_json),
                    "--stage45-replay-output-root",
                    str(stage45_replay_output_root),
                    "--output-json",
                    str(output_path),
                    "--created-at",
                    "2026-05-24T00:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            run_state = written["controller_result"]["run_state"]
            self.assertEqual(run_state["stage1_6_readiness_summary"]["stage1_6_readiness_record_count"], 1)
            self.assertEqual(run_state["stage123_front_chain_summary"]["stage123_front_chain_state"], "READY")
            self.assertEqual(run_state["stage123_front_chain_summary"]["stage1_selected_candidate_count"], 1)
            self.assertEqual(run_state["stage123_front_chain_summary"]["stage2_capture_record_count"], 1)
            self.assertEqual(run_state["stage123_front_chain_summary"]["stage3_parse_record_count"], 1)
            self.assertEqual(run_state["stage6_cycle_summary"]["stage5_calibration_sample_count"], 1)
            self.assertEqual(run_state["stage45_replay_summary"]["stage4_probe_replay_count"], 1)
            self.assertEqual(run_state["stage45_replay_summary"]["stage4_blocker_ledger_count"], 1)
            self.assertEqual(run_state["stage45_replay_summary"]["stage5_missing_readback_count"], 1)
            self.assertIn(str(readiness_json), run_state["input_refs"])
            self.assertIn(str(gap_json), run_state["input_refs"])
            self.assertIn(str(market_scan_json), run_state["input_refs"])
            self.assertIn(str(source_blueprint_json), run_state["input_refs"])
            self.assertIn(str(stage2_capture_json), run_state["input_refs"])
            self.assertIn(str(stage3_parse_json), run_state["input_refs"])
            self.assertIn(str(calibration_json), run_state["input_refs"])
            self.assertIn(str(stage45_replay_json), run_state["input_refs"])
            self.assertTrue((stage123_output_root / "stage123-runtime-front-chain-v1.json").exists())
            self.assertTrue((stage45_replay_output_root / "stage45-runtime-sample-replay-v1.json").exists())
            self.assertFalse(written["safety"]["external_customer_action_enabled"])
            self.assertNotIn("无风险", str(written))

    def test_entrypoint_cli_accepts_gdcic_browser_readback_artifact_ref(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import main
        from tests.test_stage6_review_cycle_runner import (
            _write_gdcic_project_manager_change_readback,
            _write_gdcic_release_plan_for_stage6_cycle,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload_path = root / "payload.json"
            output_path = root / "runtime-cycle-result.json"
            release_plan_json = _write_gdcic_release_plan_for_stage6_cycle(root / "release-plan")
            gdcic_readback_json = _write_gdcic_project_manager_change_readback(root / "gdcic-readback")
            payload_path.write_text(
                json.dumps(
                    {
                        "project_id": "PROJ-RUNTIME-GDCIC-READBACK",
                        "batch_closeout_root": str(root / "missing-closeout"),
                        "output_root": str(root / "out"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--entrypoint-id",
                    "stage6_review_cycle_runner",
                    "--payload-json",
                    str(payload_path),
                    "--release-evidence-adapter-plan-json",
                    str(release_plan_json),
                    "--gdcic-browser-readback-json",
                    str(gdcic_readback_json),
                    "--output-json",
                    str(output_path),
                    "--created-at",
                    "2026-05-24T00:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            run_state = written["controller_result"]["run_state"]
            self.assertIn(str(release_plan_json), run_state["input_refs"])
            self.assertIn(str(gdcic_readback_json), run_state["input_refs"])
            self.assertIn("guangdong-local-field-query-probe-v1.json", " ".join(run_state["output_artifact_refs"]))
            self.assertEqual(
                run_state["stage4_release_field_query_summary"]["release_field_query_state_counts"],
                {"RELEASE_FIELD_QUERY_REVIEW_READY": 1},
            )
            self.assertEqual(
                run_state["stage4_release_field_query_summary"]["release_field_query_operator_next_action_counts"],
                {},
            )
            gdcic_summary = run_state["stage4_release_chain_bootstrap_summary"][
                "stage4_gdcic_authorized_readback_summary"
            ]
            self.assertEqual(gdcic_summary["source_gdcic_browser_readback_json"], str(gdcic_readback_json))
            self.assertEqual(gdcic_summary["gdcic_browser_readback_ready_count"], 1)
            self.assertEqual(gdcic_summary["project_manager_change_ready_count"], 1)
            self.assertEqual(
                gdcic_summary["project_manager_change_interpretation_counts"],
                {"ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1},
            )
            self.assertTrue(gdcic_summary["query_miss_is_not_clearance"])
            self.assertFalse(gdcic_summary["customer_visible_allowed"])
            projection = written["controller_result"]["runtime_persistence"]
            self.assertEqual(projection["runtime_persistence_state"], "PERSISTED")
            latest_projection = written["controller_result"]["runtime_persistence"]
            text = json.dumps(written, ensure_ascii=False)
            self.assertIn("C_REVERSE_EXPLANATION_OFFICIAL_READBACK", text)
            self.assertIn("stage4_gdcic_authorized_readback_summary", text)
            self.assertNotIn("无风险", text)
            self.assertNotIn("无冲突", text)
            self.assertNotIn("确认本人", text)

    def test_entrypoint_cli_accepts_stage1_6_pressure_report_as_batch_ledger_input(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload_path = root / "payload.json"
            pressure_report_json = root / "stage1-6-real-public-pressure-report-v1.json"
            output_path = root / "runtime-cycle-result.json"
            pressure_report_json.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "summary": {
                                "coverage_state": "PARTIAL_SOURCE_COVERAGE",
                                "candidate_count": 2,
                                "closed_loop_results_count": 2,
                                "stage1_6_readiness_record_count": 2,
                                "stage1_6_gap_summary_record_count": 1,
                                "stage5_calibration_sample_count": 2,
                                "stage1_3_stability_summary": {
                                    "stage2_attachment_snapshot_missing_count": 1,
                                    "attachment_snapshot_readback_missing_count": 1,
                                    "stage3_attachment_ocr_pending_count": 1,
                                    "stage3_responsible_role_gap_count": 1,
                                    "stage3_parse_blocker_count": 0,
                                },
                            },
                            "stage1_6_readiness_records": [
                                {
                                    "project_id": "PROJ-PRESSURE-1",
                                    "stage1_6_readiness_state": "STAGE1_6_INTERNAL_READY",
                                    "bottleneck_stage": "READY",
                                    "recommended_next_action": "advance_to_stage7_9_internal_review",
                                },
                                {
                                    "project_id": "PROJ-PRESSURE-2",
                                    "stage1_6_readiness_state": "STAGE4_PUBLIC_SOURCE_REVIEW_REQUIRED",
                                    "bottleneck_stage": "Stage4",
                                    "recommended_next_action": "run_stage4_release_evidence_bridge_builder",
                                },
                            ],
                            "stage1_6_gap_summary_records": [
                                {
                                    "gap_family": "stage4",
                                    "gap_state": "release_evidence_missing",
                                    "gap_value": "missing_stage4_5_source_type:contract_public_info",
                                    "next_action": "run_stage4_release_evidence_bridge_builder",
                                }
                            ],
                            "stage5_calibration_records": [
                                {"stage5_calibration_sample_id": "PRESSURE-CAL-1"},
                                {"stage5_calibration_sample_id": "PRESSURE-CAL-2"},
                            ],
                        },
                        "summary": {
                            "coverage_state": "PARTIAL_SOURCE_COVERAGE",
                            "candidate_count": 2,
                            "closed_loop_results_count": 2,
                            "stage5_calibration_sample_count": 2,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            payload_path.write_text(
                json.dumps(
                    {
                        "project_id": "PROJ-RUNTIME-PRESSURE",
                        "batch_closeout_root": str(root / "missing-closeout"),
                        "output_root": str(root / "out"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--entrypoint-id",
                    "stage6_review_cycle_runner",
                    "--payload-json",
                    str(payload_path),
                    "--stage1-6-real-public-pressure-report-json",
                    str(pressure_report_json),
                    "--output-json",
                    str(output_path),
                    "--created-at",
                    "2026-05-24T00:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            run_state = written["controller_result"]["run_state"]
            readiness = run_state["stage1_6_readiness_summary"]
            self.assertEqual(readiness["stage1_6_readiness_record_count"], 2)
            self.assertEqual(readiness["stage1_6_gap_summary_record_count"], 1)
            self.assertEqual(readiness["stage1_6_pressure_coverage_state"], "PARTIAL_SOURCE_COVERAGE")
            self.assertEqual(readiness["stage1_6_pressure_candidate_count"], 2)
            self.assertEqual(readiness["stage1_6_pressure_closed_loop_results_count"], 2)
            self.assertEqual(readiness["stage1_6_pressure_stage5_calibration_sample_count"], 2)
            self.assertEqual(readiness["stage1_6_next_action_counts"]["run_stage4_release_evidence_bridge_builder"], 1)
            self.assertEqual(readiness["stage1_6_gap_next_action_counts"]["run_stage4_release_evidence_bridge_builder"], 1)
            self.assertIn(str(pressure_report_json), run_state["input_refs"])
            text = json.dumps(written, ensure_ascii=False)
            self.assertIn("PARTIAL_SOURCE_COVERAGE", text)
            self.assertNotIn("无风险", text)

    def test_entrypoint_cli_accepts_stage4_release_chain_bootstrap_artifact_refs(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import main
        from tests.test_stage6_review_cycle_runner import _write_standalone_stage16_p13b_continuation

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload_path = root / "payload.json"
            output_path = root / "runtime-cycle-result.json"
            stage16_json = _write_standalone_stage16_p13b_continuation(root / "stage16")
            payload_path.write_text(
                json.dumps(
                    {
                        "project_id": "PROJ-RUNTIME-CLI-P13B",
                        "output_root": str(root / "out"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--entrypoint-id",
                    "stage6_review_cycle_runner",
                    "--payload-json",
                    str(payload_path),
                    "--batch-closeout-root",
                    str(root / "missing-closeout"),
                    "--stage16-p13b-continuation-json",
                    str(stage16_json),
                    "--output-json",
                    str(output_path),
                    "--created-at",
                    "2026-05-24T00:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            run_state = written["controller_result"]["run_state"]
            summary = run_state["stage4_release_chain_bootstrap_summary"]
            self.assertEqual(summary["stage4_release_chain_bootstrap_source_kind"], "STAGE16_P13B_CONTINUATION_JSON")
            self.assertEqual(summary["stage4_release_chain_project_count"], 1)
            self.assertIn(str(stage16_json), run_state["input_refs"])
            self.assertFalse(written["safety"]["external_customer_action_enabled"])
            self.assertNotIn("无风险", str(written))

    def test_entrypoint_cli_accepts_stage4_backfill_followup_queue_as_controller_input(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload_path = root / "payload.json"
            output_path = root / "runtime-cycle-result.json"
            followup_queue_json = root / "followup" / "stage4-backfill-followup-queue-v1.json"
            followup_queue_json.parent.mkdir(parents=True)
            followup_queue_json.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "followup_record_id": "STAGE4-FOLLOWUP-CLI-1",
                                "project_id": "PROJ-RUNTIME-STAGE4-FOLLOWUP",
                                "project_name": "Runtime Stage4 followup",
                                "followup_route": "local_authority_not_found_specific_endpoint_or_manual_source",
                                "followup_queue_state": "FOLLOWUP_SOURCE_PLAN_REQUIRED",
                                "gap_detail": "LOCAL_AUTHORITY_NOT_FOUND_DEEPENING_REQUIRED",
                                "required_input": ["specific_search_endpoint_or_manual_source_path"],
                                "recommended_next_action": "deepen_not_found_with_specific_endpoint_without_clearance_claim",
                                "customer_visible_allowed": False,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                        "customer_visible_allowed": False,
                        "query_miss_is_not_clearance": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            payload_path.write_text(
                json.dumps(
                    {
                        "project_id": "PROJ-RUNTIME-STAGE4-FOLLOWUP",
                        "batch_closeout_root": str(root / "missing-closeout"),
                        "output_root": str(root / "out"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--entrypoint-id",
                    "stage6_review_cycle_runner",
                    "--payload-json",
                    str(payload_path),
                    "--stage4-backfill-followup-queue-json",
                    str(followup_queue_json),
                    "--output-json",
                    str(output_path),
                    "--created-at",
                    "2026-05-25T00:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            run_state = written["controller_result"]["run_state"]
            self.assertIn(str(followup_queue_json), run_state["input_refs"])
            self.assertEqual(
                run_state["stage6_cycle_summary"]["stage6_review_cycle_bootstrap_source_kind"],
                "STAGE4_BACKFILL_FOLLOWUP_QUEUE_JSON",
            )
            self.assertEqual(
                run_state["runtime_blocker_controller_summary"]["controller_queue_record_count"],
                1,
            )
            self.assertFalse(written["customer_visible_allowed"])
            self.assertTrue(written["query_miss_is_not_clearance"])
            self.assertNotIn("无风险", str(written))

    def test_runtime_entrypoint_registry_loads_formal_transport_and_target(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_registry")
        self.assertIsNotNone(spec, "runtime.entrypoint_registry module must exist")

        from runtime.entrypoint_registry import RuntimeEntrypointRegistry

        registry = RuntimeEntrypointRegistry.from_path(ROOT / "control" / "automation_entrypoint_registry.yaml")

        transport = registry.require_transport_entrypoint()
        self.assertEqual(transport["entrypoint_id"], "runtime_controller_entrypoint_transport")
        self.assertEqual(transport["module_or_command"], "runtime.entrypoint_cli")
        self.assertFalse(transport["external_customer_action_enabled"])

        target = registry.require_registered_entrypoint("stage1_6_internal_http_orchestration_preview")
        self.assertEqual(target["status"], "INTERNAL_PREVIEW_ONLY")
        self.assertFalse(target["external_customer_action_enabled"])
        self.assertTrue(target["replaces_human_memory"])

        repair_worker = registry.require_registered_entrypoint("stage1_3_repair_worker")
        self.assertEqual(repair_worker["status"], "FORMAL_CURRENT")
        self.assertEqual(repair_worker["module_or_command"], "runtime.stage13_repair_worker")
        self.assertFalse(repair_worker["external_customer_action_enabled"])

    def test_entrypoint_transport_rejects_target_missing_from_registry(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import run_runtime_entrypoint

        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "automation_entrypoint_registry.yaml"
            registry_path.write_text(
                yaml.safe_dump(
                    {
                        "formal_entrypoints": [
                            {
                                "entrypoint_id": "runtime_controller_entrypoint_transport",
                                "kind": "script",
                                "script": "scripts/run-runtime-entrypoint.ps1",
                                "entrypoint_role": "orchestrator",
                                "status": "SUPPORTING_TOOL",
                                "automation_layer": "runtime_controller_entrypoint_transport",
                                "module_or_command": "runtime.entrypoint_cli",
                                "state_inputs": ["entrypoint_id", "payload"],
                                "state_outputs": ["run state"],
                                "manual_gate_required": False,
                                "external_customer_action_enabled": False,
                                "replaces_human_memory": True,
                            }
                        ]
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unregistered_runtime_entrypoint_id"):
                run_runtime_entrypoint(
                    entrypoint_id="stage1_6_internal_http_orchestration_preview",
                    payload={"project_id": "PROJ-RUNTIME-UNREGISTERED"},
                    registry_path=registry_path,
                    created_at="2026-05-24T00:00:00+08:00",
                )

    def test_entrypoint_cli_writes_json_output(self) -> None:
        spec = importlib.util.find_spec("runtime.entrypoint_cli")
        self.assertIsNotNone(spec, "runtime.entrypoint_cli module must exist")

        from runtime.entrypoint_cli import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload_path = root / "payload.json"
            output_path = root / "runtime-entrypoint-result.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "project_id": "PROJ-RUNTIME-FILE",
                        "source_mode": "SANITIZED_OFFLINE_INTERNAL",
                        "stage6_preview_result": {
                            "stage_id": "stage6_fact_review",
                            "stage_state": "REVIEW_REQUIRED",
                            "output_artifact_refs": ["memory://stage6-preview/PROJ-RUNTIME-FILE"],
                            "blocking_reasons": ["stage4_release_evidence_missing"],
                            "next_action": "run_stage4_release_evidence_bridge_builder",
                        },
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--entrypoint-id",
                    "stage1_6_internal_http_orchestration_preview",
                    "--payload-json",
                    str(payload_path),
                    "--output-json",
                    str(output_path),
                    "--created-at",
                    "2026-05-24T00:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["entrypoint_id"], "stage1_6_internal_http_orchestration_preview")
            self.assertEqual(written["controller_result"]["run_state"]["project_id"], "PROJ-RUNTIME-FILE")

    def test_runtime_entrypoint_script_is_transport_only(self) -> None:
        script = ROOT / "scripts" / "run-runtime-entrypoint.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("-m\", \"runtime.entrypoint_cli", text)
        self.assertIn("--entrypoint-id", text)
        self.assertIn("--release-field-query-json", text)
        self.assertIn("--release-evidence-adapter-plan-json", text)
        self.assertIn("--gdcic-browser-readback-json", text)
        self.assertIn("--original-backtrace-continuation-json", text)
        self.assertIn("--stage16-p13b-continuation-json", text)
        self.assertIn("--stage1-6-readiness-json", text)
        self.assertIn("--stage1-market-scan-json", text)
        self.assertIn("--stage2-capture-json", text)
        self.assertIn("--stage3-parse-json", text)
        self.assertIn("--stage5-calibration-sample-json", text)
        self.assertIn("--stage4-backfill-followup-queue-json", text)
        self.assertIn("--stage4-backfill-followup-queue-root", text)
        self.assertIn("--stage45-replay-samples-json", text)
        self.assertNotIn("storage.stage6_review_loop_runner", text)
        self.assertNotIn("storage.evidence_orchestration_state_machine", text)


if __name__ == "__main__":
    unittest.main()
