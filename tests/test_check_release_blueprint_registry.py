from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load(read_text(relative_path))


class TestSourceBlueprintRegistry(unittest.TestCase):
    def test_registry_marks_required_blueprints_as_valid(self) -> None:
        registry = read_yaml("control/source_blueprint_registry.yaml")
        entries = registry["registered_blueprints"]
        registered = {entry["blueprint_id"]: entry for entry in entries}

        self.assertIn("B10", registered)
        self.assertEqual(registered["B10"]["family"], "legacy_full_repair")
        self.assertIn("FF-18", registered)
        self.assertIn("POST-FF-CONTROL-01", registered)
        self.assertNotIn("UNKNOWN-BATCH", registered)

    def test_registry_covers_legacy_ff_and_post_ff_sets(self) -> None:
        registry = read_yaml("control/source_blueprint_registry.yaml")
        registered = {entry["blueprint_id"] for entry in registry["registered_blueprints"]}

        self.assertTrue({f"B{i}" for i in range(0, 11)}.issubset(registered))
        self.assertTrue({f"FF-{i:02d}" for i in range(1, 19)}.issubset(registered))
        self.assertTrue({"POST-FF-CONTROL-01", "POST-FF-REPORT-01", "POST-FF-GIT-01"}.issubset(registered))

    def test_check_final_gate_uses_new_registry(self) -> None:
        gate_script = read_text("scripts/check-final-gate.ps1")
        self.assertIn("control/source_blueprint_registry.yaml", gate_script)
        self.assertIn("UNREGISTERED_SOURCE_BLUEPRINT_BATCH", gate_script)
        self.assertNotIn("control/task_packet_library.yaml", gate_script)

    def test_current_task_source_blueprint_is_registered(self) -> None:
        current_task = read_yaml("control/current_task.yaml")
        registry = read_yaml("control/source_blueprint_registry.yaml")
        registered = {entry["blueprint_id"] for entry in registry["registered_blueprints"]}
        source_blueprint = current_task["currentTask"]["task_packet"]["source_blueprint_batch_id"]
        self.assertIn(source_blueprint, registered)


if __name__ == "__main__":
    unittest.main()
