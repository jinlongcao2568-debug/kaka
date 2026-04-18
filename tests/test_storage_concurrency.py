from __future__ import annotations

import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from storage.db import DatabaseSession, PersistedStageState, build_persisted_at


class TestStorageConcurrency(unittest.TestCase):
    def test_default_storage_path_is_process_scoped(self) -> None:
        path = DatabaseSession.default_storage_path()

        self.assertTrue(path.name.startswith("internal_operator_loop_store-"))
        self.assertTrue(path.name.endswith(".json"))
        self.assertIn(str(os.getpid()), path.name)

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
