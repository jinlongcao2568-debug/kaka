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
    "KAKA_STORAGE_PATH",
    "KAKA_STORAGE_SCOPE",
    "KAKA_STORAGE_TEST_ISOLATION",
)


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
