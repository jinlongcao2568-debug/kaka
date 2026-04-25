from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from stage2_ingestion.public_source_adapters import (
    LocalPublicResourceTradingCenterSourceAdapter,
    PublicSourceAdapterConfig,
    PublicSourceBoundaryError,
    PublicSourceSnapshotRequest,
    PublicSourceTimeoutError,
    PublicSourceTransportError,
    PublicSourceTransportResponse,
    StaticPublicSourceTransport,
)
from stage2_ingestion.service import Stage2Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


NOW = "2026-04-25T00:00:00+00:00"
PUBLIC_HTML_URL = (
    "https://public.example.local/local-public-resource-trading-centers/notices/114a.html"
)
SANDBOX_PDF_URL = "sandbox://local-public-resource-trading-centers/mirror/114a.pdf"


class Stage2PublicSourceAdapterTests(unittest.TestCase):
    def _repo(self, tmp_dir: str) -> ObjectStorageRepository:
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(Path(tmp_dir) / "repo.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(Path(tmp_dir) / "objects"),
        )
        return ObjectStorageRepository(
            session=DatabaseSession(settings=settings),
            settings=settings,
        )

    def _request(
        self,
        *,
        source_url: str = PUBLIC_HTML_URL,
        source_registry_id: str = "SRC-REG-PROC-NATIONAL-HTML",
        source_family: str = "PROCUREMENT_NOTICE",
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "notice-v1",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
    ) -> PublicSourceSnapshotRequest:
        return PublicSourceSnapshotRequest(
            source_url=source_url,
            source_registry_id=source_registry_id,
            source_family=source_family,
            source_visibility_state=source_visibility_state,
            fetch_mode=fetch_mode,
            snapshot_version=snapshot_version,
            lineage_refs={
                "project_id": "P-114A",
                "stage1_handoff_intent_id": "HINT-114A",
            },
            timeout_seconds=3,
            max_retries=max_retries,
            boundary_flags=boundary_flags or {},
        )

    def _adapter(
        self,
        repo: ObjectStorageRepository,
        transport: StaticPublicSourceTransport,
        *,
        config: PublicSourceAdapterConfig | None = None,
    ) -> LocalPublicResourceTradingCenterSourceAdapter:
        return LocalPublicResourceTradingCenterSourceAdapter(
            repository=repo,
            transport=transport,
            config=config,
            clock=lambda: NOW,
        )

    def test_allowlisted_public_source_generates_raw_snapshot_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    PUBLIC_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html><body>public notice 114A</body></html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )

            result = self._adapter(repo, transport).capture(self._request())

            metadata = result.raw_snapshot_metadata
            self.assertEqual(result.status, "SNAPSHOT_CAPTURED")
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata["adapter_id"], "stage2.local_public_resource_trading_center.v1")
            self.assertEqual(metadata["source_family"], "PROCUREMENT_NOTICE")
            self.assertEqual(metadata["source_url"], PUBLIC_HTML_URL)
            self.assertEqual(metadata["source_visibility_state"], "PUBLIC_VISIBLE")
            self.assertEqual(metadata["content_type"], "text/html")
            self.assertEqual(metadata["byte_size"], len(b"<html><body>public notice 114A</body></html>"))
            self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(metadata["snapshot_version"], "notice-v1")
            self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114A")
            self.assertEqual(metadata["fetched_at"], NOW)
            self.assertEqual(metadata["captured_at"], NOW)
            self.assertEqual(metadata["fetch_mode"], "controlled_test_transport")
            self.assertEqual(metadata["replay_state"], "READBACK_READY")
            self.assertFalse(metadata["fetch_audit"]["uncontrolled_live_crawler_enabled"])
            self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
            self.assertEqual(result.readback["readback_state"], "READBACK_READY")
            self.assertEqual(result.readback["manifest"]["raw_snapshot_metadata"]["sha256"], metadata["sha256"])

    def test_html_pdf_and_attachment_snapshots_carry_hash_version_and_lineage(self) -> None:
        cases = [
            (
                PUBLIC_HTML_URL,
                "SRC-REG-PROC-NATIONAL-HTML",
                "PUBLIC_VISIBLE",
                "text/html",
                b"<html>notice</html>",
                "raw_html",
            ),
            (
                SANDBOX_PDF_URL,
                "SRC-REG-PROC-CITY-PDF",
                "SANDBOX_LOCAL_MIRROR",
                "application/pdf",
                b"%PDF-1.4 local sandbox bytes",
                "raw_pdf",
            ),
            (
                "sandbox://local-public-resource-trading-centers/mirror/114a-attachment.bin",
                "SRC-REG-PROC-CITY-PDF",
                "SANDBOX_LOCAL_MIRROR",
                "application/octet-stream",
                b"attachment bytes",
                "raw_attachment",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            responses = {
                source_url: PublicSourceTransportResponse(
                    content=body,
                    content_type=content_type,
                    fetched_at=NOW,
                    captured_at=NOW,
                )
                for source_url, _, _, content_type, body, _ in cases
            }
            adapter = self._adapter(repo, StaticPublicSourceTransport(responses))

            for source_url, source_registry_id, visibility, content_type, body, kind in cases:
                result = adapter.capture(
                    self._request(
                        source_url=source_url,
                        source_registry_id=source_registry_id,
                        source_visibility_state=visibility,
                        snapshot_version=f"{kind}-v1",
                    )
                )

                metadata = result.raw_snapshot_metadata
                self.assertEqual(metadata["content_type"], content_type)
                self.assertEqual(metadata["byte_size"], len(body))
                self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["snapshot_version"], f"{kind}-v1")
                self.assertEqual(metadata["lineage_refs"]["stage_scope"], "2")
                self.assertEqual(result.readback["snapshot_kind"], kind)
                self.assertEqual(result.readback["manifest"]["snapshot_version_optional"], f"{kind}-v1")

    def test_snapshot_readback_replay_and_missing_refs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            data = b"<html>readback replay</html>"
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        PUBLIC_HTML_URL: PublicSourceTransportResponse(
                            content=data,
                            content_type="text/html",
                            fetched_at=NOW,
                            captured_at=NOW,
                        )
                    }
                ),
            )

            result = adapter.capture(self._request())
            replay = repo.replay_snapshot(result.snapshot_id)
            missing_manifest = repo.replay_snapshot("SNAP-S2-114A-MISSING")
            object_key = replay["object_key"]
            repo.object_store.object_path(object_key).unlink()
            missing_object = repo.replay_snapshot(result.snapshot_id)

            self.assertEqual(replay["bytes"], data)
            self.assertEqual(replay["readback_state"], "READBACK_READY")
            self.assertTrue(replay["replayable"])
            self.assertEqual(missing_manifest["readback_state"], "MISSING_MANIFEST")
            self.assertTrue(missing_manifest["fail_closed"])
            self.assertTrue(missing_manifest["no_broad_fallback"])
            self.assertEqual(missing_object["readback_state"], "MISSING_OBJECT")
            self.assertTrue(missing_object["fail_closed"])
            self.assertTrue(missing_object["no_broad_fallback"])

    def test_retry_timeout_rate_limit_failure_degrade_and_source_health_are_explainable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            retry_transport = StaticPublicSourceTransport(
                {
                    PUBLIC_HTML_URL: [
                        PublicSourceTimeoutError("timed out once"),
                        PublicSourceTransportResponse(
                            content=b"<html>retry success</html>",
                            content_type="text/html",
                            fetched_at=NOW,
                            captured_at=NOW,
                        ),
                    ]
                }
            )
            retry_result = self._adapter(repo, retry_transport).capture(
                self._request(max_retries=1)
            )

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(retry_result.source_health["source_health_state"], "HEALTHY")
            self.assertEqual(retry_result.source_health["retry_count"], 1)
            self.assertEqual(retry_result.fetch_audit["retry_events"][0]["reason"], "PublicSourceTimeoutError")

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            rate_transport = StaticPublicSourceTransport(
                {
                    PUBLIC_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html>rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                rate_transport,
                config=PublicSourceAdapterConfig(min_interval_seconds=60),
            )
            rate_adapter.capture(self._request())
            rate_limited = rate_adapter.capture(self._request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertEqual(len(rate_transport.call_log), 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            failing = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        PUBLIC_HTML_URL: [
                            PublicSourceTransportError("connection refused in sandbox"),
                            PublicSourceTransportError("still refused in sandbox"),
                        ]
                    }
                ),
            ).capture(self._request(max_retries=1))

            self.assertEqual(failing.status, "DEGRADED")
            self.assertEqual(failing.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(failing.failure_degrade["degrade_reason"], "fetch_failed")
            self.assertTrue(failing.failure_degrade["manual_review_required"])
            self.assertTrue(failing.failure_degrade["no_broad_fallback"])
            self.assertEqual(failing.fetch_audit["attempt_count"], 2)

    def test_private_gray_login_captcha_antibot_and_unknown_sources_are_rejected(self) -> None:
        blocked_visibility_states = [
            "PRIVATE",
            "GRAY",
            "LOGIN_REQUIRED",
            "CAPTCHA_REQUIRED",
            "ANTI_BOT_RESTRICTED",
            "UNKNOWN",
        ]
        for visibility_state in blocked_visibility_states:
            with self.subTest(visibility_state=visibility_state):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(self._repo(tmp_dir), transport)
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(
                            self._request(source_visibility_state=visibility_state)
                        )
                    self.assertIn("blocked", raised.exception.carrier["status"].lower())
                    self.assertEqual(transport.call_log, [])

        blocked_flag_sets = [
            {"private_source": True},
            {"gray_source": True},
            {"login_required": True},
            {"captcha_required": True},
            {"anti_bot_restricted": True},
        ]
        for flags in blocked_flag_sets:
            with self.subTest(flags=flags):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(self._repo(tmp_dir), transport)
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(self._request(boundary_flags=flags))
                    self.assertTrue(raised.exception.carrier["source_boundary"]["blocked_reason"])
                    self.assertEqual(transport.call_log, [])

        with tempfile.TemporaryDirectory() as tmp_dir:
            transport = StaticPublicSourceTransport({})
            adapter = self._adapter(self._repo(tmp_dir), transport)
            with self.assertRaises(PublicSourceBoundaryError) as raised:
                adapter.capture(
                    self._request(source_registry_id="SRC-REG-UNKNOWN")
                )
            self.assertIn("unknown_or_unregistered_source", raised.exception.reason)
            self.assertEqual(transport.call_log, [])

    def test_uncontrolled_live_crawler_modes_are_blocked_before_transport(self) -> None:
        for fetch_mode in ("live_crawl", "uncontrolled_live_crawl", "real_provider"):
            with self.subTest(fetch_mode=fetch_mode):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(self._repo(tmp_dir), transport)
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(self._request(fetch_mode=fetch_mode))
                    self.assertIn("blocked_fetch_mode", raised.exception.reason)
                    self.assertEqual(transport.call_log, [])
                    self.assertFalse(adapter.runtime_policy()["uncontrolled_live_crawler_enabled"])
                    self.assertFalse(adapter.runtime_policy()["real_provider_connection_enabled"])

    def test_stage2_service_exposes_adapter_without_polluting_stage1_or_stage3_to_stage9(self) -> None:
        adapter_text = (SRC / "stage2_ingestion" / "public_source_adapters.py").read_text(encoding="utf-8")
        for forbidden_import in (
            "stage1_tasking",
            "stage3_parsing",
            "stage4_verification",
            "stage5_rules_evidence",
            "stage6_fact_review",
            "stage7_sales",
            "stage8_outreach",
            "stage9_delivery",
        ):
            self.assertNotIn(forbidden_import, adapter_text)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            service = Stage2Service()
            result = service.capture_public_source_snapshot(
                self._request(),
                repository=repo,
                transport=StaticPublicSourceTransport(
                    {
                        PUBLIC_HTML_URL: PublicSourceTransportResponse(
                            content=b"<html>service seam</html>",
                            content_type="text/html",
                            fetched_at=NOW,
                            captured_at=NOW,
                        )
                    }
                ),
            )
            replay = service.replay_public_source_snapshot(result.snapshot_id, repository=repo)

            self.assertEqual(result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(replay["readback_state"], "READBACK_READY")
            self.assertTrue(hasattr(service, "run"))


if __name__ == "__main__":
    unittest.main()
