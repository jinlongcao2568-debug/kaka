from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.operational_observability import (
    OperationalEventSink,
    OperationalObservabilityConfigError,
    load_operational_events,
    operational_metrics_snapshot,
    record_operational_event_safely,
    render_prometheus_metrics,
)


class OperationalObservabilityTests(unittest.TestCase):
    def test_actual_events_are_persisted_redacted_and_rendered_as_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_path = Path(tmp_dir) / "runtime" / "events.jsonl"
            sink = OperationalEventSink(
                service_name="api",
                event_path=event_path,
                emit_stdout=False,
            )
            success = sink.record(
                component="fetch",
                operation="public_detail",
                outcome="success",
                duration_ms=12.3456,
                trace_id="trace-1",
                attributes={"source_host": "example.com", "api_token": "secret"},
            )
            failure = sink.record(
                component="parse",
                operation="pdf_text",
                outcome="error",
                severity="ERROR",
                error_category="PDF_TEXT_EXTRACT_FAILED",
                attributes={"password_file": "do-not-log", "document_type": "PDF"},
            )

            events = load_operational_events(event_path)
            snapshot = operational_metrics_snapshot(event_path)
            metrics = render_prometheus_metrics(snapshot)

        self.assertTrue(success["recorded"])
        self.assertTrue(failure["alert_eligible"])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["attributes"]["api_token"], "[REDACTED]")
        self.assertEqual(events[1]["attributes"]["password_file"], "[REDACTED]")
        self.assertFalse(events[0]["contains_secret_material"])
        self.assertEqual(snapshot["event_count"], 2)
        self.assertIn("kaka_operational_events_total", metrics)
        self.assertIn('component="fetch"', metrics)
        self.assertIn("kaka_operational_errors_total", metrics)
        self.assertNotIn("secret", metrics)

    def test_private_edge_requires_persistent_event_path(self) -> None:
        with patch.dict(
            os.environ,
            {
                "KAKA_OBSERVABILITY_ENABLED": "true",
                "KAKA_PRIVATE_EDGE_REQUIRED": "true",
            },
            clear=False,
        ):
            os.environ.pop("KAKA_OBSERVABILITY_EVENT_PATH", None)
            with self.assertRaisesRegex(
                OperationalObservabilityConfigError,
                "requires KAKA_OBSERVABILITY_EVENT_PATH",
            ):
                OperationalEventSink.from_env(default_service_name="api")

    def test_invalid_or_truncated_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_path = Path(tmp_dir) / "events.jsonl"
            event_path.write_text('{"event_id":"ok"}\n{"broken":', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON at line 2"):
                load_operational_events(event_path)

    def test_rotation_bounds_primary_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_path = Path(tmp_dir) / "events.jsonl"
            sink = OperationalEventSink(
                service_name="worker",
                event_path=event_path,
                emit_stdout=False,
                max_file_bytes=1024,
            )
            for index in range(20):
                sink.record(
                    component="queue",
                    operation="claim",
                    outcome="success",
                    attributes={"index": index, "message": "x" * 200},
                )
            self.assertTrue(event_path.is_file())
            self.assertTrue(event_path.with_name("events.jsonl.1").is_file())
            self.assertLessEqual(event_path.stat().st_size, 1024)

    def test_disabled_sink_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            event_path = Path(tmp_dir) / "events.jsonl"
            event = OperationalEventSink(
                service_name="api",
                event_path=event_path,
                enabled=False,
                emit_stdout=False,
            ).record(component="api", operation="request", outcome="success")
            self.assertFalse(event["recorded"])
            self.assertFalse(event_path.exists())

    def test_telemetry_write_failure_does_not_replace_business_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent_file = Path(tmp_dir) / "not-a-directory"
            parent_file.write_text("occupied", encoding="utf-8")
            sink = OperationalEventSink(
                service_name="api",
                event_path=parent_file / "events.jsonl",
                emit_stdout=False,
            )

            result = record_operational_event_safely(
                sink,
                component="api",
                operation="request",
                outcome="success",
            )

            self.assertFalse(result["recorded"])
            self.assertEqual(result["recording_state"], "WRITE_FAILED")
            self.assertEqual(result["error_category"], "FileExistsError")


if __name__ == "__main__":
    unittest.main()
