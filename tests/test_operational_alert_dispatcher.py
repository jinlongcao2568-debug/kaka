from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from runtime.operational_alert_dispatcher import (
    OperationalAlertConfig,
    OperationalAlertConfigError,
    OperationalAlertDispatcher,
)
from runtime.operational_observability import OperationalEventSink


class _WebhookHandler(BaseHTTPRequestHandler):
    response_codes: list[int] = []
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(content_length)
        type(self).requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        status = type(self).response_codes.pop(0) if type(self).response_codes else 202
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"accepted":true}')

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class OperationalAlertDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        _WebhookHandler.response_codes = []
        _WebhookHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _WebhookHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _config(
        self,
        tmp_dir: str,
        *,
        max_attempts: int = 3,
    ) -> OperationalAlertConfig:
        root = Path(tmp_dir)
        secret_file = root / "alert-secret"
        secret_file.write_bytes(b"controlled-alert-secret-32-bytes!!")
        return OperationalAlertConfig(
            event_path=root / "events.jsonl",
            state_path=root / "state.json",
            dead_letter_path=root / "dead-letter.jsonl",
            webhook_url=f"http://127.0.0.1:{self.server.server_port}/alerts",
            allowed_hosts=frozenset({"127.0.0.1"}),
            signing_secret_file=secret_file,
            max_attempts=max_attempts,
            allow_http_loopback=True,
        )

    @staticmethod
    def _record_alert_eligible_event(path: Path, *, component: str = "fetch") -> dict:
        return OperationalEventSink(
            service_name="worker",
            event_path=path,
            emit_stdout=False,
        ).record(
            component=component,
            operation="controlled_drill_failure",
            outcome="error",
            severity="ERROR",
            trace_id="TRACE-ALERT-DRILL-1",
            error_category="CONTROLLED_DRILL",
            attributes={"source_host": "example.gov.cn", "api_token": "must-redact"},
        )

    def test_actual_webhook_delivery_is_signed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._config(tmp_dir)
            source_event = self._record_alert_eligible_event(config.event_path)
            dispatcher = OperationalAlertDispatcher(config)

            first = dispatcher.dispatch_once(now_unix_seconds=100.0)
            second = dispatcher.dispatch_once(now_unix_seconds=101.0)

            self.assertEqual(first["delivered_count"], 1)
            self.assertEqual(second["attempted_count"], 0)
            self.assertEqual(len(_WebhookHandler.requests), 1)
            request = _WebhookHandler.requests[0]
            body = bytes(request["body"])
            headers = {str(k).lower(): str(v) for k, v in dict(request["headers"]).items()}
            expected_signature = hmac.new(
                config.signing_secret_file.read_bytes().strip(),
                body,
                hashlib.sha256,
            ).hexdigest()
            payload = json.loads(body)
            self.assertEqual(headers["x-kaka-alert-id"], source_event["event_id"])
            self.assertEqual(headers["x-kaka-signature"], f"sha256={expected_signature}")
            self.assertEqual(payload["component"], "fetch")
            self.assertEqual(payload["attributes"]["api_token"], "[REDACTED]")
            self.assertNotIn("controlled-alert-secret", body.decode("utf-8"))

    def test_retry_backoff_then_dead_letter_is_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._config(tmp_dir, max_attempts=2)
            source_event = self._record_alert_eligible_event(config.event_path)
            _WebhookHandler.response_codes = [500, 503]
            dispatcher = OperationalAlertDispatcher(config)

            first = dispatcher.dispatch_once(now_unix_seconds=100.0)
            too_early = dispatcher.dispatch_once(now_unix_seconds=100.5)
            final = dispatcher.dispatch_once(now_unix_seconds=101.0)

            self.assertEqual(first["retry_scheduled_count"], 1)
            self.assertEqual(too_early["attempted_count"], 0)
            self.assertEqual(final["dead_lettered_count"], 1)
            state = json.loads(config.state_path.read_text(encoding="utf-8"))
            dead_letter = json.loads(config.dead_letter_path.read_text(encoding="utf-8"))
            self.assertIn(source_event["event_id"], state["dead_letter_event_ids"])
            self.assertEqual(dead_letter["event_id"], source_event["event_id"])
            self.assertEqual(dead_letter["attempt_count"], 2)
            self.assertEqual(len(_WebhookHandler.requests), 2)

    def test_dispatcher_error_events_are_not_recursively_alerted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._config(tmp_dir)
            self._record_alert_eligible_event(config.event_path, component="alert_dispatch")

            result = OperationalAlertDispatcher(config).dispatch_once()

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(_WebhookHandler.requests, [])

    def test_url_allowlist_example_secret_and_invalid_state_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            secret = root / "secret"
            secret.write_text("replace-with-random-32-byte-secret\n", encoding="utf-8")
            with self.assertRaisesRegex(OperationalAlertConfigError, "example"):
                OperationalAlertConfig(
                    event_path=root / "events.jsonl",
                    state_path=root / "state.json",
                    dead_letter_path=root / "dead.jsonl",
                    webhook_url="https://alerts.example.com/hook",
                    allowed_hosts=frozenset({"alerts.example.com"}),
                    signing_secret_file=secret,
                )

            secret.write_bytes(b"controlled-alert-secret-32-bytes!!")
            with self.assertRaisesRegex(OperationalAlertConfigError, "exactly match"):
                OperationalAlertConfig(
                    event_path=root / "events.jsonl",
                    state_path=root / "state.json",
                    dead_letter_path=root / "dead.jsonl",
                    webhook_url="https://evil.example.com/hook",
                    allowed_hosts=frozenset({"alerts.example.com"}),
                    signing_secret_file=secret,
                )
            with self.assertRaisesRegex(OperationalAlertConfigError, "controlled egress proxy"):
                OperationalAlertConfig(
                    event_path=root / "events.jsonl",
                    state_path=root / "state.json",
                    dead_letter_path=root / "dead.jsonl",
                    webhook_url="https://alerts.example.com/hook",
                    allowed_hosts=frozenset({"alerts.example.com"}),
                    signing_secret_file=secret,
                )

            config = self._config(tmp_dir)
            config.state_path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(OperationalAlertConfigError, "invalid"):
                OperationalAlertDispatcher(config).dispatch_once()


if __name__ == "__main__":
    unittest.main()
