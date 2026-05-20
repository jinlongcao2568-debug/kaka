from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage2_ingestion.scrapling_adaptive_selector_registry import (  # noqa: E402
    SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID,
    ScraplingAdaptiveSelectorProbe,
    build_scrapling_adaptive_selector_registry_readback,
)


class ScraplingAdaptiveSelectorRegistryTests(unittest.TestCase):
    def test_registry_trains_and_relocates_after_selector_drift_without_live_request(self) -> None:
        probes = (
            ScraplingAdaptiveSelectorProbe(
                probe_id="notice_title",
                selector_kind="css",
                selectors=(".notice-title",),
                max_records=1,
            ),
            ScraplingAdaptiveSelectorProbe(
                probe_id="attachment_link",
                selector_kind="css",
                selectors=(".download-link",),
                max_records=1,
            ),
        )
        train_html = """
        <html><body>
          <h1 class="notice-title">测试道路工程中标候选人公示</h1>
          <a class="download-link" href="/files/notice.pdf">候选人公示附件</a>
        </body></html>
        """
        replay_html = """
        <html><body>
          <div class="renamed-title">测试道路工程中标候选人公示</div>
          <a class="file-entry" href="/files/notice.pdf">候选人公示附件</a>
        </body></html>
        """

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            storage_file = Path(temp_dir) / "adaptive.sqlite"
            base_url = "https://example.gov/detail/1.html"
            train_readback = build_scrapling_adaptive_selector_registry_readback(
                train_html,
                base_url=base_url,
                storage_file=storage_file,
                train=True,
                allow_adaptive_relocation=False,
                probes=probes,
                percentage=20,
            )
            replay_readback = build_scrapling_adaptive_selector_registry_readback(
                replay_html,
                base_url=base_url,
                storage_file=storage_file,
                train=False,
                allow_adaptive_relocation=True,
                probes=probes,
                percentage=20,
            )

        self.assertEqual(train_readback["parser_adapter_id"], SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID)
        self.assertTrue(train_readback["no_live_request"])
        self.assertTrue(replay_readback["no_live_request"])
        self.assertEqual(train_readback["registry_state"], "ADAPTIVE_SELECTOR_REGISTRY_PROBED")
        self.assertEqual(replay_readback["registry_state"], "ADAPTIVE_SELECTOR_REGISTRY_PROBED")
        train_summary = train_readback["adaptive_selector_summary"]
        replay_summary = replay_readback["adaptive_selector_summary"]
        self.assertEqual(train_summary["trained_probe_count"], 2)
        self.assertEqual(replay_summary["adaptive_relocated_probe_count"], 2)
        self.assertEqual(set(replay_summary["adaptive_relocated_probe_ids"]), {"notice_title", "attachment_link"})
        replay_by_id = {record["probe_id"]: record for record in replay_readback["probe_records"]}
        self.assertEqual(replay_by_id["notice_title"]["records"][0]["text_probe"], "测试道路工程中标候选人公示")
        self.assertEqual(
            replay_by_id["attachment_link"]["records"][0]["url_optional"],
            "https://example.gov/files/notice.pdf",
        )
        self.assertFalse(replay_by_id["notice_title"]["customer_visible_allowed"])
        self.assertTrue(replay_by_id["notice_title"]["no_legal_conclusion"])

    def test_registry_reports_disabled_when_storage_is_not_configured(self) -> None:
        readback = build_scrapling_adaptive_selector_registry_readback(
            "<html><body><h1>测试标题</h1></body></html>",
            base_url="https://example.gov/detail.html",
            storage_file=None,
        )

        self.assertEqual(readback["registry_state"], "ADAPTIVE_SELECTOR_STORAGE_NOT_CONFIGURED")
        self.assertTrue(readback["no_live_request"])
        self.assertIn("adaptive_selector_storage_not_configured", readback["failure_taxonomy"])
        self.assertEqual(readback["adaptive_selector_summary"]["probe_count"], 5)


if __name__ == "__main__":
    unittest.main()
