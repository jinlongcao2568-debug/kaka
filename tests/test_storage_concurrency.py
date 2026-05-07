from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from storage.db import (
    DatabaseSession,
    PersistedOperatorAction,
    PersistedRecord,
    PersistedStageState,
    PersistedWorkItem,
    build_persisted_at,
)
from storage.production_infra_readiness import (
    is_postgresql_database_url,
    storage_database_url_dialect,
    storage_database_url_driver,
)
from storage.sqlalchemy_backend import SQLAlchemyStorageBackend
from storage.repositories import (
    MonitoringAlertingRepository,
    ProductionSloIncidentRepository,
    WorkerQueueRepository,
)
from storage.repositories.backup_restore_repo import BackupRestoreRepository
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.object_storage import OBJECT_STORAGE_OBJECT_TYPE, ObjectStorageMissingError
from storage.backup_restore import compute_manifest_hash
from storage.json_storage_migration import (
    MIGRATION_MANIFEST_OBJECT_TYPE,
    migrate_json_storage_to_database,
)
from storage.object_storage_inventory import (
    OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE,
    REFERENCED_BY_RECORD,
    UNREFERENCED_LEGACY_OBJECT,
    build_object_storage_inventory,
)
from shared.settings import Settings


STORAGE_ENV_KEYS = (
    "KAKA_STORAGE_BACKEND",
    "KAKA_STORAGE_PATH",
    "KAKA_STORAGE_DATABASE_URL",
    "KAKA_STORAGE_SCOPE",
    "KAKA_STORAGE_TEST_ISOLATION",
    "KAKA_OBJECT_STORAGE_BACKEND",
    "KAKA_OBJECT_STORAGE_PATH",
)
RESERVED_INFRA_BACKENDS = {
    "alembic",
    "redis",
    "dramatiq",
    "minio",
    "s3",
    "docker-compose",
}
RESERVED_OR_NOT_CONFIGURED = {"RESERVED_NOT_LIVE", "NOT_CONFIGURED"}
LOCAL_STACK_FILES = (".dockerignore", "Dockerfile", "docker-compose.yml")
FORBIDDEN_REAL_SECRET_MARKERS = (
    "akia",
    "sk_live",
    "pk_live",
    "xoxb-",
    "aws_secret_access_key=",
    "stripe_live",
    "production_secret",
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.cmd_opts = argparse.Namespace(x=[f"database_url={database_url}"])
    return config


def build_envelope_entries(now: str) -> tuple[
    PersistedRecord,
    PersistedStageState,
    PersistedWorkItem,
    PersistedOperatorAction,
]:
    record = PersistedRecord(
        object_type="test_record",
        record_id="REC-1",
        stage_scope=8,
        project_id="P-1",
        object_refs={"project_id": "P-1"},
        decision_states={"policy_decision_state": "ALLOW"},
        trace_refs={"trace_id": "TRACE-1"},
        audit_refs={"audit_id": "AUDIT-1"},
        governed_state={"primary_status": "READY"},
        writeback_state={"writeback_targets": ["test_record"]},
        payload={"record_id": "REC-1", "project_id": "P-1", "status": "READY"},
        persisted_at=now,
    )
    stage_state = PersistedStageState(
        stage_scope=8,
        project_id="P-1",
        surface_id="outreach_workbench",
        root_object_type="test_record",
        root_record_id="REC-1",
        inputs={"project_id": "P-1", "record_id": "REC-1"},
        persisted_at=now,
        typed_object_refs={"record_id": "REC-1"},
    )
    work_item = PersistedWorkItem(
        work_item_id="WI-1",
        work_item_key="8:outreach_workbench:test_record:REC-1",
        stage_scope=8,
        project_id="P-1",
        surface_id="outreach_workbench",
        primary_object_type="test_record",
        primary_record_id="REC-1",
        assignment_profile_id="single_operator",
        assignment_lifecycle_state="assigned",
        object_refs={"record_id": "REC-1"},
        surface_operational_state="draft_only",
        current_operational_state="ready_for_internal_operator_action",
        assigned_owner_role="sales_user",
        assigned_owner="operator",
        reviewer_role="delivery_governance_user",
        reviewer="reviewer",
        assignment_resolved_from="test",
        assignment_simplified_boundary=["internal_only"],
        pending_actions=["stage8_mark_ready"],
        pending_button_flows=[{"action_id": "stage8_mark_ready"}],
        last_action_id=None,
        last_action_state=None,
        last_action_at=None,
        trace_refs={"trace_id": "TRACE-1"},
        audit_refs={"audit_id": "AUDIT-1"},
        decision_states={"policy_decision_state": "ALLOW"},
        governed_context={"approval_state": "PENDING_APPROVAL"},
        created_at=now,
        updated_at=now,
    )
    action = PersistedOperatorAction(
        action_event_id="ACT-1",
        work_item_id="WI-1",
        stage_scope=8,
        action_id="stage8_mark_ready",
        button_flow_id="submit_stage8_mark_ready",
        action_state="action_completed",
        resulting_assignment_lifecycle_state="completed",
        requested_by_role="sales_user",
        requested_by="operator",
        assigned_owner_role="sales_user",
        assigned_owner="operator",
        reviewer_role="delivery_governance_user",
        reviewer="reviewer",
        reason="sqlalchemy reload coverage",
        object_refs={"record_id": "REC-1"},
        trace_refs={"trace_id": "TRACE-1"},
        audit_refs={"audit_id": "AUDIT-1"},
        requested_at=now,
        completed_at=now,
    )
    return record, stage_state, work_item, action


class TestStorageConcurrency(unittest.TestCase):
    def _write_content_addressed_object(self, root: Path, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        object_key = f"objects/{digest[:2]}/{digest}"
        path = root / "objects" / digest[:2] / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return object_key

    def _docx_bytes(self) -> bytes:
        archive_path = Path(tempfile.gettempdir()) / f"kaka-docx-fixture-{os.getpid()}.docx"
        try:
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<w:document/>")
            return archive_path.read_bytes()
        finally:
            archive_path.unlink(missing_ok=True)

    def test_postgresql_psycopg_url_is_recognized_without_silent_fallback(self) -> None:
        database_url = "postgresql+psycopg://kaka_local:placeholder@example.invalid:5432/kaka_local"

        self.assertTrue(is_postgresql_database_url(database_url))
        self.assertEqual(storage_database_url_dialect(database_url), "postgresql")
        self.assertEqual(storage_database_url_driver(database_url), "psycopg")

    def test_postgresql_readiness_uses_configured_database_url_and_driver(self) -> None:
        if find_spec("psycopg") is not None:
            driver = "psycopg"
        elif find_spec("psycopg2") is not None:
            driver = "psycopg2"
        else:
            self.skipTest("no PostgreSQL SQLAlchemy driver installed")
        database_url = f"postgresql+{driver}://kaka_local:placeholder@example.invalid:5432/kaka_local"
        settings = Settings(
            storage_backend="postgresql",
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )

        readiness = settings.storage_bootstrap_payload()["platform_infra_readiness"]

        self.assertEqual(readiness["active_backend"], "postgresql")
        self.assertTrue(readiness["storage_database_url_configured"])
        self.assertEqual(readiness["storage_database_url_dialect"], "postgresql")
        self.assertEqual(readiness["postgresql_readiness"]["database_url_driver"], driver)
        self.assertEqual(readiness["postgresql_readiness"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["postgresql_readiness"]["executable"])
        self.assertTrue(readiness["postgresql_readiness"]["migration_required"])
        self.assertTrue(readiness["migration_readiness"]["database_url_configured"])
        self.assertTrue(readiness["migration_readiness"]["manual_migration_cli_available"])
        self.assertFalse(readiness["migration_readiness"]["app_bootstrap_auto_migration_enabled"])

    def test_default_storage_path_is_stable_without_process_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir}, clear=False):
                for key in STORAGE_ENV_KEYS:
                    os.environ.pop(key, None)

                settings = Settings.from_env()
                settings_path = settings.resolved_storage_path()
                settings_object_path = settings.resolved_object_storage_path()
                path = DatabaseSession.default_storage_path()

        self.assertEqual(path, Path(tmp_dir) / "kaka" / "internal_operator_loop_store.json")
        self.assertEqual(path.name, "internal_operator_loop_store.json")
        self.assertNotIn(str(os.getpid()), path.name)
        self.assertEqual(settings.storage_backend, "json-file")
        self.assertIsNone(settings.storage_path_optional)
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
        self.assertEqual(settings.object_storage_backend, "local-filesystem")
        self.assertEqual(
            settings_object_path,
            Path(tmp_dir) / "kaka" / "object-storage",
        )
        self.assertEqual(path, settings_path)

    def test_settings_from_env_consumes_storage_backend_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "postgres",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)

                settings = Settings.from_env()

        self.assertEqual(settings.storage_backend, "postgres")
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
        readiness = settings.storage_bootstrap_payload()["platform_infra_readiness"]
        self.assertEqual(readiness["active_backend"], "postgresql")
        self.assertEqual(readiness["postgresql_readiness"]["readiness_state"], "CONFIG_REQUIRED")
        self.assertTrue(readiness["postgresql_readiness"]["configured"])
        self.assertFalse(readiness["postgresql_readiness"]["executable"])
        self.assertFalse(readiness["postgresql_readiness"]["database_url_configured"])
        self.assertEqual(readiness["sqlalchemy_readiness"]["readiness_state"], "NOT_CONFIGURED")
        executable_backend_names = [
            entry["backend"]
            for entry in readiness["executable_backends"]
            if entry["executable"]
        ]
        self.assertEqual(executable_backend_names, ["json-file", "sqlite"])

    def test_database_session_default_fast_fails_postgres_without_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="postgres",
                storage_path_optional=str(Path(tmp_dir) / "store.json"),
                storage_database_url_optional=None,
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )

            with self.assertRaisesRegex(ValueError, "KAKA_STORAGE_DATABASE_URL"):
                DatabaseSession.default_storage_path(settings=settings)
            with self.assertRaisesRegex(ValueError, "KAKA_STORAGE_DATABASE_URL"):
                DatabaseSession.default(settings=settings, reload_from_disk=True)

    def test_database_session_default_fast_fails_unsupported_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="unsupported-backend",
                storage_path_optional=str(Path(tmp_dir) / "store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )

            with self.assertRaisesRegex(ValueError, "unsupported storage backend"):
                DatabaseSession.default_storage_path(settings=settings)
            with self.assertRaisesRegex(ValueError, "unsupported storage backend"):
                DatabaseSession.default(settings=settings, reload_from_disk=True)

    def test_storage_bootstrap_payload_projects_reserved_platform_infra_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )

            payload = settings.storage_bootstrap_payload()

        self.assertEqual(payload["storage_backend"], "json-file")
        self.assertFalse(payload["storage_database_url_configured"])
        self.assertIsNone(payload["storage_database_url_redacted"])
        self.assertEqual(payload["storage_scope"], "shared")
        self.assertEqual(payload["storage_runtime_mode"], "explicit-path")
        self.assertEqual(payload["queue_backend"], "storage")
        self.assertEqual(payload["worker_runtime"], "internal-storage-worker")
        self.assertTrue(payload["worker_queue_bootstrap"]["durable_queue_enabled"])
        self.assertTrue(payload["worker_queue_bootstrap"]["worker_lease_enabled"])
        self.assertFalse(payload["worker_queue_bootstrap"]["external_queue_connection_enabled"])
        self.assertIn("monitoring_alerting_readiness", payload)
        self.assertIn("monitoring_readiness", payload)
        self.assertIn("alert_rule_catalog", payload)
        self.assertIn("alert_readiness", payload)
        self.assertIn("incident_readiness", payload)
        self.assertIn("production_slo_incident_readiness", payload)
        self.assertIn("production_slo_readiness", payload)
        self.assertIn("production_monitoring_dashboard", payload)
        self.assertIn("production_alert_rule_catalog", payload)
        self.assertIn("simulated_alert_evaluation_readback", payload)
        self.assertIn("production_incident_runbook", payload)
        self.assertIn("production_drill_evidence", payload)
        self.assertIn("suspended_state_operation_readback", payload)
        self.assertIn("platform_infra_readiness", payload)

        readiness = payload["platform_infra_readiness"]
        self.assertEqual(readiness["active_backend"], "json-file")
        executable_backends = readiness["executable_backends"]
        self.assertEqual(
            [entry["backend"] for entry in executable_backends],
            ["json-file", "sqlite", "sqlalchemy", "postgresql"],
        )
        self.assertEqual(
            [entry["backend"] for entry in executable_backends if entry["executable"]],
            ["json-file", "sqlite"],
        )
        self.assertEqual(executable_backends[0]["readiness_state"], "EXECUTABLE")
        self.assertTrue(executable_backends[0]["configured"])
        self.assertEqual(executable_backends[1]["readiness_state"], "EXECUTABLE")
        self.assertFalse(executable_backends[1]["configured"])
        self.assertEqual(executable_backends[2]["readiness_state"], "NOT_CONFIGURED")
        self.assertFalse(executable_backends[2]["configured"])
        self.assertFalse(executable_backends[2]["database_url_configured"])
        self.assertEqual(executable_backends[3]["readiness_state"], "NOT_CONFIGURED")
        self.assertFalse(executable_backends[3]["configured"])
        self.assertFalse(executable_backends[3]["database_url_configured"])

        reserved_by_backend = {
            entry["backend"]: entry
            for entry in readiness["reserved_backends"]
        }
        self.assertEqual(set(reserved_by_backend), RESERVED_INFRA_BACKENDS)
        for backend, entry in reserved_by_backend.items():
            self.assertFalse(entry["executable"], backend)
            self.assertIn(entry["readiness_state"], RESERVED_OR_NOT_CONFIGURED, backend)
            self.assertIn("why_not_live", entry)

        self.assertEqual(readiness["postgresql_readiness"]["readiness_state"], "NOT_CONFIGURED")
        self.assertFalse(readiness["postgresql_readiness"]["executable"])
        self.assertFalse(readiness["postgresql_readiness"]["configured"])
        self.assertEqual(readiness["sqlalchemy_readiness"]["readiness_state"], "NOT_CONFIGURED")
        self.assertFalse(readiness["sqlalchemy_readiness"]["executable"])
        self.assertFalse(readiness["sqlalchemy_readiness"]["configured"])
        self.assertFalse(readiness["sqlalchemy_readiness"]["database_url_configured"])
        self.assertEqual(readiness["migration_readiness"]["readiness_state"], "CLI_AVAILABLE")
        self.assertTrue(readiness["migration_readiness"]["manual_migration_cli_available"])
        self.assertFalse(readiness["migration_readiness"]["app_bootstrap_auto_migration_enabled"])
        self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
        self.assertIn(readiness["queue_readiness"]["readiness_state"], RESERVED_OR_NOT_CONFIGURED)
        self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["queue_readiness"]["internal_durable_queue"]["repository_backed"])
        self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
        self.assertEqual(readiness["worker_runtime_readiness"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["worker_runtime_readiness"]["lease_persistence_enabled"])
        self.assertTrue(readiness["worker_runtime_readiness"]["retry_persistence_enabled"])
        self.assertTrue(readiness["worker_runtime_readiness"]["suspend_resume_persistence_enabled"])
        self.assertFalse(readiness["worker_runtime_readiness"]["stage1_scheduler_enabled"])
        self.assertTrue(readiness["worker_queue_bootstrap"]["audit_replay_enabled"])
        self.assertEqual(readiness["object_storage_readiness"]["active_backend"], "local-filesystem")
        self.assertEqual(readiness["object_storage_readiness"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["object_storage_readiness"]["local_filesystem"]["executable"])
        self.assertTrue(
            readiness["object_storage_readiness"]["snapshot_durability"][
                "manifest_repository_backed"
            ]
        )
        self.assertTrue(
            readiness["object_storage_readiness"]["snapshot_durability"][
                "readback_replay_enabled"
            ]
        )
        self.assertFalse(readiness["object_storage_readiness"]["connection_enabled"])
        self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
        self.assertEqual(readiness["compose_readiness"]["readiness_state"], "CONFIG_PRESENT_NOT_EXECUTED")
        self.assertTrue(readiness["compose_readiness"]["dockerfile_present"])
        self.assertTrue(readiness["compose_readiness"]["compose_file_present"])
        self.assertTrue(readiness["compose_readiness"]["dockerignore_present"])
        self.assertTrue(readiness["compose_readiness"]["docker_compose_config_present"])
        self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
        self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
        self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
        self.assertFalse(readiness["compose_readiness"]["external_service_connection_enabled"])
        self.assertFalse(readiness["compose_readiness"]["real_provider_execution_enabled"])
        self.assertFalse(readiness["compose_readiness"]["real_payment_delivery_enabled"])
        self.assertFalse(readiness["compose_readiness"]["automated_refund_enabled"])
        service_summary = readiness["compose_readiness"]["service_dependency_summary"]
        self.assertEqual(set(service_summary), {"app", "app-postgres", "postgres", "redis", "minio"})
        self.assertTrue(service_summary["app-postgres"]["migration_required_before_bootstrap"])
        self.assertFalse(service_summary["app-postgres"]["external_service_connection_enabled"])
        self.assertFalse(service_summary["app-postgres"]["container_execution_enabled"])
        for reserved_service in ("postgres", "redis", "minio"):
            self.assertEqual(service_summary[reserved_service]["readiness_state"], "RESERVED_NOT_LIVE")
            self.assertFalse(service_summary[reserved_service]["external_service_connection_enabled"])
            self.assertFalse(service_summary[reserved_service]["container_execution_enabled"])

        policy = readiness["backend_policy"]
        self.assertTrue(policy["unsupported_backend_fast_fail"])
        self.assertTrue(policy["missing_database_url_fast_fail"])
        self.assertTrue(policy["no_silent_fallback"])
        self.assertTrue(policy["no_migration_execution"])
        self.assertTrue(policy["no_external_service_connection"])
        self.assertTrue(policy["readback_only"])
        self.assertFalse(policy["runtime_behavior_changed"])
        monitoring = readiness["monitoring_readiness"]
        self.assertEqual(monitoring["readiness_state"], "INTERNAL_READBACK_READY")
        self.assertTrue(monitoring["replayable_readback"])
        self.assertIn("storage.backend", monitoring["component_ids"])
        self.assertIn("queue.worker", monitoring["component_ids"])
        self.assertIn("object_storage.local_snapshot", monitoring["component_ids"])
        self.assertIn("backup_restore.local_manifest", monitoring["component_ids"])
        self.assertIn("local_stack.compose_definition", monitoring["component_ids"])
        self.assertIn("provider.controlled_opening_requirement", monitoring["component_ids"])
        for component in readiness["monitoring_alerting_readiness"]["monitoring_components"]:
            self.assertIn("component_id", component)
            self.assertIn("component_family", component)
            self.assertIn("readiness_state", component)
            self.assertIn("health_state", component)
            self.assertIn("signal_sources", component)
            self.assertIn("last_observed_at_optional", component)
            self.assertIn("degraded_reasons", component)
            self.assertIn("blocking_reasons", component)
            self.assertIn("audit_refs", component)
            self.assertTrue(component["replayable_readback"])
        alert_readiness = readiness["alert_readiness"]
        self.assertEqual(alert_readiness["readiness_state"], "CATALOG_READY_READBACK_ONLY")
        self.assertFalse(alert_readiness["notification_enabled"])
        self.assertFalse(alert_readiness["live_dispatch_enabled"])
        self.assertFalse(alert_readiness["external_observability_provider_enabled"])
        self.assertTrue(alert_readiness["approval_required"])
        self.assertTrue(alert_readiness["audit_required"])
        self.assertGreaterEqual(len(readiness["alert_rule_catalog"]), 6)
        for rule in readiness["alert_rule_catalog"]:
            self.assertIn("alert_rule_id", rule)
            self.assertIn("severity", rule)
            self.assertIn("threshold_summary", rule)
            self.assertIn("owner_role", rule)
            self.assertFalse(rule["notification_enabled"])
            self.assertFalse(rule["live_dispatch_enabled"])
            self.assertIn("suppression_state", rule)
            self.assertIn("suspended_state", rule)
            self.assertTrue(rule["approval_required"])
            self.assertTrue(rule["audit_required"])
        incident = readiness["incident_readiness"]
        self.assertEqual(incident["incident_state"], "MANUAL_OWNER_ACTION_READY")
        self.assertTrue(incident["runbook_refs"])
        self.assertTrue(incident["rollback_refs"])
        self.assertTrue(incident["backup_refs"])
        self.assertTrue(incident["manual_owner_action_required"])
        self.assertFalse(incident["incident_automation_enabled"])
        self.assertFalse(incident["external_paging_enabled"])
        controlled_opening_requirements = readiness["controlled_opening_requirements"]
        self.assertTrue(controlled_opening_requirements["no_live_provider_call"])
        self.assertTrue(controlled_opening_requirements["no_real_payment"])
        self.assertTrue(controlled_opening_requirements["no_real_delivery"])
        self.assertTrue(controlled_opening_requirements["no_real_refund"])
        self.assertTrue(controlled_opening_requirements["no_automated_refund"])
        self.assertFalse(controlled_opening_requirements["compose_runtime_enabled"])
        self.assertFalse(controlled_opening_requirements["container_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["docker_compose_up_executed"])
        self.assertFalse(controlled_opening_requirements["real_provider_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["real_payment_delivery_enabled"])
        self.assertFalse(controlled_opening_requirements["external_observability_provider_enabled"])
        self.assertFalse(controlled_opening_requirements["external_apm_enabled"])
        self.assertFalse(controlled_opening_requirements["external_paging_enabled"])
        self.assertFalse(controlled_opening_requirements["notification_enabled"])
        self.assertFalse(controlled_opening_requirements["live_alert_dispatch_enabled"])
        self.assertFalse(controlled_opening_requirements["real_alert_dispatch_enabled"])
        self.assertFalse(controlled_opening_requirements["incident_automation_enabled"])
        self.assertFalse(controlled_opening_requirements["active_storage_mutation_enabled"])
        self.assertFalse(controlled_opening_requirements["automated_refund_enabled"])
        self.assertFalse(controlled_opening_requirements["external_software_release_enabled"])
        production = readiness["production_slo_incident_readiness"]
        self.assertEqual(production["target_capability_state"], "PRODUCTION_READY")
        self.assertTrue(production["repository_backed_readback"])
        self.assertTrue(production["validation"]["valid"])
        self.assertTrue(
            all(
                evaluation["alert_fired"]
                for evaluation in production["simulated_alert_evaluation_readback"]
            )
        )
        self.assertFalse(production["controlled_opening_requirements"]["real_alert_dispatch_enabled"])
        self.assertFalse(production["controlled_opening_requirements"]["incident_automation_enabled"])
        self.assertFalse(production["controlled_opening_requirements"]["destructive_restore_enabled"])
        self.assertFalse(production["controlled_opening_requirements"]["rollback_execution_enabled"])

    def test_monitoring_alerting_repository_persists_readback_and_replay_with_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "monitoring-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            repo = MonitoringAlertingRepository(session=session, settings=settings)

            record = repo.save_current()
            readback = repo.readback()
            replay = repo.replay()

        self.assertEqual(record.object_type, "monitoring_alerting_readiness")
        self.assertEqual(readback["readback_state"], "READBACK_READY")
        self.assertTrue(readback["payload_present"])
        self.assertFalse(readback["fail_closed"])
        self.assertTrue(replay["replayable"])
        self.assertEqual(replay["replay_state"], "READBACK_READY")
        self.assertTrue(replay["monitoring_readiness"]["replayable_readback"])
        self.assertFalse(replay["alert_readiness"]["notification_enabled"])
        self.assertFalse(replay["alert_readiness"]["live_dispatch_enabled"])
        self.assertTrue(replay["incident_readiness"]["manual_owner_action_required"])
        self.assertFalse(replay["incident_readiness"]["incident_automation_enabled"])
        self.assertFalse(replay["incident_readiness"]["external_paging_enabled"])

    def test_production_slo_incident_repository_persists_readback_and_replay_with_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "production-slo-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            repo = ProductionSloIncidentRepository(session=session, settings=settings)

            record = repo.save_current()
            readback = repo.readback()
            replay = repo.replay()

        self.assertEqual(record.object_type, "production_slo_incident_readiness")
        self.assertEqual(readback["readback_state"], "PRODUCTION_READY")
        self.assertTrue(readback["payload_present"])
        self.assertFalse(readback["fail_closed"])
        self.assertTrue(replay["replayable"])
        self.assertEqual(replay["replay_state"], "PRODUCTION_READY")
        self.assertTrue(replay["slo_readiness_carrier"]["repository_backed_readback"])
        self.assertTrue(
            all(
                evaluation["alert_fired"]
                for evaluation in replay["simulated_alert_evaluation_readback"]
            )
        )
        self.assertFalse(replay["real_alert_dispatch_enabled"])
        self.assertFalse(replay["incident_automation_enabled"])
        self.assertFalse(replay["destructive_restore_enabled"])
        self.assertFalse(replay["rollback_execution_enabled"])

    def test_local_stack_definition_files_exist_without_real_secret_material(self) -> None:
        for relative_path in LOCAL_STACK_FILES:
            path = ROOT / relative_path
            self.assertTrue(path.exists(), relative_path)
            content = path.read_text(encoding="utf-8").lower()
            for marker in FORBIDDEN_REAL_SECRET_MARKERS:
                self.assertNotIn(marker, content, relative_path)

        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("requirements.txt", dockerfile)
        self.assertIn("-r /app/requirements.txt", dockerfile)

        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for ignored_path in (".git", "__pycache__/", ".pytest_cache/", "object-storage/", "minio-data/"):
            self.assertIn(ignored_path, dockerignore)

        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("reserved-local-deps", compose)
        self.assertIn("local-postgres", compose)
        self.assertIn("app-postgres", compose)
        self.assertIn("postgresql+psycopg://kaka_local:local_dev_placeholder_not_secret@postgres:5432/kaka_local", compose)
        self.assertIn("local_dev_placeholder_not_secret", compose)
        self.assertIn("compose_runtime_enabled: false", compose)
        self.assertIn("container_execution_enabled: false", compose)
        self.assertIn("docker_compose_up_executed: false", compose)

    def test_alembic_initial_migration_creates_storage_envelope_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "storage-migration.sqlite"
            command.upgrade(alembic_config(sqlalchemy_sqlite_url(database_path)), "head")
            connection = sqlite3.connect(database_path)
            try:
                rows = connection.execute("select name from sqlite_master where type='table'").fetchall()
            finally:
                connection.close()

        tables = {row[0] for row in rows}
        self.assertTrue(set(SQLAlchemyStorageBackend.required_table_names()).issubset(tables))
        self.assertIn("alembic_version", tables)

    def test_sqlalchemy_backend_requires_migrated_schema_for_non_sqlite_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "schema-validation.sqlite"
            database_url = sqlalchemy_sqlite_url(database_path)
            engine = create_engine(database_url, future=True)
            try:
                with self.assertRaisesRegex(RuntimeError, r"run scripts\\run-storage-migrations\.ps1"):
                    SQLAlchemyStorageBackend.validate_required_schema(
                        engine,
                        storage_backend="postgresql",
                    )
            finally:
                engine.dispose()

            command.upgrade(alembic_config(database_url), "head")
            migrated_engine = create_engine(database_url, future=True)
            try:
                SQLAlchemyStorageBackend.validate_required_schema(
                    migrated_engine,
                    storage_backend="postgresql",
                )
            finally:
                migrated_engine.dispose()

    @unittest.skipUnless(
        os.getenv("KAKA_TEST_POSTGRES_DATABASE_URL"),
        "set KAKA_TEST_POSTGRES_DATABASE_URL to run the PostgreSQL migration integration test",
    )
    def test_optional_postgres_migration_and_repository_roundtrip(self) -> None:
        database_url = os.environ["KAKA_TEST_POSTGRES_DATABASE_URL"]
        command.upgrade(alembic_config(database_url), "head")
        settings = Settings(
            storage_backend="postgresql",
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
        )
        session = DatabaseSession(settings=settings)
        now = build_persisted_at()
        record, _, _, _ = build_envelope_entries(now)
        record = replace(
            record,
            record_id="REC-POSTGRES-INTEGRATION",
            payload={"record_id": "REC-POSTGRES-INTEGRATION", "project_id": "P-POSTGRES", "status": "READY"},
        )
        try:
            session.upsert_record(record)
            loaded = session.get_record("test_record", "REC-POSTGRES-INTEGRATION")
        finally:
            session.close()

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.payload["record_id"], "REC-POSTGRES-INTEGRATION")

    def test_object_storage_readiness_keeps_minio_s3_reserved_not_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_backend="minio",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )

            readiness = settings.storage_bootstrap_payload()["platform_infra_readiness"]

        object_readiness = readiness["object_storage_readiness"]
        self.assertEqual(object_readiness["active_backend"], "minio")
        self.assertEqual(object_readiness["readiness_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(object_readiness["executable"])
        self.assertFalse(object_readiness["connection_enabled"])
        self.assertFalse(object_readiness["external_service_connection_enabled"])
        self.assertFalse(object_readiness["minio_connection_enabled"])
        self.assertFalse(object_readiness["s3_connection_enabled"])
        reserved_by_backend = {
            entry["backend"]: entry
            for entry in readiness["reserved_backends"]
        }
        self.assertEqual(reserved_by_backend["minio"]["readiness_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(reserved_by_backend["minio"]["executable"])

    def test_storage_backend_sqlite_env_opt_in_creates_sqlite_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "sqlite",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                settings = Settings.from_env()
                session = DatabaseSession.default(settings=settings, reload_from_disk=True)
                try:
                    readiness = settings.storage_bootstrap_payload()["platform_infra_readiness"]

                    self.assertEqual(settings.storage_backend, "sqlite")
                    self.assertEqual(session.storage_backend, "sqlite")
                    self.assertEqual(session.storage_path, explicit_path.with_suffix(".sqlite"))
                    self.assertTrue(session.storage_path.exists())
                    self.assertEqual(readiness["active_backend"], "sqlite")
                    executable_by_backend = {
                        entry["backend"]: entry
                        for entry in readiness["executable_backends"]
                    }
                    self.assertEqual(set(executable_by_backend), {"json-file", "sqlite", "sqlalchemy", "postgresql"})
                    self.assertTrue(executable_by_backend["json-file"]["executable"])
                    self.assertFalse(executable_by_backend["json-file"]["configured"])
                    self.assertTrue(executable_by_backend["sqlite"]["executable"])
                    self.assertTrue(executable_by_backend["sqlite"]["configured"])
                    self.assertEqual(
                        readiness["object_storage_readiness"]["readiness_state"],
                        "EXECUTABLE",
                    )
                    self.assertTrue(
                        readiness["object_storage_readiness"]["snapshot_durability"][
                            "readback_replay_enabled"
                        ]
                    )
                finally:
                    session.close()

    def test_local_object_storage_persists_snapshot_manifest_with_json_file_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "object-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )
            repo = ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)
            data = b"public notice bytes"

            manifest = repo.save_snapshot(
                data,
                snapshot_id="SNAP-JSON-1",
                snapshot_kind="evidence_snapshot",
                content_type="text/plain",
                source_url_optional="https://example.invalid/notice/1",
                source_family_optional="public_notice",
                lineage_refs={
                    "project_id": "P-1",
                    "source_trace_id": "TRACE-1",
                    "audit_ref": "AUDIT-1",
                },
                created_at="2026-04-25T00:00:00+00:00",
            )
            replay = repo.replay_snapshot("SNAP-JSON-1")

            self.assertEqual(repo.read_snapshot_bytes("SNAP-JSON-1"), data)
            self.assertEqual(replay["bytes"], data)
            self.assertEqual(manifest.snapshot_id, "SNAP-JSON-1")
            self.assertEqual(manifest.snapshot_kind, "evidence_snapshot")
            self.assertEqual(manifest.content_type, "text/plain")
            self.assertEqual(manifest.byte_size, len(data))
            self.assertEqual(len(manifest.sha256), 64)
            self.assertEqual(replay["object_key"], manifest.object_key)
            self.assertEqual(replay["lineage_refs"]["project_id"], "P-1")
            self.assertTrue(manifest.replay_metadata["sha256_verified"])
            self.assertTrue(manifest.replay_metadata["byte_size_verified"])
            self.assertTrue((Path(tmp_dir) / "objects" / manifest.object_key).exists())

    def test_local_object_storage_persists_manifest_with_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="sqlite",
                storage_path_optional=str(Path(tmp_dir) / "object-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )
            session = DatabaseSession(settings=settings)
            repo = ObjectStorageRepository(session=session, settings=settings)
            manifest = repo.save_snapshot(
                b"sqlite bytes",
                snapshot_id="SNAP-SQLITE-1",
                snapshot_kind="artifact_manifest",
                content_type="application/octet-stream",
                lineage_refs={"project_id": "P-SQLITE", "audit_ref": "AUDIT-SQLITE"},
                created_at="2026-04-25T00:00:00+00:00",
            )
            session.close()

            reloaded_repo = ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)
            try:
                reloaded = reloaded_repo.get_manifest("SNAP-SQLITE-1")
                replay = reloaded_repo.replay_snapshot("SNAP-SQLITE-1")

                self.assertIsNotNone(reloaded)
                self.assertEqual(reloaded.object_key, manifest.object_key)
                self.assertEqual(reloaded.content_type, "application/octet-stream")
                self.assertEqual(reloaded.byte_size, len(b"sqlite bytes"))
                self.assertEqual(reloaded.sha256, manifest.sha256)
                self.assertEqual(reloaded.snapshot_kind, "artifact_manifest")
                self.assertEqual(replay["bytes"], b"sqlite bytes")
                self.assertEqual(replay["readback_state"], "READBACK_READY")
            finally:
                reloaded_repo.session.close()

    def test_local_object_storage_persists_manifest_with_sqlalchemy_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "object-store-sqlalchemy.sqlite"
            settings = Settings(
                storage_backend="sqlalchemy",
                storage_database_url_optional=sqlalchemy_sqlite_url(database_path),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )
            session = DatabaseSession(settings=settings)
            repo = ObjectStorageRepository(session=session, settings=settings)
            manifest = repo.save_snapshot(
                b"sqlalchemy bytes",
                snapshot_id="SNAP-SA-1",
                snapshot_kind="evidence_snapshot",
                content_type="text/plain",
                lineage_refs={"project_id": "P-SA", "trace_id": "TRACE-SA"},
                created_at="2026-04-25T00:00:00+00:00",
            )
            session.close()

            reloaded_repo = ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)
            try:
                replay = reloaded_repo.replay_snapshot("SNAP-SA-1")

                self.assertEqual(replay["manifest"]["object_key"], manifest.object_key)
                self.assertEqual(replay["manifest"]["content_type"], "text/plain")
                self.assertEqual(replay["manifest"]["byte_size"], len(b"sqlalchemy bytes"))
                self.assertEqual(replay["manifest"]["sha256"], manifest.sha256)
                self.assertEqual(replay["manifest"]["snapshot_kind"], "evidence_snapshot")
                self.assertEqual(replay["lineage_refs"]["project_id"], "P-SA")
                self.assertEqual(replay["bytes"], b"sqlalchemy bytes")
            finally:
                reloaded_repo.session.close()

    def test_object_storage_replay_fails_closed_for_missing_object_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "object-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )
            repo = ObjectStorageRepository(session=DatabaseSession(settings=settings), settings=settings)
            manifest = repo.save_snapshot(
                b"delete me",
                snapshot_id="SNAP-MISSING-1",
                snapshot_kind="evidence_snapshot",
                content_type="text/plain",
                lineage_refs={"project_id": "P-MISSING"},
                created_at="2026-04-25T00:00:00+00:00",
            )
            (Path(tmp_dir) / "objects" / manifest.object_key).unlink()

            replay = repo.replay_snapshot("SNAP-MISSING-1")

            self.assertEqual(replay["readback_state"], "MISSING_OBJECT")
            self.assertTrue(replay["manifest_present"])
            self.assertFalse(replay["object_present"])
            self.assertEqual(replay["object_key"], manifest.object_key)
            with self.assertRaises(ObjectStorageMissingError):
                repo.read_snapshot_bytes("SNAP-MISSING-1")

    def test_sqlite_backend_reloads_records_stage_states_work_items_and_operator_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="sqlite",
                storage_path_optional=str(Path(tmp_dir) / "durable-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            now = build_persisted_at()
            record = PersistedRecord(
                object_type="test_record",
                record_id="REC-1",
                stage_scope=8,
                project_id="P-1",
                object_refs={"project_id": "P-1"},
                decision_states={"policy_decision_state": "ALLOW"},
                trace_refs={"trace_id": "TRACE-1"},
                audit_refs={"audit_id": "AUDIT-1"},
                governed_state={"primary_status": "READY"},
                writeback_state={"writeback_targets": ["test_record"]},
                payload={"record_id": "REC-1", "project_id": "P-1", "status": "READY"},
                persisted_at=now,
            )
            stage_state = PersistedStageState(
                stage_scope=8,
                project_id="P-1",
                surface_id="outreach_workbench",
                root_object_type="test_record",
                root_record_id="REC-1",
                inputs={"project_id": "P-1", "record_id": "REC-1"},
                persisted_at=now,
                typed_object_refs={"record_id": "REC-1"},
            )
            work_item = PersistedWorkItem(
                work_item_id="WI-1",
                work_item_key="8:outreach_workbench:test_record:REC-1",
                stage_scope=8,
                project_id="P-1",
                surface_id="outreach_workbench",
                primary_object_type="test_record",
                primary_record_id="REC-1",
                assignment_profile_id="single_operator",
                assignment_lifecycle_state="assigned",
                object_refs={"record_id": "REC-1"},
                surface_operational_state="draft_only",
                current_operational_state="ready_for_internal_operator_action",
                assigned_owner_role="sales_user",
                assigned_owner="operator",
                reviewer_role="delivery_governance_user",
                reviewer="reviewer",
                assignment_resolved_from="test",
                assignment_simplified_boundary=["internal_only"],
                pending_actions=["stage8_mark_ready"],
                pending_button_flows=[{"action_id": "stage8_mark_ready"}],
                last_action_id=None,
                last_action_state=None,
                last_action_at=None,
                trace_refs={"trace_id": "TRACE-1"},
                audit_refs={"audit_id": "AUDIT-1"},
                decision_states={"policy_decision_state": "ALLOW"},
                governed_context={"approval_state": "PENDING_APPROVAL"},
                created_at=now,
                updated_at=now,
            )
            action = PersistedOperatorAction(
                action_event_id="ACT-1",
                work_item_id="WI-1",
                stage_scope=8,
                action_id="stage8_mark_ready",
                button_flow_id="submit_stage8_mark_ready",
                action_state="action_completed",
                resulting_assignment_lifecycle_state="completed",
                requested_by_role="sales_user",
                requested_by="operator",
                assigned_owner_role="sales_user",
                assigned_owner="operator",
                reviewer_role="delivery_governance_user",
                reviewer="reviewer",
                reason="sqlite reload coverage",
                object_refs={"record_id": "REC-1"},
                trace_refs={"trace_id": "TRACE-1"},
                audit_refs={"audit_id": "AUDIT-1"},
                requested_at=now,
                completed_at=now,
            )

            session.upsert_record(record)
            session.upsert_stage_state(stage_state)
            session.upsert_work_item(work_item)
            session.append_operator_action(action)
            sqlite_path = session.storage_path
            session.close()

            connection = sqlite3.connect(sqlite_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertTrue({"records", "stage_states", "work_items", "operator_actions"}.issubset(table_names))

            reloaded = DatabaseSession(settings=settings)
            try:
                self.assertEqual(reloaded.get_record("test_record", "REC-1"), record)
                self.assertEqual(reloaded.get_stage_state(8, "outreach_workbench", "REC-1"), stage_state)
                self.assertEqual(
                    reloaded.find_work_item(
                        stage_scope=8,
                        surface_id="outreach_workbench",
                        primary_object_type="test_record",
                        primary_record_id="REC-1",
                    ),
                    work_item,
                )
                self.assertEqual(reloaded.list_operator_actions("WI-1"), [action])
                self.assertEqual(reloaded.storage_path, Path(tmp_dir) / "durable-store.sqlite")
            finally:
                reloaded.close()

    def test_sqlalchemy_backend_reloads_records_stage_states_work_items_and_operator_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "sqlalchemy-store.sqlite"
            settings = Settings(
                storage_backend="sqlalchemy",
                storage_path_optional=str(Path(tmp_dir) / "unused-json-store.json"),
                storage_database_url_optional=sqlalchemy_sqlite_url(database_path),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            now = build_persisted_at()
            record, stage_state, work_item, action = build_envelope_entries(now)

            session.upsert_record(record)
            session.upsert_stage_state(stage_state)
            session.upsert_work_item(work_item)
            session.append_operator_action(action)
            session.close()

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertTrue({"records", "stage_states", "work_items", "operator_actions"}.issubset(table_names))

            reloaded = DatabaseSession(settings=settings)
            try:
                self.assertEqual(reloaded.storage_backend, "sqlalchemy")
                self.assertEqual(reloaded.storage_path, database_path)
                self.assertEqual(reloaded.storage_database_url, sqlalchemy_sqlite_url(database_path))
                self.assertEqual(reloaded.get_record("test_record", "REC-1"), record)
                self.assertEqual(reloaded.list_records("test_record"), [record])
                self.assertEqual(reloaded.get_stage_state(8, "outreach_workbench", "REC-1"), stage_state)
                self.assertEqual(reloaded.list_stage_states(stage_scope=8), [stage_state])
                self.assertEqual(
                    reloaded.find_work_item(
                        stage_scope=8,
                        surface_id="outreach_workbench",
                        primary_object_type="test_record",
                        primary_record_id="REC-1",
                    ),
                    work_item,
                )
                self.assertEqual(reloaded.list_work_items(stage_scope=8), [work_item])
                self.assertEqual(reloaded.list_operator_actions("WI-1"), [action])
            finally:
                reloaded.close()

    def test_explicit_storage_path_takes_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "explicit-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "KAKA_STORAGE_SCOPE": "process",
                    "KAKA_STORAGE_TEST_ISOLATION": "1",
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in ("KAKA_OBJECT_STORAGE_BACKEND", "KAKA_OBJECT_STORAGE_PATH"):
                    os.environ.pop(key, None)
                settings = Settings.from_env()
                settings_path = settings.resolved_storage_path()
                path = DatabaseSession.default_storage_path()

        self.assertEqual(path, explicit_path)
        self.assertEqual(settings.storage_path_optional, str(explicit_path))
        self.assertEqual(settings.storage_scope, "process")
        self.assertEqual(settings.storage_runtime_mode, "explicit-path")
        self.assertEqual(path, settings_path)

    def test_process_scoped_storage_path_requires_opt_in(self) -> None:
        cases = (
            ("scope", {"KAKA_STORAGE_SCOPE": "process"}),
            ("test_isolation", {"KAKA_STORAGE_TEST_ISOLATION": "1"}),
        )
        for label, env in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir, **env}, clear=False):
                        os.environ.pop("KAKA_STORAGE_PATH", None)
                        for key in (
                            "KAKA_STORAGE_SCOPE",
                            "KAKA_STORAGE_TEST_ISOLATION",
                            "KAKA_OBJECT_STORAGE_BACKEND",
                            "KAKA_OBJECT_STORAGE_PATH",
                        ):
                            if key not in env:
                                os.environ.pop(key, None)

                        settings = Settings.from_env()
                        settings_path = settings.resolved_storage_path()
                        path = DatabaseSession.default_storage_path()

                self.assertTrue(path.name.startswith("internal_operator_loop_store-"))
                self.assertTrue(path.name.endswith(".json"))
                self.assertIn(str(os.getpid()), path.name)
                self.assertEqual(path.parent, Path(tmp_dir) / "kaka")
                self.assertEqual(settings.storage_scope, "process")
                self.assertEqual(settings.storage_runtime_mode, "process-scoped-default")
                self.assertEqual(path, settings_path)

    def test_parallel_sessions_can_flush_same_storage_path_without_tmp_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            shared_path = Path(tmp_dir) / "shared-store.json"
            session_a = DatabaseSession(storage_path=shared_path)
            session_b = DatabaseSession(storage_path=shared_path)

            def write_many(session: DatabaseSession, writer_id: str) -> None:
                for _ in range(20):
                    session.upsert_stage_state(
                        PersistedStageState(
                            stage_scope=8,
                            project_id="P-1",
                            surface_id="outreach_workbench",
                            root_object_type="touch_record",
                            root_record_id="TOUCH-1",
                            inputs={"writer": writer_id},
                            persisted_at=build_persisted_at(),
                        )
                    )

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_a = executor.submit(write_many, session_a, "A")
                future_b = executor.submit(write_many, session_b, "B")
                future_a.result()
                future_b.result()

            reloaded = DatabaseSession(storage_path=shared_path)
            stage_state = reloaded.get_stage_state(8, "outreach_workbench", "TOUCH-1")
            self.assertIsNotNone(stage_state)
            self.assertIn(stage_state.inputs.get("writer"), {"A", "B"})

    def test_worker_queue_repo_persists_lease_retry_suspend_dead_letter_with_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "worker-queue.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            repo = WorkerQueueRepository(session=DatabaseSession(settings=settings))

            queued = repo.enqueue(
                queue_item_id="WQ-JSON-1",
                queue_name="stage8-outbox",
                payload={"task": "sandbox-send-readback"},
                max_attempts=3,
                trace_refs={"trace_id": "TRACE-WQ-1"},
                audit_refs={"audit_id": "AUDIT-WQ-1"},
                now="2026-04-25T00:00:00+00:00",
            )
            claimed = repo.claim_next(
                queue_name="stage8-outbox",
                worker_id="worker-a",
                lease_id="lease-a",
                lease_seconds=10,
                now="2026-04-25T00:00:01+00:00",
            )
            self.assertIsNotNone(claimed)
            self.assertEqual(queued.status, "queued")
            self.assertEqual(claimed.status, "running")
            self.assertEqual(claimed.lease_id, "lease-a")
            self.assertEqual(claimed.worker_id, "worker-a")
            self.assertEqual(claimed.attempt_count, 1)
            self.assertEqual(claimed.claimed_at, "2026-04-25T00:00:01+00:00")
            self.assertEqual(claimed.heartbeat_at, "2026-04-25T00:00:01+00:00")
            self.assertEqual(claimed.expires_at, "2026-04-25T00:00:11+00:00")

            heartbeat = repo.heartbeat(
                queue_item_id="WQ-JSON-1",
                worker_id="worker-a",
                lease_id="lease-a",
                lease_seconds=20,
                now="2026-04-25T00:00:05+00:00",
            )
            retry = repo.mark_failed(
                queue_item_id="WQ-JSON-1",
                worker_id="worker-a",
                lease_id="lease-a",
                error="sandbox provider unavailable",
                retry_delay_seconds=30,
                now="2026-04-25T00:00:06+00:00",
            )

            self.assertEqual(heartbeat.heartbeat_at, "2026-04-25T00:00:05+00:00")
            self.assertEqual(heartbeat.expires_at, "2026-04-25T00:00:25+00:00")
            self.assertEqual(retry.status, "retry")
            self.assertEqual(retry.next_run_at, "2026-04-25T00:00:36+00:00")
            self.assertEqual(retry.last_error, "sandbox provider unavailable")
            self.assertIsNone(retry.lease_id)

            reloaded_repo = WorkerQueueRepository(session=DatabaseSession(settings=settings))
            replay = reloaded_repo.replay("WQ-JSON-1")
            self.assertEqual(replay["current_status"], "retry")
            self.assertEqual(
                [event["event_type"] for event in replay["events"]],
                ["queued", "claimed", "heartbeat", "retry_scheduled"],
            )
            self.assertEqual(replay["queue_item"]["audit_refs"]["audit_id"], "AUDIT-WQ-1")
            self.assertEqual(len(replay["queue_item"]["audit_trace"]), 4)

            second_claim = reloaded_repo.claim_next(
                queue_name="stage8-outbox",
                worker_id="worker-b",
                lease_id="lease-b",
                now="2026-04-25T00:00:37+00:00",
            )
            self.assertIsNotNone(second_claim)
            self.assertEqual(second_claim.attempt_count, 2)

            suspended = reloaded_repo.suspend(
                queue_item_id="WQ-JSON-1",
                suspended_by="operator",
                reason="manual hold before external/live gate",
                now="2026-04-25T00:00:38+00:00",
            )
            resumed = reloaded_repo.resume(
                queue_item_id="WQ-JSON-1",
                now="2026-04-25T00:00:39+00:00",
            )
            final_claim = reloaded_repo.claim_next(
                queue_name="stage8-outbox",
                worker_id="worker-c",
                lease_id="lease-c",
                now="2026-04-25T00:00:40+00:00",
            )
            dead_letter = reloaded_repo.mark_failed(
                queue_item_id="WQ-JSON-1",
                worker_id="worker-c",
                lease_id="lease-c",
                error="retry budget exhausted",
                retryable=True,
                now="2026-04-25T00:00:41+00:00",
            )

            self.assertEqual(suspended.status, "suspended")
            self.assertEqual(resumed.status, "queued")
            self.assertEqual(final_claim.attempt_count, 3)
            self.assertEqual(dead_letter.status, "dead-letter")
            self.assertEqual(dead_letter.dead_letter_at, "2026-04-25T00:00:41+00:00")
            self.assertIn("dead_lettered", [event.event_type for event in reloaded_repo.list_events("WQ-JSON-1")])

    def test_worker_queue_repo_persists_terminal_states_with_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="sqlite",
                storage_path_optional=str(Path(tmp_dir) / "worker-queue.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            repo = WorkerQueueRepository(session=session)

            repo.enqueue(queue_item_id="WQ-SQLITE-SUCCESS", now="2026-04-25T01:00:00+00:00")
            repo.claim(
                queue_item_id="WQ-SQLITE-SUCCESS",
                worker_id="worker-a",
                lease_id="lease-a",
                now="2026-04-25T01:00:01+00:00",
            )
            succeeded = repo.mark_succeeded(
                queue_item_id="WQ-SQLITE-SUCCESS",
                worker_id="worker-a",
                lease_id="lease-a",
                result={"recorded": True},
                now="2026-04-25T01:00:02+00:00",
            )

            repo.enqueue(queue_item_id="WQ-SQLITE-FAILED", now="2026-04-25T01:00:03+00:00")
            repo.claim(
                queue_item_id="WQ-SQLITE-FAILED",
                worker_id="worker-b",
                lease_id="lease-b",
                now="2026-04-25T01:00:04+00:00",
            )
            failed = repo.mark_failed(
                queue_item_id="WQ-SQLITE-FAILED",
                worker_id="worker-b",
                lease_id="lease-b",
                error="non-retryable validation failure",
                retryable=False,
                now="2026-04-25T01:00:05+00:00",
            )
            sqlite_path = session.storage_path
            session.close()

            connection = sqlite3.connect(sqlite_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertTrue({"worker_queue_items", "worker_queue_events"}.issubset(table_names))

            reloaded_repo = WorkerQueueRepository(session=DatabaseSession(settings=settings))
            try:
                self.assertEqual(succeeded.status, "succeeded")
                self.assertEqual(failed.status, "failed")
                self.assertEqual(reloaded_repo.get("WQ-SQLITE-SUCCESS").status, "succeeded")
                self.assertEqual(reloaded_repo.get("WQ-SQLITE-FAILED").status, "failed")
                self.assertEqual(
                    [event.event_type for event in reloaded_repo.list_events("WQ-SQLITE-SUCCESS")],
                    ["queued", "claimed", "succeeded"],
                )
                self.assertEqual(
                    [event.event_type for event in reloaded_repo.list_events("WQ-SQLITE-FAILED")],
                    ["queued", "claimed", "failed"],
                )
            finally:
                reloaded_repo.session.close()

    def test_worker_queue_repo_timeout_replay_works_with_sqlalchemy_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "worker-queue-sqlalchemy.sqlite"
            settings = Settings(
                storage_backend="sqlalchemy",
                storage_database_url_optional=sqlalchemy_sqlite_url(database_path),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )
            repo = WorkerQueueRepository(session=DatabaseSession(settings=settings))

            repo.enqueue(
                queue_item_id="WQ-SA-1",
                max_attempts=2,
                now="2026-04-25T02:00:00+00:00",
            )
            repo.claim(
                queue_item_id="WQ-SA-1",
                worker_id="worker-a",
                lease_id="lease-a",
                lease_seconds=1,
                now="2026-04-25T02:00:01+00:00",
            )
            timed_out = repo.mark_timeouts(now="2026-04-25T02:00:03+00:00")
            self.assertEqual(len(timed_out), 1)
            self.assertEqual(timed_out[0].status, "retry")
            repo.claim(
                queue_item_id="WQ-SA-1",
                worker_id="worker-b",
                lease_id="lease-b",
                lease_seconds=1,
                now="2026-04-25T02:00:04+00:00",
            )
            dead_lettered = repo.mark_timeouts(now="2026-04-25T02:00:06+00:00")
            self.assertEqual(dead_lettered[0].status, "dead-letter")
            repo.session.close()

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertTrue({"worker_queue_items", "worker_queue_events"}.issubset(table_names))

            reloaded_repo = WorkerQueueRepository(session=DatabaseSession(settings=settings))
            try:
                replay = reloaded_repo.replay("WQ-SA-1")
                self.assertEqual(replay["current_status"], "dead-letter")
                self.assertEqual(replay["current_attempt_count"], 2)
                self.assertEqual(
                    [event["event_type"] for event in replay["events"]],
                    [
                        "queued",
                        "claimed",
                        "lease_timeout_retry_scheduled",
                        "claimed",
                        "lease_timeout_dead_lettered",
                    ],
                )
            finally:
                reloaded_repo.session.close()

    def test_backup_manifest_persists_readback_and_counts_core_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "backup-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )
            session = DatabaseSession(settings=settings)
            now = "2026-04-25T03:00:00+00:00"
            record, stage_state, work_item, action = build_envelope_entries(now)
            session.upsert_record(record)
            session.upsert_stage_state(stage_state)
            session.upsert_work_item(work_item)
            session.append_operator_action(action)
            WorkerQueueRepository(session=session).enqueue(
                queue_item_id="WQ-BACKUP-1",
                queue_name="backup-readiness",
                payload={"dry_run": True},
                now=now,
            )
            snapshot_manifest = ObjectStorageRepository(
                session=session,
                settings=settings,
            ).save_snapshot(
                b"backup object bytes",
                snapshot_id="SNAP-BACKUP-1",
                snapshot_kind="backup_fixture",
                content_type="text/plain",
                lineage_refs={"project_id": "P-1", "audit_ref": "AUDIT-BACKUP-1"},
                created_at=now,
            )
            backup_repo = BackupRestoreRepository(session=session, settings=settings)

            manifest = backup_repo.create_manifest(
                backup_id="BACKUP-TEST-1",
                created_at=now,
            )
            readback = backup_repo.readback_manifest("BACKUP-TEST-1")

        self.assertEqual(readback["manifest"], manifest)
        self.assertTrue(readback["manifest_valid"])
        self.assertEqual(manifest["manifest_hash"], compute_manifest_hash(manifest))
        self.assertEqual(manifest["sha256"], manifest["manifest_hash"])
        self.assertEqual(
            manifest["included_scopes"],
            [
                "PersistedRecord",
                "PersistedStageState",
                "PersistedWorkItem",
                "PersistedOperatorAction",
                "worker_queue_state",
                "object_storage_metadata",
                "object_storage_refs",
            ],
        )
        self.assertEqual(manifest["record_counts"]["PersistedStageState"], 1)
        self.assertEqual(manifest["record_counts"]["PersistedWorkItem"], 1)
        self.assertEqual(manifest["record_counts"]["PersistedOperatorAction"], 1)
        self.assertEqual(manifest["record_counts"]["worker_queue_items"], 1)
        self.assertEqual(manifest["record_counts"]["worker_queue_events"], 1)
        self.assertEqual(
            manifest["record_counts"]["PersistedRecord_by_object_type"]["test_record"],
            1,
        )
        self.assertEqual(manifest["record_counts"]["object_storage_metadata"], 1)
        self.assertEqual(manifest["record_counts"]["evidence_snapshot_manifests"], 1)
        self.assertIn(
            snapshot_manifest.object_key,
            manifest["object_refs_summary"]["object_keys"],
        )
        self.assertTrue(manifest["approval_required"])
        self.assertTrue(manifest["audit_required"])
        self.assertFalse(manifest["external_service_connection_enabled"])
        self.assertFalse(manifest["destructive_restore_enabled"])

    def test_json_storage_migration_imports_envelopes_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "source-store.json"
            object_storage_path = Path(tmp_dir) / "objects"
            target_path = Path(tmp_dir) / "target.sqlite"
            database_url = sqlalchemy_sqlite_url(target_path)
            now = "2026-05-07T01:00:00+00:00"
            source_settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(source_path),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(object_storage_path),
            )
            source_session = DatabaseSession(settings=source_settings)
            record, stage_state, work_item, action = build_envelope_entries(now)
            source_session.upsert_record(record)
            source_session.upsert_stage_state(stage_state)
            source_session.upsert_work_item(work_item)
            source_session.append_operator_action(action)
            WorkerQueueRepository(session=source_session).enqueue(
                queue_item_id="WQ-MIGRATE-1",
                queue_name="storage-migration",
                payload={"migration": "json-to-db"},
                now=now,
            )
            source_session.close()

            dry_run = migrate_json_storage_to_database(
                source_path=source_path,
                object_storage_path=object_storage_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=False,
                created_at=now,
            )

            self.assertTrue(dry_run["safe_to_execute"])
            self.assertFalse(dry_run["execution"]["executed"])
            self.assertEqual(dry_run["plan_counts"]["records"]["to_insert"], 1)
            self.assertEqual(dry_run["plan_counts"]["stage_states"]["to_insert"], 1)
            self.assertEqual(dry_run["plan_counts"]["work_items"]["to_insert"], 1)
            self.assertEqual(dry_run["plan_counts"]["operator_actions"]["to_append"], 1)
            self.assertEqual(dry_run["plan_counts"]["worker_queue_items"]["to_insert"], 1)
            self.assertEqual(dry_run["plan_counts"]["worker_queue_events"]["to_append"], 1)
            dry_target = DatabaseSession(
                settings=Settings(
                    storage_backend="sqlalchemy",
                    storage_database_url_optional=database_url,
                    storage_scope="shared",
                    storage_runtime_mode="explicit-path",
                )
            )
            try:
                self.assertEqual(dry_target.list_all_records(), [])
            finally:
                dry_target.close()

            executed = migrate_json_storage_to_database(
                source_path=source_path,
                object_storage_path=object_storage_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at=now,
            )

            self.assertTrue(executed["execution"]["executed"])
            self.assertEqual(executed["target_counts_before"]["records"], 0)
            self.assertEqual(executed["target_counts_after"]["records"], 1)
            self.assertEqual(executed["post_execute_plan_counts"]["records"]["unchanged"], 1)
            target_session = DatabaseSession(
                settings=Settings(
                    storage_backend="sqlalchemy",
                    storage_database_url_optional=database_url,
                    storage_scope="shared",
                    storage_runtime_mode="explicit-path",
                )
            )
            try:
                self.assertEqual(target_session.list_records("test_record"), [record])
                self.assertEqual(target_session.list_stage_states(stage_scope=8), [stage_state])
                self.assertEqual(target_session.list_work_items(stage_scope=8), [work_item])
                self.assertEqual(target_session.list_operator_actions("WI-1"), [action])
                self.assertEqual(len(target_session.list_worker_queue_items()), 1)
                self.assertEqual(len(target_session.list_all_worker_queue_events()), 1)
                migration_records = target_session.list_records(MIGRATION_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(migration_records), 1)
                self.assertEqual(
                    migration_records[0].payload["safety"]["large_object_blob_database_import_enabled"],
                    False,
                )
            finally:
                target_session.close()

            repeated = migrate_json_storage_to_database(
                source_path=source_path,
                object_storage_path=object_storage_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at=now,
            )
            self.assertEqual(repeated["plan_counts"]["operator_actions"]["skipped_existing"], 1)
            self.assertEqual(repeated["plan_counts"]["worker_queue_events"]["skipped_existing"], 1)
            repeated_target = DatabaseSession(
                settings=Settings(
                    storage_backend="sqlalchemy",
                    storage_database_url_optional=database_url,
                    storage_scope="shared",
                    storage_runtime_mode="explicit-path",
                )
            )
            try:
                self.assertEqual(len(repeated_target.list_operator_actions("WI-1")), 1)
                self.assertEqual(len(repeated_target.list_all_worker_queue_events()), 1)
                self.assertEqual(len(repeated_target.list_records(MIGRATION_MANIFEST_OBJECT_TYPE)), 1)
            finally:
                repeated_target.close()

    def test_object_storage_inventory_indexes_legacy_objects_without_blob_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "objects"
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "inventory.sqlite")
            pdf_key = self._write_content_addressed_object(root, b"%PDF-1.7\nfixture")
            json_key = self._write_content_addressed_object(root, b'{"status":"ok"}')
            html_key = self._write_content_addressed_object(root, b"<!DOCTYPE html><html></html>")
            png_key = self._write_content_addressed_object(root, b"\x89PNG\r\n\x1a\nfixture")
            docx_key = self._write_content_addressed_object(root, self._docx_bytes())
            mismatch_path = root / "legacy" / "mismatch.bin"
            mismatch_path.parent.mkdir(parents=True, exist_ok=True)
            mismatch_path.write_bytes(b"\x00\x01\x02legacy")

            target_settings = Settings(
                storage_backend="sqlalchemy",
                storage_database_url_optional=database_url,
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(root),
            )
            target_session = DatabaseSession(settings=target_settings)
            target_session.upsert_record(
                PersistedRecord(
                    object_type="existing_snapshot_ref",
                    record_id="SNAP-REF-1",
                    stage_scope=0,
                    project_id="P-INVENTORY",
                    object_refs={"object_key": pdf_key},
                    decision_states={},
                    trace_refs={},
                    audit_refs={},
                    governed_state={},
                    writeback_state={},
                    payload={"object_key": pdf_key},
                    persisted_at=build_persisted_at(),
                )
            )
            target_session.close()

            dry_run = build_object_storage_inventory(
                object_storage_path=root,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=False,
                created_at="2026-05-07T02:00:00+00:00",
            )

            self.assertTrue(dry_run["safe_to_execute"])
            self.assertFalse(dry_run["execution"]["executed"])
            self.assertEqual(dry_run["summary"]["object_count"], 6)
            self.assertEqual(dry_run["summary"]["content_kind_counts"]["pdf"], 1)
            self.assertEqual(dry_run["summary"]["content_kind_counts"]["json"], 1)
            self.assertEqual(dry_run["summary"]["content_kind_counts"]["html"], 1)
            self.assertEqual(dry_run["summary"]["content_kind_counts"]["png"], 1)
            self.assertEqual(dry_run["summary"]["content_kind_counts"]["docx"], 1)
            self.assertEqual(dry_run["summary"]["content_kind_counts"]["unknown_binary"], 1)
            self.assertEqual(dry_run["summary"]["orphan_state_counts"][REFERENCED_BY_RECORD], 1)
            self.assertEqual(dry_run["summary"]["orphan_state_counts"][UNREFERENCED_LEGACY_OBJECT], 5)
            self.assertEqual(dry_run["summary"]["hash_path_counts"]["valid"], 5)
            self.assertEqual(dry_run["summary"]["hash_path_counts"]["invalid"], 1)
            dry_target = DatabaseSession(settings=target_settings)
            try:
                self.assertEqual(dry_target.list_records(OBJECT_STORAGE_OBJECT_TYPE), [])
                self.assertEqual(
                    dry_target.list_records(OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE),
                    [],
                )
            finally:
                dry_target.close()

            executed = build_object_storage_inventory(
                object_storage_path=root,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at="2026-05-07T02:00:00+00:00",
            )

            self.assertTrue(executed["execution"]["executed"])
            target = DatabaseSession(settings=target_settings)
            try:
                object_records = target.list_records(OBJECT_STORAGE_OBJECT_TYPE)
                manifests = target.list_records(OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(object_records), 6)
                self.assertEqual(len(manifests), 1)
                by_key = {row.record_id: row for row in object_records}
                self.assertEqual(by_key[pdf_key].payload["orphan_state"], REFERENCED_BY_RECORD)
                self.assertEqual(by_key[json_key].payload["content_kind"], "json")
                self.assertEqual(by_key[html_key].payload["content_kind"], "html")
                self.assertEqual(by_key[png_key].payload["content_type"], "image/png")
                self.assertEqual(by_key[docx_key].payload["content_kind"], "docx")
                self.assertFalse(by_key["legacy/mismatch.bin"].payload["hash_path_valid"])
                for row in object_records:
                    self.assertNotIn("bytes", row.payload)
                    self.assertFalse(row.payload["large_object_blob_database_import_enabled"])
                self.assertEqual(
                    manifests[0].payload["summary"]["unreferenced_legacy_object_count"],
                    5,
                )
            finally:
                target.close()

            repeated = build_object_storage_inventory(
                object_storage_path=root,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at="2026-05-07T02:05:00+00:00",
            )
            self.assertTrue(repeated["execution"]["executed"])
            repeated_target = DatabaseSession(settings=target_settings)
            try:
                self.assertEqual(len(repeated_target.list_records(OBJECT_STORAGE_OBJECT_TYPE)), 6)
                self.assertEqual(
                    len(repeated_target.list_records(OBJECT_STORAGE_INVENTORY_MANIFEST_OBJECT_TYPE)),
                    1,
                )
            finally:
                repeated_target.close()

    def test_restore_dry_run_marks_missing_object_refs_and_does_not_write_active_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="json-file",
                storage_path_optional=str(Path(tmp_dir) / "backup-store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
                object_storage_path_optional=str(Path(tmp_dir) / "objects"),
            )
            session = DatabaseSession(settings=settings)
            now = "2026-04-25T04:00:00+00:00"
            ObjectStorageRepository(session=session, settings=settings).save_snapshot(
                b"dry-run object bytes",
                snapshot_id="SNAP-DRY-RUN-1",
                snapshot_kind="backup_fixture",
                content_type="text/plain",
                lineage_refs={"project_id": "P-DRY-RUN"},
                created_at=now,
            )
            backup_repo = BackupRestoreRepository(session=session, settings=settings)
            manifest = backup_repo.create_manifest(
                backup_id="BACKUP-DRY-RUN-1",
                created_at=now,
            )
            before_record_count = len(session.list_all_records())
            missing_key = manifest["object_refs_summary"]["object_storage_refs"][0]["object_key"]
            (settings.resolved_object_storage_path() / missing_key).unlink()

            dry_run = backup_repo.restore_dry_run(
                "BACKUP-DRY-RUN-1",
                target_path=Path(tmp_dir) / "restore-target",
            )
            after_record_count = len(session.list_all_records())
            rollback = backup_repo.rollback_readiness("BACKUP-DRY-RUN-1")

        self.assertEqual(after_record_count, before_record_count)
        self.assertEqual(dry_run["restore_mode"], "DRY_RUN_ONLY")
        self.assertFalse(dry_run["safe_to_restore"])
        self.assertFalse(dry_run["destructive_restore_enabled"])
        self.assertFalse(dry_run["active_storage_write_enabled"])
        self.assertTrue(dry_run["approval_required"])
        self.assertTrue(dry_run["audit_required"])
        self.assertFalse(dry_run["external_service_connection_enabled"])
        self.assertFalse(dry_run["migration_execution_enabled"])
        self.assertIn("missing_or_invalid_object_refs", dry_run["blocking_reasons"])
        self.assertEqual(
            dry_run["restore_plan"]["missing_object_refs"][0]["reason"],
            "object_missing",
        )
        self.assertEqual(rollback["rollback_point"], "BACKUP-DRY-RUN-1")
        self.assertFalse(rollback["safe_to_restore"])
        self.assertFalse(rollback["destructive_restore_enabled"])
        self.assertFalse(rollback["rollback_execution_enabled"])
        self.assertTrue(rollback["approval_required"])
        self.assertTrue(rollback["audit_required"])
        self.assertFalse(rollback["external_service_connection_enabled"])


if __name__ == "__main__":
    unittest.main()
