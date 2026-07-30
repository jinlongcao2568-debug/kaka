from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from storage.gdcic_browser_authorized_readback import (  # noqa: E402
    build_gdcic_browser_authorized_readback,
)
from storage.guangdong_local_field_query_probe import (  # noqa: E402
    build_guangdong_local_field_query_probe,
)
from storage.repositories.runtime_state_repo import RuntimeStateRepository  # noqa: E402
from storage_test_support import IsolatedStorageTestMixin  # noqa: E402


class GDCICBrowserAuthorizedReadbackTests(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="gdcic-browser-authorized-readback.json")

    def tearDown(self) -> None:
        self.tearDown_storage_test_env()

    def test_plan_only_builds_gdcic_contract_and_project_manager_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            out_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=out_root,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(summary["authorized_session_input_state"], "NO_AUTHORIZED_SESSION_INPUT")
            self.assertFalse(summary["authorized_session_input_ready"])
            self.assertEqual(summary["authorized_session_preflight_state"], "NO_AUTHORIZED_SESSION_INPUT")
            self.assertEqual(summary["authorized_session_required_input"], ["authorized_browser_storage_state_or_user_data_dir"])
            self.assertEqual(
                summary["authorized_session_preflight"]["operator_next_action"],
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            )
            self.assertIn(
                ".auth/gdcic-storage-state.json",
                summary["authorized_session_preflight"]["default_discovery_paths"],
            )
            self.assertFalse(summary["http_dynamic_stealthy_can_replace_login_state"])
            self.assertEqual(summary["target_real_readback_success_count"], 0)
            self.assertEqual(summary["target_project_manager_change_real_readback_success_count"], 0)
            self.assertTrue(summary["real_readback_success_not_faked"])
            self.assertEqual(summary["real_readback_success_proof_state"], "NO_REAL_AUTHORIZED_READBACK_SUCCESS")
            self.assertEqual(
                summary["authorization_blocker_operator_next_action"],
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            )
            self.assertEqual(
                summary["operator_next_action_counts"],
                {
                    "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun": 1,
                    "run_alternative_public_source_release_evidence_readback_chain": 2,
                },
            )
            self.assertTrue(summary["authorization_blocker_is_not_terminal_if_alternative_public_sources_exist"])
            self.assertEqual(
                summary["authorization_blocker_alternative_operator_next_action"],
                "run_alternative_public_source_release_evidence_readback_chain",
            )
            self.assertEqual(summary["alternative_public_source_route_count"], 2)
            self.assertEqual(
                {record["release_evidence_target_type"] for record in summary["alternative_public_source_route_records"]},
                {"contract_performance", "project_manager_change_notice"},
            )
            self.assertIn(
                "data_ggzy_bid_show_notice_content_and_original_url",
                summary["alternative_public_source_route_records"][0]["recommended_source_chain"],
            )
            self.assertEqual(summary["gdcic_browser_readback_task_count"], 2)
            self.assertEqual(summary["gdcic_browser_readback_record_count"], 0)
            self.assertEqual(summary["gdcic_authorized_session_overall_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertEqual(summary["project_manager_change_readback_task_count"], 1)
            self.assertEqual(summary["project_manager_change_readback_record_count"], 0)
            self.assertEqual(summary["project_manager_change_ready_count"], 0)
            self.assertEqual(result["manifest"]["authorized_session_input_state"], "NO_AUTHORIZED_SESSION_INPUT")
            self.assertEqual(result["manifest"]["authorized_session_preflight"]["preflight_state"], "NO_AUTHORIZED_SESSION_INPUT")
            self.assertEqual(
                result["manifest"]["source_release_evidence_adapter_plan_manifest_id"],
                "RELEASE-PLAN-FIXTURE-1",
            )
            self.assertTrue(result["manifest"]["source_release_evidence_adapter_plan_manifest_sha256"])
            tasks = result["manifest"]["browser_readback_task_records"]
            self.assertEqual(
                {task["release_evidence_target_type"] for task in tasks},
                {"contract_performance", "project_manager_change_notice"},
            )
            self.assertTrue((out_root / "gdcic-browser-authorized-readback-v1.json").exists())

    def test_authorized_session_input_state_reports_supplied_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            out_root = root / "gdcic-readback"
            storage_state = root / "gdcic-storage-state.json"
            user_data_dir = root / "gdcic-user-data"
            missing_storage_state = root / "missing-storage-state.json"
            _write_release_evidence_adapter_plan(plan_root)
            storage_state.write_text("{}", encoding="utf-8")
            user_data_dir.mkdir()

            storage_result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=out_root / "storage",
                storage_state_json=storage_state,
                created_at="2026-05-20T00:00:00+08:00",
            )
            self.assertEqual(storage_result["summary"]["authorized_session_input_state"], "STORAGE_STATE_JSON_SUPPLIED")
            self.assertTrue(storage_result["summary"]["authorized_session_input_ready"])
            self.assertEqual(storage_result["summary"]["authorized_session_preflight_state"], "AUTHORIZED_SESSION_INPUT_READY")
            self.assertEqual(storage_result["summary"]["authorized_session_required_input"], [])
            self.assertTrue(storage_result["summary"]["authorized_session_preflight"]["storage_state_json_exists"])
            self.assertEqual(storage_result["manifest"]["storage_state_json_used"], str(storage_state))

            user_data_result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=out_root / "user-data",
                user_data_dir=user_data_dir,
                created_at="2026-05-20T00:00:00+08:00",
            )
            self.assertEqual(user_data_result["summary"]["authorized_session_input_state"], "USER_DATA_DIR_SUPPLIED")
            self.assertTrue(user_data_result["summary"]["authorized_session_input_ready"])
            self.assertEqual(user_data_result["summary"]["authorized_session_preflight_state"], "AUTHORIZED_SESSION_INPUT_READY")
            self.assertTrue(user_data_result["summary"]["authorized_session_preflight"]["user_data_dir_exists"])
            self.assertEqual(user_data_result["manifest"]["user_data_dir_used"], str(user_data_dir))

            missing_result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=out_root / "missing",
                storage_state_json=missing_storage_state,
                created_at="2026-05-20T00:00:00+08:00",
            )
            self.assertEqual(
                missing_result["summary"]["authorized_session_input_state"],
                "STORAGE_STATE_JSON_SUPPLIED_BUT_MISSING",
            )
            self.assertFalse(missing_result["summary"]["authorized_session_input_ready"])
            self.assertEqual(
                missing_result["summary"]["authorized_session_preflight_state"],
                "AUTHORIZED_SESSION_INPUT_SUPPLIED_BUT_NOT_READABLE",
            )
            self.assertEqual(
                missing_result["summary"]["authorized_session_preflight"]["operator_next_action"],
                "fix_gdcic_authorized_session_input_path_then_rerun",
            )

    def test_live_request_without_authorized_session_skips_protected_source_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            out_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=out_root,
                enable_live_browser_execution=True,
                created_at="2026-07-19T12:00:00+08:00",
            )

            summary = result["summary"]
            records = result["manifest"]["browser_readback_records"]
            self.assertEqual(
                summary["execution_mode"],
                "LIVE_BROWSER_EXECUTION_SKIPPED_NO_AUTHORIZED_SESSION",
            )
            self.assertEqual(summary["browser_network_attempt_count"], 0)
            self.assertEqual(
                summary["protected_source_skipped_without_authorized_session_count"],
                len(records),
            )
            self.assertEqual(summary["gdcic_authorized_session_overall_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertTrue(result["manifest"]["live_browser_execution_requested"])
            self.assertFalse(result["manifest"]["live_browser_execution_enabled"])
            self.assertFalse(result["manifest"]["safety"]["network_enabled"])
            self.assertTrue(
                result["manifest"]["safety"]["protected_source_skipped_without_authorized_session"]
            )
            self.assertTrue(records)
            self.assertTrue(
                all(record["readback_state"] == "LOGIN_OR_SSO_REQUIRED_BLOCKED" for record in records)
            )
            self.assertTrue(all(not record["network_attempted"] for record in records))
            self.assertGreater(summary["alternative_public_source_route_count"], 0)
            self.assertEqual(
                summary["authorization_blocker_alternative_operator_next_action"],
                "run_alternative_public_source_release_evidence_readback_chain",
            )

    def test_field_query_artifact_can_seed_live30_authorized_readback_tasks_without_release_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            field_query_json = root / "field" / "guangdong-local-field-query-probe-v1.json"
            missing_plan_root = root / "missing-release-plan"
            out_root = root / "gdcic-readback"
            _write_field_query_artifact(field_query_json)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=missing_plan_root,
                field_query_json=field_query_json,
                output_root=out_root,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["blocking_reasons"], [])
            self.assertEqual(result["manifest"]["source_field_query_json"], str(field_query_json))
            self.assertEqual(result["summary"]["gdcic_browser_readback_task_count"], 2)
            self.assertEqual(
                result["summary"]["release_evidence_target_type_counts"],
                {"contract_performance": 1, "project_manager_change_notice": 1},
            )
            self.assertEqual(result["summary"]["target_real_readback_success_count"], 0)
            tasks = result["manifest"]["browser_readback_task_records"]
            self.assertEqual(
                {task["project_id"] for task in tasks},
                {"PROJ-CN-GD-JG2026-11366"},
            )

    def test_live_fake_runner_ready_artifact_flows_into_local_field_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            field_root = root / "field"
            _write_release_evidence_adapter_plan(plan_root)

            readback = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_contract_text_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(readback["safe_to_execute"])
            self.assertEqual(readback["summary"]["authorized_session_input_state"], "INJECTED_BROWSER_RUNNER")
            self.assertTrue(readback["summary"]["authorized_session_input_ready"])
            self.assertEqual(readback["summary"]["gdcic_browser_readback_ready_count"], 1)
            self.assertEqual(
                readback["summary"]["gdcic_authorized_session_overall_state"],
                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
            )
            readback_record = readback["manifest"]["browser_readback_records"][0]
            self.assertEqual(
                readback_record["authorization_readiness_state"],
                "FIELD_SURFACE_REACHED_REVIEW_REQUIRED",
            )
            self.assertEqual(readback_record["field_surface_state"], "TARGET_FIELD_MATCHED_REVIEW_REQUIRED")
            field = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                gdcic_browser_readback_root=readback_root,
                output_root=field_root,
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=1,
                http_getter=_gdcic_sso_empty_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(field["safe_to_execute"])
            task = field["manifest"]["field_task_records"][0]
            self.assertEqual(task["release_evidence_target_type"], "project_manager_change_notice")
            self.assertEqual(task["field_query_probe_state"], "LIVE_FIELD_QUERY_NEEDS_BROWSER")
            self.assertEqual(task["adapter_result_state"], "NEEDS_BROWSER")
            self.assertEqual(
                task["downstream_release_evidence_abcd_grade"],
                "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            )
            self.assertTrue(task["field_match_summary"]["browser_authorized_readback_consumed"])
            self.assertTrue(task["field_match_summary"]["browser_authorized_readback_pending_or_not_executed"])
            self.assertEqual(task["field_summary"]["authorized_session_input_state"], "INJECTED_BROWSER_RUNNER")
            self.assertTrue(task["field_summary"]["authorized_session_input_ready"])
            self.assertEqual(task["field_summary"]["record_count"], 0)
            self.assertEqual(
                field["summary"]["authorized_session_input_state_counts"],
                {"INJECTED_BROWSER_RUNNER": 1},
            )
            self.assertEqual(
                task["field_summary"]["authorization_readiness_state_counts"],
                {"NOT_EXECUTED_DEFERRED_BY_LIMIT": 1},
            )
            self.assertIn(
                "gd_gdcic_browser_authorized_readback_pending_or_not_executed",
                task["blocker_taxonomy"],
            )

    def test_project_manager_change_runner_extracts_release_fields_and_flows_into_field_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            field_root = root / "field"
            _write_release_evidence_adapter_plan(plan_root)

            readback = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=2,
                browser_runner=_target_aware_browser_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(readback["safe_to_execute"])
            by_target = {
                record["release_evidence_target_type"]: record
                for record in readback["manifest"]["browser_readback_records"]
            }
            change_record = by_target["project_manager_change_notice"]
            self.assertEqual(change_record["readback_state"], "BROWSER_AUTHORIZED_READBACK_READY")
            extracted = change_record["records"][0]
            self.assertEqual(extracted["original_project_manager_name"], "张三")
            self.assertEqual(extracted["new_project_manager_name"], "李四")
            self.assertEqual(extracted["change_date"], "2026-01-15")
            self.assertEqual(
                extracted["project_manager_change_release_window_interpretation"],
                "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
            )
            self.assertTrue(extracted["original_project_manager_matches_query_person"])
            self.assertEqual(readback["summary"]["project_manager_change_readback_task_count"], 1)
            self.assertEqual(readback["summary"]["project_manager_change_readback_record_count"], 1)
            self.assertEqual(readback["summary"]["project_manager_change_ready_count"], 1)
            self.assertEqual(readback["summary"]["project_manager_change_not_found_count"], 0)
            self.assertEqual(readback["summary"]["project_manager_change_login_or_sso_required_count"], 0)
            self.assertEqual(
                readback["summary"]["project_manager_change_interpretation_counts"],
                {"ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1},
            )
            self.assertEqual(readback["summary"]["project_manager_change_date_count"], 1)
            self.assertEqual(readback["summary"]["project_manager_change_original_manager_matches_query_count"], 1)
            self.assertEqual(readback["summary"]["project_manager_change_new_manager_matches_query_count"], 0)
            self.assertEqual(readback["summary"]["stage5_calibration_sample_count"], 1)
            self.assertEqual(readback["summary"]["stage5_calibration_truth_label_required_count"], 1)
            self.assertEqual(
                readback["summary"]["stage5_abcd_calibration_counts"],
                {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(
                readback["summary"]["stage5_calibration_review_bucket_counts"],
                {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            )
            calibration_sample = readback["manifest"]["stage5_calibration_sample_records"][0]
            self.assertEqual(calibration_sample["rule_code"], "P13B_PROJECT_MANAGER_CHANGE_READBACK")
            self.assertEqual(
                calibration_sample["stage5_abcd_calibration_bucket"],
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
            )
            self.assertTrue(calibration_sample["calibration_truth_label_required"])
            persisted = RuntimeStateRepository().latest_worker_result(
                worker_id="gdcic_browser_authorized_readback_worker"
            )
            self.assertEqual(persisted["worker_id"], "gdcic_browser_authorized_readback_worker")
            self.assertEqual(persisted["worker_result_state"], "FIELD_SURFACE_REACHED_REVIEW_REQUIRED")
            self.assertEqual(persisted["project_manager_change_ready_count"], 1)
            self.assertEqual(persisted["stage5_calibration_sample_count"], 1)
            self.assertEqual(
                persisted["stage5_abcd_calibration_counts"],
                {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(
                persisted["stage5_calibration_review_bucket_counts"],
                {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            )
            self.assertEqual(persisted["project_id"], "PROJ-P13B-1")
            self.assertEqual(persisted["trace_refs"]["stage5_calibration_sample_count"], "1")
            self.assertIn(
                "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
                persisted["trace_refs"]["stage5_calibration_review_bucket_counts_json"],
            )
            self.assertEqual(persisted["trace_refs"]["project_manager_change_ready_count"], "1")
            self.assertIn(
                "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
                persisted["trace_refs"]["project_manager_change_interpretation_counts_json"],
            )
            self.assertFalse(persisted["governed_state"]["external_customer_action_enabled"])

            field = build_guangdong_local_field_query_probe(
                release_evidence_adapter_plan_root=plan_root,
                gdcic_browser_readback_root=readback_root,
                output_root=field_root,
                source_profile_ids=["GUANGDONG-GDCIC-HOME"],
                enable_live_public_query=True,
                max_live_tasks=2,
                http_getter=_gdcic_sso_empty_getter,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(field["safe_to_execute"])
            field_by_target = {
                task["release_evidence_target_type"]: task
                for task in field["manifest"]["field_task_records"]
            }
            task = field_by_target["project_manager_change_notice"]
            self.assertEqual(task["adapter_result_state"], "MATCHED")
            self.assertEqual(task["downstream_release_evidence_abcd_grade"], "C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
            self.assertEqual(
                field["summary"]["guangdong_gdcic_browser_authorized_project_manager_change_ready_count"],
                1,
            )
            self.assertEqual(
                field["summary"][
                    "guangdong_gdcic_browser_authorized_project_manager_change_interpretation_counts"
                ],
                {"ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED": 1},
            )
            compact = task["field_match_summary"]["source_specific_records"][0]
            self.assertEqual(compact["original_project_manager_name_probe"], "张三")
            self.assertEqual(compact["new_project_manager_name_probe"], "李四")
            self.assertEqual(compact["change_date_probe"], "2026-01-15")
            self.assertEqual(
                compact["project_manager_change_release_window_interpretation"],
                "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED",
            )

    def test_login_or_sso_text_is_blocked_not_field_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_sso_text_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["browser_readback_records"][0]
            self.assertEqual(record["readback_state"], "LOGIN_OR_SSO_REQUIRED_BLOCKED")
            self.assertEqual(record["adapter_result_state"], "BLOCKED")
            self.assertEqual(record["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertEqual(record["field_surface_state"], "LOGIN_OR_SSO_BLOCKED_BEFORE_FIELD_SURFACE")
            self.assertFalse(
                record["browser_capability_assessment"]["http_dynamic_stealthy_can_replace_login_state"]
            )
            self.assertEqual(
                record["browser_capability_assessment"]["required_capability"],
                "AUTHORIZED_SESSION_STORAGE_STATE_OR_USER_DATA_DIR",
            )
            self.assertIn(
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
                record["operator_next_actions"],
            )
            self.assertIn(
                "do_not_treat_http_dynamic_stealthy_as_login_state_replacement",
                record["operator_next_actions"],
            )
            self.assertIn(
                "run_alternative_public_source_release_evidence_readback_chain",
                record["operator_next_actions"],
            )
            self.assertEqual(result["summary"]["gdcic_authorized_session_overall_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertEqual(result["summary"]["alternative_public_source_route_count"], 2)
            self.assertEqual(
                result["summary"]["authorization_blocker_alternative_operator_next_action"],
                "run_alternative_public_source_release_evidence_readback_chain",
            )
            self.assertEqual(result["summary"]["target_real_readback_success_count"], 0)
            self.assertTrue(result["summary"]["real_readback_success_not_faked"])
            self.assertEqual(
                result["summary"]["authorization_blocker_operator_next_action"],
                "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun",
            )
            self.assertEqual(result["summary"]["project_manager_change_ready_count"], 0)
            self.assertIn("gdcic_login_or_sso_required_for_authorized_readback", record["blocker_taxonomy"])
            self.assertTrue(record["query_miss_is_not_clearance"])

    def test_gdcic_contract_system_login_shell_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_contract_login_shell_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["browser_readback_records"][0]
            self.assertEqual(record["readback_state"], "LOGIN_OR_SSO_REQUIRED_BLOCKED")
            self.assertEqual(record["adapter_result_state"], "BLOCKED")
            self.assertEqual(record["authorization_readiness_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertFalse(
                record["browser_capability_assessment"]["http_dynamic_stealthy_can_replace_login_state"]
            )
            self.assertEqual(result["summary"]["gdcic_authorized_session_overall_state"], "LOGIN_OR_SSO_REQUIRED")
            self.assertIn("gdcic_login_or_sso_required_for_authorized_readback", record["blocker_taxonomy"])

    def test_no_target_text_is_not_found_not_clearance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan_root = root / "release-plan"
            readback_root = root / "gdcic-readback"
            _write_release_evidence_adapter_plan(plan_root)

            result = build_gdcic_browser_authorized_readback(
                release_evidence_adapter_plan_root=plan_root,
                output_root=readback_root,
                enable_live_browser_execution=True,
                max_live_browser_tasks=1,
                browser_runner=_no_target_text_runner,
                created_at="2026-05-20T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            record = result["manifest"]["browser_readback_records"][0]
            self.assertEqual(record["readback_state"], "NO_FIELD_MATCH_REVIEW_REQUIRED")
            self.assertEqual(record["adapter_result_state"], "NOT_FOUND")
            self.assertEqual(record["authorization_readiness_state"], "FIELD_SURFACE_REACHED_REVIEW_REQUIRED")
            self.assertEqual(record["field_surface_state"], "TARGET_FIELD_NOT_FOUND_REVIEW_REQUIRED")
            self.assertIn(
                "review_gdcic_authorized_query_terms_or_capture_more_precise_field_page",
                record["operator_next_actions"],
            )
            self.assertEqual(record["record_count"], 0)
            self.assertTrue(record["query_miss_is_not_clearance"])


def _write_release_evidence_adapter_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tasks = [
        _release_plan_task("REL-TASK-1", "construction_permit", "B_ENHANCEMENT_OFFICIAL_READBACK"),
        _release_plan_task("REL-TASK-2", "contract_performance", "B_ENHANCEMENT_OFFICIAL_READBACK"),
        _release_plan_task("REL-TASK-3", "completion_acceptance", "C_REVERSE_EXPLANATION_OFFICIAL_READBACK"),
        _release_plan_task("REL-TASK-4", "project_manager_change_notice", "C_REVERSE_EXPLANATION_OFFICIAL_READBACK"),
    ]
    payload = {
        "manifest": {
            "manifest_kind": "release_evidence_adapter_plan_v1_manifest",
            "manifest_id": "RELEASE-PLAN-FIXTURE-1",
            "release_evidence_adapter_task_records": tasks,
        },
        "summary": {"adapter_task_count": len(tasks)},
    }
    payload["manifest"]["manifest_sha256"] = __import__("hashlib").sha256(
        json.dumps(
            {key: value for key, value in payload["manifest"].items() if key != "manifest_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    (root / "release-evidence-adapter-plan-v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_field_query_artifact(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            **_release_plan_task("FIELD-TASK-1", "contract_performance", "B_ENHANCEMENT_OFFICIAL_READBACK"),
            "project_id": "PROJ-CN-GD-JG2026-11366",
            "source_profile_id": "GUANGDONG-GDCIC-HOME",
            "adapter_result_state": "NEEDS_BROWSER",
        },
        {
            **_release_plan_task("FIELD-TASK-2", "project_manager_change_notice", "C_REVERSE_EXPLANATION_OFFICIAL_READBACK"),
            "project_id": "PROJ-CN-GD-JG2026-11366",
            "source_profile_id": "GUANGDONG-GDCIC-HOME",
            "adapter_result_state": "NEEDS_BROWSER",
        },
        {
            **_release_plan_task("FIELD-TASK-3", "completion_acceptance", "D_INSUFFICIENT_OR_BLOCKED_READBACK"),
            "project_id": "PROJ-CN-GD-JG2026-11366",
            "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
            "adapter_result_state": "NOT_FOUND",
        },
    ]
    payload = {
        "manifest": {
            "manifest_kind": "guangdong_local_field_query_probe_v1_manifest",
            "manifest_id": "FIELD-QUERY-FIXTURE-1",
            "manifest_sha256": "field-query-sha",
            "field_task_records": records,
        },
        "summary": {"field_task_count": len(records)},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _release_plan_task(task_id: str, target_type: str, grade_on_match: str) -> dict[str, Any]:
    return {
        "release_evidence_adapter_task_id": task_id,
        "source_release_evidence_probe_task_id": "P13B-RELEASE-PROBE-TASK-1",
        "source_release_evidence_probe_plan_id": "P13B-RELEASE-PROBE-PLAN-1",
        "project_id": "PROJ-P13B-1",
        "project_name": "广州测试项目中标候选人公示",
        "candidate_company_name": "广州测试建设有限公司",
        "matched_person_names": ["张三"],
        "release_evidence_target_type": target_type,
        "release_evidence_grade_on_match": grade_on_match,
        "initial_release_evidence_abcd_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
        "release_evidence_query_region_code": "CN-GD",
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "local_housing_authority_adapter_scope": "HISTORICAL_PROJECT_JURISDICTION",
        "local_housing_authority_adapter_region_code": "CN-GD",
        "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
        "source_url": "https://zfcj.gz.gov.cn/zfcj/xyxx/",
        "source_family": "guangzhou_local_housing_public_source",
        "trigger_source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
        "query_params": {
            "projectId": "PROJ-P13B-1",
            "projectName": "广州测试项目中标候选人公示",
            "companyName": "广州测试建设有限公司",
            "personName": "张三",
            "keywords": ["广州测试项目中标候选人公示", "广州测试建设有限公司", "张三"],
        },
        "adapter_result_state": "PLAN_ONLY_NOT_EXECUTED",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _contract_text_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": str(task.get("source_url") or ""),
        "body_text": (
            "广东建设信息网 合同 履约 工期 广州测试项目中标候选人公示 "
            "广州测试建设有限公司 项目经理 张三 合同开始 2025-08-01 合同结束 2026-08-01"
        ),
    }


def _target_aware_browser_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    if task.get("release_evidence_target_type") == "project_manager_change_notice":
        return {
            "status_code": 200,
            "final_url": str(task.get("source_url") or ""),
            "body_text": (
                "广东建设信息网 项目经理变更 广州测试项目中标候选人公示 "
                "广州测试建设有限公司 原项目经理：张三 新项目经理：李四 "
                "变更日期：2026-01-15 变更原因：建设单位申请调整项目负责人"
            ),
        }
    return _contract_text_runner(task)


def _sso_text_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": "http://210.76.80.152:8008/SSO/jrsso/auth",
        "body_text": "统一身份认证 用户登录 验证码",
    }


def _contract_login_shell_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": "http://210.76.80.152:8008/JG",
        "body_text": "登录 广东省建筑市场监管公共服务平台 招投标及合同履约监管系统 信息公示区",
    }


def _no_target_text_runner(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status_code": 200,
        "final_url": str(task.get("source_url") or ""),
        "body_text": "广东建设信息网 查询页面 广州测试建设有限公司 张三",
    }


def _gdcic_sso_empty_getter(url: str, _params: Mapping[str, Any]) -> Mapping[str, Any]:
    if "Indexht" in url:
        return {
            "http_status": 200,
            "content_type": "text/html; charset=utf-8",
            "text_probe": "<script>top.window.location.href='http://210.76.80.152:8008/SSO/jrsso/auth'</script>",
        }
    return {
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
        "text_probe": "<table><tbody></tbody></table>",
    }


if __name__ == "__main__":
    unittest.main()
