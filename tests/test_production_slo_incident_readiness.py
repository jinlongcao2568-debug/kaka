from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from storage.db import DatabaseSession
from storage.production_slo_incident_readiness import (
    PRODUCTION_READINESS_FAIL_CLOSED,
    PRODUCTION_READINESS_MISSING,
    PRODUCTION_READINESS_READY,
    validate_production_slo_incident_readiness,
)
from storage.repositories.production_slo_incident_repo import ProductionSloIncidentRepository


class TestProductionSloIncidentReadiness(unittest.TestCase):
    def _settings(self, tmp_dir: str) -> Settings:
        return Settings(
            repo_root=str(ROOT),
            environment="INTERNAL_ONLY",
            storage_backend="json-file",
            storage_path_optional=str(Path(tmp_dir) / "production-slo.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )

    def _approved_drill_inputs(self) -> dict[str, object]:
        return {
            "approved_production_live_dependency_drill_requested": True,
            "approved_container_stack_drill_requested": True,
            "approved_alert_dispatch_drill_requested": True,
            "approved_backup_restore_drill_requested": True,
            "approved_rollback_drill_requested": True,
            "approved_incident_manual_execution_requested": True,
            "owner_approval_state": "APPROVED",
            "external_dependency_provider_approval_state": "APPROVED",
            "alert_dispatch_approval_state": "APPROVED",
            "restore_drill_approval_state": "APPROVED",
            "rollback_drill_approval_state": "APPROVED",
            "incident_owner_approval_state": "APPROVED",
            "operator_action_audit_refs": [
                "operator_action:approve-production-drill",
                "audit:production-drill-approval",
            ],
        }

    def test_production_slo_carrier_covers_alerts_runbook_drills_and_suspended_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = self._settings(tmp_dir)
            payload = settings.storage_bootstrap_payload()["production_slo_incident_readiness"]

        self.assertEqual(payload["target_capability_state"], PRODUCTION_READINESS_READY)
        self.assertTrue(payload["repository_backed_readback"])
        self.assertTrue(payload["replayable_readback"])
        slo = payload["slo_readiness_carrier"]
        objective_capabilities = {row["capability"] for row in slo["objectives"]}
        self.assertTrue(
            {
                "source_fetch",
                "parser",
                "verification",
                "rule_factory",
                "stage6_product_package",
                "stage8_outreach_pilot",
                "stage9_payment_delivery_pilot",
                "provider_reliability",
                "backup_restore",
                "rollback",
                "audit_replay",
            }.issubset(objective_capabilities)
        )

        dashboard = payload["monitoring_dashboard_readback"]
        self.assertEqual(dashboard["dashboard_state"], PRODUCTION_READINESS_READY)
        self.assertGreaterEqual(dashboard["panel_count"], 6)
        for panel in dashboard["panels"]:
            self.assertIn("latency_ms_p95_readback", panel)
            self.assertIn("error_rate_readback", panel)
            self.assertIn("throughput_per_minute_readback", panel)
            self.assertIn("failure_counter", panel)
            self.assertIn("suspension_state", panel)
            self.assertIn("owner_action_refs", panel)

        failure_families = {
            family
            for rule in payload["alert_rule_catalog"]
            for family in rule["failure_families"]
        }
        self.assertTrue(
            {
                "source",
                "provider",
                "outreach",
                "payment",
                "delivery",
                "backup_restore",
                "rollback",
            }.issubset(failure_families)
        )
        for evaluation in payload["simulated_alert_evaluation_readback"]:
            self.assertTrue(evaluation["alert_fired"])
            self.assertFalse(evaluation["notification_enabled"])
            self.assertFalse(evaluation["live_dispatch_enabled"])
            self.assertFalse(evaluation["real_alert_dispatch_enabled"])
            self.assertFalse(evaluation["external_paging_enabled"])
            self.assertFalse(evaluation["external_apm_enabled"])
            self.assertFalse(evaluation["incident_automation_enabled"])

        runbook = payload["incident_runbook_carrier"]
        self.assertEqual(runbook["runbook_state"], PRODUCTION_READINESS_READY)
        self.assertEqual(
            [step["step_id"] for step in runbook["runbook_steps"]],
            [
                "detection",
                "triage",
                "suspend",
                "rollback_dry_run",
                "restore_dry_run",
                "manual_owner_action",
                "resume_readiness",
                "post_incident_audit",
            ],
        )
        self.assertFalse(runbook["incident_automation_enabled"])

        backup_drill = payload["backup_restore_drill_evidence"]
        rollback_drill = payload["rollback_drill_evidence"]
        for drill in (backup_drill, rollback_drill):
            self.assertEqual(drill["drill_mode"], "DRY_RUN_ONLY")
            self.assertFalse(drill["destructive_restore_enabled"])
            self.assertFalse(drill["restore_execution_enabled"])
            self.assertFalse(drill["rollback_execution_enabled"])
            self.assertFalse(drill["active_storage_mutation_enabled"])
            self.assertFalse(drill["external_service_connection_enabled"])
            self.assertTrue(drill["audit_refs"])

        suspended = payload["suspended_state_operation_readback"]
        self.assertEqual(suspended["suspension_state"], "SUSPENDED")
        self.assertTrue(suspended["suspension_reason"])
        self.assertTrue(suspended["affected_capability"])
        self.assertTrue(suspended["owner_action_required"])
        self.assertTrue(suspended["manual_resume_required"])
        self.assertEqual(suspended["resume_readiness_state"], "MANUAL_REVIEW_REQUIRED")
        self.assertTrue(suspended["audit_refs"])
        self.assertTrue(suspended["fail_closed"])
        self.assertTrue(suspended["no_broad_fallback"])
        self.assertTrue(payload["validation"]["valid"])

    def test_repository_persists_readback_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = self._settings(tmp_dir)
            session = DatabaseSession(settings=settings)
            repo = ProductionSloIncidentRepository(session=session, settings=settings)
            record = repo.save_current()
            readback = repo.readback()
            replay = repo.replay()

        self.assertEqual(record.object_type, "production_slo_incident_readiness")
        self.assertEqual(readback["readback_state"], PRODUCTION_READINESS_READY)
        self.assertFalse(readback["fail_closed"])
        self.assertTrue(replay["replayable"])
        self.assertEqual(replay["replay_state"], PRODUCTION_READINESS_READY)
        self.assertFalse(replay["notification_enabled"])
        self.assertFalse(replay["live_dispatch_enabled"])
        self.assertFalse(replay["incident_automation_enabled"])
        self.assertFalse(replay["destructive_restore_enabled"])
        self.assertFalse(replay["rollback_execution_enabled"])

    def test_approved_production_live_dependency_drill_records_controlled_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = replace(
                self._settings(tmp_dir),
                production_live_dependency_drill_inputs=self._approved_drill_inputs(),
            )
            payload = settings.storage_bootstrap_payload()["production_slo_incident_readiness"]
            repo = ProductionSloIncidentRepository(
                session=DatabaseSession(settings=settings),
                settings=settings,
            )
            repo.save(payload)
            replay = repo.replay()

        carrier = payload["approved_production_live_dependency_drill"]
        self.assertTrue(carrier["approved_production_live_dependency_drill_enabled"])
        self.assertEqual(carrier["controlled_drill_state"], "APPROVED_CONTROLLED_DRILL_RECORDED")
        self.assertEqual(carrier["controlled_execution_scope"], "LOCAL_CONTROLLED_DRILL_READBACK")
        self.assertTrue(carrier["container_stack_drill_record"]["runbook_validation_recorded"])
        self.assertFalse(carrier["container_stack_drill_record"]["docker_compose_up_executed"])
        self.assertTrue(carrier["alert_dispatch_drill_record"]["controlled_dispatch_simulation_recorded"])
        self.assertFalse(carrier["alert_dispatch_drill_record"]["real_alert_dispatch_enabled"])
        self.assertTrue(carrier["backup_restore_drill_record"]["controlled_restore_dry_run_recorded"])
        self.assertFalse(carrier["backup_restore_drill_record"]["destructive_restore_enabled"])
        self.assertTrue(carrier["rollback_drill_record"]["controlled_rollback_dry_run_recorded"])
        self.assertFalse(carrier["rollback_drill_record"]["rollback_execution_enabled"])
        self.assertTrue(carrier["incident_manual_execution_record"]["manual_owner_action_recorded"])
        self.assertFalse(carrier["incident_manual_execution_record"]["incident_automation_enabled"])
        self.assertFalse(carrier["external_release_enabled"])
        self.assertFalse(carrier["provider_call_enabled"])
        self.assertFalse(carrier["real_provider_call_enabled"])
        self.assertFalse(carrier["automated_refund_enabled"])
        self.assertEqual(
            replay["approved_production_live_dependency_drill"]["controlled_drill_state"],
            "APPROVED_CONTROLLED_DRILL_RECORDED",
        )
        self.assertFalse(replay["real_alert_dispatch_enabled"])
        self.assertFalse(replay["destructive_restore_enabled"])
        self.assertFalse(replay["rollback_execution_enabled"])

    def test_approved_production_live_dependency_drill_fails_closed_without_audit(self) -> None:
        inputs = self._approved_drill_inputs()
        inputs["operator_action_audit_refs"] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = replace(
                self._settings(tmp_dir),
                production_live_dependency_drill_inputs=inputs,
            )
            payload = settings.storage_bootstrap_payload()["production_slo_incident_readiness"]

        carrier = payload["approved_production_live_dependency_drill"]
        self.assertFalse(carrier["approved_production_live_dependency_drill_enabled"])
        self.assertEqual(carrier["controlled_drill_state"], "BLOCKED")
        self.assertIn("operator_action_audit_refs_missing", carrier["blocked_reasons"])
        self.assertFalse(carrier["container_stack_drill_record"]["docker_compose_up_executed"])
        self.assertFalse(carrier["alert_dispatch_drill_record"]["real_alert_dispatch_enabled"])
        self.assertFalse(carrier["backup_restore_drill_record"]["destructive_restore_enabled"])
        self.assertFalse(carrier["rollback_drill_record"]["rollback_execution_enabled"])
        self.assertFalse(carrier["incident_manual_execution_record"]["incident_automation_enabled"])

    def test_stale_alert_or_missing_suspended_refs_fail_closed_without_broad_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = self._settings(tmp_dir)
            repo = ProductionSloIncidentRepository(
                session=DatabaseSession(settings=settings),
                settings=settings,
            )
            payload = repo.build_current_payload()
            repo.save(payload)
            good_replay = repo.replay()

            stale_payload = copy.deepcopy(payload)
            stale_payload["simulated_alert_evaluation_readback"][0][
                "alert_rule_id"
            ] = "missing.alert.rule"
            stale_payload["suspended_state_operation_readback"]["audit_refs"] = []
            repo.save(stale_payload)
            stale_replay = repo.replay()

        self.assertEqual(good_replay["readback_state"], PRODUCTION_READINESS_READY)
        self.assertTrue(good_replay["replayable"])
        self.assertEqual(stale_replay["readback_state"], PRODUCTION_READINESS_FAIL_CLOSED)
        self.assertFalse(stale_replay["replayable"])
        self.assertTrue(stale_replay["fail_closed"])
        self.assertTrue(stale_replay["no_broad_fallback"])
        self.assertIn(
            "missing.alert.rule",
            {
                ref.get("missing_alert_rule_id")
                for ref in stale_replay["validation"]["stale_or_missing_refs"]
            },
        )

    def test_missing_repository_record_returns_fail_closed_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = self._settings(tmp_dir)
            repo = ProductionSloIncidentRepository(
                session=DatabaseSession(settings=settings),
                settings=settings,
            )
            replay = repo.replay("MISSING-PRODUCTION-SLO")

        self.assertEqual(replay["readback_state"], PRODUCTION_READINESS_MISSING)
        self.assertFalse(replay["payload_present"])
        self.assertTrue(replay["fail_closed"])
        self.assertTrue(replay["no_broad_fallback"])
        self.assertFalse(replay["real_alert_dispatch_enabled"])
        self.assertFalse(replay["destructive_restore_enabled"])
        self.assertFalse(replay["rollback_execution_enabled"])

    def test_real_alert_automation_restore_and_rollback_flags_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = self._settings(tmp_dir)
            repo = ProductionSloIncidentRepository(
                session=DatabaseSession(settings=settings),
                settings=settings,
            )
            payload = repo.build_current_payload()
            live_payload = copy.deepcopy(payload)
            live_payload["alert_rule_catalog"][0]["notification_enabled"] = True
            restore_payload = copy.deepcopy(payload)
            restore_payload["backup_restore_drill_evidence"]["destructive_restore_enabled"] = True
            rollback_payload = copy.deepcopy(payload)
            rollback_payload["rollback_drill_evidence"]["rollback_execution_enabled"] = True

            with self.assertRaisesRegex(ValueError, "must remain false"):
                repo.save(live_payload)
            with self.assertRaisesRegex(ValueError, "must remain false"):
                repo.save(restore_payload)
            with self.assertRaisesRegex(ValueError, "must remain false"):
                repo.save(rollback_payload)

        self.assertFalse(validate_production_slo_incident_readiness(payload)["fail_closed"])

    def test_provider_suspended_signal_is_read_back_without_dispatch_or_live_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_PROVIDER_ADAPTER_CIRCUIT_OPEN": "true",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                settings = Settings.from_env(repo_root=str(ROOT), environment="INTERNAL_ONLY")
                payload = settings.storage_bootstrap_payload()["production_slo_incident_readiness"]

        suspended = payload["suspended_state_operation_readback"]
        provider_eval = next(
            evaluation
            for evaluation in payload["simulated_alert_evaluation_readback"]
            if evaluation["failure_families"] == ["provider"]
        )
        self.assertTrue(provider_eval["alert_fired"])
        self.assertTrue(suspended["provider_adapter_suspended"])
        self.assertEqual(suspended["provider_circuit_breaker_state"], "OPEN")
        self.assertFalse(provider_eval["real_alert_dispatch_enabled"])
        self.assertFalse(suspended["provider_call_enabled"])
        self.assertFalse(suspended["real_provider_call_enabled"])


if __name__ == "__main__":
    unittest.main()
