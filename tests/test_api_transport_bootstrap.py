from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from api.deps import get_settings
from api.main import create_app
from api.routes.stage1 import register_stage1_routes
from api.routes.stage2 import register_stage2_routes
from api.routes.stage3 import register_stage3_routes
from api.routes.stage4 import register_stage4_routes
from api.routes.stage5 import register_stage5_routes
from api.routes.stage6 import (
    register_stage1_to_stage6_internal_orchestration_routes,
    register_stage6_routes,
)
from helpers import load_fixture
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    PROVIDER_FAMILIES,
)
from shared.pipeline import run_internal_chain
from storage import persist_stage_bundle, reset_default_storage


RESERVED_ENTRY_PLAN_READBACK_KEYS = (
    "stage_scope",
    "availability_state",
    "transport_state",
    "reserved_entry_state",
    "reserved_operation_id",
    "reserved_path",
    "reserved_method",
    "handoff_refs",
    "http_entry_enabled",
    "real_transport_enabled",
    "orchestrator_enabled",
    "internal_orchestration_entry_available",
    "internal_orchestration_operation_id",
    "internal_orchestration_path",
    "internal_orchestration_method",
    "internal_orchestration_payload_boundary",
    "stage6_readback_mode",
    "stage1_to_stage5_external_live_transport_state",
    "route_registrar",
)
RESERVED_ENTRY_EXPECTATIONS = {
    1: {
        "reserved_operation_id": "reservedStage1TaskingEntry",
        "reserved_path": "/reserved/stage1/tasking",
        "reserved_method": "POST",
        "handoff_refs": ["H-01-STAGE1-TO-STAGE2"],
    },
    2: {
        "reserved_operation_id": "reservedStage2IngestionEntry",
        "reserved_path": "/reserved/stage2/ingestion",
        "reserved_method": "POST",
        "handoff_refs": ["H-01-STAGE1-TO-STAGE2", "H-02-STAGE2-TO-STAGE3"],
    },
    3: {
        "reserved_operation_id": "reservedStage3ParsingEntry",
        "reserved_path": "/reserved/stage3/parsing",
        "reserved_method": "POST",
        "handoff_refs": ["H-02-STAGE2-TO-STAGE3", "H-03-STAGE3-TO-STAGE4"],
    },
    4: {
        "reserved_operation_id": "reservedStage4VerificationEntry",
        "reserved_path": "/reserved/stage4/verification",
        "reserved_method": "POST",
        "handoff_refs": ["H-03-STAGE3-TO-STAGE4", "H-04-STAGE4-TO-STAGE5"],
    },
    5: {
        "reserved_operation_id": "reservedStage5RulesEvidenceEntry",
        "reserved_path": "/reserved/stage5/rules-evidence",
        "reserved_method": "POST",
        "handoff_refs": ["H-04-STAGE4-TO-STAGE5", "H-05-STAGE5-TO-STAGE6"],
    },
}
RESERVED_INFRA_BACKENDS = {
    "alembic",
    "redis",
    "dramatiq",
    "minio",
    "s3",
    "docker-compose",
}
RESERVED_OR_NOT_CONFIGURED = {"RESERVED_NOT_LIVE", "NOT_CONFIGURED"}
STORAGE_ENV_KEYS = (
    "KAKA_STORAGE_BACKEND",
    "KAKA_STORAGE_PATH",
    "KAKA_STORAGE_DATABASE_URL",
    "KAKA_STORAGE_SCOPE",
    "KAKA_STORAGE_TEST_ISOLATION",
    "KAKA_OBJECT_STORAGE_BACKEND",
    "KAKA_OBJECT_STORAGE_PATH",
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def expected_reserved_entry_plan(stage_scope: int) -> dict[str, object]:
    return {
        "stage_scope": stage_scope,
        "availability_state": "CONTROLLED_UNAVAILABLE",
        "transport_state": "TRANSPORT_NOT_WIRED",
        "reserved_entry_state": "RESERVED_NOT_LIVE",
        **RESERVED_ENTRY_EXPECTATIONS[stage_scope],
        "http_entry_enabled": False,
        "real_transport_enabled": False,
        "orchestrator_enabled": False,
        "internal_orchestration_entry_available": True,
        "internal_orchestration_operation_id": "runStage1ToStage6InternalOrchestration",
        "internal_orchestration_path": "/internal/stage1-6/orchestrations",
        "internal_orchestration_method": "POST",
        "internal_orchestration_payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
        "stage6_readback_mode": "repository_backed_preview",
        "stage1_to_stage5_external_live_transport_state": "BLOCKED_CONTROLLED_UNAVAILABLE",
        "route_registrar": f"register_stage{stage_scope}_routes",
    }


class TestApiTransportBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        reset_default_storage()

    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_get_settings_returns_formal_internal_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir}, clear=False):
                for key in STORAGE_ENV_KEYS:
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                settings = get_settings()
                resolved_storage_path = settings.resolved_storage_path()

        self.assertEqual(settings.environment, "INTERNAL_ONLY")
        self.assertEqual(Path(settings.repo_root).resolve(), ROOT.resolve())
        self.assertEqual(settings.storage_backend, "json-file")
        self.assertIsNone(settings.storage_path_optional)
        self.assertIsNone(settings.storage_database_url_optional)
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
        self.assertEqual(
            resolved_storage_path,
            Path(tmp_dir) / "kaka" / "internal_operator_loop_store.json",
        )

    def test_get_settings_consumes_storage_backend_from_env(self) -> None:
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
                get_settings.cache_clear()
                settings = get_settings()

        self.assertEqual(settings.storage_backend, "postgres")
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")

    def test_create_app_mounts_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "json-file",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "KAKA_STORAGE_SCOPE": "process",
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()

        self.assertEqual(app.state.settings.storage_backend, "json-file")
        self.assertEqual(app.state.settings.storage_path_optional, str(explicit_path))
        self.assertEqual(app.state.settings.storage_scope, "process")
        self.assertEqual(app.state.settings.storage_runtime_mode, "explicit-path")
        self.assertEqual(app.state.storage_session.storage_backend, "json-file")
        self.assertEqual(app.state.storage_session.storage_path, explicit_path)
        storage_bootstrap = app.state.storage_bootstrap
        self.assertEqual(storage_bootstrap["storage_backend"], "json-file")
        self.assertEqual(storage_bootstrap["storage_path"], str(explicit_path))
        self.assertEqual(storage_bootstrap["storage_path_optional"], str(explicit_path))
        self.assertFalse(storage_bootstrap["storage_database_url_configured"])
        self.assertIsNone(storage_bootstrap["storage_database_url_redacted"])
        self.assertEqual(storage_bootstrap["storage_scope"], "process")
        self.assertEqual(storage_bootstrap["storage_runtime_mode"], "explicit-path")
        self.assertEqual(storage_bootstrap["queue_backend"], "storage")
        self.assertEqual(storage_bootstrap["worker_runtime"], "internal-storage-worker")
        self.assertEqual(storage_bootstrap["active_object_storage_backend"], "local-filesystem")
        self.assertEqual(storage_bootstrap["object_storage_backend"], "local-filesystem")
        self.assertEqual(
            storage_bootstrap["object_storage_path"],
            str(explicit_path.parent / "object-storage"),
        )
        self.assertTrue(storage_bootstrap["worker_queue_bootstrap"]["durable_queue_enabled"])
        self.assertTrue(storage_bootstrap["worker_queue_bootstrap"]["worker_lease_enabled"])
        self.assertFalse(storage_bootstrap["worker_queue_bootstrap"]["external_queue_connection_enabled"])
        self.assertIn("backup_restore_readiness", storage_bootstrap)
        self.assertIn("rollback_readiness", storage_bootstrap)
        self.assertTrue(storage_bootstrap["backup_restore_readiness"]["backup_manifest_enabled"])
        self.assertTrue(storage_bootstrap["backup_restore_readiness"]["restore_dry_run_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["destructive_restore_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["external_backup_service_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["external_service_connection_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["migration_execution_enabled"])
        self.assertFalse(storage_bootstrap["rollback_readiness"]["rollback_execution_enabled"])
        self.assertFalse(storage_bootstrap["rollback_readiness"]["destructive_restore_enabled"])
        self.assertTrue(storage_bootstrap["rollback_readiness"]["approval_required"])
        self.assertTrue(storage_bootstrap["rollback_readiness"]["audit_required"])
        self.assertIn("monitoring_alerting_readiness", storage_bootstrap)
        self.assertIn("monitoring_readiness", storage_bootstrap)
        self.assertIn("alert_rule_catalog", storage_bootstrap)
        self.assertIn("alert_readiness", storage_bootstrap)
        self.assertIn("incident_readiness", storage_bootstrap)
        self.assertIn("production_slo_incident_readiness", storage_bootstrap)
        self.assertIn("production_slo_readiness", storage_bootstrap)
        self.assertIn("production_monitoring_dashboard", storage_bootstrap)
        self.assertIn("production_alert_rule_catalog", storage_bootstrap)
        self.assertIn("simulated_alert_evaluation_readback", storage_bootstrap)
        self.assertIn("production_incident_runbook", storage_bootstrap)
        self.assertIn("production_drill_evidence", storage_bootstrap)
        self.assertIn("suspended_state_operation_readback", storage_bootstrap)
        self.assertEqual(
            storage_bootstrap["monitoring_readiness"]["readiness_state"],
            "INTERNAL_READBACK_READY",
        )
        self.assertIn("storage.backend", storage_bootstrap["monitoring_readiness"]["component_ids"])
        self.assertIn("queue.worker", storage_bootstrap["monitoring_readiness"]["component_ids"])
        self.assertFalse(storage_bootstrap["alert_readiness"]["notification_enabled"])
        self.assertFalse(storage_bootstrap["alert_readiness"]["live_dispatch_enabled"])
        self.assertGreaterEqual(len(storage_bootstrap["alert_rule_catalog"]), 6)
        self.assertEqual(
            storage_bootstrap["incident_readiness"]["incident_state"],
            "MANUAL_OWNER_ACTION_READY",
        )
        self.assertTrue(storage_bootstrap["incident_readiness"]["manual_owner_action_required"])
        self.assertFalse(storage_bootstrap["incident_readiness"]["incident_automation_enabled"])
        self.assertFalse(storage_bootstrap["incident_readiness"]["external_paging_enabled"])
        production = storage_bootstrap["production_slo_incident_readiness"]
        self.assertEqual(production["target_capability_state"], "PRODUCTION_READY")
        self.assertTrue(production["repository_backed_readback"])
        self.assertTrue(production["validation"]["valid"])
        self.assertTrue(
            all(
                evaluation["alert_fired"]
                for evaluation in production["simulated_alert_evaluation_readback"]
            )
        )
        self.assertFalse(production["redlines"]["real_alert_dispatch_enabled"])
        self.assertFalse(production["redlines"]["incident_automation_enabled"])
        self.assertFalse(production["redlines"]["destructive_restore_enabled"])
        self.assertFalse(production["redlines"]["rollback_execution_enabled"])
        self.assertIn("platform_infra_readiness", storage_bootstrap)
        self.assertIn("provider_adapter_bootstrap", storage_bootstrap)
        provider_bootstrap = storage_bootstrap["provider_adapter_bootstrap"]
        self.assertEqual(provider_bootstrap["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(provider_bootstrap["provider_adapter_live_execution_enabled"])
        self.assertFalse(provider_bootstrap["provider_adapter_real_provider_call_enabled"])
        self.assertEqual(
            set(provider_bootstrap[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["families"]),
            set(PROVIDER_FAMILIES),
        )

        readiness = storage_bootstrap["platform_infra_readiness"]
        self.assertEqual(readiness["active_backend"], "json-file")
        self.assertEqual(
            [entry["backend"] for entry in readiness["executable_backends"] if entry["executable"]],
            ["json-file", "sqlite"],
        )
        executable_by_backend = {
            entry["backend"]: entry
            for entry in readiness["executable_backends"]
        }
        self.assertTrue(executable_by_backend["json-file"]["configured"])
        self.assertFalse(executable_by_backend["sqlite"]["configured"])
        self.assertEqual(set(executable_by_backend), {"json-file", "sqlite", "sqlalchemy", "postgresql"})
        self.assertEqual(executable_by_backend["sqlalchemy"]["readiness_state"], "NOT_CONFIGURED")
        self.assertEqual(executable_by_backend["postgresql"]["readiness_state"], "NOT_CONFIGURED")
        reserved_by_backend = {
            entry["backend"]: entry
            for entry in readiness["reserved_backends"]
        }
        self.assertEqual(set(reserved_by_backend), RESERVED_INFRA_BACKENDS)
        for backend, entry in reserved_by_backend.items():
            self.assertFalse(entry["executable"], backend)
            self.assertIn(entry["readiness_state"], RESERVED_OR_NOT_CONFIGURED, backend)
        self.assertFalse(readiness["postgresql_readiness"]["executable"])
        self.assertFalse(readiness["postgresql_readiness"]["database_url_configured"])
        self.assertFalse(readiness["sqlalchemy_readiness"]["executable"])
        self.assertFalse(readiness["sqlalchemy_readiness"]["database_url_configured"])
        self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
        self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["queue_readiness"]["internal_durable_queue"]["repository_backed"])
        self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
        self.assertEqual(readiness["worker_runtime_readiness"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["worker_runtime_readiness"]["heartbeat_persistence_enabled"])
        self.assertTrue(readiness["worker_runtime_readiness"]["dead_letter_persistence_enabled"])
        self.assertFalse(readiness["worker_runtime_readiness"]["stage1_scheduler_enabled"])
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
        self.assertEqual(
            readiness["backup_restore_readiness"],
            storage_bootstrap["backup_restore_readiness"],
        )
        self.assertEqual(
            readiness["rollback_readiness"],
            storage_bootstrap["rollback_readiness"],
        )
        self.assertTrue(readiness["backup_restore_readiness"]["manifest_hash_enabled"])
        self.assertFalse(readiness["backup_restore_readiness"]["restore_execution_enabled"])
        self.assertFalse(readiness["backup_restore_readiness"]["active_storage_write_enabled"])
        self.assertFalse(readiness["rollback_readiness"]["rollback_execution_enabled"])
        self.assertEqual(
            readiness["monitoring_alerting_readiness"],
            storage_bootstrap["monitoring_alerting_readiness"],
        )
        self.assertEqual(readiness["monitoring_readiness"], storage_bootstrap["monitoring_readiness"])
        self.assertEqual(readiness["alert_readiness"], storage_bootstrap["alert_readiness"])
        self.assertEqual(readiness["alert_rule_catalog"], storage_bootstrap["alert_rule_catalog"])
        self.assertEqual(readiness["incident_readiness"], storage_bootstrap["incident_readiness"])
        self.assertEqual(
            readiness["production_slo_incident_readiness"],
            storage_bootstrap["production_slo_incident_readiness"],
        )
        self.assertEqual(
            readiness["production_slo_readiness"],
            storage_bootstrap["production_slo_readiness"],
        )
        self.assertIn("local_stack_readiness", storage_bootstrap)
        self.assertEqual(storage_bootstrap["local_stack_readiness"], readiness["compose_readiness"])
        self.assertTrue(readiness["compose_readiness"]["dockerfile_present"])
        self.assertTrue(readiness["compose_readiness"]["compose_file_present"])
        self.assertTrue(readiness["compose_readiness"]["docker_compose_config_present"])
        self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
        self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
        self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
        self.assertEqual(
            readiness["compose_readiness"]["service_dependency_summary"]["postgres"]["readiness_state"],
            "RESERVED_NOT_LIVE",
        )
        self.assertFalse(
            readiness["compose_readiness"]["service_dependency_summary"]["redis"][
                "external_service_connection_enabled"
            ]
        )
        self.assertFalse(
            readiness["compose_readiness"]["service_dependency_summary"]["minio"][
                "external_service_connection_enabled"
            ]
        )
        self.assertTrue(readiness["backend_policy"]["unsupported_backend_fast_fail"])
        self.assertTrue(readiness["backend_policy"]["missing_database_url_fast_fail"])
        self.assertTrue(readiness["backend_policy"]["no_silent_fallback"])
        self.assertTrue(readiness["backend_policy"]["no_migration_execution"])
        self.assertTrue(readiness["backend_policy"]["no_external_service_connection"])
        self.assertTrue(readiness["backend_policy"]["readback_only"])
        self.assertFalse(readiness["backend_policy"]["runtime_behavior_changed"])

    def test_create_app_mounts_sqlite_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
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
                get_settings.cache_clear()
                app = create_app()
                try:
                    self.assertEqual(app.state.settings.storage_backend, "sqlite")
                    self.assertEqual(app.state.storage_session.storage_backend, "sqlite")
                    self.assertEqual(app.state.storage_session.storage_path, explicit_path.with_suffix(".sqlite"))
                    storage_bootstrap = app.state.storage_bootstrap
                    self.assertEqual(storage_bootstrap["active_backend"], "sqlite")
                    self.assertEqual(storage_bootstrap["storage_backend"], "sqlite")
                    self.assertEqual(storage_bootstrap["storage_path"], str(explicit_path))
                    readiness = storage_bootstrap["platform_infra_readiness"]
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
                    reserved_by_backend = {
                        entry["backend"]: entry
                        for entry in readiness["reserved_backends"]
                    }
                    self.assertEqual(set(reserved_by_backend), RESERVED_INFRA_BACKENDS)
                    self.assertFalse(readiness["postgresql_readiness"]["executable"])
                    self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
                    self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["active_storage_backend"], "sqlite")
                    self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
                    self.assertTrue(readiness["worker_runtime_readiness"]["suspend_resume_persistence_enabled"])
                    self.assertEqual(readiness["object_storage_readiness"]["readiness_state"], "EXECUTABLE")
                    self.assertTrue(
                        readiness["object_storage_readiness"]["snapshot_durability"][
                            "readback_replay_enabled"
                        ]
                    )
                    self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
                    self.assertTrue(readiness["backend_policy"]["unsupported_backend_fast_fail"])
                    self.assertTrue(readiness["backend_policy"]["no_silent_fallback"])
                    self.assertTrue(readiness["backend_policy"]["no_external_service_connection"])
                finally:
                    app.state.storage_session.close()

    def test_create_app_keeps_minio_object_storage_reserved_not_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "json-file",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "KAKA_OBJECT_STORAGE_BACKEND": "minio",
                    "KAKA_OBJECT_STORAGE_PATH": str(Path(tmp_dir) / "objects"),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in ("KAKA_STORAGE_DATABASE_URL", "KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()

        readiness = app.state.storage_bootstrap["platform_infra_readiness"]
        object_readiness = readiness["object_storage_readiness"]
        self.assertEqual(app.state.storage_bootstrap["active_object_storage_backend"], "minio")
        self.assertEqual(object_readiness["active_backend"], "minio")
        self.assertEqual(object_readiness["readiness_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(object_readiness["executable"])
        self.assertFalse(object_readiness["connection_enabled"])
        self.assertFalse(object_readiness["external_service_connection_enabled"])
        self.assertFalse(object_readiness["minio_connection_enabled"])
        self.assertFalse(object_readiness["s3_connection_enabled"])
        self.assertFalse(app.state.transport_bootstrap["redlines"]["minio_connection_enabled"])
        reserved_by_backend = {
            entry["backend"]: entry
            for entry in readiness["reserved_backends"]
        }
        self.assertEqual(reserved_by_backend["minio"]["readiness_state"], "RESERVED_NOT_LIVE")

    def test_create_app_mounts_sqlalchemy_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "storage" / "sqlalchemy-store.sqlite"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "sqlalchemy",
                    "KAKA_STORAGE_DATABASE_URL": sqlalchemy_sqlite_url(database_path),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()
                try:
                    storage_bootstrap = app.state.storage_bootstrap
                    readiness = storage_bootstrap["platform_infra_readiness"]
                    self.assertEqual(app.state.storage_session.storage_backend, "sqlalchemy")
                    self.assertEqual(app.state.storage_session.storage_path, database_path)
                    self.assertEqual(storage_bootstrap["active_backend"], "sqlalchemy")
                    self.assertEqual(storage_bootstrap["storage_backend"], "sqlalchemy")
                    self.assertTrue(storage_bootstrap["storage_database_url_configured"])
                    self.assertEqual(storage_bootstrap["storage_database_url_dialect"], "sqlite")
                    self.assertEqual(readiness["active_backend"], "sqlalchemy")
                    self.assertEqual(readiness["sqlalchemy_readiness"]["readiness_state"], "EXECUTABLE")
                    self.assertTrue(readiness["sqlalchemy_readiness"]["executable"])
                    self.assertTrue(readiness["sqlalchemy_readiness"]["configured"])
                    self.assertEqual(readiness["sqlalchemy_readiness"]["database_url_dialect"], "sqlite")
                    self.assertEqual(readiness["postgresql_readiness"]["readiness_state"], "NOT_CONFIGURED")
                    self.assertFalse(readiness["postgresql_readiness"]["configured"])
                    self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
                    self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["active_storage_backend"], "sqlalchemy")
                    self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
                    self.assertTrue(readiness["worker_runtime_readiness"]["retry_persistence_enabled"])
                    self.assertEqual(readiness["object_storage_readiness"]["readiness_state"], "EXECUTABLE")
                    self.assertTrue(readiness["object_storage_readiness"]["local_filesystem"]["executable"])
                    self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
                    self.assertEqual(app.state.transport_bootstrap["storage_bootstrap"], storage_bootstrap)
                    self.assertEqual(app.state.transport_bootstrap["platform_infra_readiness"], readiness)
                    self.assertEqual(
                        app.state.transport_bootstrap["local_stack_readiness"],
                        readiness["compose_readiness"],
                    )
                    self.assertEqual(
                        app.state.transport_bootstrap["worker_queue_bootstrap"],
                        storage_bootstrap["worker_queue_bootstrap"],
                    )
                    self.assertTrue(app.state.transport_bootstrap["queue_worker_readiness"]["durable_queue_enabled"])
                finally:
                    app.state.storage_session.close()

    def test_create_app_exposes_single_transport_bootstrap_readback_projection(self) -> None:
        app = create_app()

        self.assertTrue(hasattr(app.state, "transport_bootstrap"))
        bootstrap = app.state.transport_bootstrap
        self.assertTrue(bootstrap["internal_only"])
        self.assertFalse(bootstrap["live_execution_enabled"])
        self.assertIn("provider_adapter_bootstrap", bootstrap)
        self.assertEqual(bootstrap["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertEqual(bootstrap["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(bootstrap["provider_circuit_breaker_state"], "CLOSED")
        self.assertFalse(bootstrap["provider_adapter_suspended"])
        self.assertTrue(bootstrap["provider_status_replayable"])
        self.assertTrue(bootstrap["provider_reliability_summary"]["circuit_breaker_visible"])
        self.assertFalse(
            bootstrap["provider_adapter_bootstrap"]["provider_adapter_live_execution_enabled"]
        )
        self.assertFalse(
            bootstrap["provider_adapter_bootstrap"]["provider_adapter_real_provider_call_enabled"]
        )
        self.assertEqual(
            set(bootstrap[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["families"]),
            set(PROVIDER_FAMILIES),
        )
        self.assertEqual(
            app.state.provider_adapter_config_readback.payload["mode"],
            "SANDBOX_DRY_RUN_READBACK",
        )
        self.assertEqual(
            app.state.provider_adapter_config_readback.governed_state["provider_reliability_state"],
            "APPROVAL_READY",
        )

        disabled_registry = bootstrap["stage1_to_stage5_transport_state"]
        self.assertEqual(disabled_registry, app.state.disabled_stage_transports)
        reserved_entry_plan = bootstrap["stage1_to_stage5_reserved_entry_plan"]
        self.assertEqual(set(reserved_entry_plan), {f"stage{stage_scope}" for stage_scope in range(1, 6)})
        for stage_scope in range(1, 6):
            stage_key = f"stage{stage_scope}"
            self.assertIn(stage_key, disabled_registry)
            self.assertEqual(len(disabled_registry[stage_key]), 1)
            transport_status = disabled_registry[stage_key][0]
            self.assertEqual(transport_status["stage_scope"], stage_scope)
            self.assertEqual(transport_status["availability_state"], "CONTROLLED_UNAVAILABLE")
            self.assertEqual(transport_status["transport_state"], "TRANSPORT_NOT_WIRED")
            self.assertFalse(transport_status["live_execution_enabled"])
            self.assertTrue(transport_status["internal_only"])
            self.assertEqual(
                reserved_entry_plan[stage_key],
                [
                    {
                        key: transport_status[key]
                        for key in RESERVED_ENTRY_PLAN_READBACK_KEYS
                    }
                ],
            )
            self.assertEqual(reserved_entry_plan[stage_key][0], expected_reserved_entry_plan(stage_scope))
            self.assertFalse(reserved_entry_plan[stage_key][0]["http_entry_enabled"])
            self.assertFalse(reserved_entry_plan[stage_key][0]["real_transport_enabled"])
            self.assertFalse(reserved_entry_plan[stage_key][0]["orchestrator_enabled"])

        mounted_operations = bootstrap["stage6_to_stage9_mounted_operations"]
        mounted_by_id = {operation["operationId"]: operation for operation in mounted_operations}
        expected_operations = {
            "runStage1ToStage6InternalOrchestration",
            "previewStage6ReviewReportWorkbench",
            "listSaleableOpportunities",
            "listContactTargets",
            "listOrders",
            "createOutreachPlan",
            "createOrder",
        }
        self.assertTrue(expected_operations.issubset(mounted_by_id))
        for operation_id in expected_operations:
            operation = mounted_by_id[operation_id]
            for key in (
                "stage_scope",
                "operationId",
                "method",
                "path",
                "surface_mode",
                "internal_only",
                "live_execution_enabled",
                "blocked_by_default",
            ):
                self.assertIn(key, operation)
            self.assertTrue(operation["internal_only"])
            self.assertFalse(operation["live_execution_enabled"])
            if operation["stage_scope"] in (7, 8, 9):
                self.assertEqual(operation["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
                self.assertEqual(operation["provider_reliability_state"], "APPROVAL_READY")
                self.assertEqual(operation["provider_circuit_breaker_state"], "CLOSED")
                self.assertFalse(operation["provider_adapter_suspended"])
                self.assertFalse(operation["provider_adapter_live_execution_enabled"])
                self.assertFalse(operation["provider_adapter_real_provider_call_enabled"])
                self.assertIn(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY, operation)

        orchestration_operation = mounted_by_id["runStage1ToStage6InternalOrchestration"]
        self.assertEqual(orchestration_operation["stage_scope"], 6)
        self.assertEqual(orchestration_operation["method"], "POST")
        self.assertEqual(orchestration_operation["path"], "/internal/stage1-6/orchestrations")
        self.assertEqual(
            orchestration_operation["accepted_payload_boundary"],
            "SANITIZED_OFFLINE_INTERNAL",
        )
        self.assertTrue(orchestration_operation["repository_backed_readback"])
        self.assertEqual(orchestration_operation["orchestrates_stage_scope"], "stage1_to_stage6")
        self.assertEqual(mounted_by_id["previewStage6ReviewReportWorkbench"]["stage_scope"], 6)
        self.assertEqual(mounted_by_id["listSaleableOpportunities"]["stage_scope"], 7)
        self.assertEqual(mounted_by_id["listContactTargets"]["stage_scope"], 8)
        self.assertIn("createPaymentRecord", mounted_by_id)
        self.assertIn("createDeliveryRecord", mounted_by_id)
        self.assertTrue(
            mounted_by_id["createPaymentRecord"]["payment_sandbox_provider_records"]["readback_ready"]
        )
        self.assertFalse(
            mounted_by_id["createPaymentRecord"]["payment_sandbox_provider_records"]["payment_capture_enabled"]
        )
        self.assertTrue(
            mounted_by_id["createDeliveryRecord"]["delivery_sandbox_provider_records"]["version_lock_enabled"]
        )
        self.assertFalse(
            mounted_by_id["createDeliveryRecord"]["delivery_sandbox_provider_records"]["real_delivery_enabled"]
        )
        self.assertFalse(
            mounted_by_id["createPaymentRecord"]["manual_refund_exception_record"][
                "automated_refund_enabled"
            ]
        )
        live_pilot_metadata = mounted_by_id["createPaymentRecord"]["payment_delivery_live_pilot"]
        self.assertEqual(
            live_pilot_metadata["readiness_scope"],
            "gated_small_sample_payment_delivery_live_pilot_readback",
        )
        self.assertFalse(live_pilot_metadata["batch_execution_enabled"])
        self.assertTrue(live_pilot_metadata["payment_approval_required"])
        self.assertTrue(live_pilot_metadata["delivery_approval_required"])
        self.assertTrue(live_pilot_metadata["finance_review_required"])
        self.assertTrue(live_pilot_metadata["operator_action_audit_required"])
        self.assertTrue(live_pilot_metadata["artifact_version_lock_required"])
        self.assertTrue(live_pilot_metadata["download_auth_required"])
        self.assertFalse(live_pilot_metadata["provider_call_enabled"])
        self.assertFalse(live_pilot_metadata["real_provider_call_enabled"])
        self.assertFalse(live_pilot_metadata["real_charge_attempted"])
        self.assertFalse(live_pilot_metadata["real_delivery_fulfillment_attempted"])
        self.assertFalse(live_pilot_metadata["real_refund_attempted"])
        self.assertFalse(live_pilot_metadata["automated_refund_enabled"])
        approved_execution_metadata = mounted_by_id["createPaymentRecord"][
            "approved_payment_delivery_execution"
        ]
        self.assertEqual(
            approved_execution_metadata["readiness_scope"],
            "approved_payment_delivery_provider_execution_readback",
        )
        self.assertEqual(
            approved_execution_metadata["controlled_provider_adapter_scope"],
            "LOCAL_CONTROLLED_FAKE_PROVIDER",
        )
        self.assertTrue(approved_execution_metadata["requires_payment_approval"])
        self.assertTrue(approved_execution_metadata["requires_delivery_approval"])
        self.assertTrue(approved_execution_metadata["requires_callback_verification"])
        self.assertTrue(approved_execution_metadata["requires_settlement_reconciliation"])
        self.assertFalse(approved_execution_metadata["provider_call_enabled"])
        self.assertFalse(approved_execution_metadata["real_provider_call_enabled"])
        self.assertFalse(approved_execution_metadata["real_refund_attempted"])
        self.assertFalse(approved_execution_metadata["automated_refund_enabled"])
        self.assertEqual(mounted_by_id["listOrders"]["stage_scope"], 9)
        self.assertTrue(mounted_by_id["listContactTargets"]["blocked_by_default"])
        self.assertTrue(
            mounted_by_id["listContactTargets"]["stage8_execution_outbox_readiness"][
                "sandbox_execution_record_enabled"
            ]
        )
        self.assertEqual(
            mounted_by_id["listContactTargets"]["stage8_execution_outbox_readiness"][
                "sandbox_adapter_families"
            ],
            ["email", "sms", "phone_call", "wecom_im"],
        )
        self.assertTrue(
            mounted_by_id["listContactTargets"]["stage8_execution_outbox_readiness"][
                "execution_timeline_visible"
            ]
        )
        self.assertTrue(mounted_by_id["createOutreachPlan"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["listOrders"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["createOrder"]["blocked_by_default"])

        leadpack_candidate = mounted_by_id["previewLeadpackExternalDeliveryCandidate"]
        self.assertTrue(leadpack_candidate["candidate_only"])
        self.assertTrue(leadpack_candidate["readiness_only"])
        self.assertTrue(leadpack_candidate["review_only"])
        self.assertFalse(leadpack_candidate["external_delivery_enabled"])
        self.assertFalse(leadpack_candidate["direct_export_enabled"])

        self.assertFalse(leadpack_candidate["external_ready_direct_export"])
        self.assertFalse(leadpack_candidate["customer_visible_export_enabled"])
        self.assertFalse(leadpack_candidate["client_page_release_enabled"])
        self.assertFalse(leadpack_candidate["page_layer_release_enabled"])
        self.assertFalse(leadpack_candidate["external_release_enabled"])
        self.assertFalse(leadpack_candidate["export_artifact_generation_enabled"])
        self.assertFalse(leadpack_candidate["page_publication_enabled"])
        self.assertTrue(leadpack_candidate["projection_only"])
        self.assertTrue(leadpack_candidate["non_live"])
        self.assertTrue(leadpack_candidate["release_blocked"])
        self.assertTrue(leadpack_candidate["requires_review"])
        formal_export_page_readiness = leadpack_candidate["formal_client_export_page_layer_readiness"]
        self.assertEqual(
            formal_export_page_readiness["surface_id"],
            "formal_client_export_page_layer_readiness",
        )
        self.assertTrue(formal_export_page_readiness["internal_only"])
        self.assertTrue(formal_export_page_readiness["readiness_only"])
        self.assertTrue(formal_export_page_readiness["projection_only"])
        self.assertTrue(formal_export_page_readiness["review_only"])
        self.assertTrue(formal_export_page_readiness["release_blocked"])
        self.assertFalse(formal_export_page_readiness["customer_visible_export_enabled"])
        self.assertFalse(formal_export_page_readiness["client_page_release_enabled"])
        self.assertFalse(formal_export_page_readiness["external_release_enabled"])
        self.assertFalse(formal_export_page_readiness["external_delivery_enabled"])
        self.assertFalse(formal_export_page_readiness["direct_export_enabled"])
        self.assertFalse(formal_export_page_readiness["export_artifact_generation_enabled"])
        self.assertFalse(formal_export_page_readiness["page_publication_enabled"])
        leadpack_readiness = leadpack_candidate["leadpack_external_delivery_candidate_readiness"]
        self.assertTrue(leadpack_readiness["approval_audit_readiness_only"])
        self.assertTrue(leadpack_readiness["candidate_only"])
        self.assertTrue(leadpack_readiness["review_only"])
        self.assertFalse(leadpack_readiness["external_delivery_enabled"])
        self.assertFalse(leadpack_readiness["direct_export_enabled"])
        self.assertFalse(leadpack_readiness["customer_visible_export_enabled"])
        self.assertFalse(leadpack_readiness["client_page_release_enabled"])
        self.assertFalse(leadpack_readiness["page_layer_release_enabled"])
        package_readiness = leadpack_candidate["leadpack_delivery_package_readiness"]
        self.assertTrue(package_readiness["owner_operated_workbench"])
        self.assertTrue(package_readiness["package_manifest_visible"])
        self.assertTrue(package_readiness["evidence_item_manifest_visible"])
        self.assertTrue(package_readiness["field_masking_summary_visible"])
        self.assertTrue(package_readiness["field_allowlist_blacklist_visible"])
        self.assertTrue(package_readiness["customer_visible_artifact_candidate_visible"])
        self.assertTrue(package_readiness["watermark_visible"])
        self.assertTrue(package_readiness["artifact_version_hash_visible"])
        self.assertTrue(package_readiness["download_audit_visible"])
        self.assertTrue(package_readiness["export_page_replay_visible"])
        self.assertTrue(package_readiness["page_draft_visible"])
        self.assertTrue(package_readiness["delivery_readiness_visible"])
        self.assertFalse(package_readiness["customer_visible_enabled"])
        self.assertFalse(package_readiness["external_delivery_enabled"])
        self.assertFalse(package_readiness["page_publication_enabled"])
        for operation_id in (
            "requestLeadpackExternalDeliveryCandidateReview",
            "simulateLeadpackExternalDeliveryExport",
            "previewLeadpackActivationPrepPacket",
            "requestLeadpackActivationPrepReview",
            "previewLeadpackActivationDesignImplementationPrepPacket",
            "requestLeadpackActivationDesignImplementationPrepReview",
            "previewLeadpackImplementationDecisionReadinessPacket",
        ):
            operation = mounted_by_id[operation_id]
            self.assertTrue(operation["candidate_only"], operation_id)
            self.assertTrue(operation["readiness_only"], operation_id)
            self.assertTrue(operation["review_only"], operation_id)
            self.assertFalse(operation["external_delivery_enabled"], operation_id)
            self.assertFalse(operation["direct_export_enabled"], operation_id)
            self.assertFalse(operation["client_page_release_enabled"], operation_id)
            self.assertFalse(operation["page_layer_release_enabled"], operation_id)
            self.assertFalse(operation["external_release_enabled"], operation_id)
            self.assertFalse(operation["export_artifact_generation_enabled"], operation_id)
            self.assertFalse(operation["page_publication_enabled"], operation_id)
            self.assertTrue(operation["projection_only"], operation_id)
            self.assertTrue(operation["release_blocked"], operation_id)
            self.assertIn("formal_client_export_page_layer_readiness", operation, operation_id)
            self.assertIn("leadpack_delivery_package_readiness", operation, operation_id)
            self.assertIn("package_page_delivery_summary", operation, operation_id)

        entry_strategy = bootstrap["entry_strategy"]
        self.assertFalse(entry_strategy["stage1_to_stage5"]["http_entry_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["real_transport_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["orchestrator_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["external_live_transport_enabled"])
        self.assertTrue(entry_strategy["stage1_to_stage5"]["internal_orchestration_entry_available"])
        self.assertEqual(
            entry_strategy["stage1_to_stage5"]["internal_orchestration_entry"]["internal_orchestration_path"],
            "/internal/stage1-6/orchestrations",
        )
        self.assertEqual(entry_strategy["stage1_to_stage5"]["reserved_entry_plan"], reserved_entry_plan)
        self.assertTrue(entry_strategy["stage6"]["http_entry_enabled"])
        self.assertIn(
            "previewStage6ReviewReportWorkbench",
            entry_strategy["stage6"]["mounted_operations"],
        )
        self.assertTrue(entry_strategy["stage7_to_stage9"]["http_entry_enabled"])
        self.assertIn(
            "listSaleableOpportunities",
            entry_strategy["stage7_to_stage9"]["mounted_operations_by_stage"]["stage7"],
        )
        self.assertFalse(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_stage1_to_stage5_transport"]
        )
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["http_entry_enabled"])
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["internal_only"])
        self.assertFalse(entry_strategy["stage1_to_stage6_full_chain_entry"]["live_execution_enabled"])
        self.assertEqual(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["accepted_payload_boundary"],
            "SANITIZED_OFFLINE_INTERNAL",
        )
        self.assertEqual(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["operation_id"],
            "runStage1ToStage6InternalOrchestration",
        )
        self.assertFalse(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_external_live_transport"]
        )
        self.assertFalse(entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_real_orchestrator"])
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_existing_internal_chain"])
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["persists_stage6_bundle"])
        self.assertEqual(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["stage6_readback_mode"],
            "repository_backed_preview",
        )
        self.assertEqual(entry_strategy["queue_worker"]["effective_queue_backend"], "storage")
        self.assertTrue(entry_strategy["queue_worker"]["repository_backed"])
        self.assertFalse(entry_strategy["queue_worker"]["redis_connection_enabled"])
        self.assertFalse(entry_strategy["queue_worker"]["stage1_scheduler_enabled"])
        self.assertEqual(entry_strategy["object_storage"]["object_storage_backend"], "local-filesystem")
        self.assertEqual(entry_strategy["object_storage"]["effective_backend"], "local-filesystem")
        self.assertTrue(entry_strategy["object_storage"]["local_filesystem_executable"])
        self.assertTrue(entry_strategy["object_storage"]["snapshot_manifest_repository_backed"])
        self.assertTrue(entry_strategy["object_storage"]["snapshot_readback_replay_enabled"])
        self.assertFalse(entry_strategy["object_storage"]["external_service_connection_enabled"])
        self.assertTrue(entry_strategy["backup_restore"]["backup_manifest_enabled"])
        self.assertTrue(entry_strategy["backup_restore"]["restore_dry_run_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["safe_to_restore"])
        self.assertFalse(entry_strategy["backup_restore"]["destructive_restore_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["restore_execution_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["rollback_execution_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["external_backup_service_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["external_service_connection_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["migration_execution_enabled"])
        self.assertEqual(
            entry_strategy["backup_restore"]["rollback_readiness"],
            bootstrap["rollback_readiness"],
        )
        monitoring_entry = entry_strategy["monitoring_alerting"]
        self.assertEqual(monitoring_entry["monitoring_readiness_state"], "INTERNAL_READBACK_READY")
        self.assertEqual(monitoring_entry["alert_readiness_state"], "CATALOG_READY_READBACK_ONLY")
        self.assertEqual(monitoring_entry["incident_state"], "MANUAL_OWNER_ACTION_READY")
        self.assertTrue(monitoring_entry["repository_backed_readback"])
        self.assertTrue(monitoring_entry["replayable_readback"])
        self.assertFalse(monitoring_entry["notification_enabled"])
        self.assertFalse(monitoring_entry["live_dispatch_enabled"])
        self.assertFalse(monitoring_entry["external_observability_provider_enabled"])
        self.assertFalse(monitoring_entry["external_paging_enabled"])
        self.assertFalse(monitoring_entry["incident_automation_enabled"])
        production_entry = entry_strategy["production_slo_incident_readiness"]
        self.assertEqual(production_entry["capability_state"], "PRODUCTION_READY")
        self.assertEqual(production_entry["readiness_state"], "PRODUCTION_READY")
        self.assertTrue(production_entry["repository_backed_readback"])
        self.assertTrue(production_entry["replayable_readback"])
        self.assertGreaterEqual(production_entry["slo_objective_count"], 10)
        self.assertGreaterEqual(production_entry["alert_rule_count"], 7)
        self.assertTrue(production_entry["simulated_alerts_fire"])
        self.assertEqual(production_entry["incident_runbook_state"], "PRODUCTION_READY")
        self.assertEqual(production_entry["backup_restore_drill_mode"], "DRY_RUN_ONLY")
        self.assertEqual(production_entry["rollback_drill_mode"], "DRY_RUN_ONLY")
        self.assertEqual(production_entry["suspension_state"], "SUSPENDED")
        self.assertTrue(production_entry["manual_resume_required"])
        self.assertFalse(production_entry["real_alert_dispatch_enabled"])
        self.assertFalse(production_entry["incident_automation_enabled"])
        self.assertFalse(production_entry["destructive_restore_enabled"])
        self.assertFalse(production_entry["rollback_execution_enabled"])

        queue_worker = bootstrap["queue_worker_readiness"]
        self.assertEqual(queue_worker["effective_queue_backend"], "storage")
        self.assertEqual(queue_worker["readiness_state"], "EXECUTABLE")
        self.assertTrue(queue_worker["durable_queue_enabled"])
        self.assertTrue(queue_worker["worker_lease_enabled"])
        self.assertTrue(queue_worker["retry_enabled"])
        self.assertTrue(queue_worker["suspend_resume_enabled"])
        self.assertTrue(queue_worker["audit_replay_enabled"])
        self.assertFalse(queue_worker["external_queue_connection_enabled"])
        self.assertFalse(queue_worker["real_provider_execution_enabled"])

        redlines = bootstrap["redlines"]
        self.assertFalse(redlines["new_http_endpoint_added"])
        self.assertTrue(redlines["internal_stage1_to_stage6_http_endpoint_added"])
        self.assertFalse(redlines["new_external_or_live_http_endpoint_added"])
        self.assertFalse(redlines["stage1_to_stage5_real_transport_enabled"])
        self.assertFalse(redlines["stage1_to_stage5_external_live_transport_enabled"])
        self.assertFalse(redlines["external_software_release_enabled"])
        self.assertTrue(redlines["external_leadpack_delivery_requires_approval_and_audit"])
        self.assertFalse(redlines["stage8_real_execution_enabled"])
        self.assertFalse(redlines["stage9_real_payment_delivery_refund_enabled"])
        self.assertFalse(redlines["provider_adapter_live_execution_enabled"])
        self.assertFalse(redlines["provider_adapter_provider_call_enabled"])
        self.assertFalse(redlines["provider_adapter_real_provider_call_enabled"])
        self.assertFalse(redlines["redis_connection_enabled"])
        self.assertFalse(redlines["external_queue_connection_enabled"])
        self.assertFalse(redlines["external_worker_process_enabled"])
        self.assertFalse(redlines["minio_connection_enabled"])
        self.assertFalse(redlines["s3_connection_enabled"])
        self.assertFalse(redlines["external_object_storage_connection_enabled"])
        self.assertFalse(redlines["external_backup_service_enabled"])
        self.assertFalse(redlines["destructive_restore_enabled"])
        self.assertFalse(redlines["restore_execution_enabled"])
        self.assertFalse(redlines["rollback_execution_enabled"])
        self.assertFalse(redlines["migration_execution_enabled"])
        self.assertFalse(redlines["compose_runtime_enabled"])
        self.assertFalse(redlines["container_execution_enabled"])
        self.assertFalse(redlines["docker_compose_up_executed"])
        self.assertFalse(redlines["real_provider_execution_enabled"])
        self.assertFalse(redlines["real_payment_delivery_enabled"])
        self.assertFalse(redlines["provider_credentials_plaintext_persisted"])
        self.assertFalse(redlines["external_observability_provider_enabled"])
        self.assertFalse(redlines["external_apm_enabled"])
        self.assertFalse(redlines["external_paging_enabled"])
        self.assertFalse(redlines["notification_enabled"])
        self.assertFalse(redlines["live_alert_dispatch_enabled"])
        self.assertFalse(redlines["real_alert_dispatch_enabled"])
        self.assertFalse(redlines["incident_automation_enabled"])
        self.assertFalse(redlines["active_storage_mutation_enabled"])
        self.assertFalse(redlines["automated_refund_program_present"])
        self.assertFalse(redlines["automated_refund_program_enabled"])
        self.assertFalse(redlines["automated_refund_enabled"])
        stage9_live_pilot = app.state.transport_bootstrap["entry_strategy"][
            "stage9_payment_delivery_live_pilot"
        ]
        self.assertFalse(stage9_live_pilot["batch_execution_enabled"])
        self.assertTrue(stage9_live_pilot["payment_approval_required"])
        self.assertTrue(stage9_live_pilot["delivery_approval_required"])
        self.assertTrue(stage9_live_pilot["finance_review_required"])
        self.assertTrue(stage9_live_pilot["operator_action_audit_required"])
        self.assertTrue(stage9_live_pilot["artifact_version_lock_required"])
        self.assertTrue(stage9_live_pilot["download_auth_required"])
        self.assertFalse(stage9_live_pilot["provider_call_enabled"])
        self.assertFalse(stage9_live_pilot["real_provider_call_enabled"])
        self.assertFalse(stage9_live_pilot["real_charge_attempted"])
        self.assertFalse(stage9_live_pilot["real_delivery_fulfillment_attempted"])
        self.assertFalse(stage9_live_pilot["real_customer_download_attempted"])
        self.assertFalse(stage9_live_pilot["real_refund_attempted"])
        self.assertFalse(stage9_live_pilot["automated_refund_enabled"])

        local_stack = app.state.transport_bootstrap["local_stack_readiness"]
        self.assertTrue(local_stack["dockerfile_present"])
        self.assertTrue(local_stack["compose_file_present"])
        self.assertTrue(local_stack["docker_compose_config_present"])
        self.assertFalse(local_stack["compose_runtime_enabled"])
        self.assertFalse(local_stack["container_execution_enabled"])
        self.assertFalse(local_stack["docker_compose_up_executed"])
        self.assertEqual(
            app.state.transport_bootstrap["entry_strategy"]["local_stack"]["reserved_services"],
            ["postgres", "redis", "minio"],
        )
        for reserved_service in ("postgres", "redis", "minio"):
            dependency = local_stack["service_dependency_summary"][reserved_service]
            self.assertEqual(dependency["readiness_state"], "RESERVED_NOT_LIVE")
            self.assertFalse(dependency["external_service_connection_enabled"])
            self.assertFalse(dependency["container_execution_enabled"])

        self.assertEqual(len(app.state.disabled_stage_transports), 5)
        self.assertEqual(
            app.state.mounted_transport_operations,
            [operation["operationId"] for operation in mounted_operations],
        )
        self.assertEqual(app.state.storage_bootstrap, app.state.settings.storage_bootstrap_payload())
        self.assertIn("platform_infra_readiness", app.state.storage_bootstrap)
        self.assertEqual(app.state.transport_bootstrap["storage_bootstrap"], app.state.storage_bootstrap)
        self.assertEqual(
            app.state.transport_bootstrap["platform_infra_readiness"],
            app.state.storage_bootstrap["platform_infra_readiness"],
        )
        self.assertEqual(
            app.state.transport_bootstrap["monitoring_alerting_readiness"],
            app.state.storage_bootstrap["monitoring_alerting_readiness"],
        )
        self.assertEqual(
            app.state.monitoring_alerting_readback.payload["readiness_id"],
            "MONITORING_ALERTING_READINESS_CURRENT",
        )
        self.assertEqual(
            app.state.production_slo_incident_readback.payload["readiness_id"],
            "PRODUCTION_SLO_INCIDENT_READINESS_CURRENT",
        )
        self.assertEqual(
            app.state.production_slo_incident_readback.payload,
            app.state.storage_bootstrap["production_slo_incident_readiness"],
        )

    def test_provider_circuit_breaker_status_is_visible_in_api_bootstrap_and_route_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": tmp_dir,
                    "KAKA_PROVIDER_ADAPTER_CIRCUIT_OPEN": "true",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                app = create_app()
                try:
                    bootstrap = app.state.transport_bootstrap
                    mounted_by_id = {
                        operation["operationId"]: operation
                        for operation in bootstrap["stage6_to_stage9_mounted_operations"]
                    }
                    provider_readback = app.state.provider_adapter_config_readback
                finally:
                    app.state.storage_session.close()

        self.assertEqual(bootstrap["provider_reliability_state"], "SUSPENDED")
        self.assertEqual(bootstrap["provider_circuit_breaker_state"], "OPEN")
        self.assertTrue(bootstrap["provider_adapter_suspended"])
        self.assertEqual(set(bootstrap["provider_adapter_suspended_families"]), set(PROVIDER_FAMILIES))
        self.assertTrue(bootstrap["provider_reliability_summary"]["replayable_provider_status"])
        self.assertFalse(bootstrap["provider_reliability_summary"]["live_fallback_allowed"])
        self.assertEqual(provider_readback.governed_state["provider_reliability_state"], "SUSPENDED")
        self.assertEqual(provider_readback.governed_state["provider_circuit_breaker_state"], "OPEN")
        for operation_id in ("listSaleableOpportunities", "listContactTargets", "listOrders"):
            operation = mounted_by_id[operation_id]
            self.assertEqual(operation["provider_reliability_state"], "SUSPENDED")
            self.assertEqual(operation["provider_circuit_breaker_state"], "OPEN")
            self.assertTrue(operation["provider_adapter_suspended"])
            self.assertFalse(operation["provider_adapter_real_provider_call_enabled"])

    def test_create_app_fast_fails_postgres_without_database_url(self) -> None:
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
                get_settings.cache_clear()

                with self.assertRaisesRegex(ValueError, "KAKA_STORAGE_DATABASE_URL"):
                    create_app()

    def test_create_app_fast_fails_unsupported_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "unsupported-backend",
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
                get_settings.cache_clear()

                with self.assertRaisesRegex(ValueError, "unsupported storage backend"):
                    create_app()

    def test_stage1_to_stage5_route_registrars_are_controlled_unavailable(self) -> None:
        registrars = [
            register_stage1_routes,
            register_stage2_routes,
            register_stage3_routes,
            register_stage4_routes,
            register_stage5_routes,
        ]

        for stage_scope, registrar in enumerate(registrars, start=1):
            routes = registrar()
            self.assertEqual(len(routes), 1)
            transport_status = routes[0]
            self.assertEqual(transport_status["stage_scope"], stage_scope)
            self.assertEqual(transport_status["availability_state"], "CONTROLLED_UNAVAILABLE")
            self.assertEqual(transport_status["contract_state"], "CONTRACT_READY")
            self.assertEqual(transport_status["transport_state"], "TRANSPORT_NOT_WIRED")
            self.assertTrue(transport_status["internal_only"])
            self.assertFalse(transport_status["live_execution_enabled"])
            self.assertEqual(
                {
                    key: transport_status[key]
                    for key in RESERVED_ENTRY_PLAN_READBACK_KEYS
                },
                expected_reserved_entry_plan(stage_scope),
            )

    def test_stage6_route_registrar_exposes_internal_queue_surface(self) -> None:
        routes = register_stage6_routes()

        self.assertEqual(len(routes), 3)
        preview_route = next(route for route in routes if route["operationId"] == "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["operationId"], "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["method"], "GET")
        self.assertEqual(preview_route["path"], "/review-report-workbench")
        self.assertEqual(preview_route["surface_mode"], "preview-only")
        self.assertTrue(preview_route["internal_only"])
        self.assertFalse(preview_route["live_execution_enabled"])
        self.assertFalse(preview_route["blocked_by_default"])
        list_route = next(route for route in routes if route["operationId"] == "listStage6WorkItems")
        action_route = next(route for route in routes if route["operationId"] == "submitStage6OperatorAction")
        self.assertEqual(list_route["method"], "GET")
        self.assertEqual(list_route["path"], "/review-report-work-items")
        self.assertEqual(action_route["method"], "POST")
        self.assertEqual(action_route["path"], "/review-report-workbench/{project_fact_id}/operator-actions")
        self.assertTrue(action_route["internal_only"])
        self.assertFalse(action_route["live_execution_enabled"])

    def test_stage1_to_stage6_internal_orchestration_route_registrar_is_separate(self) -> None:
        routes = register_stage1_to_stage6_internal_orchestration_routes()

        self.assertEqual(len(routes), 1)
        orchestration_route = next(
            route for route in routes if route["operationId"] == "runStage1ToStage6InternalOrchestration"
        )
        self.assertEqual(orchestration_route["method"], "POST")
        self.assertEqual(orchestration_route["path"], "/internal/stage1-6/orchestrations")
        self.assertTrue(orchestration_route["internal_only"])
        self.assertFalse(orchestration_route["live_execution_enabled"])
        self.assertEqual(
            orchestration_route["accepted_payload_boundary"],
            "SANITIZED_OFFLINE_INTERNAL",
        )
        self.assertTrue(orchestration_route["repository_backed_readback"])

    def test_create_app_mounts_stage7_to_stage9_transport_routes(self) -> None:
        app = create_app()

        mounted_operation_ids = {
            route.operation_id
            for route in app.routes
            if getattr(route, "operation_id", None)
        }
        self.assertTrue(
            {
                "previewStage6ReviewReportWorkbench",
                "runStage1ToStage6InternalOrchestration",
                "listStage6WorkItems",
                "submitStage6OperatorAction",
                "listSaleableOpportunities",
                "listContactTargets",
                "listOrders",
                "createOutreachPlan",
                "createOrder",
            }.issubset(mounted_operation_ids)
        )
        self.assertEqual(len(app.state.disabled_stage_transports), 5)
        self.assertIn("stage1", app.state.disabled_stage_transports)
        self.assertNotIn("stage6", app.state.disabled_stage_transports)

        reserved_operation_ids = {
            expected["reserved_operation_id"]
            for expected in RESERVED_ENTRY_EXPECTATIONS.values()
        }
        reserved_paths = {
            expected["reserved_path"]
            for expected in RESERVED_ENTRY_EXPECTATIONS.values()
        }
        mounted_paths = {
            getattr(route, "path", None)
            for route in app.routes
        }
        self.assertTrue(reserved_operation_ids.isdisjoint(mounted_operation_ids))
        self.assertTrue(reserved_paths.isdisjoint(mounted_paths))

    def test_stage1_to_stage6_internal_orchestration_runs_repository_backed_readback(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "source_mode": "OFFLINE_FIXTURE",
                "run_mode": "DRY_RUN",
            }
        )

        client = TestClient(create_app())
        response = client.post("/internal/stage1-6/orchestrations", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["operation_id"], "runStage1ToStage6InternalOrchestration")
        self.assertEqual(body["orchestration_scope"], "stage1_to_stage6")
        self.assertEqual(body["payload_boundary"], "SANITIZED_OFFLINE_INTERNAL")
        self.assertTrue(body["internal_only"])
        self.assertFalse(body["live_execution_enabled"])
        self.assertFalse(body["external_live_transport_enabled"])
        self.assertEqual(body["stage1_to_stage5_transport_state"], "BLOCKED_CONTROLLED_UNAVAILABLE")
        self.assertFalse(body["stage1_to_stage5_http_entry_enabled"])
        self.assertFalse(body["stage1_to_stage5_real_transport_enabled"])
        self.assertFalse(body["stage1_to_stage5_external_live_transport_enabled"])
        self.assertTrue(body["stage6_repository_backed_preview"])
        self.assertTrue(body["stage6_persisted"])

        readback = body["stage6_readback"]
        self.assertEqual(readback["surface_id"], "review_report_workbench")
        self.assertEqual(readback["surface_mode"], "preview-only")
        self.assertTrue(readback["internal_only"])
        self.assertFalse(readback["live_execution_enabled"])
        self.assertEqual(readback["operational_context_status"], "persisted")
        self.assertEqual(
            readback["formal_object_refs"]["project_fact"]["object_id"],
            body["stage6_project_fact_id"],
        )
        self.assertEqual(
            readback["preview_projection"]["project_fact_summary"]["project_id"],
            body["stage6_project_id"],
        )

    def test_stage1_to_stage6_internal_orchestration_rejects_live_payloads(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "source_mode": "OFFLINE_FIXTURE",
                "run_mode": "LIVE",
                "live_execution_enabled": True,
            }
        )

        client = TestClient(create_app())
        response = client.post("/internal/stage1-6/orchestrations", json=payload)

        self.assertEqual(response.status_code, 409)
        self.assertIn("run_mode", response.json()["detail"])

    def test_stage6_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = result["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")

        client = TestClient(create_app())
        response = client.request("GET", "/review-report-workbench", json={"project_id": project_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "review_report_workbench")
        self.assertEqual(payload["surface_mode"], "preview-only")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["blocked_by_default"])
        self.assertEqual(
            payload["formal_object_refs"]["project_fact"]["object_id"],
            stage6.record("project_fact").get("project_fact_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["report_record"]["object_id"],
            stage6.record("report_record").get("report_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["review_queue_profile"]["object_id"],
            stage6.record("review_queue_profile").get("queue_profile_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["challenger_candidate_profile"]["object_id"],
            stage6.record("challenger_candidate_profile").get("challenger_profile_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["legal_action_recommendation"]["object_id"],
            stage6.record("legal_action_recommendation").get("action_id"),
        )
        self.assertEqual(
            payload["preview_projection"]["project_fact_summary"]["sale_gate_status"],
            stage6.record("project_fact").get("sale_gate_status"),
        )

    def test_stage6_http_transport_lists_and_submits_operator_actions(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = result["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")
        project_fact_id = stage6.record("project_fact").get("project_fact_id")

        client = TestClient(create_app())
        list_response = client.request("GET", "/review-report-work-items", json={"project_id": project_id})
        action_response = client.request(
            "POST",
            f"/review-report-workbench/{project_fact_id}/operator-actions",
            json={
                "project_id": project_id,
                "action_id": "stage6_return_for_revision",
                "button_flow_id": "submit_stage6_return_for_revision",
                "reason": "transport-level stage6 revision return",
                "requested_by_role": "single_operator",
                "requested_by": "卡卡罗特",
            },
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(action_response.status_code, 200)
        list_payload = list_response.json()
        action_payload = action_response.json()
        self.assertEqual(len(list_payload["work_items"]), 1)
        self.assertEqual(list_payload["work_items"][0]["primary_object_type"], "project_fact")
        self.assertEqual(action_payload["action_result"]["action_id"], "stage6_return_for_revision")
        self.assertEqual(
            action_payload["persisted_operational_context"]["current_operational_state"],
            "action_returned_for_revision",
        )
        self.assertEqual(action_payload["persisted_operational_context"]["pending_actions"], ["stage6_mark_reviewed"])

    def test_stage7_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/saleable-opportunities", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "opportunity_pool")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_ONLY")
        self.assertIn("refreshSaleableOpportunity", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["offer_recommendation"]["object_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["buyer_fit"]["object_id"],
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )
        self.assertEqual(
            payload["crm_quote_workbench"]["quote_draft_id"],
            stage7.inputs["crm_quote_workbench"]["quote_draft_id"],
        )
        self.assertFalse(payload["crm_quote_workbench"]["live_execution_enabled"])
        self.assertFalse(payload["crm_quote_workbench"]["real_external_quote_sent"])
        self.assertEqual(
            payload["crm_quote_workbench_readiness_summary"]["crm_action_id"],
            stage7.inputs["crm_quote_workbench"]["crm_action_id"],
        )
        self.assertEqual(
            payload["leadpack_delivery_package"]["package_id"],
            stage7.inputs["leadpack_delivery_package"]["package_id"],
        )
        self.assertEqual(
            payload["leadpack_delivery_readiness_summary"]["page_draft_id"],
            stage7.inputs["leadpack_delivery_package"]["page_draft_id"],
        )
        self.assertFalse(payload["leadpack_delivery_package"]["customer_visible_enabled"])
        self.assertFalse(payload["leadpack_delivery_package"]["external_delivery_enabled"])
        self.assertFalse(payload["package_page_delivery_summary"]["page_publication_enabled"])

    def test_stage7_crm_quote_readiness_metadata_is_non_live_in_bootstrap_and_readback(self) -> None:
        app = create_app()
        mounted_by_id = {
            operation["operationId"]: operation
            for operation in app.state.transport_bootstrap["stage6_to_stage9_mounted_operations"]
        }
        stage7_metadata = mounted_by_id["listSaleableOpportunities"]["crm_quote_prerequisite_readiness"]
        provider_metadata = mounted_by_id["listSaleableOpportunities"][PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]

        self.assertTrue(stage7_metadata["readiness_only"])
        self.assertEqual(provider_metadata["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(provider_metadata["provider_call_enabled"])
        self.assertFalse(provider_metadata["real_provider_call_enabled"])
        self.assertIn("crm_quote", provider_metadata["families"])
        self.assertIn("leadpack_page_delivery", provider_metadata["families"])
        self.assertTrue(stage7_metadata["prerequisite_only"])
        self.assertTrue(stage7_metadata["blocked_by_default"])
        self.assertEqual(stage7_metadata["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(stage7_metadata["crm_runtime_enabled"])
        self.assertFalse(stage7_metadata["external_quote_enabled"])
        self.assertFalse(stage7_metadata["external_delivery_enabled"])
        self.assertFalse(mounted_by_id["listSaleableOpportunities"]["crm_runtime_enabled"])
        self.assertFalse(mounted_by_id["listSaleableOpportunities"]["external_quote_enabled"])
        self.assertFalse(mounted_by_id["listSaleableOpportunities"]["external_delivery_enabled"])
        self.assertTrue(mounted_by_id["listSaleableOpportunities"]["readiness_only"])
        workbench_metadata = mounted_by_id["listSaleableOpportunities"]["crm_quote_workbench_readiness"]
        self.assertTrue(workbench_metadata["readiness_only"])
        self.assertTrue(workbench_metadata["draft_only"])
        self.assertTrue(workbench_metadata["blocked_live"])
        self.assertTrue(workbench_metadata["repository_backed_readback"])
        self.assertTrue(workbench_metadata["crm_account_sandbox_sync_record_visible"])
        self.assertTrue(workbench_metadata["crm_opportunity_sandbox_sync_record_visible"])
        self.assertTrue(workbench_metadata["crm_activity_sandbox_sync_record_visible"])
        self.assertTrue(workbench_metadata["quote_sandbox_record_visible"])
        self.assertTrue(workbench_metadata["deal_tracking_record_visible"])
        self.assertTrue(workbench_metadata["sales_note_callback_record_visible"])
        self.assertEqual(workbench_metadata["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(workbench_metadata["live_execution_enabled"])
        self.assertFalse(workbench_metadata["real_external_quote_sent"])
        approved_crm_quote_metadata = mounted_by_id["listSaleableOpportunities"][
            "stage7_approved_crm_quote_provider_execution_readiness"
        ]
        self.assertEqual(
            approved_crm_quote_metadata["readiness_scope"],
            "approved_crm_quote_provider_execution_readback",
        )
        self.assertEqual(
            approved_crm_quote_metadata["provider_adapter_scope"],
            "LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER",
        )
        self.assertTrue(approved_crm_quote_metadata["requires_provider_config"])
        self.assertTrue(approved_crm_quote_metadata["requires_sandbox_pass"])
        self.assertTrue(approved_crm_quote_metadata["requires_operator_action_audit"])
        self.assertTrue(approved_crm_quote_metadata["provider_result_readback_visible"])
        self.assertTrue(approved_crm_quote_metadata["deal_tracking_timeline_visible"])
        self.assertFalse(approved_crm_quote_metadata["provider_call_enabled"])
        self.assertFalse(approved_crm_quote_metadata["real_provider_call_enabled"])
        self.assertFalse(approved_crm_quote_metadata["real_crm_sync_enabled"])
        self.assertFalse(approved_crm_quote_metadata["external_quote_sent"])
        package_metadata = mounted_by_id["listSaleableOpportunities"]["leadpack_delivery_package_readiness"]
        self.assertTrue(package_metadata["repository_backed_readback"])
        self.assertTrue(package_metadata["package_manifest_visible"])
        self.assertTrue(package_metadata["customer_visible_artifact_candidate_visible"])
        self.assertTrue(package_metadata["artifact_version_hash_visible"])
        self.assertTrue(package_metadata["download_audit_visible"])
        self.assertTrue(package_metadata["page_draft_visible"])
        self.assertFalse(package_metadata["customer_visible_enabled"])
        self.assertFalse(package_metadata["external_delivery_enabled"])

        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(app)
        response = client.request("GET", "/saleable-opportunities", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        carrier = response.json()["crm_quote_prerequisite_readiness"]
        self.assertEqual(carrier["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertTrue(carrier["readiness_only"])
        self.assertFalse(carrier["crm_runtime_enabled"])
        self.assertFalse(carrier["external_quote_enabled"])
        self.assertFalse(carrier["external_delivery_enabled"])
        self.assertEqual(
            carrier["source_object_refs"]["saleable_opportunity"]["object_id"],
            stage7.record("saleable_opportunity").get("opportunity_id"),
        )
        body = response.json()
        self.assertEqual(body[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(body["crm_quote_workbench"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertFalse(body["leadpack_delivery_package"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertEqual(
            body["crm_quote_workbench"]["quote_draft_id"],
            stage7.inputs["crm_quote_workbench"]["quote_draft_id"],
        )
        self.assertEqual(
            set(body["crm_quote_workbench"]["crm_sandbox_sync_records"]),
            {"account", "opportunity", "activity"},
        )
        self.assertEqual(
            body["crm_quote_workbench"]["quote_sandbox_record"]["quote_sandbox_record_id"],
            stage7.inputs["crm_quote_workbench"]["quote_sandbox_record"]["quote_sandbox_record_id"],
        )
        self.assertFalse(body["crm_quote_workbench"]["live_execution_enabled"])
        self.assertFalse(body["crm_quote_workbench"]["real_external_quote_sent"])
        self.assertIn("approved_crm_quote_execution_summary", body["crm_quote_workbench"])
        self.assertIn("provider_result_readback", body["crm_quote_workbench"])
        self.assertIn("deal_tracking_timeline", body["crm_quote_workbench"])
        self.assertIn("approved_crm_quote_execution_summary", body)
        self.assertIn("provider_result_readback", body)
        self.assertIn("deal_tracking_timeline", body)
        self.assertFalse(body["crm_quote_workbench"]["provider_result_readback"]["provider_call_executed"])
        self.assertFalse(body["crm_quote_workbench"]["provider_result_readback"]["real_provider_call_enabled"])
        self.assertFalse(body["crm_quote_workbench"]["quote_send_record"]["external_quote_sent"])
        self.assertEqual(
            body["crm_quote_workbench"]["provider_execution_id"],
            stage7.inputs["crm_quote_workbench"]["provider_execution_id"],
        )
        self.assertEqual(
            body["crm_quote_workbench_readiness_summary"]["quote_draft_id"],
            stage7.inputs["crm_quote_workbench"]["quote_draft_id"],
        )
        self.assertEqual(
            body["leadpack_delivery_package"]["artifact_manifest_id"],
            stage7.inputs["leadpack_delivery_package"]["artifact_manifest_id"],
        )
        self.assertEqual(
            body["leadpack_delivery_package"]["artifact_version_hash"],
            stage7.inputs["leadpack_delivery_package"]["artifact_version_hash"],
        )
        self.assertEqual(
            body["package_page_delivery_summary"]["export_page_replay"]["replay_id"],
            stage7.inputs["leadpack_delivery_package"]["export_page_replay"]["replay_id"],
        )
        self.assertFalse(body["leadpack_delivery_readiness_summary"]["delivery_ready"])

    def test_stage8_http_transport_reads_repository_backed_preview(self) -> None:
        app = create_app()
        mounted_by_id = {
            operation["operationId"]: operation
            for operation in app.state.transport_bootstrap["stage6_to_stage9_mounted_operations"]
        }
        live_pilot_metadata = mounted_by_id["listContactTargets"]["stage8_live_pilot_readiness"]
        approved_provider_metadata = mounted_by_id["listContactTargets"][
            "stage8_approved_provider_execution_readiness"
        ]
        self.assertEqual(live_pilot_metadata["readiness_scope"], "gated_small_sample_live_pilot_readback")
        self.assertEqual(
            approved_provider_metadata["readiness_scope"],
            "approved_small_sample_provider_execution_readback",
        )
        self.assertEqual(
            set(live_pilot_metadata["supported_adapter_families"]),
            {"email", "sms", "phone_call", "wecom_im"},
        )
        self.assertEqual(
            set(approved_provider_metadata["supported_adapter_families"]),
            {"email", "sms", "phone_call", "wecom_im"},
        )
        self.assertFalse(live_pilot_metadata["batch_send_enabled"])
        self.assertFalse(approved_provider_metadata["batch_send_enabled"])
        self.assertFalse(approved_provider_metadata["bulk_send_enabled"])
        self.assertTrue(approved_provider_metadata["requires_provider_config"])
        self.assertTrue(approved_provider_metadata["requires_sandbox_pass"])
        self.assertTrue(approved_provider_metadata["requires_operator_action_audit"])
        self.assertFalse(live_pilot_metadata["provider_call_enabled"])
        self.assertFalse(live_pilot_metadata["real_provider_call_enabled"])
        self.assertFalse(approved_provider_metadata["provider_call_enabled"])
        self.assertFalse(approved_provider_metadata["real_provider_call_enabled"])
        self.assertEqual(
            approved_provider_metadata["provider_adapter_scope"],
            "LOCAL_CONTROLLED_FAKE_PROVIDER",
        )
        self.assertFalse(live_pilot_metadata["real_send_attempted"])
        self.assertFalse(approved_provider_metadata["real_send_attempted"])
        self.assertFalse(live_pilot_metadata["stage9_payment_delivery_refund_enabled"])
        self.assertFalse(live_pilot_metadata["automated_refund_enabled"])
        self.assertFalse(app.state.transport_bootstrap["entry_strategy"]["stage8_live_pilot"]["real_send_attempted"])
        self.assertFalse(
            app.state.transport_bootstrap["entry_strategy"]["stage8_approved_provider_execution"][
                "real_send_attempted"
            ]
        )

        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        persist_stage_bundle(stage8)
        opportunity_id = stage8.record("touch_record").get("opportunity_id")

        client = TestClient(app)
        response = client.request("GET", "/contact-targets", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "outreach_workbench")
        self.assertTrue(payload["blocked_by_default"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertTrue(payload["outreach_execution_outbox"]["execution_id"].startswith("EXEC-"))
        self.assertEqual(payload["outreach_execution_outbox"]["adapter_family"], "email")
        self.assertEqual(payload["outreach_execution_outbox"]["pilot_scope"], "small_sample")
        self.assertFalse(payload["outreach_execution_outbox"]["batch_send_enabled"])
        self.assertEqual(payload["outreach_execution_outbox"]["live_pilot_readiness_state"], "BLOCKED")
        self.assertFalse(payload["outreach_execution_outbox"]["approved_provider_execution_enabled"])
        self.assertEqual(payload["outreach_execution_outbox"]["execution_request_state"], "BLOCKED")
        self.assertIn("approved_provider_execution_summary", payload["outreach_execution_outbox"])
        self.assertIn("approved_provider_execution_summary", payload)
        self.assertIn("provider_result_readback", payload)
        self.assertIn("execution_timeline", payload)
        self.assertFalse(payload["outreach_execution_outbox"]["provider_result_readback"]["provider_call_executed"])
        self.assertIn("execution_timeline", payload["outreach_execution_outbox"])
        self.assertEqual(
            payload["outbox_readiness_summary"]["execution_id"],
            payload["outreach_execution_outbox"]["execution_id"],
        )
        self.assertIn("live_pilot_readiness_summary", payload["outbox_readiness_summary"])
        self.assertFalse(payload["outreach_execution_outbox"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertFalse(payload["outreach_execution_outbox"]["real_send_attempted"])
        self.assertFalse(payload["outreach_execution_outbox"]["external_delivery_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        self.assertIn("createOutreachPlan", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["contact_target"]["object_id"],
            stage8.record("contact_target").get("contact_target_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["outreach_plan"]["object_id"],
            stage8.record("outreach_plan").get("outreach_plan_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["touch_record"]["object_id"],
            stage8.record("touch_record").get("touch_record_id"),
        )

    def test_stage9_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        persist_stage_bundle(stage9)
        opportunity_id = stage9.record("order_record").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/orders", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "order_delivery_workbench")
        self.assertTrue(payload["blocked_by_default"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(payload["stage9_execution_ledger"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        self.assertIn("createOrder", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["payment_record"]["object_id"],
            stage9.record("payment_record").get("payment_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["delivery_record"]["object_id"],
            stage9.record("delivery_record").get("delivery_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["opportunity_outcome_event"]["object_id"],
            stage9.record("opportunity_outcome_event").get("outcome_event_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["governance_feedback_event"]["object_id"],
            stage9.record("governance_feedback_event").get("governance_feedback_event_id"),
        )
        self.assertEqual(
            payload["stage9_execution_ledger"]["order_id"],
            stage9.record("order_record").get("order_id"),
        )
        self.assertTrue(payload["stage9_execution_ledger_readiness"]["owner_operable"])
        self.assertTrue(payload["stage9_execution_ledger_readiness"]["payment_recording_enabled"])
        self.assertTrue(payload["stage9_execution_ledger_readiness"]["delivery_recording_enabled"])
        self.assertFalse(payload["stage9_execution_ledger_readiness"]["automated_refund_enabled"])
        self.assertEqual(
            payload["payment_sandbox_provider_records"],
            stage9.record("payment_record").get("payment_sandbox_provider_records"),
        )
        self.assertEqual(
            payload["delivery_sandbox_provider_records"],
            stage9.record("delivery_record").get("delivery_sandbox_provider_records"),
        )
        self.assertEqual(
            payload["manual_refund_exception_record"],
            stage9.record("payment_record").get("manual_refund_exception_record"),
        )
        self.assertEqual(
            payload["payment_delivery_live_pilot"],
            stage9.inputs["payment_delivery_live_pilot"],
        )
        self.assertEqual(
            payload["preview_projection"]["payment_delivery_live_pilot_preview"],
            stage9.inputs["payment_delivery_live_pilot"],
        )
        self.assertEqual(
            payload["approved_payment_delivery_execution"],
            stage9.inputs["approved_payment_delivery_execution"],
        )
        self.assertEqual(
            payload["preview_projection"]["approved_payment_delivery_execution_preview"],
            stage9.inputs["approved_payment_delivery_execution"],
        )
        self.assertFalse(
            payload["approved_payment_delivery_execution"][
                "approved_payment_delivery_execution_enabled"
            ]
        )
        self.assertFalse(payload["approved_payment_delivery_execution"]["provider_call_executed"])
        self.assertFalse(payload["approved_payment_delivery_execution"]["real_refund_attempted"])
        self.assertFalse(
            payload["approved_payment_delivery_execution"]["automated_refund_program"]["enabled"]
        )
        self.assertFalse(payload["payment_delivery_live_pilot"]["payment_provider_result_readback"]["provider_call_executed"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["delivery_provider_result_readback"]["provider_call_executed"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["real_charge_attempted"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["real_delivery_fulfillment_attempted"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["real_refund_attempted"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["automated_refund_program"]["enabled"])
        self.assertFalse(
            payload["payment_sandbox_provider_records"]["charge_status_callback_sandbox_record"][
                "payment_capture_enabled"
            ]
        )
        self.assertFalse(
            payload["delivery_sandbox_provider_records"]["delivery_provider_sandbox_record"][
                "real_delivery_fulfillment_attempted"
            ]
        )
        self.assertFalse(
            payload["order_payment_delivery_execution_summary"]["real_payment_gateway_enabled"]
        )


if __name__ == "__main__":
    unittest.main()
