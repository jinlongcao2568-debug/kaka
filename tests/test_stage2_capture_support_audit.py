from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage2_capture_support_audit import (  # noqa: E402
    build_stage2_capture_support_audit,
)


class Stage2CaptureSupportAuditTests(unittest.TestCase):
    def test_offline_support_matrix_passes_and_writes_machine_readable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_stage2_capture_support_audit(
                output_root=tmp_dir,
                created_at="2026-07-20T00:00:00+08:00",
            )

            self.assertTrue(result["audit_passed"])
            self.assertEqual(result["summary"]["case_count"], 12)
            self.assertEqual(result["summary"]["failed_case_count"], 0)
            self.assertFalse(
                result["manifest"]["capture_support_policy"][
                    "browser_resolution_enabled_by_default"
                ]
            )
            self.assertEqual(
                result["manifest"]["browser_runtime_budgets"][
                    "detail_browser_route_attempts_max"
                ],
                12,
            )
            output = Path(tmp_dir) / "stage2-capture-support-audit.json"
            self.assertTrue(output.exists())
            self.assertTrue((Path(tmp_dir) / "summary.md").exists())
            reloaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["summary"]["audit_state"], "PASSED")
            mime_case = next(
                case
                for case in reloaded["manifest"]["case_results"]
                if case["case_id"]
                == "misleading_filename_does_not_override_explicit_mime"
            )
            self.assertTrue(mime_case["passed"])


if __name__ == "__main__":
    unittest.main()
