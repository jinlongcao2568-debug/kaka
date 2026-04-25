from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


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
from storage.repositories import WorkerQueueRepository
from shared.settings import Settings


STORAGE_ENV_KEYS = (
    "KAKA_STORAGE_BACKEND",
    "KAKA_STORAGE_PATH",
    "KAKA_STORAGE_DATABASE_URL",
    "KAKA_STORAGE_SCOPE",
    "KAKA_STORAGE_TEST_ISOLATION",
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


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


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
    def test_default_storage_path_is_stable_without_process_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir}, clear=False):
                for key in STORAGE_ENV_KEYS:
                    os.environ.pop(key, None)

                settings = Settings.from_env()
                settings_path = settings.resolved_storage_path()
                path = DatabaseSession.default_storage_path()

        self.assertEqual(path, Path(tmp_dir) / "kaka" / "internal_operator_loop_store.json")
        self.assertEqual(path.name, "internal_operator_loop_store.json")
        self.assertNotIn(str(os.getpid()), path.name)
        self.assertEqual(settings.storage_backend, "json-file")
        self.assertIsNone(settings.storage_path_optional)
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
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
        self.assertEqual(readiness["migration_readiness"]["readiness_state"], "NOT_CONFIGURED")
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
        self.assertIn(readiness["object_storage_readiness"]["readiness_state"], RESERVED_OR_NOT_CONFIGURED)
        self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
        self.assertIn(readiness["compose_readiness"]["readiness_state"], RESERVED_OR_NOT_CONFIGURED)
        self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])

        policy = readiness["backend_policy"]
        self.assertTrue(policy["unsupported_backend_fast_fail"])
        self.assertTrue(policy["missing_database_url_fast_fail"])
        self.assertTrue(policy["no_silent_fallback"])
        self.assertTrue(policy["no_migration_execution"])
        self.assertTrue(policy["no_external_service_connection"])
        self.assertTrue(policy["readback_only"])
        self.assertFalse(policy["runtime_behavior_changed"])
        redlines = readiness["redlines"]
        self.assertTrue(redlines["no_live_provider_call"])
        self.assertTrue(redlines["no_real_payment"])
        self.assertTrue(redlines["no_real_delivery"])
        self.assertTrue(redlines["no_real_refund"])
        self.assertTrue(redlines["no_automated_refund"])
        self.assertFalse(redlines["external_software_release_enabled"])

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
                for key in ("KAKA_STORAGE_DATABASE_URL", "KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
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
                finally:
                    session.close()

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
                        for key in ("KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
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


if __name__ == "__main__":
    unittest.main()
