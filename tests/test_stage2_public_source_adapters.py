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
    CREDIT_CHINA_ADAPTER_ID,
    CREDIT_CHINA_ADMINISTRATIVE_PENALTY_RECORD_KIND,
    CREDIT_CHINA_CREDIT_EXCEPTION_RECORD_KIND,
    CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
    CREDIT_CHINA_SOURCE_FAMILY,
    GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND,
    GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
    GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
    LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
    LocalPublicResourceTradingCenterSourceAdapter,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PERSONNEL_RECORD_KIND,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PROJECT_RECORD_KIND,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
    PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
    PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
    PublicSourceAdapterConfig,
    PublicSourceBoundaryError,
    PublicSourceSnapshotRequest,
    PublicSourceTimeoutError,
    PublicSourceTransportError,
    PublicSourceTransportResponse,
    StaticPublicSourceTransport,
    credit_china_adapter_config,
    government_procurement_public_site_adapter_config,
    national_enterprise_credit_publicity_system_adapter_config,
    national_construction_market_platform_adapter_config,
    provincial_bidding_platform_adapter_config,
    resolve_public_source_adapter_config,
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
NATIONAL_ENTERPRISE_HTML_URL = (
    "https://public.example.local/national-construction-market-platform/enterprise/114c.html"
)
NATIONAL_PERSONNEL_SANDBOX_PDF_URL = (
    "sandbox://national-construction-market-platform/personnel/114c.pdf"
)
NATIONAL_PROJECT_ATTACHMENT_URL = (
    "sandbox://national-construction-market-platform/project/114c-attachment.zip"
)
NATIONAL_ENTERPRISE_REGISTRY_ID = "SRC-REG-NCMP-ENTERPRISE-PUBLIC-RECORD"
NATIONAL_PERSONNEL_REGISTRY_ID = "SRC-REG-NCMP-PERSONNEL-PUBLIC-RECORD"
NATIONAL_PROJECT_REGISTRY_ID = "SRC-REG-NCMP-PROJECT-PUBLIC-RECORD"
CREDIT_CHINA_PUBLIC_HTML_URL = (
    "https://public.example.local/credit-china/public-records/114d.html"
)
CREDIT_CHINA_PENALTY_SANDBOX_PDF_URL = (
    "sandbox://credit-china/administrative-penalty/114d.pdf"
)
CREDIT_CHINA_EXCEPTION_ATTACHMENT_URL = (
    "sandbox://credit-china/credit-exception/114d-attachment.zip"
)
CREDIT_CHINA_PUBLIC_REGISTRY_ID = "SRC-REG-CREDIT-CHINA-PUBLIC-RECORD"
CREDIT_CHINA_PENALTY_REGISTRY_ID = "SRC-REG-CREDIT-CHINA-ADMINISTRATIVE-PENALTY"
CREDIT_CHINA_EXCEPTION_REGISTRY_ID = "SRC-REG-CREDIT-CHINA-CREDIT-EXCEPTION"
NECPS_PUBLIC_HTML_URL = (
    "https://public.example.local/national-enterprise-credit-publicity-system/enterprise/114e.html"
)
NECPS_REGISTRATION_SANDBOX_PDF_URL = (
    "sandbox://national-enterprise-credit-publicity-system/registration/114e.pdf"
)
NECPS_ABNORMAL_ATTACHMENT_URL = (
    "sandbox://national-enterprise-credit-publicity-system/abnormal-operation/114e-attachment.zip"
)
NECPS_PUBLIC_REGISTRY_ID = "SRC-REG-NECPS-ENTERPRISE-PUBLIC-RECORD"
NECPS_REGISTRATION_REGISTRY_ID = "SRC-REG-NECPS-ENTERPRISE-REGISTRATION"
NECPS_ABNORMAL_REGISTRY_ID = "SRC-REG-NECPS-ENTERPRISE-ABNORMAL-OPERATION"
GOV_PROC_NOTICE_URL = (
    "https://public.example.local/government-procurement-public-sites/notices/114f.html"
)
GOV_PROC_RESULT_PDF_URL = (
    "sandbox://government-procurement-public-sites/results/114f-result.pdf"
)
GOV_PROC_ATTACHMENT_URL = (
    "sandbox://government-procurement-public-sites/attachments/114f-attachment.zip"
)
GOV_PROC_NOTICE_REGISTRY_ID = "SRC-REG-GOV-PROCUREMENT-NOTICE"
GOV_PROC_RESULT_REGISTRY_ID = "SRC-REG-GOV-PROCUREMENT-RESULT"
GOV_PROC_ATTACHMENT_REGISTRY_ID = "SRC-REG-GOV-PROCUREMENT-ATTACHMENT"


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

    def _national_request(
        self,
        *,
        source_url: str = NATIONAL_ENTERPRISE_HTML_URL,
        source_registry_id: str = NATIONAL_ENTERPRISE_REGISTRY_ID,
        record_kind: str = NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "national-record-v1",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
    ) -> PublicSourceSnapshotRequest:
        return PublicSourceSnapshotRequest(
            source_url=source_url,
            source_registry_id=source_registry_id,
            source_family=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY,
            record_kind=record_kind,
            source_visibility_state=source_visibility_state,
            fetch_mode=fetch_mode,
            snapshot_version=snapshot_version,
            lineage_refs={
                "project_id": "P-114C",
                "stage1_handoff_intent_id": "HINT-114C",
                "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            },
            timeout_seconds=5,
            max_retries=max_retries,
            boundary_flags=boundary_flags or {},
        )

    def _credit_china_request(
        self,
        *,
        source_url: str = CREDIT_CHINA_PUBLIC_HTML_URL,
        source_registry_id: str = CREDIT_CHINA_PUBLIC_REGISTRY_ID,
        record_kind: str = CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "credit-china-record-v1",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
    ) -> PublicSourceSnapshotRequest:
        return PublicSourceSnapshotRequest(
            source_url=source_url,
            source_registry_id=source_registry_id,
            source_family=CREDIT_CHINA_SOURCE_FAMILY,
            record_kind=record_kind,
            source_visibility_state=source_visibility_state,
            fetch_mode=fetch_mode,
            snapshot_version=snapshot_version,
            lineage_refs={
                "project_id": "P-114D",
                "stage1_handoff_intent_id": "HINT-114D",
                "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            },
            timeout_seconds=6,
            max_retries=max_retries,
            boundary_flags=boundary_flags or {},
        )

    def _necps_request(
        self,
        *,
        source_url: str = NECPS_PUBLIC_HTML_URL,
        source_registry_id: str = NECPS_PUBLIC_REGISTRY_ID,
        source_family: str = NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
        record_kind: str = NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "necps-record-v1",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
    ) -> PublicSourceSnapshotRequest:
        return PublicSourceSnapshotRequest(
            source_url=source_url,
            source_registry_id=source_registry_id,
            source_family=source_family,
            record_kind=record_kind,
            source_visibility_state=source_visibility_state,
            fetch_mode=fetch_mode,
            snapshot_version=snapshot_version,
            lineage_refs={
                "project_id": "P-114E",
                "stage1_handoff_intent_id": "HINT-114E",
                "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            },
            timeout_seconds=7,
            max_retries=max_retries,
            boundary_flags=boundary_flags or {},
        )

    def _government_procurement_request(
        self,
        *,
        source_url: str = GOV_PROC_NOTICE_URL,
        source_registry_id: str = GOV_PROC_NOTICE_REGISTRY_ID,
        source_family: str = GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
        record_kind: str = GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "gov-procurement-notice-v1",
        content_type_hint: str | None = None,
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
        lineage_refs: dict[str, str] | None = None,
    ) -> PublicSourceSnapshotRequest:
        resolved_lineage_refs = {
            "project_id": "P-114F",
            "stage1_handoff_intent_id": "HINT-114F",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            "project_lineage_id": "PROJECT-LINEAGE-114F",
        }
        resolved_lineage_refs.update(lineage_refs or {})
        return PublicSourceSnapshotRequest(
            source_url=source_url,
            source_registry_id=source_registry_id,
            source_family=source_family,
            record_kind=record_kind,
            source_visibility_state=source_visibility_state,
            fetch_mode=fetch_mode,
            snapshot_version=snapshot_version,
            content_type_hint=content_type_hint,
            lineage_refs=resolved_lineage_refs,
            timeout_seconds=8,
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

    def test_national_construction_market_enterprise_personnel_project_records_capture_raw_snapshots(self) -> None:
        cases = [
            (
                NATIONAL_ENTERPRISE_HTML_URL,
                NATIONAL_ENTERPRISE_REGISTRY_ID,
                NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                "text/html",
                b"<html><body>national enterprise public record 114C</body></html>",
                "raw_html",
            ),
            (
                NATIONAL_PERSONNEL_SANDBOX_PDF_URL,
                NATIONAL_PERSONNEL_REGISTRY_ID,
                NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PERSONNEL_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/pdf",
                b"%PDF-1.4 national personnel public record",
                "raw_pdf",
            ),
            (
                NATIONAL_PROJECT_ATTACHMENT_URL,
                NATIONAL_PROJECT_REGISTRY_ID,
                NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PROJECT_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/zip",
                b"national project public record attachment",
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
                for source_url, _, _, _, _, content_type, body, _ in cases
            }
            transport = StaticPublicSourceTransport(responses)
            service = Stage2Service()

            for source_url, registry_id, record_kind, visibility, fetch_mode, content_type, body, kind in cases:
                result = service.capture_public_source_snapshot(
                    self._national_request(
                        source_url=source_url,
                        source_registry_id=registry_id,
                        record_kind=record_kind,
                        source_visibility_state=visibility,
                        fetch_mode=fetch_mode,
                        snapshot_version=f"114c-{record_kind}-v1",
                    ),
                    repository=repo,
                    transport=transport,
                )

                metadata = result.raw_snapshot_metadata
                self.assertEqual(result.status, "SNAPSHOT_CAPTURED")
                self.assertEqual(result.adapter_id, NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID)
                self.assertTrue(result.snapshot_id.startswith("SNAP-S2-114C-"))
                self.assertIsNotNone(metadata)
                self.assertEqual(metadata["adapter_id"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID)
                self.assertEqual(metadata["source_family"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY)
                self.assertEqual(metadata["record_kind"], record_kind)
                self.assertEqual(metadata["source_registry_id"], registry_id)
                self.assertEqual(metadata["source_url"], source_url)
                self.assertEqual(metadata["source_visibility_state"], visibility)
                self.assertEqual(metadata["content_type"], content_type)
                self.assertEqual(metadata["byte_size"], len(body))
                self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["snapshot_version"], f"114c-{record_kind}-v1")
                self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114C")
                self.assertEqual(metadata["lineage_refs"]["adapter_id"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID)
                self.assertEqual(metadata["lineage_refs"]["source_family"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY)
                self.assertEqual(metadata["lineage_refs"]["record_kind"], record_kind)
                self.assertEqual(metadata["fetched_at"], NOW)
                self.assertEqual(metadata["captured_at"], NOW)
                self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                self.assertFalse(metadata["fetch_audit"]["uncontrolled_live_crawler_enabled"])
                self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                self.assertEqual(result.readback["snapshot_kind"], kind)
                self.assertEqual(result.readback["readback_state"], "READBACK_READY")
                self.assertEqual(
                    result.readback["manifest"]["raw_snapshot_metadata"]["record_kind"],
                    record_kind,
                )
                self.assertEqual(
                    result.readback["manifest"]["source_health"]["record_kind"],
                    record_kind,
                )

    def test_credit_china_public_penalty_and_exception_records_capture_raw_snapshots(self) -> None:
        cases = [
            (
                CREDIT_CHINA_PUBLIC_HTML_URL,
                CREDIT_CHINA_PUBLIC_REGISTRY_ID,
                CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                "text/html",
                b"<html><body>credit china public record 114D</body></html>",
                "raw_html",
            ),
            (
                CREDIT_CHINA_PENALTY_SANDBOX_PDF_URL,
                CREDIT_CHINA_PENALTY_REGISTRY_ID,
                CREDIT_CHINA_ADMINISTRATIVE_PENALTY_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/pdf",
                b"%PDF-1.4 credit china administrative penalty record",
                "raw_pdf",
            ),
            (
                CREDIT_CHINA_EXCEPTION_ATTACHMENT_URL,
                CREDIT_CHINA_EXCEPTION_REGISTRY_ID,
                CREDIT_CHINA_CREDIT_EXCEPTION_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/zip",
                b"credit china exception record attachment",
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
                for source_url, _, _, _, _, content_type, body, _ in cases
            }
            transport = StaticPublicSourceTransport(responses)
            service = Stage2Service()

            for source_url, registry_id, record_kind, visibility, fetch_mode, content_type, body, kind in cases:
                result = service.capture_public_source_snapshot(
                    self._credit_china_request(
                        source_url=source_url,
                        source_registry_id=registry_id,
                        record_kind=record_kind,
                        source_visibility_state=visibility,
                        fetch_mode=fetch_mode,
                        snapshot_version=f"114d-{record_kind}-v1",
                    ),
                    repository=repo,
                    transport=transport,
                )
                replay = service.replay_public_source_snapshot(result.snapshot_id, repository=repo)

                metadata = result.raw_snapshot_metadata
                self.assertEqual(result.status, "SNAPSHOT_CAPTURED")
                self.assertEqual(result.adapter_id, CREDIT_CHINA_ADAPTER_ID)
                self.assertTrue(result.snapshot_id.startswith("SNAP-S2-114D-"))
                self.assertIsNotNone(metadata)
                self.assertEqual(metadata["adapter_id"], CREDIT_CHINA_ADAPTER_ID)
                self.assertEqual(metadata["source_family"], CREDIT_CHINA_SOURCE_FAMILY)
                self.assertEqual(metadata["record_kind"], record_kind)
                self.assertEqual(metadata["source_registry_id"], registry_id)
                self.assertEqual(metadata["source_url"], source_url)
                self.assertEqual(metadata["source_visibility_state"], visibility)
                self.assertEqual(metadata["content_type"], content_type)
                self.assertEqual(metadata["byte_size"], len(body))
                self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["snapshot_version"], f"114d-{record_kind}-v1")
                self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114D")
                self.assertEqual(metadata["lineage_refs"]["adapter_id"], CREDIT_CHINA_ADAPTER_ID)
                self.assertEqual(metadata["lineage_refs"]["source_family"], CREDIT_CHINA_SOURCE_FAMILY)
                self.assertEqual(metadata["lineage_refs"]["record_kind"], record_kind)
                self.assertEqual(metadata["fetched_at"], NOW)
                self.assertEqual(metadata["captured_at"], NOW)
                self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                self.assertEqual(metadata["fetch_audit"]["source_family"], CREDIT_CHINA_SOURCE_FAMILY)
                self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                self.assertFalse(metadata["fetch_audit"]["uncontrolled_live_crawler_enabled"])
                self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                self.assertEqual(result.readback["snapshot_kind"], kind)
                self.assertEqual(result.readback["readback_state"], "READBACK_READY")
                self.assertEqual(result.readback["content_type"], content_type)
                self.assertEqual(result.readback["byte_size"], len(body))
                self.assertEqual(result.readback["sha256"], metadata["sha256"])
                self.assertEqual(result.readback["bytes"], body)
                self.assertEqual(replay["bytes"], body)
                self.assertEqual(replay["manifest"]["raw_snapshot_metadata"]["record_kind"], record_kind)
                self.assertEqual(replay["manifest"]["source_health"]["record_kind"], record_kind)
                self.assertEqual(repo.read_snapshot_bytes(result.snapshot_id), body)

            policy = self._adapter(
                repo,
                transport,
                config=credit_china_adapter_config(),
            ).runtime_policy()
            self.assertEqual(policy["adapter_id"], CREDIT_CHINA_ADAPTER_ID)
            self.assertEqual(policy["allowed_source_families"], [CREDIT_CHINA_SOURCE_FAMILY])
            self.assertEqual(
                set(policy["allowed_record_kinds"]),
                {
                    CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
                    CREDIT_CHINA_ADMINISTRATIVE_PENALTY_RECORD_KIND,
                    CREDIT_CHINA_CREDIT_EXCEPTION_RECORD_KIND,
                },
            )
            self.assertIn(CREDIT_CHINA_PUBLIC_REGISTRY_ID, policy["allowlisted_source_registry_ids"])
            self.assertEqual(policy["public_url_prefixes"], ["https://public.example.local/credit-china/"])
            self.assertEqual(policy["sandbox_url_prefixes"], ["sandbox://credit-china/"])
            self.assertFalse(policy["uncontrolled_live_crawler_enabled"])
            self.assertFalse(policy["real_provider_connection_enabled"])

    def test_national_enterprise_credit_publicity_system_records_capture_readback_and_replay(self) -> None:
        cases = [
            (
                NECPS_PUBLIC_HTML_URL,
                NECPS_PUBLIC_REGISTRY_ID,
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                "text/html",
                b"<html><body>national enterprise credit public record 114E</body></html>",
                "raw_html",
            ),
            (
                NECPS_REGISTRATION_SANDBOX_PDF_URL,
                NECPS_REGISTRATION_REGISTRY_ID,
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/pdf",
                b"%PDF-1.4 national enterprise registration record",
                "raw_pdf",
            ),
            (
                NECPS_ABNORMAL_ATTACHMENT_URL,
                NECPS_ABNORMAL_REGISTRY_ID,
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                "application/zip",
                b"national enterprise abnormal operation attachment",
                "raw_attachment",
            ),
        ]
        required_metadata_keys = {
            "adapter_id",
            "source_family",
            "record_kind",
            "source_registry_id",
            "source_url",
            "source_visibility_state",
            "content_type",
            "byte_size",
            "sha256",
            "snapshot_version",
            "lineage_refs",
            "fetched_at",
            "captured_at",
            "fetch_mode",
            "fetch_audit",
            "source_health",
            "replay_state",
            "snapshot_id",
            "snapshot_kind",
            "object_key",
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            responses = {
                source_url: PublicSourceTransportResponse(
                    content=body,
                    content_type=content_type,
                    fetched_at=NOW,
                    captured_at=NOW,
                )
                for source_url, _, _, _, _, content_type, body, _ in cases
            }
            transport = StaticPublicSourceTransport(responses)
            service = Stage2Service()

            for source_url, registry_id, record_kind, visibility, fetch_mode, content_type, body, kind in cases:
                result = service.capture_public_source_snapshot(
                    self._necps_request(
                        source_url=source_url,
                        source_registry_id=registry_id,
                        record_kind=record_kind,
                        source_visibility_state=visibility,
                        fetch_mode=fetch_mode,
                        snapshot_version=f"114e-{record_kind}-v1",
                    ),
                    repository=repo,
                    transport=transport,
                )
                replay = service.replay_public_source_snapshot(result.snapshot_id, repository=repo)

                metadata = result.raw_snapshot_metadata
                self.assertEqual(result.status, "SNAPSHOT_CAPTURED")
                self.assertEqual(result.adapter_id, NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID)
                self.assertTrue(result.snapshot_id.startswith("SNAP-S2-114E-"))
                self.assertIsNotNone(metadata)
                self.assertTrue(required_metadata_keys.issubset(metadata))
                self.assertEqual(
                    metadata["adapter_id"],
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
                )
                self.assertEqual(
                    metadata["source_family"],
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
                )
                self.assertEqual(metadata["record_kind"], record_kind)
                self.assertEqual(metadata["source_registry_id"], registry_id)
                self.assertEqual(metadata["source_url"], source_url)
                self.assertEqual(metadata["source_visibility_state"], visibility)
                self.assertEqual(metadata["content_type"], content_type)
                self.assertEqual(metadata["byte_size"], len(body))
                self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["snapshot_version"], f"114e-{record_kind}-v1")
                self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114E")
                self.assertEqual(
                    metadata["lineage_refs"]["adapter_id"],
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
                )
                self.assertEqual(
                    metadata["lineage_refs"]["source_family"],
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
                )
                self.assertEqual(metadata["lineage_refs"]["record_kind"], record_kind)
                self.assertEqual(metadata["fetched_at"], NOW)
                self.assertEqual(metadata["captured_at"], NOW)
                self.assertEqual(metadata["fetch_mode"], fetch_mode)
                self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                self.assertEqual(
                    metadata["fetch_audit"]["source_family"],
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
                )
                self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                self.assertFalse(metadata["fetch_audit"]["uncontrolled_live_crawler_enabled"])
                self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                self.assertEqual(result.readback["snapshot_kind"], kind)
                self.assertEqual(result.readback["readback_state"], "READBACK_READY")
                self.assertEqual(result.readback["content_type"], content_type)
                self.assertEqual(result.readback["byte_size"], len(body))
                self.assertEqual(result.readback["sha256"], metadata["sha256"])
                self.assertEqual(result.readback["bytes"], body)
                self.assertEqual(replay["bytes"], body)
                self.assertEqual(replay["manifest"]["raw_snapshot_metadata"]["record_kind"], record_kind)
                self.assertEqual(replay["manifest"]["source_health"]["record_kind"], record_kind)
                self.assertEqual(repo.read_snapshot_bytes(result.snapshot_id), body)

            policy = self._adapter(
                repo,
                transport,
                config=national_enterprise_credit_publicity_system_adapter_config(),
            ).runtime_policy()
            self.assertEqual(
                policy["adapter_id"],
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
            )
            self.assertEqual(
                policy["allowed_source_families"],
                [NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY],
            )
            self.assertEqual(
                set(policy["allowed_record_kinds"]),
                {
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND,
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND,
                },
            )
            self.assertIn(NECPS_PUBLIC_REGISTRY_ID, policy["allowlisted_source_registry_ids"])
            self.assertIn(NECPS_REGISTRATION_REGISTRY_ID, policy["allowlisted_source_registry_ids"])
            self.assertIn(NECPS_ABNORMAL_REGISTRY_ID, policy["allowlisted_source_registry_ids"])
            self.assertEqual(
                policy["public_url_prefixes"],
                [
                    "https://public.example.local/national-enterprise-credit-publicity-system/",
                ],
            )
            self.assertEqual(
                policy["sandbox_url_prefixes"],
                ["sandbox://national-enterprise-credit-publicity-system/"],
            )
            self.assertFalse(policy["uncontrolled_live_crawler_enabled"])
            self.assertFalse(policy["real_provider_connection_enabled"])

            resolver_cases = [
                self._necps_request(),
                PublicSourceSnapshotRequest(
                    source_url=PUBLIC_HTML_URL,
                    source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                    source_family="PROCUREMENT_NOTICE",
                    record_kind=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND,
                ),
                self._request(source_registry_id=NECPS_PUBLIC_REGISTRY_ID),
                self._request(source_url=NECPS_PUBLIC_HTML_URL),
            ]
            for request in resolver_cases:
                self.assertEqual(
                    resolve_public_source_adapter_config(request).adapter_id,
                    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
                )

    def test_government_procurement_notice_result_attachment_capture_readback_replay_and_metadata(self) -> None:
        required_metadata_keys = {
            "adapter_id",
            "source_family",
            "record_kind",
            "source_registry_id",
            "source_url",
            "source_visibility_state",
            "content_type",
            "byte_size",
            "sha256",
            "snapshot_version",
            "lineage_refs",
            "fetched_at",
            "captured_at",
            "fetch_mode",
            "fetch_audit",
            "source_health",
            "replay_state",
            "snapshot_id",
            "snapshot_kind",
            "object_key",
        }
        notice_body = b"<html><body>government procurement notice 114F</body></html>"
        result_body = b"%PDF-1.4 government procurement result announcement"
        attachment_body = b"government procurement attachment snapshot"

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            service = Stage2Service()
            transport = StaticPublicSourceTransport(
                {
                    GOV_PROC_NOTICE_URL: PublicSourceTransportResponse(
                        content=notice_body,
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    ),
                    GOV_PROC_RESULT_PDF_URL: PublicSourceTransportResponse(
                        content=result_body,
                        content_type="application/pdf",
                        fetched_at=NOW,
                        captured_at=NOW,
                    ),
                    GOV_PROC_ATTACHMENT_URL: PublicSourceTransportResponse(
                        content=attachment_body,
                        content_type="application/zip",
                        fetched_at=NOW,
                        captured_at=NOW,
                    ),
                }
            )

            notice = service.capture_public_source_snapshot(
                self._government_procurement_request(
                    snapshot_version="114f-notice-v1",
                ),
                repository=repo,
                transport=transport,
            )
            result = service.capture_public_source_snapshot(
                self._government_procurement_request(
                    source_url=GOV_PROC_RESULT_PDF_URL,
                    source_registry_id=GOV_PROC_RESULT_REGISTRY_ID,
                    record_kind=GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
                    source_visibility_state="SANDBOX_LOCAL_MIRROR",
                    fetch_mode="sandbox_local_mirror",
                    snapshot_version="114f-result-v1",
                ),
                repository=repo,
                transport=transport,
            )
            attachment = service.capture_public_source_snapshot(
                self._government_procurement_request(
                    source_url=GOV_PROC_ATTACHMENT_URL,
                    source_registry_id=GOV_PROC_ATTACHMENT_REGISTRY_ID,
                    record_kind=GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND,
                    source_visibility_state="SANDBOX_LOCAL_MIRROR",
                    fetch_mode="sandbox_local_mirror",
                    snapshot_version="114f-attachment-v1",
                    lineage_refs={
                        "notice_snapshot_id": notice.snapshot_id,
                        "notice_source_url": GOV_PROC_NOTICE_URL,
                        "parent_record_kind": GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
                    },
                ),
                repository=repo,
                transport=transport,
            )

            cases = [
                (
                    notice,
                    GOV_PROC_NOTICE_URL,
                    GOV_PROC_NOTICE_REGISTRY_ID,
                    GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
                    "PUBLIC_VISIBLE",
                    "controlled_test_transport",
                    "text/html",
                    notice_body,
                    "raw_html",
                    "114f-notice-v1",
                ),
                (
                    result,
                    GOV_PROC_RESULT_PDF_URL,
                    GOV_PROC_RESULT_REGISTRY_ID,
                    GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
                    "SANDBOX_LOCAL_MIRROR",
                    "sandbox_local_mirror",
                    "application/pdf",
                    result_body,
                    "raw_pdf",
                    "114f-result-v1",
                ),
                (
                    attachment,
                    GOV_PROC_ATTACHMENT_URL,
                    GOV_PROC_ATTACHMENT_REGISTRY_ID,
                    GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND,
                    "SANDBOX_LOCAL_MIRROR",
                    "sandbox_local_mirror",
                    "application/zip",
                    attachment_body,
                    "raw_attachment",
                    "114f-attachment-v1",
                ),
            ]

            for capture, source_url, registry_id, record_kind, visibility, fetch_mode, content_type, body, kind, version in cases:
                replay = service.replay_public_source_snapshot(capture.snapshot_id, repository=repo)
                metadata = capture.raw_snapshot_metadata

                self.assertEqual(capture.status, "SNAPSHOT_CAPTURED")
                self.assertEqual(capture.adapter_id, GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID)
                self.assertTrue(capture.snapshot_id.startswith("SNAP-S2-114F-"))
                self.assertIsNotNone(metadata)
                self.assertTrue(required_metadata_keys.issubset(metadata))
                self.assertEqual(metadata["adapter_id"], GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID)
                self.assertEqual(metadata["source_family"], GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY)
                self.assertEqual(metadata["record_kind"], record_kind)
                self.assertEqual(metadata["source_registry_id"], registry_id)
                self.assertEqual(metadata["source_url"], source_url)
                self.assertEqual(metadata["source_visibility_state"], visibility)
                self.assertEqual(metadata["content_type"], content_type)
                self.assertEqual(metadata["byte_size"], len(body))
                self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(metadata["snapshot_version"], version)
                self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114F")
                self.assertEqual(
                    metadata["lineage_refs"]["adapter_id"],
                    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
                )
                self.assertEqual(
                    metadata["lineage_refs"]["source_family"],
                    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
                )
                self.assertEqual(metadata["lineage_refs"]["record_kind"], record_kind)
                self.assertEqual(metadata["fetched_at"], NOW)
                self.assertEqual(metadata["captured_at"], NOW)
                self.assertEqual(metadata["fetch_mode"], fetch_mode)
                self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                self.assertEqual(
                    metadata["fetch_audit"]["source_family"],
                    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
                )
                self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                self.assertFalse(metadata["fetch_audit"]["uncontrolled_live_crawler_enabled"])
                self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                self.assertEqual(capture.readback["snapshot_kind"], kind)
                self.assertEqual(capture.readback["readback_state"], "READBACK_READY")
                self.assertEqual(capture.readback["content_type"], content_type)
                self.assertEqual(capture.readback["byte_size"], len(body))
                self.assertEqual(capture.readback["bytes"], body)
                self.assertEqual(replay["bytes"], body)
                self.assertEqual(replay["manifest"]["raw_snapshot_metadata"]["record_kind"], record_kind)
                self.assertEqual(replay["manifest"]["source_health"]["record_kind"], record_kind)
                self.assertEqual(repo.read_snapshot_bytes(capture.snapshot_id), body)

            attachment_lineage = attachment.raw_snapshot_metadata["lineage_refs"]
            self.assertEqual(attachment_lineage["notice_snapshot_id"], notice.snapshot_id)
            self.assertEqual(attachment_lineage["notice_source_url"], GOV_PROC_NOTICE_URL)
            self.assertEqual(
                attachment_lineage["parent_record_kind"],
                GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
            )

    def test_government_procurement_runtime_policy_resolver_and_adapter_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport({})
            policy = self._adapter(
                repo,
                transport,
                config=government_procurement_public_site_adapter_config(),
            ).runtime_policy()

            self.assertEqual(policy["adapter_id"], GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID)
            self.assertEqual(
                policy["allowed_source_families"],
                [GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY],
            )
            self.assertEqual(
                set(policy["allowed_record_kinds"]),
                {
                    GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
                    GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
                    GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND,
                },
            )
            self.assertEqual(
                set(policy["allowlisted_source_registry_ids"]),
                {
                    GOV_PROC_NOTICE_REGISTRY_ID,
                    GOV_PROC_RESULT_REGISTRY_ID,
                    GOV_PROC_ATTACHMENT_REGISTRY_ID,
                },
            )
            self.assertEqual(
                policy["public_url_prefixes"],
                ["https://public.example.local/government-procurement-public-sites/"],
            )
            self.assertEqual(
                policy["sandbox_url_prefixes"],
                ["sandbox://government-procurement-public-sites/"],
            )
            self.assertFalse(policy["uncontrolled_live_crawler_enabled"])
            self.assertFalse(policy["real_provider_connection_enabled"])

        resolver_cases = [
            self._government_procurement_request(),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
                record_kind=GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
            ),
            self._request(source_registry_id=GOV_PROC_RESULT_REGISTRY_ID),
            self._request(source_url=GOV_PROC_NOTICE_URL),
        ]
        for request in resolver_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
            )

        old_adapter_cases = [
            (self._request(), LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID),
            (self._provincial_request(), PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID),
            (self._national_request(), NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID),
            (self._credit_china_request(), CREDIT_CHINA_ADAPTER_ID),
            (
                self._necps_request(),
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
            ),
            (
                PublicSourceSnapshotRequest(
                    source_url=PROVINCIAL_ATTACHMENT_URL,
                    source_registry_id=PROVINCIAL_ATTACHMENT_REGISTRY_ID,
                    source_family=PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
                    record_kind="attachment",
                ),
                PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
            ),
        ]
        for request, expected_adapter_id in old_adapter_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                expected_adapter_id,
            )

    def test_government_procurement_retry_timeout_rate_limit_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        GOV_PROC_NOTICE_URL: [
                            PublicSourceTimeoutError("government procurement timeout once"),
                            PublicSourceTransportResponse(
                                content=b"<html>government procurement retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=government_procurement_public_site_adapter_config(),
            )
            retry_result = adapter.capture(
                self._government_procurement_request(max_retries=1)
            )

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.adapter_id, GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID)
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(
                retry_result.fetch_audit["retry_events"][0]["reason"],
                "PublicSourceTimeoutError",
            )
            self.assertEqual(
                retry_result.fetch_audit["record_kind"],
                GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
            )
            self.assertEqual(retry_result.source_health["source_health_state"], "HEALTHY")
            self.assertEqual(retry_result.source_health["retry_count"], 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        GOV_PROC_NOTICE_URL: [
                            PublicSourceTimeoutError("government procurement timeout one"),
                            PublicSourceTimeoutError("government procurement timeout two"),
                        ]
                    }
                ),
                config=government_procurement_public_site_adapter_config(),
            )
            timed_out = adapter.capture(
                self._government_procurement_request(max_retries=1)
            )

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.adapter_id, GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(
                timed_out.source_health["record_kind"],
                GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
            )
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["degrade_reason"], "fetch_timeout")
            self.assertEqual(
                timed_out.failure_degrade["readback_state"],
                "NO_SNAPSHOT_DUE_TO_DEGRADE",
            )
            self.assertTrue(timed_out.failure_degrade["manual_review_required"])
            self.assertTrue(timed_out.failure_degrade["fail_closed"])
            self.assertTrue(timed_out.failure_degrade["no_broad_fallback"])
            self.assertEqual(timed_out.fetch_audit["attempt_count"], 2)
            self.assertEqual(timed_out.fetch_audit["transport_mode"], "controlled_test_transport")
            self.assertEqual(
                timed_out.fetch_audit["record_kind"],
                GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    GOV_PROC_NOTICE_URL: PublicSourceTransportResponse(
                        content=b"<html>government procurement rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=government_procurement_public_site_adapter_config(
                    min_interval_seconds=60
                ),
            )
            rate_adapter.capture(self._government_procurement_request())
            rate_limited = rate_adapter.capture(self._government_procurement_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(
                rate_limited.source_health["record_kind"],
                GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
            )
            self.assertTrue(rate_limited.failure_degrade["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(
                rate_limited.fetch_audit["transport_mode"],
                "not_called_due_to_rate_limit",
            )
            self.assertEqual(len(transport.call_log), 1)

    def test_government_procurement_duplicate_capture_keeps_dedupe_metadata_without_source_confusion(self) -> None:
        duplicate_body = b"same government procurement public source bytes"
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        GOV_PROC_NOTICE_URL: PublicSourceTransportResponse(
                            content=duplicate_body,
                            content_type="application/octet-stream",
                            fetched_at=NOW,
                            captured_at=NOW,
                        ),
                        GOV_PROC_RESULT_PDF_URL: PublicSourceTransportResponse(
                            content=duplicate_body,
                            content_type="application/octet-stream",
                            fetched_at=NOW,
                            captured_at=NOW,
                        ),
                    }
                ),
                config=government_procurement_public_site_adapter_config(),
            )

            first = adapter.capture(
                self._government_procurement_request(
                    snapshot_version="114f-duplicate-v1",
                    content_type_hint="application/octet-stream",
                )
            )
            second = adapter.capture(
                self._government_procurement_request(
                    source_url=GOV_PROC_RESULT_PDF_URL,
                    source_registry_id=GOV_PROC_RESULT_REGISTRY_ID,
                    record_kind=GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
                    source_visibility_state="SANDBOX_LOCAL_MIRROR",
                    fetch_mode="sandbox_local_mirror",
                    snapshot_version="114f-duplicate-v1",
                    content_type_hint="application/octet-stream",
                )
            )

            self.assertEqual(first.fetch_audit["dedupe_state"], "NEW_OBJECT_WRITTEN")
            self.assertEqual(
                second.fetch_audit["dedupe_state"],
                "DEDUPED_BY_SHA256_OBJECT_KEY",
            )
            self.assertNotEqual(first.snapshot_id, second.snapshot_id)
            self.assertEqual(
                first.raw_snapshot_metadata["object_key"],
                second.raw_snapshot_metadata["object_key"],
            )
            self.assertEqual(
                first.raw_snapshot_metadata["record_kind"],
                GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
            )
            self.assertEqual(
                second.raw_snapshot_metadata["record_kind"],
                GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
            )
            self.assertEqual(
                repo.replay_snapshot(first.snapshot_id)["manifest"]["raw_snapshot_metadata"]["source_registry_id"],
                GOV_PROC_NOTICE_REGISTRY_ID,
            )
            self.assertEqual(
                repo.replay_snapshot(second.snapshot_id)["manifest"]["raw_snapshot_metadata"]["source_registry_id"],
                GOV_PROC_RESULT_REGISTRY_ID,
            )
            self.assertEqual(repo.read_snapshot_bytes(first.snapshot_id), duplicate_body)
            self.assertEqual(repo.read_snapshot_bytes(second.snapshot_id), duplicate_body)

    def test_government_procurement_blocked_sources_fail_closed_before_transport(self) -> None:
        blocked_requests = [
            self._government_procurement_request(source_registry_id="SRC-REG-GOV-PROCUREMENT-UNKNOWN"),
            self._government_procurement_request(
                source_family="unknown_source_family",
                source_registry_id=GOV_PROC_NOTICE_REGISTRY_ID,
            ),
            self._government_procurement_request(
                source_url="https://unlisted.example.local/government/notice.html"
            ),
            self._government_procurement_request(record_kind="unknown_government_record"),
            self._government_procurement_request(source_visibility_state="PRIVATE"),
            self._government_procurement_request(source_visibility_state="GRAY"),
            self._government_procurement_request(source_visibility_state="LOGIN_REQUIRED"),
            self._government_procurement_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._government_procurement_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._government_procurement_request(source_visibility_state="UNKNOWN"),
            self._government_procurement_request(boundary_flags={"private_source": True}),
            self._government_procurement_request(boundary_flags={"gray_source": True}),
            self._government_procurement_request(boundary_flags={"login_required": True}),
            self._government_procurement_request(boundary_flags={"captcha_required": True}),
            self._government_procurement_request(boundary_flags={"anti_bot_restricted": True}),
            self._government_procurement_request(fetch_mode="live"),
            self._government_procurement_request(fetch_mode="live_crawl"),
            self._government_procurement_request(fetch_mode="uncontrolled_live_crawl"),
            self._government_procurement_request(fetch_mode="crawler"),
            self._government_procurement_request(fetch_mode="real_provider"),
        ]

        for request in blocked_requests:
            with self.subTest(
                source_url=request.source_url,
                state=request.source_visibility_state,
                mode=request.fetch_mode,
            ):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=government_procurement_public_site_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self.assertEqual(raised.exception.carrier["status"], "BLOCKED")
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["blocked_reason"])
                    self.assertFalse(raised.exception.carrier["uncontrolled_live_crawler_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertFalse(raised.exception.carrier["private_or_gray_source_enabled"])
                    self.assertFalse(raised.exception.carrier["login_bypass_enabled"])
                    self.assertFalse(raised.exception.carrier["captcha_bypass_enabled"])
                    self.assertFalse(raised.exception.carrier["anti_bot_bypass_enabled"])
                    self.assertEqual(transport.call_log, [])

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

    def test_national_construction_market_source_health_retry_timeout_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        NATIONAL_ENTERPRISE_HTML_URL: [
                            PublicSourceTimeoutError("national mirror timed out once"),
                            PublicSourceTransportResponse(
                                content=b"<html>national retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=national_construction_market_platform_adapter_config(),
            )
            retry_result = adapter.capture(self._national_request(max_retries=1))

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(retry_result.fetch_audit["retry_events"][0]["reason"], "PublicSourceTimeoutError")
            self.assertEqual(
                retry_result.fetch_audit["record_kind"],
                NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
            )
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
                        NATIONAL_ENTERPRISE_HTML_URL: [
                            PublicSourceTimeoutError("national timeout one"),
                            PublicSourceTimeoutError("national timeout two"),
                        ]
                    }
                ),
                config=national_construction_market_platform_adapter_config(),
            )
            timed_out = adapter.capture(self._national_request(max_retries=1))

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(timed_out.source_health["record_kind"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND)
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["degrade_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["readback_state"], "NO_SNAPSHOT_DUE_TO_DEGRADE")
            self.assertTrue(timed_out.failure_degrade["manual_review_required"])
            self.assertTrue(timed_out.failure_degrade["fail_closed"])
            self.assertEqual(timed_out.fetch_audit["attempt_count"], 2)
            self.assertEqual(timed_out.fetch_audit["record_kind"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    NATIONAL_ENTERPRISE_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html>national rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=national_construction_market_platform_adapter_config(min_interval_seconds=60),
            )
            rate_adapter.capture(self._national_request())
            rate_limited = rate_adapter.capture(self._national_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(rate_limited.source_health["record_kind"], NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND)
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(len(transport.call_log), 1)

    def test_credit_china_source_health_retry_timeout_rate_limit_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        CREDIT_CHINA_PUBLIC_HTML_URL: [
                            PublicSourceTimeoutError("credit china mirror timed out once"),
                            PublicSourceTransportResponse(
                                content=b"<html>credit china retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=credit_china_adapter_config(),
            )
            retry_result = adapter.capture(self._credit_china_request(max_retries=1))

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.adapter_id, CREDIT_CHINA_ADAPTER_ID)
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(retry_result.fetch_audit["retry_events"][0]["reason"], "PublicSourceTimeoutError")
            self.assertEqual(retry_result.fetch_audit["record_kind"], CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND)
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
                        CREDIT_CHINA_PUBLIC_HTML_URL: [
                            PublicSourceTimeoutError("credit china timeout one"),
                            PublicSourceTimeoutError("credit china timeout two"),
                        ]
                    }
                ),
                config=credit_china_adapter_config(),
            )
            timed_out = adapter.capture(self._credit_china_request(max_retries=1))

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.adapter_id, CREDIT_CHINA_ADAPTER_ID)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(timed_out.source_health["record_kind"], CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND)
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["degrade_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["readback_state"], "NO_SNAPSHOT_DUE_TO_DEGRADE")
            self.assertTrue(timed_out.failure_degrade["manual_review_required"])
            self.assertTrue(timed_out.failure_degrade["fail_closed"])
            self.assertTrue(timed_out.failure_degrade["no_broad_fallback"])
            self.assertEqual(timed_out.fetch_audit["attempt_count"], 2)
            self.assertEqual(timed_out.fetch_audit["transport_mode"], "controlled_test_transport")
            self.assertEqual(timed_out.fetch_audit["record_kind"], CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    CREDIT_CHINA_PUBLIC_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html>credit china rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=credit_china_adapter_config(min_interval_seconds=60),
            )
            rate_adapter.capture(self._credit_china_request())
            rate_limited = rate_adapter.capture(self._credit_china_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(rate_limited.source_health["record_kind"], CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND)
            self.assertTrue(rate_limited.failure_degrade["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(rate_limited.fetch_audit["transport_mode"], "not_called_due_to_rate_limit")
            self.assertEqual(len(transport.call_log), 1)

    def test_national_enterprise_credit_publicity_system_source_health_retry_timeout_rate_limit_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        NECPS_PUBLIC_HTML_URL: [
                            PublicSourceTimeoutError("necps mirror timed out once"),
                            PublicSourceTransportResponse(
                                content=b"<html>necps retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=national_enterprise_credit_publicity_system_adapter_config(),
            )
            retry_result = adapter.capture(self._necps_request(max_retries=1))

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(
                retry_result.adapter_id,
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
            )
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(
                retry_result.fetch_audit["retry_events"][0]["reason"],
                "PublicSourceTimeoutError",
            )
            self.assertEqual(
                retry_result.fetch_audit["record_kind"],
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
            )
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
                        NECPS_PUBLIC_HTML_URL: [
                            PublicSourceTimeoutError("necps timeout one"),
                            PublicSourceTimeoutError("necps timeout two"),
                        ]
                    }
                ),
                config=national_enterprise_credit_publicity_system_adapter_config(),
            )
            timed_out = adapter.capture(self._necps_request(max_retries=1))

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(
                timed_out.adapter_id,
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
            )
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(
                timed_out.source_health["record_kind"],
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
            )
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.failure_degrade["degrade_reason"], "fetch_timeout")
            self.assertEqual(
                timed_out.failure_degrade["readback_state"],
                "NO_SNAPSHOT_DUE_TO_DEGRADE",
            )
            self.assertTrue(timed_out.failure_degrade["manual_review_required"])
            self.assertTrue(timed_out.failure_degrade["fail_closed"])
            self.assertTrue(timed_out.failure_degrade["no_broad_fallback"])
            self.assertEqual(timed_out.fetch_audit["attempt_count"], 2)
            self.assertEqual(timed_out.fetch_audit["transport_mode"], "controlled_test_transport")
            self.assertEqual(
                timed_out.fetch_audit["record_kind"],
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    NECPS_PUBLIC_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html>necps rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=national_enterprise_credit_publicity_system_adapter_config(
                    min_interval_seconds=60
                ),
            )
            rate_adapter.capture(self._necps_request())
            rate_limited = rate_adapter.capture(self._necps_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(
                rate_limited.source_health["record_kind"],
                NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
            )
            self.assertTrue(rate_limited.failure_degrade["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(
                rate_limited.fetch_audit["transport_mode"],
                "not_called_due_to_rate_limit",
            )
            self.assertEqual(len(transport.call_log), 1)

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

    def test_national_construction_market_unknown_unlisted_private_gray_login_captcha_antibot_are_blocked_before_transport(self) -> None:
        blocked_requests = [
            self._national_request(source_registry_id="SRC-REG-NCMP-UNKNOWN"),
            self._national_request(source_url="https://unlisted.example.local/ncmp/enterprise.html"),
            self._national_request(record_kind="unknown_public_record"),
            self._national_request(source_visibility_state="PRIVATE"),
            self._national_request(source_visibility_state="GRAY"),
            self._national_request(source_visibility_state="LOGIN_REQUIRED"),
            self._national_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._national_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._national_request(boundary_flags={"private_source": True}),
            self._national_request(boundary_flags={"gray_source": True}),
            self._national_request(boundary_flags={"login_required": True}),
            self._national_request(boundary_flags={"captcha_required": True}),
            self._national_request(boundary_flags={"anti_bot_restricted": True}),
        ]

        for request in blocked_requests:
            with self.subTest(source_url=request.source_url, state=request.source_visibility_state):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=national_construction_market_platform_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self.assertEqual(raised.exception.carrier["status"], "BLOCKED")
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["blocked_reason"])
                    self.assertEqual(transport.call_log, [])

    def test_credit_china_unknown_unlisted_private_gray_login_captcha_antibot_are_blocked_before_transport(self) -> None:
        blocked_requests = [
            self._credit_china_request(source_registry_id="SRC-REG-CREDIT-CHINA-UNKNOWN"),
            self._credit_china_request(source_url="https://unlisted.example.local/credit-china/record.html"),
            self._credit_china_request(record_kind="unknown_credit_record"),
            self._credit_china_request(source_visibility_state="PRIVATE"),
            self._credit_china_request(source_visibility_state="GRAY"),
            self._credit_china_request(source_visibility_state="LOGIN_REQUIRED"),
            self._credit_china_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._credit_china_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._credit_china_request(boundary_flags={"private_source": True}),
            self._credit_china_request(boundary_flags={"gray_source": True}),
            self._credit_china_request(boundary_flags={"login_required": True}),
            self._credit_china_request(boundary_flags={"captcha_required": True}),
            self._credit_china_request(boundary_flags={"anti_bot_restricted": True}),
            self._credit_china_request(fetch_mode="live_crawl"),
            self._credit_china_request(fetch_mode="uncontrolled_live_crawl"),
            self._credit_china_request(fetch_mode="real_provider"),
        ]

        for request in blocked_requests:
            with self.subTest(source_url=request.source_url, state=request.source_visibility_state, mode=request.fetch_mode):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=credit_china_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self.assertEqual(raised.exception.carrier["status"], "BLOCKED")
                    self.assertEqual(raised.exception.carrier["adapter_id"], CREDIT_CHINA_ADAPTER_ID)
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["blocked_reason"])
                    self.assertFalse(raised.exception.carrier["uncontrolled_live_crawler_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertFalse(raised.exception.carrier["login_bypass_enabled"])
                    self.assertFalse(raised.exception.carrier["captcha_bypass_enabled"])
                    self.assertFalse(raised.exception.carrier["anti_bot_bypass_enabled"])
                    self.assertEqual(transport.call_log, [])

    def test_national_enterprise_credit_publicity_system_blocked_sources_fail_closed_before_transport(self) -> None:
        blocked_requests = [
            self._necps_request(source_registry_id="SRC-REG-NECPS-UNKNOWN"),
            self._necps_request(
                source_family="unknown_source_family",
                source_registry_id=NECPS_PUBLIC_REGISTRY_ID,
            ),
            self._necps_request(
                source_url="https://unlisted.example.local/necps/record.html"
            ),
            self._necps_request(record_kind="unknown_enterprise_record"),
            self._necps_request(source_visibility_state="PRIVATE"),
            self._necps_request(source_visibility_state="GRAY"),
            self._necps_request(source_visibility_state="LOGIN_REQUIRED"),
            self._necps_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._necps_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._necps_request(source_visibility_state="UNKNOWN"),
            self._necps_request(boundary_flags={"private_source": True}),
            self._necps_request(boundary_flags={"gray_source": True}),
            self._necps_request(boundary_flags={"login_required": True}),
            self._necps_request(boundary_flags={"captcha_required": True}),
            self._necps_request(boundary_flags={"anti_bot_restricted": True}),
            self._necps_request(fetch_mode="live"),
            self._necps_request(fetch_mode="live_crawl"),
            self._necps_request(fetch_mode="uncontrolled_live_crawl"),
            self._necps_request(fetch_mode="real_provider"),
        ]

        for request in blocked_requests:
            with self.subTest(
                source_url=request.source_url,
                state=request.source_visibility_state,
                mode=request.fetch_mode,
            ):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=national_enterprise_credit_publicity_system_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self.assertEqual(raised.exception.carrier["status"], "BLOCKED")
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["blocked_reason"])
                    self.assertFalse(raised.exception.carrier["uncontrolled_live_crawler_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertFalse(raised.exception.carrier["private_or_gray_source_enabled"])
                    self.assertFalse(raised.exception.carrier["login_bypass_enabled"])
                    self.assertFalse(raised.exception.carrier["captcha_bypass_enabled"])
                    self.assertFalse(raised.exception.carrier["anti_bot_bypass_enabled"])
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
