from __future__ import annotations

import os
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

from storage.db import DatabaseSession, PersistedStageState, build_persisted_at
from shared.settings import Settings


STORAGE_ENV_KEYS = (
    "KAKA_STORAGE_BACKEND",
    "KAKA_STORAGE_PATH",
    "KAKA_STORAGE_SCOPE",
    "KAKA_STORAGE_TEST_ISOLATION",
)
RESERVED_INFRA_BACKENDS = {
    "postgresql",
    "sqlalchemy",
    "alembic",
    "redis",
    "dramatiq",
    "minio",
    "s3",
    "docker-compose",
}
RESERVED_OR_NOT_CONFIGURED = {"RESERVED_NOT_LIVE", "NOT_CONFIGURED"}


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
                for key in ("KAKA_STORAGE_PATH", "KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
                    os.environ.pop(key, None)

                settings = Settings.from_env()

        self.assertEqual(settings.storage_backend, "postgres")
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
        readiness = settings.storage_bootstrap_payload()["platform_infra_readiness"]
        self.assertEqual(readiness["active_backend"], "postgres")
        self.assertEqual(readiness["postgresql_readiness"]["readiness_state"], "RESERVED_NOT_LIVE")
        self.assertTrue(readiness["postgresql_readiness"]["configured"])
        self.assertFalse(readiness["postgresql_readiness"]["executable"])
        executable_backend_names = [
            entry["backend"]
            for entry in readiness["executable_backends"]
            if entry["executable"]
        ]
        self.assertEqual(executable_backend_names, ["json-file"])

    def test_database_session_default_fast_fails_unsupported_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_backend="postgres",
                storage_path_optional=str(Path(tmp_dir) / "store.json"),
                storage_scope="shared",
                storage_runtime_mode="explicit-path",
            )

            with self.assertRaisesRegex(ValueError, "postgres"):
                DatabaseSession.default_storage_path(settings=settings)
            with self.assertRaisesRegex(ValueError, "postgres"):
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
        self.assertEqual(payload["storage_scope"], "shared")
        self.assertEqual(payload["storage_runtime_mode"], "explicit-path")
        self.assertIn("platform_infra_readiness", payload)

        readiness = payload["platform_infra_readiness"]
        self.assertEqual(readiness["active_backend"], "json-file")
        executable_backends = readiness["executable_backends"]
        self.assertEqual([entry["backend"] for entry in executable_backends], ["json-file"])
        self.assertEqual([entry["backend"] for entry in executable_backends if entry["executable"]], ["json-file"])
        self.assertEqual(executable_backends[0]["readiness_state"], "EXECUTABLE")
        self.assertTrue(executable_backends[0]["configured"])

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
        self.assertEqual(readiness["migration_readiness"]["readiness_state"], "NOT_CONFIGURED")
        self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
        self.assertIn(readiness["queue_readiness"]["readiness_state"], RESERVED_OR_NOT_CONFIGURED)
        self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
        self.assertIn(readiness["object_storage_readiness"]["readiness_state"], RESERVED_OR_NOT_CONFIGURED)
        self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
        self.assertIn(readiness["compose_readiness"]["readiness_state"], RESERVED_OR_NOT_CONFIGURED)
        self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])

        policy = readiness["backend_policy"]
        self.assertTrue(policy["unsupported_backend_fast_fail"])
        self.assertTrue(policy["no_silent_fallback"])
        self.assertTrue(policy["no_migration_execution"])
        self.assertTrue(policy["no_external_service_connection"])
        self.assertTrue(policy["readback_only"])
        self.assertFalse(policy["runtime_behavior_changed"])

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


if __name__ == "__main__":
    unittest.main()
