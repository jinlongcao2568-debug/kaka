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

from storage.guangzhou_detail_transport_diagnostics import (  # noqa: E402
    build_guangzhou_detail_transport_diagnostics,
)


class GuangzhouDetailTransportDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_preserves_route_attempts_and_failure_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_analysis_plan(input_root)
            fetcher = FakeDetailFetcher(
                {
                    "https://example.test/03.html": {
                        "status": "DEGRADED",
                        "http_status": None,
                        "degraded_reasons": ["fetch_failed"],
                        "detail_transport_attempts": [
                            {
                                "route": "guangzhou_https_browser",
                                "state": "FAILED",
                                "failure_taxonomy": ["detail_ssl_protocol_error"],
                            }
                        ],
                        "detail_fetch_repair_state": "DETAIL_BROWSER_FALLBACK_FAILED",
                    }
                }
            )

            result = build_guangzhou_detail_transport_diagnostics(
                input_root=input_root,
                output_root=output_root,
                project_ids=["PROJ-CN-GD-JG2026-10815"],
                flow_nos=["03"],
                execute=True,
                fetcher=fetcher,
                created_at="2026-05-11T00:00:00+08:00",
            )

            summary = result["summary"]
            self.assertEqual(summary["detail_url_count"], 1)
            self.assertEqual(summary["failed_count"], 1)
            self.assertEqual(summary["failure_taxonomy_counts"]["detail_ssl_protocol_error"], 1)
            self.assertEqual(summary["route_state_counts"]["guangzhou_https_browser:FAILED"], 1)
            self.assertTrue((output_root / "detail-transport-diagnostics.json").exists())
            self.assertTrue((output_root / "manual-detail-transport-check-table.json").exists())

    def test_diagnostics_planned_mode_does_not_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_analysis_plan(input_root)
            fetcher = FakeDetailFetcher({})

            result = build_guangzhou_detail_transport_diagnostics(
                input_root=input_root,
                output_root=output_root,
                execute=False,
                fetcher=fetcher,
                created_at="2026-05-11T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["planned_count"], 1)
            self.assertEqual(fetcher.calls, [])


class FakeDetailFetcher:
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def fetch_candidate_detail_url(self, url: str, **kwargs: object) -> dict:
        self.calls.append({"url": url, **kwargs})
        return dict(self.responses[url])


def _write_analysis_plan(input_root: Path) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "items": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "广州测试项目",
                    "flow_no": "03",
                    "flow_title": "招标公告/关联公告",
                    "document_kind": "tender_file",
                    "source_url": "https://example.test/03.html",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            ]
        }
    }
    (input_root / "analysis-plan.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
