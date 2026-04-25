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
    LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
    LocalPublicResourceTradingCenterSourceAdapter,
    PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
    PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
    PublicSourceAdapterConfig,
    PublicSourceBoundaryError,
    PublicSourceSnapshotRequest,
    PublicSourceTimeoutError,
    PublicSourceTransportError,
    PublicSourceTransportResponse,
    StaticPublicSourceTransport,
    provincial_bidding_platform_adapter_config,
)
from stage2_ingestion.service import Stage2Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


NOW = "2026-04-25T00:00:00+00:00"
PUBLIC_HTML_URL = (
    "https://public.example.local/local-public-resource-trading-centers/notices/114a.html"
)
SANDBOX_PDF_URL = "sandbox://local-public-resource-trading-centers/mirror/114a.pdf"
PROVINCIAL_HTML_URL = (
    "https://public.example.local/provincial-bidding-platforms/notices/114b.html"
)
PROVINCIAL_SANDBOX_PDF_URL = "sandbox://provincial-bidding-platforms/mirror/114b.pdf"
PROVINCIAL_ATTACHMENT_URL = (
    "sandbox://provincial-bidding-platforms/mirror/114b-attachment.docx"
)
PROVINCIAL_HTML_REGISTRY_ID = "SRC-REG-PROV-BID-ANNOUNCEMENT-HTML"
PROVINCIAL_PDF_REGISTRY_ID = "SRC-REG-PROV-BID-ANNOUNCEMENT-PDF"
PROVINCIAL_ATTACHMENT_REGISTRY_ID = "SRC-REG-PROV-BID-ATTACHMENT"


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

    def _provincial_request(
        self,
        *,
        source_url: str = PROVINCIAL_HTML_URL,
        source_registry_id: str = PROVINCIAL_HTML_REGISTRY_ID,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "provincial-notice-v1",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
    ) -> PublicSourceSnapshotRequest:
        return PublicSourceSnapshotRequest(
            source_url=source_url,
            source_registry_id=source_registry_id,
            source_family=PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
            source_visibility_state=source_visibility_state,
            fetch_mode=fetch_mode,
            snapshot_version=snapshot_version,
            lineage_refs={
                "project_id": "P-114B",
                "stage1_handoff_intent_id": "HINT-114B",
                "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            },
            timeout_seconds=4,
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

    def test_provincial_bidding_platform_allowlisted_source_can_capture_raw_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    PROVINCIAL_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html><body>provincial bidding notice 114B</body></html>",
                        content_type="text/html; charset=utf-8",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )

            result = Stage2Service().capture_public_source_snapshot(
                self._provincial_request(),
                repository=repo,
                transport=transport,
            )

            metadata = result.raw_snapshot_metadata
            self.assertEqual(result.status, "SNAPSHOT_CAPTURED")
            self.assertIsNotNone(metadata)
            self.assertEqual(result.adapter_id, PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID)
            self.assertEqual(metadata["adapter_id"], PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID)
            self.assertEqual(metadata["source_family"], PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY)
            self.assertEqual(metadata["source_registry_id"], PROVINCIAL_HTML_REGISTRY_ID)
            self.assertEqual(metadata["source_url"], PROVINCIAL_HTML_URL)
            self.assertEqual(metadata["source_visibility_state"], "PUBLIC_VISIBLE")
            self.assertEqual(metadata["content_type"], "text/html; charset=utf-8")
            self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(metadata["snapshot_version"], "provincial-notice-v1")
            self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114B")
            self.assertEqual(metadata["lineage_refs"]["source_registry_id"], PROVINCIAL_HTML_REGISTRY_ID)
            self.assertEqual(metadata["fetched_at"], NOW)
            self.assertEqual(metadata["captured_at"], NOW)
            self.assertEqual(metadata["fetch_audit"]["transport_mode"], "controlled_test_transport")
            self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
            self.assertFalse(metadata["fetch_audit"]["uncontrolled_live_crawler_enabled"])
            self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
            self.assertTrue(result.snapshot_id.startswith("SNAP-S2-114B-"))
            self.assertEqual(result.readback["readback_state"], "READBACK_READY")
            self.assertEqual(
                result.readback["manifest"]["raw_snapshot_metadata"]["source_health"]["source_health_state"],
                "HEALTHY",
            )

    def test_provincial_html_pdf_and_attachment_metadata_keep_hash_version_and_lineage(self) -> None:
        cases = [
            (
                PROVINCIAL_HTML_URL,
                PROVINCIAL_HTML_REGISTRY_ID,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                "text/html",
                b"<html>provincial notice</html>",
                "raw_html",
            ),
            (
                PROVINCIAL_SANDBOX_PDF_URL,
                PROVINCIAL_PDF_REGISTRY_ID,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/pdf",
                b"%PDF-1.4 provincial sandbox bytes",
                "raw_pdf",
            ),
            (
                PROVINCIAL_ATTACHMENT_URL,
                PROVINCIAL_ATTACHMENT_REGISTRY_ID,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                b"provincial attachment bytes",
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
                for source_url, _, _, _, content_type, body, _ in cases
            }
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(responses),
                config=provincial_bidding_platform_adapter_config(),
            )

            for source_url, registry_id, visibility, fetch_mode, content_type, body, kind in cases:
                result = adapter.capture(
                    self._provincial_request(
                        source_url=source_url,
                        source_registry_id=registry_id,
                        source_visibility_state=visibility,
                        fetch_mode=fetch_mode,
                        snapshot_version=f"114b-{kind}-v1",
                    )
                )

                metadata = result.raw_snapshot_metadata
                self.assertEqual(metadata["adapter_id"], PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID)
                self.assertEqual(metadata["source_family"], PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY)
                self.assertEqual(metadata["content_type"], content_type)
                self.assertEqual(metadata["byte_size"], len(body))
                self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["snapshot_version"], f"114b-{kind}-v1")
                self.assertEqual(metadata["lineage_refs"]["stage_scope"], "2")
                self.assertEqual(metadata["lineage_refs"]["adapter_id"], PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID)
                self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                self.assertEqual(metadata["source_health"]["failure_degrade_state"], "NOT_DEGRADED")
                self.assertEqual(result.readback["snapshot_kind"], kind)
                self.assertEqual(result.readback["manifest"]["snapshot_version_optional"], f"114b-{kind}-v1")

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

    def test_provincial_source_health_retry_timeout_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        PROVINCIAL_HTML_URL: [
                            PublicSourceTimeoutError("provincial mirror timed out once"),
                            PublicSourceTransportResponse(
                                content=b"<html>provincial retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=provincial_bidding_platform_adapter_config(),
            )
            retry_result = adapter.capture(self._provincial_request(max_retries=1))

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(retry_result.fetch_audit["retry_events"][0]["reason"], "PublicSourceTimeoutError")
            self.assertEqual(retry_result.source_health["source_health_state"], "HEALTHY")
            self.assertEqual(retry_result.source_health["retry_count"], 1)
            self.assertEqual(
                retry_result.readback["manifest"]["source_health"]["retry_count"],
                1,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        PROVINCIAL_HTML_URL: [
                            PublicSourceTimeoutError("provincial timeout one"),
                            PublicSourceTimeoutError("provincial timeout two"),
                        ]
                    }
                ),
                config=provincial_bidding_platform_adapter_config(),
            )
            timed_out = adapter.capture(self._provincial_request(max_retries=1))

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["degrade_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["readback_state"], "NO_SNAPSHOT_DUE_TO_DEGRADE")
            self.assertTrue(timed_out.failure_degrade["manual_review_required"])
            self.assertTrue(timed_out.failure_degrade["fail_closed"])
            self.assertEqual(timed_out.fetch_audit["attempt_count"], 2)
            self.assertEqual(timed_out.fetch_audit["transport_mode"], "controlled_test_transport")

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

        with tempfile.TemporaryDirectory() as tmp_dir:
            transport = StaticPublicSourceTransport({})
            adapter = self._adapter(self._repo(tmp_dir), transport)
            with self.assertRaises(PublicSourceBoundaryError) as raised:
                adapter.capture(
                    self._request(source_url="https://unlisted.example.local/public/notice.html")
                )
            self.assertEqual(raised.exception.reason, "source_url_not_allowlisted")
            self.assertEqual(transport.call_log, [])

    def test_provincial_unknown_unlisted_private_gray_login_captcha_antibot_are_blocked_before_transport(self) -> None:
        blocked_requests = [
            self._provincial_request(source_registry_id="SRC-REG-PROV-BID-UNKNOWN"),
            self._provincial_request(source_url="https://unlisted.example.local/provincial/notice.html"),
            self._provincial_request(source_visibility_state="PRIVATE"),
            self._provincial_request(source_visibility_state="GRAY"),
            self._provincial_request(source_visibility_state="LOGIN_REQUIRED"),
            self._provincial_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._provincial_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._provincial_request(boundary_flags={"private_source": True}),
            self._provincial_request(boundary_flags={"gray_source": True}),
            self._provincial_request(boundary_flags={"login_required": True}),
            self._provincial_request(boundary_flags={"captcha_required": True}),
            self._provincial_request(boundary_flags={"anti_bot_restricted": True}),
        ]

        for request in blocked_requests:
            with self.subTest(source_url=request.source_url, state=request.source_visibility_state):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=provincial_bidding_platform_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self.assertEqual(raised.exception.carrier["status"], "BLOCKED")
                    self.assertTrue(raised.exception.carrier["source_boundary"]["blocked_reason"])
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
            self.assertEqual(result.adapter_id, LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID)
            self.assertTrue(result.snapshot_id.startswith("SNAP-S2-114A-"))
            self.assertEqual(
                result.raw_snapshot_metadata["adapter_id"],
                LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
            )
            self.assertEqual(replay["readback_state"], "READBACK_READY")
            self.assertTrue(hasattr(service, "run"))


if __name__ == "__main__":
    unittest.main()
