from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from api.deps import get_settings
from api.main import create_app
from runtime.operational_observability import (
    load_operational_events,
    reset_operational_event_sinks,
)
from storage import reset_default_storage
from storage.db import DatabaseSession


class ApiOperationalObservabilityTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()
        reset_operational_event_sinks()
        if DatabaseSession._default is not None:
            DatabaseSession._default.close()
            DatabaseSession._default = None

    def test_api_records_requests_errors_and_exposes_authenticated_metrics(self) -> None:
        async def exercise(app: object) -> tuple[httpx.Response, ...]:
            transport = httpx.ASGITransport(
                app=app,
                client=("testclient", 50000),
                raise_app_exceptions=False,
            )
            headers = {
                "x-kaka-test-operator-auth": "approved",
                "x-kaka-test-role": "owner",
                "x-request-id": "trace-api-1",
            }
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://kaka.internal",
                headers=headers,
            ) as client:
                health = await client.get("/healthz")
                missing = await client.get("/missing-route")
                failed = await client.get("/internal/test-observability-error")
                snapshot = await client.get("/internal/observability")
                metrics = await client.get("/internal/observability/metrics")
            return health, missing, failed, snapshot, metrics

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            event_path = root / "runtime" / "events.jsonl"
            env = {
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_PATH": str(root / "storage.json"),
                "KAKA_OBJECT_STORAGE_PATH": str(root / "objects"),
                "KAKA_OBSERVABILITY_ENABLED": "true",
                "KAKA_OBSERVABILITY_EVENT_PATH": str(event_path),
                "KAKA_OBSERVABILITY_SERVICE_NAME": "api",
                "KAKA_OBSERVABILITY_STDOUT_ENABLED": "false",
                "LOCALAPPDATA": str(root / "local-app-data"),
            }
            with patch.dict(os.environ, env, clear=False):
                for key in (
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_DATABASE_PASSWORD_FILE",
                    "KAKA_STORAGE_DATABASE_HOST",
                    "KAKA_STORAGE_DATABASE_PORT",
                    "KAKA_STORAGE_DATABASE_USER",
                    "KAKA_STORAGE_DATABASE_NAME",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                reset_operational_event_sinks()
                reset_default_storage()
                app = create_app()

                @app.get("/internal/test-observability-error")
                async def fail_for_observability_test() -> None:
                    raise RuntimeError("controlled observability test failure")

                health, missing, failed, snapshot, metrics = asyncio.run(
                    exercise(app)
                )
                events = load_operational_events(event_path)

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.headers["x-request-id"], "trace-api-1")
        self.assertTrue(health.json()["operational_observability"]["enabled"])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(snapshot.status_code, 200)
        self.assertTrue(snapshot.json()["actual_runtime_events"])
        self.assertFalse(snapshot.json()["simulated_readback_only"])
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("kaka_operational_events_total", metrics.text)
        self.assertIn("kaka_operational_errors_total", metrics.text)
        self.assertTrue(
            any(event["outcome"] == "error" for event in events),
            events,
        )
        self.assertTrue(
            any(event["attributes"].get("status_code") == 404 for event in events),
            events,
        )


if __name__ == "__main__":
    unittest.main()
