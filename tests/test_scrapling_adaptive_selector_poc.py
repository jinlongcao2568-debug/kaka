from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage2_ingestion.scrapling_adaptive_selector_poc import (  # noqa: E402
    STAGE2_SCRAPLING_ADAPTIVE_SELECTOR_POC_KIND,
    build_stage2_scrapling_adaptive_selector_poc,
)


class ScraplingAdaptiveSelectorPocTests(unittest.TestCase):
    def test_poc_recovers_selector_drift_with_local_html_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            result = build_stage2_scrapling_adaptive_selector_poc(output_dir=temp_dir, percentage=20)
            json_exists = Path(result["json_path"]).exists()
            markdown_exists = Path(result["markdown_path"]).exists()

        manifest = result["manifest"]
        self.assertEqual(manifest["kind"], STAGE2_SCRAPLING_ADAPTIVE_SELECTOR_POC_KIND)
        self.assertTrue(manifest["no_live_request_all_true"])
        self.assertFalse(manifest["customer_visible_allowed"])
        self.assertTrue(manifest["no_legal_conclusion"])
        self.assertTrue(manifest["acceptance"]["selector_drift_recovered"])
        self.assertEqual(manifest["acceptance"]["trained_probe_count"], 3)
        self.assertEqual(manifest["acceptance"]["adaptive_relocated_probe_count"], 3)
        self.assertTrue(json_exists)
        self.assertTrue(markdown_exists)


if __name__ == "__main__":
    unittest.main()
