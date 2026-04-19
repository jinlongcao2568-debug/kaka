from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read_text(relative_path))


class TestCheckReleaseBlueprintRegistry(unittest.TestCase):
    def test_registry_marks_required_blueprints_as_valid(self) -> None:
        library = read_yaml("control/task_packet_library.yaml")
        entries = library["blueprint_registry"]["registered_blueprints"]
        registered = {entry["blueprint_id"]: entry for entry in entries}

        self.assertIn("B10", registered)
        self.assertEqual(registered["B10"]["family"], "legacy_full_repair")
        self.assertEqual(registered["B10"]["compatibility"], "historical-compatible")
        self.assertIn("FF-18", registered)
        self.assertIn("POST-FF-CONTROL-01", registered)
        self.assertNotIn("UNKNOWN-BATCH", registered)

    def test_registry_covers_legacy_ff_and_post_ff_sets(self) -> None:
        library = read_yaml("control/task_packet_library.yaml")
        registered = {
            entry["blueprint_id"]
            for entry in library["blueprint_registry"]["registered_blueprints"]
        }

        self.assertTrue({f"B{i}" for i in range(0, 11)}.issubset(registered))
        self.assertTrue({f"FF-{i:02d}" for i in range(1, 19)}.issubset(registered))
        self.assertTrue(
            {
                "POST-FF-CONTROL-01",
                "POST-FF-REPORT-01",
                "POST-FF-GIT-01",
            }.issubset(registered)
        )

    def test_check_release_uses_registry_not_b10_or_packet_literals(self) -> None:
        release_script = read_text("scripts/check-release.ps1")

        self.assertIn("BLUEPRINT_REGISTRY_MISSING", release_script)
        self.assertIn("UNREGISTERED_SOURCE_BLUEPRINT_BATCH", release_script)
        self.assertIn("source_blueprint_batch_id", release_script)
        self.assertIn("control/task_packet_library.yaml", release_script)
        self.assertNotIn("CURRENT_TASK_PACKET_ID_MISMATCH", release_script)
        self.assertNotIn("CURRENT_TASK_SUBPACKET_ID_MISMATCH", release_script)
        self.assertNotIn('source_blueprint_batch_id:\\s*"B10"', release_script)

    def test_current_task_source_blueprint_is_registered(self) -> None:
        current_task = read_yaml("control/current_task.yaml")
        library = read_yaml("control/task_packet_library.yaml")
        registered = {
            entry["blueprint_id"]
            for entry in library["blueprint_registry"]["registered_blueprints"]
        }

        source_blueprint = current_task["currentTask"]["task_packet"]["source_blueprint_batch_id"]
        self.assertIn(source_blueprint, registered)


if __name__ == "__main__":
    unittest.main()
