from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.deps import get_settings
from api.main import create_app
from helpers import load_fixture
from shared.pipeline import run_internal_chain
from storage import persist_stage_bundle, reset_default_storage


class TestOperatorCustomerAccess(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        reset_default_storage()

    def tearDown(self) -> None:
        get_settings.cache_clear()

    def _approved_customer_visible_payload(self) -> dict:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "approved_customer_visible_unlock_requested": True,
                "approved_customer_artifact_access_requested": True,
                "approved_customer_page_publication_requested": True,
                "approved_export_artifact_generation_requested": True,
                "approved_customer_download_requested": True,
                "customer_download_requested": True,
                "approval_state": "APPROVED",
                "project_fact_audit_ref": "AUD-PROJECT-FACT-001",
                "candidate_projection_audit_ref": "AUD-CANDIDATE-001",
                "approval_chain_audit_ref": "AUD-APPROVAL-001",
                "customer_account_access_state": "APPROVED",
                "customer_artifact_access_approval_state": "APPROVED",
                "customer_download_auth_state": "AUTHORIZED",
                "download_auth_audit_ref": "AUD-DOWNLOAD-AUTH-001",
                "customer_access_audit_ref": "AUD-CUSTOMER-ACCESS-001",
                "external_visibility_state": "CUSTOMER_VISIBLE_APPROVED",
                "leadpack_candidate_review_gate": "APPROVED",
                "leadpack_activation_prep_review_gate": "APPROVED",
                "implementation_decision_state": "APPROVED",
            }
        )
        return payload

    def test_bootstrap_and_readiness_surface_expose_operator_customer_go_live_entries(self) -> None:
        app = create_app()
        bootstrap = app.state.transport_bootstrap

        mounted_operations = {
            operation["operationId"]: operation
            for operation in bootstrap["operator_customer_access_mounted_operations"]
        }
        expected_operations = {
            "previewOperatorCustomerAccessReadiness",
            "createOperatorTask",
            "listRealPublicSourceProfiles",
            "runOwnerRealPublicSourceCapture",
            "listOwnerRealPublicSourceTaskRuns",
            "readOwnerRealPublicSourceCapture",
            "readOperatorTask",
            "importOperatorProject",
            "previewCustomerArtifactAccessCandidate",
            "previewGoLiveReadiness",
            "previewOperatorSchedulerStatus",
        }
        self.assertEqual(set(app.state.operator_customer_access_operations), expected_operations)
        self.assertEqual(set(mounted_operations), expected_operations)
        for operation in mounted_operations.values():
            self.assertTrue(operation["internal_only"])
            self.assertTrue(operation["readiness_only"])
            self.assertTrue(operation["projection_only"])
            self.assertFalse(operation["live_execution_enabled"])
            self.assertFalse(operation["external_release_enabled"])
            self.assertFalse(operation["public_software_release"])
            self.assertFalse(operation["provider_call_enabled"])
            self.assertFalse(operation["real_provider_call_enabled"])
            self.assertFalse(operation["automated_refund_enabled"])

        access_bootstrap = bootstrap["operator_customer_access_bootstrap"]
        self.assertEqual(access_bootstrap["capability_state"], "APPROVAL_READY")
        self.assertTrue(access_bootstrap["customer_artifact_access_gated"])
        self.assertTrue(access_bootstrap["account_access_control_required"])
        self.assertTrue(access_bootstrap["download_auth_required"])
        self.assertTrue(access_bootstrap["field_allowlist_masking_required"])
        self.assertTrue(access_bootstrap["approval_audit_readback_required"])
        self.assertFalse(access_bootstrap["external_release_enabled"])
        self.assertFalse(access_bootstrap["public_software_release"])
        self.assertFalse(access_bootstrap["provider_live_execution_enabled"])
        self.assertFalse(access_bootstrap["stage8_real_execution_enabled"])
        self.assertFalse(access_bootstrap["stage9_real_payment_delivery_refund_enabled"])
        self.assertFalse(access_bootstrap["automated_refund_enabled"])

        redlines = bootstrap["redlines"]
        self.assertTrue(redlines["operator_customer_access_http_endpoint_added"])
        self.assertFalse(redlines["operator_customer_access_external_or_live_endpoint_added"])
        self.assertFalse(redlines["customer_artifact_access_public_release_enabled"])
        self.assertFalse(redlines["customer_download_without_auth_enabled"])
        self.assertFalse(redlines["customer_artifact_download_enabled"])
        self.assertFalse(redlines["external_software_release_enabled"])

        client = TestClient(app)
        response = client.request("GET", "/operator-console/readiness")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "operator_customer_access_readiness")
        self.assertEqual(payload["capability_state"], "APPROVAL_READY")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["external_release_enabled"])
        self.assertFalse(payload["public_software_release"])
        self.assertTrue(payload["operator_console"]["task_creation_entry"]["entry_visible"])
        self.assertTrue(payload["operator_console"]["project_import_entry"]["entry_visible"])
        self.assertTrue(payload["operator_console"]["real_public_source_profile_catalog"]["entry_visible"])
        self.assertTrue(payload["operator_console"]["real_public_source_runner_entry"]["entry_visible"])
        self.assertTrue(payload["operator_console"]["real_public_source_runner_entry"]["entry_capture_enabled"])
        self.assertTrue(payload["operator_console"]["real_public_source_runner_entry"]["attachment_capture_enabled"])
        self.assertFalse(payload["operator_console"]["real_public_source_runner_entry"]["uncontrolled_crawler_enabled"])
        self.assertFalse(payload["operator_console"]["real_public_source_runner_entry"]["real_provider_call_enabled"])
        self.assertTrue(payload["operator_console"]["real_public_source_task_run_list"]["entry_visible"])
        self.assertTrue(payload["operator_console"]["real_public_source_task_run_list"]["repository_backed_readback"])
        self.assertTrue(payload["operator_console"]["full_chain_run_entry"]["entry_visible"])
        self.assertFalse(
            payload["operator_console"]["full_chain_run_entry"][
                "stage1_to_stage5_external_live_transport_enabled"
            ]
        )
        self.assertTrue(payload["provider_status"]["readback_ready"])
        self.assertFalse(payload["provider_status"]["provider_call_enabled"])
        self.assertFalse(payload["provider_status"]["real_provider_call_enabled"])
        self.assertTrue(payload["scheduler_status"]["readback_ready"])
        self.assertFalse(payload["scheduler_status"]["external_queue_connection_enabled"])
        self.assertFalse(payload["scheduler_status"]["real_provider_execution_enabled"])
        self.assertTrue(payload["audit_log"]["audit_log_visible"])
        self.assertTrue(payload["customer_access"]["account_access_control_visible"])
        self.assertTrue(payload["customer_access"]["download_auth_visible"])
        self.assertTrue(payload["customer_access"]["field_allowlist_masking_visible"])
        self.assertTrue(payload["customer_access"]["approval_audit_readback_visible"])
        self.assertFalse(payload["customer_access"]["customer_visible_publication_enabled"])
        self.assertFalse(payload["customer_access"]["external_delivery_enabled"])
        self.assertFalse(payload["customer_access"]["public_software_release"])
        self.assertEqual(payload["go_live_readiness"]["capability_state"], "APPROVAL_READY")
        self.assertFalse(payload["go_live_readiness"]["go_live_enabled"])
        self.assertFalse(payload["go_live_readiness"]["external_release_enabled"])

        profiles_response = client.request("GET", "/operator-console/real-source-profiles")
        self.assertEqual(profiles_response.status_code, 200)
        profiles = profiles_response.json()
        self.assertEqual(profiles["surface_id"], "operator_real_public_source_profiles")
        self.assertGreaterEqual(profiles["entry_profile_count"], 1)
        self.assertGreaterEqual(profiles["attachment_profile_count"], 1)
        self.assertFalse(profiles["uncontrolled_crawler_enabled"])
        self.assertFalse(profiles["real_provider_call_enabled"])
        self.assertIn("GGZY-DEAL-LIST", {item["profile_id"] for item in profiles["entry_profiles"]})
        self.assertIn("BEIJING-STANDARD-BIDDING-PDF", {item["profile_id"] for item in profiles["attachment_profiles"]})

    def test_real_public_source_runner_uses_existing_stage2_fetchers_and_replay(self) -> None:
        client = TestClient(create_app())
        with patch(
            "api.routes.operator_customer_access.Stage2Service.fetch_real_public_entry_url",
            return_value={
                "status": "FETCHED",
                "entry_profile_id": "GGZY-DEAL-LIST",
                "snapshot_id_optional": "REAL-ENTRY-GGZY-001",
                "fail_closed": False,
            },
        ) as fetch_entry, patch(
            "api.routes.operator_customer_access.Stage2Service.fetch_real_public_attachment_url",
            return_value={
                "status": "FETCHED",
                "attachment_profile_id": "BEIJING-STANDARD-BIDDING-PDF",
                "snapshot_id_optional": "REAL-ATTACH-BJ-001",
                "fail_closed": False,
            },
        ) as fetch_attachment, patch(
            "api.routes.operator_customer_access.Stage2Service.replay_public_source_snapshot",
            return_value={
                "snapshot_id": "REAL-ATTACH-BJ-001",
                "readback_state": "READBACK_READY",
                "replayable": True,
                "manifest_present": True,
                "object_present": True,
            },
        ) as replay_snapshot:
            entry_response = client.request(
                "POST",
                "/operator-console/real-source-runs",
                json={"capture_kind": "entry", "profile_id": "GGZY-DEAL-LIST", "task_id": "TASK-134-001"},
            )
            self.assertEqual(entry_response.status_code, 200)
            entry_payload = entry_response.json()
            self.assertEqual(entry_payload["surface_id"], "operator_real_public_source_run")
            self.assertEqual(entry_payload["capture_kind"], "entry")
            self.assertEqual(entry_payload["capture_status"], "FETCHED")
            self.assertEqual(entry_payload["snapshot_id_optional"], "REAL-ENTRY-GGZY-001")
            self.assertEqual(entry_payload["run_record"]["profile_id"], "GGZY-DEAL-LIST")
            self.assertEqual(entry_payload["run_record"]["snapshot_id_optional"], "REAL-ENTRY-GGZY-001")
            self.assertTrue(entry_payload["repository_backed_readback"])
            self.assertFalse(entry_payload["uncontrolled_crawler_enabled"])
            self.assertFalse(entry_payload["real_provider_call_enabled"])
            fetch_entry.assert_called_once()

            attachment_response = client.request(
                "POST",
                "/operator-console/real-source-runs",
                json={"capture_kind": "attachment", "profile_id": "BEIJING-STANDARD-BIDDING-PDF", "project_id": "PROJ-134-001"},
            )
            self.assertEqual(attachment_response.status_code, 200)
            attachment_payload = attachment_response.json()
            self.assertEqual(attachment_payload["capture_kind"], "attachment")
            self.assertEqual(attachment_payload["snapshot_id_optional"], "REAL-ATTACH-BJ-001")
            self.assertEqual(attachment_payload["run_record"]["profile_id"], "BEIJING-STANDARD-BIDDING-PDF")
            fetch_attachment.assert_called_once()

            runs_response = client.request("GET", "/operator-console/real-source-task-runs")
            self.assertEqual(runs_response.status_code, 200)
            runs = runs_response.json()
            self.assertEqual(runs["surface_id"], "operator_real_public_source_task_runs")
            self.assertEqual(runs["run_count"], 2)
            self.assertTrue(runs["repository_backed_readback"])
            self.assertFalse(runs["uncontrolled_crawler_enabled"])
            self.assertFalse(runs["real_provider_call_enabled"])
            self.assertEqual(
                {run["profile_id"] for run in runs["runs"]},
                {"GGZY-DEAL-LIST", "BEIJING-STANDARD-BIDDING-PDF"},
            )

            readback_response = client.request(
                "GET",
                "/operator-console/real-source-runs/REAL-ATTACH-BJ-001",
            )
            self.assertEqual(readback_response.status_code, 200)
            readback = readback_response.json()
            self.assertEqual(readback["surface_id"], "operator_real_public_source_readback")
            self.assertEqual(readback["readback_state"], "READBACK_READY")
            self.assertTrue(readback["repository_backed_readback"])
            self.assertTrue(readback["replayable"])
            replay_snapshot.assert_called_once_with("REAL-ATTACH-BJ-001")

    def test_operator_task_and_project_import_use_stage1_scheduler_without_external_fetch(self) -> None:
        app = create_app()
        client = TestClient(app)
        task_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        task_payload.update(
            {
                "task_id": "TASK-OPERATOR-ACCESS-001",
                "project_id": "PROJ-OPERATOR-ACCESS-001",
                "now": "2026-04-26T00:00:00+00:00",
            }
        )

        create_response = client.request("POST", "/operator-console/tasks", json=task_payload)

        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        self.assertEqual(created["surface_id"], "operator_task_creation")
        self.assertEqual(created["status"], "queued")
        self.assertTrue(created["task_creation_visible"])
        self.assertTrue(created["repository_backed_readback"])
        self.assertFalse(created["stage2_fetch_enabled"])
        self.assertFalse(created["real_external_fetch_enabled"])
        self.assertFalse(created["crawler_enabled"])
        self.assertFalse(created["live_execution_enabled"])
        self.assertFalse(created["stage2_handoff_intent"]["fetch_enabled"])
        queue_item_id = created["scheduler_task"]["queue_item_id"]

        read_response = client.request("GET", f"/operator-console/tasks/{queue_item_id}")

        self.assertEqual(read_response.status_code, 200)
        readback = read_response.json()
        self.assertEqual(readback["surface_id"], "operator_task_readback")
        self.assertTrue(readback["repository_backed"])
        self.assertTrue(readback["replayable"])
        self.assertFalse(readback["fetch_execution"]["stage2_fetch_enabled"])
        self.assertFalse(readback["fetch_execution"]["crawler_enabled"])
        self.assertFalse(readback["fetch_execution"]["real_external_fetch_enabled"])
        self.assertFalse(readback["live_execution_enabled"])

        import_payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        import_payload.update(
            {
                "project_id": "PROJ-OPERATOR-IMPORT-001",
                "region_code": "CN",
                "now": "2026-04-26T00:05:00+00:00",
            }
        )
        import_payload.pop("task_id", None)
        import_response = client.request("POST", "/operator-console/project-imports", json=import_payload)

        self.assertEqual(import_response.status_code, 200)
        imported = import_response.json()
        self.assertEqual(imported["surface_id"], "operator_project_import")
        self.assertTrue(imported["project_import_entry"])
        self.assertEqual(
            imported["project_import_state"],
            "IMPORTED_AS_INTERNAL_STAGE1_TASK_INTENT",
        )
        self.assertEqual(imported["scheduler_task"]["task_id"], "IMPORT-PROJ-OPERATOR-IMPORT-001")
        self.assertFalse(imported["stage2_fetch_enabled"])
        self.assertFalse(imported["real_external_fetch_enabled"])
        self.assertFalse(imported["crawler_enabled"])
        self.assertFalse(imported["live_execution_enabled"])

        scheduler_response = client.request("GET", "/operator-console/scheduler-status")

        self.assertEqual(scheduler_response.status_code, 200)
        scheduler_status = scheduler_response.json()
        self.assertEqual(scheduler_status["surface_id"], "operator_scheduler_status")
        self.assertTrue(scheduler_status["readback_ready"])
        self.assertTrue(scheduler_status["repository_backed"])
        self.assertEqual(scheduler_status["queue_status_counts"]["queued"], 2)
        self.assertFalse(scheduler_status["stage2_fetch_enabled"])
        self.assertFalse(scheduler_status["crawler_enabled"])
        self.assertFalse(scheduler_status["real_external_fetch_enabled"])
        self.assertFalse(scheduler_status["external_queue_connection_enabled"])

    def test_customer_artifact_access_candidate_is_gated_and_readback_only(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", f"/customer-artifact-access-candidates/{opportunity_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "customer_artifact_access_candidate")
        self.assertEqual(payload["capability_state"], "APPROVAL_READY")
        self.assertTrue(payload["internal_only"])
        self.assertTrue(payload["candidate_only"])
        self.assertTrue(payload["readiness_only"])
        self.assertTrue(payload["projection_only"])
        self.assertTrue(payload["release_blocked"])
        self.assertFalse(payload["public_software_release"])
        self.assertFalse(payload["external_release_enabled"])
        self.assertFalse(payload["customer_visible_export_enabled"])
        self.assertFalse(payload["client_page_release_enabled"])
        self.assertFalse(payload["external_delivery_enabled"])
        self.assertFalse(payload["page_publication_enabled"])
        self.assertTrue(payload["account_access_control"]["account_required"])
        self.assertTrue(payload["account_access_control"]["permission_check_required"])
        self.assertFalse(payload["account_access_control"]["account_creation_enabled"])
        self.assertFalse(payload["account_access_control"]["public_signup_enabled"])
        self.assertFalse(payload["account_access_control"]["operator_can_grant_without_approval"])
        self.assertTrue(payload["download_auth"]["auth_required"])
        self.assertTrue(payload["download_auth"]["download_audit_required"])
        self.assertTrue(payload["download_auth"]["approval_required"])
        self.assertTrue(payload["download_auth"]["audit_required"])
        self.assertFalse(payload["download_auth"]["download_enabled"])
        self.assertFalse(payload["download_auth"]["customer_download_enabled"])
        self.assertFalse(payload["download_auth"]["signed_download_url_enabled"])
        self.assertTrue(payload["field_allowlist_masking"]["allowlist_enforced"])
        self.assertTrue(payload["field_allowlist_masking"]["masking_required"])
        self.assertFalse(payload["field_allowlist_masking"]["internal_blackbox_fields_exposed"])
        self.assertIn("opportunity_id", payload["field_allowlist_masking"]["field_allowlist"])
        self.assertIn("payment_record", payload["field_allowlist_masking"]["field_blacklist"])
        self.assertTrue(payload["approval_audit_readback"]["approval_required"])
        self.assertTrue(payload["approval_audit_readback"]["audit_required"])
        self.assertIn(
            "customer_account_access_control_required",
            payload["blocked_reasons"],
        )
        self.assertIn("download_auth_required", payload["blocked_reasons"])
        source_readiness = payload["source_formal_client_export_page_layer_readiness"]
        self.assertEqual(source_readiness["surface_id"], "formal_client_export_page_layer_readiness")
        self.assertTrue(source_readiness["release_blocked"])
        self.assertFalse(source_readiness["customer_visible_export_enabled"])
        self.assertFalse(source_readiness["external_release_enabled"])
        self.assertFalse(source_readiness["download_audit"]["customer_download_enabled"])

    def test_customer_artifact_access_candidate_can_read_back_approved_download_unlock(self) -> None:
        result = run_internal_chain(self._approved_customer_visible_payload())
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", f"/customer-artifact-access-candidates/{opportunity_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_state"], "approved-customer-artifact-access-readback")
        self.assertFalse(payload["candidate_only"])
        self.assertFalse(payload["readiness_only"])
        self.assertFalse(payload["release_blocked"])
        self.assertTrue(payload["customer_visible_export_enabled"])
        self.assertTrue(payload["client_page_release_enabled"])
        self.assertTrue(payload["page_publication_enabled"])
        self.assertFalse(payload["external_release_enabled"])
        self.assertEqual(payload["account_access_control"]["account_state"], "ACCESS_APPROVED_READBACK")
        self.assertTrue(payload["account_access_control"]["allowed_after_approval"])
        self.assertTrue(payload["download_auth"]["download_enabled"])
        self.assertTrue(payload["download_auth"]["customer_download_enabled"])
        self.assertFalse(payload["download_auth"]["signed_download_url_enabled"])
        self.assertFalse(
            payload["download_auth"]["download_audit_readback"]["real_customer_download_executed"]
        )
        self.assertFalse(payload["field_allowlist_masking"]["internal_blackbox_fields_exposed"])
        self.assertEqual(payload["approval_audit_readback"]["missing_prerequisites"], [])
        source_readiness = payload["source_formal_client_export_page_layer_readiness"]
        self.assertEqual(source_readiness["readiness_state"], "APPROVED_CUSTOMER_VISIBLE_READBACK")
        self.assertTrue(source_readiness["download_audit"]["customer_download_enabled"])

    def test_go_live_readiness_lists_blockers_approvals_audits_and_redlines(self) -> None:
        client = TestClient(create_app())
        response = client.request("GET", "/go-live/readiness")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "go_live_readiness")
        self.assertEqual(payload["capability_state"], "APPROVAL_READY")
        self.assertTrue(payload["approval_ready"])
        self.assertTrue(payload["internal_only"])
        self.assertTrue(payload["readiness_only"])
        self.assertFalse(payload["go_live_enabled"])
        self.assertFalse(payload["production_release_enabled"])
        self.assertFalse(payload["external_release_enabled"])
        self.assertFalse(payload["public_software_release"])
        self.assertEqual(payload["deployment_readiness"]["readiness_state"], "APPROVAL_READY")
        self.assertFalse(payload["deployment_readiness"]["compose_runtime_enabled"])
        self.assertFalse(payload["deployment_readiness"]["container_execution_enabled"])
        self.assertFalse(payload["deployment_readiness"]["migration_execution_enabled"])
        provider = payload["provider_config_readiness"]
        self.assertEqual(provider["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertTrue(provider["readback_only"])
        self.assertFalse(provider["provider_call_enabled"])
        self.assertFalse(provider["real_provider_call_enabled"])
        self.assertFalse(provider["live_fallback_allowed"])
        refs = payload["monitoring_rollback_refs"]
        self.assertIn("monitoring_readiness_state", refs)
        self.assertEqual(refs["production_slo_capability_state"], "PRODUCTION_READY")
        self.assertEqual(refs["production_slo_readiness_state"], "PRODUCTION_READY")
        self.assertEqual(refs["production_incident_runbook_state"], "PRODUCTION_READY")
        self.assertEqual(refs["suspended_state"], "SUSPENDED")
        self.assertTrue(refs["manual_resume_required"])
        self.assertTrue(refs["production_slo_incident_readiness"]["repository_backed_readback"])
        self.assertFalse(
            refs["production_slo_incident_readiness"]["redlines"]["real_alert_dispatch_enabled"]
        )
        self.assertFalse(
            refs["production_slo_incident_readiness"]["redlines"]["incident_automation_enabled"]
        )
        self.assertEqual(
            refs["production_drill_evidence"]["backup_restore_drill_evidence"]["drill_mode"],
            "DRY_RUN_ONLY",
        )
        self.assertEqual(
            refs["production_drill_evidence"]["rollback_drill_evidence"]["drill_mode"],
            "DRY_RUN_ONLY",
        )
        self.assertIn("rollback_state", refs)
        self.assertFalse(refs["rollback_execution_enabled"])
        self.assertFalse(refs["destructive_restore_enabled"])
        for blocker in (
            "external_software_release_blocked",
            "customer_artifact_access_requires_account_permission_approval_and_audit",
            "provider_live_execution_requires_dedicated_live_packet",
            "stage8_real_execution_blocked_by_default",
            "stage9_real_payment_delivery_refund_blocked_by_default",
            "automated_refund_execution_excluded",
        ):
            self.assertIn(blocker, payload["remaining_blockers"])
        for required in (
            "customer_artifact_access_approval",
            "provider_live_execution_approval",
            "stage8_live_pilot_approval",
            "stage9_payment_delivery_live_pilot_approval",
        ):
            self.assertIn(required, payload["required_approvals"])
        for required in (
            "customer_access_audit_ref",
            "download_auth_audit_ref",
            "provider_status_audit_ref",
            "operator_action_audit_ref",
        ):
            self.assertIn(required, payload["required_audits"])
        for required in (
            "review_customer_artifact_access_candidate",
            "record_operator_action_before_customer_download_unlock",
            "confirm_provider_status_readback",
            "confirm_scheduler_status_readback",
            "confirm_production_slo_incident_readback",
        ):
            self.assertIn(required, payload["required_operator_actions"])
        redlines = payload["redlines"]
        self.assertFalse(redlines["external_software_release_enabled"])
        self.assertFalse(redlines["customer_visible_publication_enabled"])
        self.assertFalse(redlines["provider_live_execution_enabled"])
        self.assertFalse(redlines["stage8_real_execution_enabled"])
        self.assertFalse(redlines["stage9_real_payment_delivery_refund_enabled"])
        self.assertFalse(redlines["real_payment_enabled"])
        self.assertFalse(redlines["real_delivery_enabled"])
        self.assertFalse(redlines["real_refund_enabled"])
        self.assertFalse(redlines["automated_refund_enabled"])
        self.assertFalse(redlines["real_alert_dispatch_enabled"])
        self.assertFalse(redlines["incident_automation_enabled"])
        self.assertFalse(redlines["destructive_restore_enabled"])
        self.assertFalse(redlines["rollback_execution_enabled"])
        self.assertFalse(redlines["active_storage_mutation_enabled"])


if __name__ == "__main__":
    unittest.main()
