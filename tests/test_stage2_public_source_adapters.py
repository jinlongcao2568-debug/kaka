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
    CONTROLLED_CHALLENGE_FLAG_NAMES,
    CONTROLLED_CHALLENGE_VISIBILITY_STATES,
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
    INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_FILING_RECORD_KIND,
    INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
    INDUSTRY_AUTHORITY_CONTRACT_FILING_RECORD_KIND,
    INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
    INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
    INDUSTRY_AUTHORITY_FILING_TYPES,
    INDUSTRY_AUTHORITY_PERFORMANCE_FILING_RECORD_KIND,
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
    TENDER_AGENCY_AWARD_RESULT_RECORD_KIND,
    TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND,
    TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND,
    TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID,
    TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY,
    TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
    TENDERER_AWARD_RESULT_RECORD_KIND,
    TENDERER_CANDIDATE_NOTICE_RECORD_KIND,
    TENDERER_CORRECTION_NOTICE_RECORD_KIND,
    TENDERER_OWNER_NOTICE_RECORD_KIND,
    TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID,
    TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY,
    credit_china_adapter_config,
    government_procurement_public_site_adapter_config,
    industry_authority_filing_page_adapter_config,
    national_enterprise_credit_publicity_system_adapter_config,
    national_construction_market_platform_adapter_config,
    provincial_bidding_platform_adapter_config,
    resolve_public_source_adapter_config,
    tender_agency_public_site_adapter_config,
    tenderer_public_notice_page_adapter_config,
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
TENDER_AGENCY_TENDER_NOTICE_URL = (
    "https://public.example.local/tender-agency-public-sites/notices/114g-tender.html"
)
TENDER_AGENCY_CORRECTION_NOTICE_URL = (
    "sandbox://tender-agency-public-sites/corrections/114g-correction.html"
)
TENDER_AGENCY_CANDIDATE_NOTICE_URL = (
    "https://public.example.local/tender-agency-public-sites/candidates/114g-candidate.html"
)
TENDER_AGENCY_AWARD_RESULT_URL = (
    "sandbox://tender-agency-public-sites/results/114g-award-result.html"
)
TENDER_AGENCY_TENDER_NOTICE_REGISTRY_ID = "SRC-REG-TENDER-AGENCY-TENDER-NOTICE"
TENDER_AGENCY_CORRECTION_NOTICE_REGISTRY_ID = (
    "SRC-REG-TENDER-AGENCY-CORRECTION-NOTICE"
)
TENDER_AGENCY_CANDIDATE_NOTICE_REGISTRY_ID = (
    "SRC-REG-TENDER-AGENCY-CANDIDATE-NOTICE"
)
TENDER_AGENCY_AWARD_RESULT_REGISTRY_ID = (
    "SRC-REG-TENDER-AGENCY-AWARD-RESULT"
)
TENDERER_OWNER_NOTICE_URL = (
    "https://public.example.local/tenderer-public-notice-pages/notices/114h-owner.html"
)
TENDERER_CORRECTION_NOTICE_URL = (
    "sandbox://tenderer-public-notice-pages/corrections/114h-correction.html"
)
TENDERER_CANDIDATE_NOTICE_URL = (
    "https://public.example.local/tenderer-public-notice-pages/candidates/114h-candidate.html"
)
TENDERER_AWARD_RESULT_URL = (
    "sandbox://tenderer-public-notice-pages/results/114h-award-result.html"
)
TENDERER_OWNER_NOTICE_REGISTRY_ID = "SRC-REG-TENDERER-OWNER-NOTICE"
TENDERER_CORRECTION_NOTICE_REGISTRY_ID = "SRC-REG-TENDERER-CORRECTION-NOTICE"
TENDERER_CANDIDATE_NOTICE_REGISTRY_ID = "SRC-REG-TENDERER-CANDIDATE-NOTICE"
TENDERER_AWARD_RESULT_REGISTRY_ID = "SRC-REG-TENDERER-AWARD-RESULT"
INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL = (
    "https://public.example.local/industry-authority-filing-pages/permits/114i-permit.html"
)
INDUSTRY_AUTHORITY_CONTRACT_FILING_URL = (
    "sandbox://industry-authority-filing-pages/contracts/114i-contract.html"
)
INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_URL = (
    "https://public.example.local/industry-authority-filing-pages/completion/114i-completion.html"
)
INDUSTRY_AUTHORITY_PERFORMANCE_FILING_URL = (
    "sandbox://industry-authority-filing-pages/performance/114i-performance.html"
)
INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_REGISTRY_ID = (
    "SRC-REG-INDUSTRY-AUTHORITY-CONSTRUCTION-PERMIT"
)
INDUSTRY_AUTHORITY_CONTRACT_FILING_REGISTRY_ID = (
    "SRC-REG-INDUSTRY-AUTHORITY-CONTRACT-FILING"
)
INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_REGISTRY_ID = (
    "SRC-REG-INDUSTRY-AUTHORITY-COMPLETION-ACCEPTANCE"
)
INDUSTRY_AUTHORITY_PERFORMANCE_FILING_REGISTRY_ID = (
    "SRC-REG-INDUSTRY-AUTHORITY-PERFORMANCE-FILING"
)


class Stage2PublicSourceAdapterTests(unittest.TestCase):
    def _expected_boundary_status(self, request: PublicSourceSnapshotRequest) -> str:
        visibility_state = str(request.source_visibility_state or "").strip()
        boundary_flags = {str(key): bool(value) for key, value in request.boundary_flags.items()}
        if visibility_state in CONTROLLED_CHALLENGE_VISIBILITY_STATES or any(
            boundary_flags.get(flag_name) for flag_name in CONTROLLED_CHALLENGE_FLAG_NAMES
        ):
            return "AUTOMATED_CHALLENGE_RESOLUTION_PENDING"
        return "BLOCKED"

    def _assert_boundary_status(
        self,
        raised: unittest.case._AssertRaisesContext[PublicSourceBoundaryError],
        request: PublicSourceSnapshotRequest,
    ) -> None:
        expected_status = self._expected_boundary_status(request)
        carrier = raised.exception.carrier
        source_boundary = carrier["source_boundary"]
        self.assertEqual(carrier["status"], expected_status)
        self.assertEqual(
            carrier["result_state"],
            "AUTOMATED_CHALLENGE_RESOLUTION_BEFORE_TRANSPORT"
            if expected_status == "AUTOMATED_CHALLENGE_RESOLUTION_PENDING"
            else "BLOCKED_BEFORE_TRANSPORT",
        )
        self.assertTrue(source_boundary["boundary_reason"])
        if expected_status == "AUTOMATED_CHALLENGE_RESOLUTION_PENDING":
            self.assertEqual(source_boundary["boundary_action"], "ROUTE_TO_AUTOMATED_CHALLENGE_RESOLUTION")
            self.assertIsNone(source_boundary["blocked_reason"])
            self.assertTrue(source_boundary["controlled_challenge"])
            self.assertTrue(source_boundary["automated_challenge_resolution_first"])
            self.assertFalse(source_boundary["resume_requires_human_input"])
            self.assertTrue(source_boundary["challenge_resolution_reason"])
        else:
            self.assertEqual(source_boundary["boundary_action"], "BLOCK")
            self.assertTrue(source_boundary["blocked_reason"])
            self.assertFalse(source_boundary.get("controlled_challenge", False))

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

    def _tender_agency_request(
        self,
        *,
        source_url: str = TENDER_AGENCY_TENDER_NOTICE_URL,
        source_registry_id: str = TENDER_AGENCY_TENDER_NOTICE_REGISTRY_ID,
        source_family: str = TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY,
        record_kind: str = TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "tender-agency-notice-v1",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
        lineage_refs: dict[str, str] | None = None,
    ) -> PublicSourceSnapshotRequest:
        resolved_lineage_refs = {
            "project_id": "P-114G",
            "stage1_handoff_intent_id": "HINT-114G",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            "project_lineage_id": "PROJECT-LINEAGE-114G",
            "agency_name_optional": "Example Tender Agency",
            "agency_site_domain_optional": "public.example.local",
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
            lineage_refs=resolved_lineage_refs,
            timeout_seconds=9,
            max_retries=max_retries,
            boundary_flags=boundary_flags or {},
        )

    def _tenderer_request(
        self,
        *,
        source_url: str = TENDERER_OWNER_NOTICE_URL,
        source_registry_id: str = TENDERER_OWNER_NOTICE_REGISTRY_ID,
        source_family: str = TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY,
        record_kind: str = TENDERER_OWNER_NOTICE_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "tenderer-owner-notice-v1",
        notice_authority_role: str = "owner",
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
        lineage_refs: dict[str, str] | None = None,
    ) -> PublicSourceSnapshotRequest:
        resolved_lineage_refs = {
            "project_id": "P-114H",
            "stage1_handoff_intent_id": "HINT-114H",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            "project_lineage_id": "PROJECT-LINEAGE-114H",
            "tenderer_name_optional": "Example Tenderer Owner",
            "tenderer_site_domain_optional": "public.example.local",
            "notice_authority_role": notice_authority_role,
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
            lineage_refs=resolved_lineage_refs,
            timeout_seconds=10,
            max_retries=max_retries,
            boundary_flags=boundary_flags or {},
        )

    def _industry_authority_coverage_report(
        self,
        *,
        coverage_state: str = "COMPLETE",
        captured_filing_types: list[str] | None = None,
        missing_filing_types: list[str] | None = None,
        duplicate_source_refs: list[str] | None = None,
        manual_review_required: bool = False,
        no_broad_fallback: bool = True,
    ) -> dict[str, object]:
        return {
            "coverage_state": coverage_state,
            "expected_filing_types": sorted(INDUSTRY_AUTHORITY_FILING_TYPES),
            "captured_filing_types": captured_filing_types
            if captured_filing_types is not None
            else sorted(INDUSTRY_AUTHORITY_FILING_TYPES),
            "missing_filing_types": missing_filing_types or [],
            "duplicate_source_refs": duplicate_source_refs or [],
            "manual_review_required": manual_review_required,
            "no_broad_fallback": no_broad_fallback,
        }

    def _industry_authority_request(
        self,
        *,
        source_url: str = INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL,
        source_registry_id: str = INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_REGISTRY_ID,
        source_family: str = INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
        record_kind: str = INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
        source_visibility_state: str = "PUBLIC_VISIBLE",
        fetch_mode: str = "controlled_test_transport",
        snapshot_version: str = "industry-authority-permit-v1",
        filing_type: str = "construction_permit",
        content_type_hint: str | None = None,
        max_retries: int = 2,
        boundary_flags: dict[str, bool] | None = None,
        lineage_refs: dict[str, object] | None = None,
    ) -> PublicSourceSnapshotRequest:
        resolved_lineage_refs: dict[str, object] = {
            "project_id": "P-114I",
            "stage1_handoff_intent_id": "HINT-114I",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            "project_lineage_id": "PROJECT-LINEAGE-114I",
            "authority_name_optional": "Example Industry Authority",
            "authority_site_domain_optional": "public.example.local",
            "authority_level_optional": "city",
            "authority_region_optional": "Example Region",
            "filing_type": filing_type,
            "filing_record_id_optional": "FILING-114I-001",
            "source_coverage_report": self._industry_authority_coverage_report(),
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
            timeout_seconds=11,
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
            self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
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
            self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
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
                self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
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
                self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
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
            self.assertFalse(policy["unapproved_live_capture_enabled"])
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
                self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
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
            self.assertFalse(policy["unapproved_live_capture_enabled"])
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
                self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
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
            self.assertFalse(policy["unapproved_live_capture_enabled"])
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

    def test_government_procurement_boundary_sources_route_to_automated_challenge_or_block_before_transport(self) -> None:
        boundary_requests = [
            self._government_procurement_request(source_registry_id="SRC-REG-GOV-PROCUREMENT-UNKNOWN"),
            self._government_procurement_request(
                source_family="unknown_source_family",
                source_registry_id=GOV_PROC_NOTICE_REGISTRY_ID,
            ),
            self._government_procurement_request(
                source_url="https://unlisted.example.local/government/notice.html"
            ),
            self._government_procurement_request(record_kind="unknown_government_record"),
            self._government_procurement_request(source_visibility_state="LOGIN_REQUIRED"),
            self._government_procurement_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._government_procurement_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._government_procurement_request(source_visibility_state="UNKNOWN"),
            self._government_procurement_request(boundary_flags={"login_required": True}),
            self._government_procurement_request(boundary_flags={"captcha_required": True}),
            self._government_procurement_request(boundary_flags={"anti_bot_restricted": True}),
            self._government_procurement_request(fetch_mode="live"),
            self._government_procurement_request(fetch_mode="live_capture"),
            self._government_procurement_request(fetch_mode="unapproved_live_capture"),
            self._government_procurement_request(fetch_mode="unregistered_capture"),
            self._government_procurement_request(fetch_mode="real_provider"),
        ]

        for request in boundary_requests:
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
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertFalse(raised.exception.carrier["unapproved_live_capture_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertEqual(transport.call_log, [])

    def test_tender_agency_notice_types_capture_readback_replay_and_lineage(self) -> None:
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
            "agency_name_optional",
            "agency_site_domain_optional",
            "notice_type",
            "project_lineage_id",
            "source_blueprint_batch_id",
        }
        cases = [
            (
                TENDER_AGENCY_TENDER_NOTICE_URL,
                TENDER_AGENCY_TENDER_NOTICE_REGISTRY_ID,
                TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                b"<html><body>tender agency tender notice 114G</body></html>",
                "tender",
                "114g-tender-v1",
            ),
            (
                TENDER_AGENCY_CORRECTION_NOTICE_URL,
                TENDER_AGENCY_CORRECTION_NOTICE_REGISTRY_ID,
                TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                b"<html><body>tender agency correction notice 114G</body></html>",
                "correction",
                "114g-correction-v1",
            ),
            (
                TENDER_AGENCY_CANDIDATE_NOTICE_URL,
                TENDER_AGENCY_CANDIDATE_NOTICE_REGISTRY_ID,
                TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                b"<html><body>tender agency candidate notice 114G</body></html>",
                "candidate",
                "114g-candidate-v1",
            ),
            (
                TENDER_AGENCY_AWARD_RESULT_URL,
                TENDER_AGENCY_AWARD_RESULT_REGISTRY_ID,
                TENDER_AGENCY_AWARD_RESULT_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                b"<html><body>tender agency award result 114G</body></html>",
                "award_result",
                "114g-award-result-v1",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            service = Stage2Service()
            transport = StaticPublicSourceTransport(
                {
                    source_url: PublicSourceTransportResponse(
                        content=body,
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                    for source_url, _, _, _, _, body, _, _ in cases
                }
            )

            for source_url, registry_id, record_kind, visibility, fetch_mode, body, notice_type, version in cases:
                with self.subTest(record_kind=record_kind):
                    capture = service.capture_public_source_snapshot(
                        self._tender_agency_request(
                            source_url=source_url,
                            source_registry_id=registry_id,
                            record_kind=record_kind,
                            source_visibility_state=visibility,
                            fetch_mode=fetch_mode,
                            snapshot_version=version,
                        ),
                        repository=repo,
                        transport=transport,
                    )
                    replay = service.replay_public_source_snapshot(
                        capture.snapshot_id,
                        repository=repo,
                    )
                    metadata = capture.raw_snapshot_metadata

                    self.assertEqual(capture.status, "SNAPSHOT_CAPTURED")
                    self.assertEqual(capture.adapter_id, TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID)
                    self.assertTrue(capture.snapshot_id.startswith("SNAP-S2-114G-"))
                    self.assertIsNotNone(metadata)
                    self.assertTrue(required_metadata_keys.issubset(metadata))
                    self.assertEqual(metadata["adapter_id"], TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID)
                    self.assertEqual(metadata["source_family"], TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY)
                    self.assertEqual(metadata["record_kind"], record_kind)
                    self.assertEqual(metadata["source_registry_id"], registry_id)
                    self.assertEqual(metadata["source_url"], source_url)
                    self.assertEqual(metadata["source_visibility_state"], visibility)
                    self.assertEqual(metadata["content_type"], "text/html")
                    self.assertEqual(metadata["byte_size"], len(body))
                    self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(metadata["snapshot_version"], version)
                    self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114G")
                    self.assertEqual(
                        metadata["lineage_refs"]["project_lineage_id"],
                        "PROJECT-LINEAGE-114G",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["source_blueprint_batch_id"],
                        "PTL-I100-ROADMAP-01",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["agency_name_optional"],
                        "Example Tender Agency",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["agency_site_domain_optional"],
                        "public.example.local",
                    )
                    self.assertEqual(metadata["lineage_refs"]["notice_type"], notice_type)
                    self.assertEqual(metadata["notice_type"], notice_type)
                    self.assertEqual(metadata["project_lineage_id"], "PROJECT-LINEAGE-114G")
                    self.assertEqual(metadata["source_blueprint_batch_id"], "PTL-I100-ROADMAP-01")
                    self.assertEqual(metadata["agency_name_optional"], "Example Tender Agency")
                    self.assertEqual(metadata["agency_site_domain_optional"], "public.example.local")
                    self.assertEqual(metadata["fetched_at"], NOW)
                    self.assertEqual(metadata["captured_at"], NOW)
                    self.assertEqual(metadata["fetch_mode"], fetch_mode)
                    self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                    self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                    self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                    self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                    self.assertEqual(metadata["source_health"]["notice_type"], notice_type)
                    self.assertFalse(metadata["source_health"]["manual_review_required"])
                    self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
                    self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                    self.assertEqual(capture.readback["snapshot_kind"], "raw_html")
                    self.assertEqual(capture.readback["readback_state"], "READBACK_READY")
                    self.assertEqual(capture.readback["bytes"], body)
                    self.assertEqual(replay["bytes"], body)
                    self.assertEqual(
                        replay["manifest"]["raw_snapshot_metadata"]["notice_type"],
                        notice_type,
                    )
                    self.assertEqual(
                        replay["manifest"]["raw_snapshot_metadata"]["agency_name_optional"],
                        "Example Tender Agency",
                    )
                    self.assertEqual(repo.read_snapshot_bytes(capture.snapshot_id), body)

    def test_tender_agency_runtime_policy_resolver_and_adapter_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = self._adapter(
                self._repo(tmp_dir),
                StaticPublicSourceTransport({}),
                config=tender_agency_public_site_adapter_config(),
            ).runtime_policy()

            self.assertEqual(policy["adapter_id"], TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID)
            self.assertEqual(
                policy["allowed_source_families"],
                [TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY],
            )
            self.assertEqual(
                set(policy["allowed_record_kinds"]),
                {
                    TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
                    TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND,
                    TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND,
                    TENDER_AGENCY_AWARD_RESULT_RECORD_KIND,
                },
            )
            self.assertEqual(
                set(policy["allowlisted_source_registry_ids"]),
                {
                    TENDER_AGENCY_TENDER_NOTICE_REGISTRY_ID,
                    TENDER_AGENCY_CORRECTION_NOTICE_REGISTRY_ID,
                    TENDER_AGENCY_CANDIDATE_NOTICE_REGISTRY_ID,
                    TENDER_AGENCY_AWARD_RESULT_REGISTRY_ID,
                },
            )
            self.assertEqual(
                policy["public_url_prefixes"],
                ["https://public.example.local/tender-agency-public-sites/"],
            )
            self.assertEqual(
                policy["sandbox_url_prefixes"],
                ["sandbox://tender-agency-public-sites/"],
            )
            self.assertFalse(policy["unapproved_live_capture_enabled"])
            self.assertFalse(policy["real_provider_connection_enabled"])

        resolver_cases = [
            self._tender_agency_request(),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family=TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY,
            ),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id=TENDER_AGENCY_CORRECTION_NOTICE_REGISTRY_ID,
                source_family="PROCUREMENT_NOTICE",
            ),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
                record_kind=TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND,
            ),
            PublicSourceSnapshotRequest(
                source_url=TENDER_AGENCY_AWARD_RESULT_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
            ),
        ]
        for request in resolver_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID,
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
            (self._government_procurement_request(), GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID),
            (
                PublicSourceSnapshotRequest(
                    source_url=PUBLIC_HTML_URL,
                    source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                    source_family="PROCUREMENT_NOTICE",
                    record_kind=GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
                ),
                GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
            ),
        ]
        for request, expected_adapter_id in old_adapter_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                expected_adapter_id,
            )

    def test_tender_agency_retry_timeout_rate_limit_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        TENDER_AGENCY_TENDER_NOTICE_URL: [
                            PublicSourceTimeoutError("tender agency timeout once"),
                            PublicSourceTransportResponse(
                                content=b"<html>tender agency retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=tender_agency_public_site_adapter_config(),
            )
            retry_result = adapter.capture(self._tender_agency_request(max_retries=1))

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.adapter_id, TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID)
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(
                retry_result.fetch_audit["retry_events"][0]["reason"],
                "PublicSourceTimeoutError",
            )
            self.assertEqual(
                retry_result.fetch_audit["record_kind"],
                TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
            )
            self.assertEqual(retry_result.source_health["source_health_state"], "HEALTHY")
            self.assertEqual(retry_result.source_health["retry_count"], 1)
            self.assertFalse(retry_result.source_health["manual_review_required"])

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        TENDER_AGENCY_TENDER_NOTICE_URL: [
                            PublicSourceTimeoutError("weak tender agency page timed out one"),
                            PublicSourceTimeoutError("weak tender agency page timed out two"),
                        ]
                    }
                ),
                config=tender_agency_public_site_adapter_config(),
            )
            timed_out = adapter.capture(self._tender_agency_request(max_retries=1))

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.adapter_id, TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(
                timed_out.source_health["record_kind"],
                TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
            )
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertTrue(timed_out.source_health["manual_review_required"])
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

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    TENDER_AGENCY_TENDER_NOTICE_URL: PublicSourceTransportResponse(
                        content=b"<html>tender agency rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=tender_agency_public_site_adapter_config(min_interval_seconds=60),
            )
            rate_adapter.capture(self._tender_agency_request())
            rate_limited = rate_adapter.capture(self._tender_agency_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(
                rate_limited.source_health["record_kind"],
                TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
            )
            self.assertEqual(rate_limited.source_health["source_health_state"], "DEGRADED")
            self.assertTrue(rate_limited.source_health["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(
                rate_limited.fetch_audit["transport_mode"],
                "not_called_due_to_rate_limit",
            )
            self.assertEqual(len(transport.call_log), 1)

    def test_tender_agency_boundary_sources_route_to_automated_challenge_or_block_before_transport(self) -> None:
        boundary_requests = [
            self._tender_agency_request(source_registry_id="SRC-REG-TENDER-AGENCY-UNKNOWN"),
            self._tender_agency_request(
                source_family="unknown_source_family",
                source_registry_id=TENDER_AGENCY_TENDER_NOTICE_REGISTRY_ID,
            ),
            self._tender_agency_request(
                source_url="https://unlisted.example.local/tender-agency/notice.html"
            ),
            self._tender_agency_request(record_kind="unknown_tender_agency_record"),
            self._tender_agency_request(source_visibility_state="LOGIN_REQUIRED"),
            self._tender_agency_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._tender_agency_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._tender_agency_request(source_visibility_state="UNKNOWN"),
            self._tender_agency_request(boundary_flags={"login_required": True}),
            self._tender_agency_request(boundary_flags={"captcha_required": True}),
            self._tender_agency_request(boundary_flags={"anti_bot_restricted": True}),
            self._tender_agency_request(fetch_mode="live"),
            self._tender_agency_request(fetch_mode="live_capture"),
            self._tender_agency_request(fetch_mode="unapproved_live_capture"),
            self._tender_agency_request(fetch_mode="unregistered_capture"),
            self._tender_agency_request(fetch_mode="real_provider"),
        ]

        for request in boundary_requests:
            with self.subTest(
                source_url=request.source_url,
                state=request.source_visibility_state,
                mode=request.fetch_mode,
                record_kind=request.record_kind,
            ):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=tender_agency_public_site_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertFalse(raised.exception.carrier["unapproved_live_capture_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertEqual(transport.call_log, [])

    def test_tenderer_notice_pages_capture_readback_replay_and_authority_lineage(self) -> None:
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
            "tenderer_name_optional",
            "tenderer_site_domain_optional",
            "notice_authority_role",
            "notice_type",
            "project_lineage_id",
            "source_blueprint_batch_id",
        }
        cases = [
            (
                TENDERER_OWNER_NOTICE_URL,
                TENDERER_OWNER_NOTICE_REGISTRY_ID,
                TENDERER_OWNER_NOTICE_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                b"<html><body>tenderer owner notice 114H</body></html>",
                "owner",
                "owner_notice",
                "114h-owner-notice-v1",
            ),
            (
                TENDERER_CORRECTION_NOTICE_URL,
                TENDERER_CORRECTION_NOTICE_REGISTRY_ID,
                TENDERER_CORRECTION_NOTICE_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                b"<html><body>tenderer correction notice 114H</body></html>",
                "tenderer",
                "correction_notice",
                "114h-correction-notice-v1",
            ),
            (
                TENDERER_CANDIDATE_NOTICE_URL,
                TENDERER_CANDIDATE_NOTICE_REGISTRY_ID,
                TENDERER_CANDIDATE_NOTICE_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                b"<html><body>procurer candidate notice 114H</body></html>",
                "procurer",
                "candidate_notice",
                "114h-candidate-notice-v1",
            ),
            (
                TENDERER_AWARD_RESULT_URL,
                TENDERER_AWARD_RESULT_REGISTRY_ID,
                TENDERER_AWARD_RESULT_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                b"<html><body>owner award result 114H</body></html>",
                "owner",
                "award_result",
                "114h-award-result-v1",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            service = Stage2Service()
            transport = StaticPublicSourceTransport(
                {
                    source_url: PublicSourceTransportResponse(
                        content=body,
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                    for source_url, _, _, _, _, body, _, _, _ in cases
                }
            )

            for source_url, registry_id, record_kind, visibility, fetch_mode, body, authority_role, notice_type, version in cases:
                with self.subTest(record_kind=record_kind):
                    capture = service.capture_public_source_snapshot(
                        self._tenderer_request(
                            source_url=source_url,
                            source_registry_id=registry_id,
                            record_kind=record_kind,
                            source_visibility_state=visibility,
                            fetch_mode=fetch_mode,
                            snapshot_version=version,
                            notice_authority_role=authority_role,
                        ),
                        repository=repo,
                        transport=transport,
                    )
                    replay = service.replay_public_source_snapshot(
                        capture.snapshot_id,
                        repository=repo,
                    )
                    metadata = capture.raw_snapshot_metadata

                    self.assertEqual(capture.status, "SNAPSHOT_CAPTURED")
                    self.assertEqual(capture.adapter_id, TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID)
                    self.assertTrue(capture.snapshot_id.startswith("SNAP-S2-114H-"))
                    self.assertIsNotNone(metadata)
                    self.assertTrue(required_metadata_keys.issubset(metadata))
                    self.assertEqual(metadata["adapter_id"], TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID)
                    self.assertEqual(metadata["source_family"], TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY)
                    self.assertEqual(metadata["record_kind"], record_kind)
                    self.assertEqual(metadata["source_registry_id"], registry_id)
                    self.assertEqual(metadata["source_url"], source_url)
                    self.assertEqual(metadata["source_visibility_state"], visibility)
                    self.assertEqual(metadata["content_type"], "text/html")
                    self.assertEqual(metadata["byte_size"], len(body))
                    self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(metadata["snapshot_version"], version)
                    self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114H")
                    self.assertEqual(
                        metadata["lineage_refs"]["project_lineage_id"],
                        "PROJECT-LINEAGE-114H",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["source_blueprint_batch_id"],
                        "PTL-I100-ROADMAP-01",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["tenderer_name_optional"],
                        "Example Tenderer Owner",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["tenderer_site_domain_optional"],
                        "public.example.local",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["notice_authority_role"],
                        authority_role,
                    )
                    self.assertEqual(metadata["lineage_refs"]["notice_type"], notice_type)
                    self.assertEqual(metadata["notice_authority_role"], authority_role)
                    self.assertEqual(metadata["notice_type"], notice_type)
                    self.assertEqual(metadata["project_lineage_id"], "PROJECT-LINEAGE-114H")
                    self.assertEqual(metadata["source_blueprint_batch_id"], "PTL-I100-ROADMAP-01")
                    self.assertEqual(metadata["tenderer_name_optional"], "Example Tenderer Owner")
                    self.assertEqual(metadata["tenderer_site_domain_optional"], "public.example.local")
                    self.assertEqual(metadata["fetched_at"], NOW)
                    self.assertEqual(metadata["captured_at"], NOW)
                    self.assertEqual(metadata["fetch_mode"], fetch_mode)
                    self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                    self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                    self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                    self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                    self.assertEqual(metadata["source_health"]["notice_type"], notice_type)
                    self.assertEqual(
                        metadata["source_health"]["notice_authority_role"],
                        authority_role,
                    )
                    self.assertFalse(metadata["source_health"]["manual_review_required"])
                    self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
                    self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                    self.assertEqual(capture.readback["snapshot_kind"], "raw_html")
                    self.assertEqual(capture.readback["readback_state"], "READBACK_READY")
                    self.assertEqual(capture.readback["bytes"], body)
                    self.assertEqual(replay["bytes"], body)
                    self.assertEqual(
                        replay["manifest"]["raw_snapshot_metadata"]["notice_type"],
                        notice_type,
                    )
                    self.assertEqual(
                        replay["manifest"]["raw_snapshot_metadata"]["notice_authority_role"],
                        authority_role,
                    )
                    self.assertEqual(
                        replay["manifest"]["source_health"]["notice_authority_role"],
                        authority_role,
                    )
                    self.assertEqual(repo.read_snapshot_bytes(capture.snapshot_id), body)

    def test_tenderer_runtime_policy_resolver_and_adapter_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = self._adapter(
                self._repo(tmp_dir),
                StaticPublicSourceTransport({}),
                config=tenderer_public_notice_page_adapter_config(),
            ).runtime_policy()

            self.assertEqual(policy["adapter_id"], TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID)
            self.assertEqual(
                policy["allowed_source_families"],
                [TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY],
            )
            self.assertEqual(
                set(policy["allowed_record_kinds"]),
                {
                    TENDERER_OWNER_NOTICE_RECORD_KIND,
                    TENDERER_CORRECTION_NOTICE_RECORD_KIND,
                    TENDERER_CANDIDATE_NOTICE_RECORD_KIND,
                    TENDERER_AWARD_RESULT_RECORD_KIND,
                },
            )
            self.assertEqual(
                set(policy["allowlisted_source_registry_ids"]),
                {
                    TENDERER_OWNER_NOTICE_REGISTRY_ID,
                    TENDERER_CORRECTION_NOTICE_REGISTRY_ID,
                    TENDERER_CANDIDATE_NOTICE_REGISTRY_ID,
                    TENDERER_AWARD_RESULT_REGISTRY_ID,
                },
            )
            self.assertEqual(
                policy["public_url_prefixes"],
                ["https://public.example.local/tenderer-public-notice-pages/"],
            )
            self.assertEqual(
                policy["sandbox_url_prefixes"],
                ["sandbox://tenderer-public-notice-pages/"],
            )
            self.assertFalse(policy["unapproved_live_capture_enabled"])
            self.assertFalse(policy["real_provider_connection_enabled"])

        resolver_cases = [
            self._tenderer_request(),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family=TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY,
            ),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id=TENDERER_CORRECTION_NOTICE_REGISTRY_ID,
                source_family="PROCUREMENT_NOTICE",
            ),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
                record_kind=TENDERER_CANDIDATE_NOTICE_RECORD_KIND,
            ),
            PublicSourceSnapshotRequest(
                source_url=TENDERER_AWARD_RESULT_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
            ),
        ]
        for request in resolver_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID,
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
            (self._government_procurement_request(), GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID),
            (self._tender_agency_request(), TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID),
        ]
        for request, expected_adapter_id in old_adapter_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                expected_adapter_id,
            )

    def test_tenderer_retry_timeout_rate_limit_weak_lineage_and_failure_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        TENDERER_OWNER_NOTICE_URL: [
                            PublicSourceTimeoutError("tenderer public page timeout once"),
                            PublicSourceTransportResponse(
                                content=b"<html>tenderer retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=tenderer_public_notice_page_adapter_config(),
            )
            retry_result = adapter.capture(self._tenderer_request(max_retries=1))

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.adapter_id, TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID)
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(
                retry_result.fetch_audit["retry_events"][0]["reason"],
                "PublicSourceTimeoutError",
            )
            self.assertEqual(
                retry_result.fetch_audit["record_kind"],
                TENDERER_OWNER_NOTICE_RECORD_KIND,
            )
            self.assertEqual(retry_result.source_health["source_health_state"], "HEALTHY")
            self.assertEqual(retry_result.source_health["retry_count"], 1)
            self.assertEqual(retry_result.source_health["notice_authority_role"], "owner")
            self.assertFalse(retry_result.source_health["manual_review_required"])

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        TENDERER_OWNER_NOTICE_URL: [
                            PublicSourceTimeoutError("weak tenderer page timeout one"),
                            PublicSourceTimeoutError("weak tenderer page timeout two"),
                        ]
                    }
                ),
                config=tenderer_public_notice_page_adapter_config(),
            )
            timed_out = adapter.capture(self._tenderer_request(max_retries=1))

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.adapter_id, TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(
                timed_out.source_health["record_kind"],
                TENDERER_OWNER_NOTICE_RECORD_KIND,
            )
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.source_health["notice_authority_role"], "owner")
            self.assertTrue(timed_out.source_health["manual_review_required"])
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

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    TENDERER_OWNER_NOTICE_URL: PublicSourceTransportResponse(
                        content=b"<html>tenderer rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=tenderer_public_notice_page_adapter_config(
                    min_interval_seconds=60
                ),
            )
            rate_adapter.capture(self._tenderer_request())
            rate_limited = rate_adapter.capture(self._tenderer_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(
                rate_limited.source_health["record_kind"],
                TENDERER_OWNER_NOTICE_RECORD_KIND,
            )
            self.assertEqual(rate_limited.source_health["notice_authority_role"], "owner")
            self.assertEqual(rate_limited.source_health["source_health_state"], "DEGRADED")
            self.assertTrue(rate_limited.source_health["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(
                rate_limited.fetch_audit["transport_mode"],
                "not_called_due_to_rate_limit",
            )
            self.assertEqual(len(transport.call_log), 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        TENDERER_OWNER_NOTICE_URL: [
                            PublicSourceTransportError("tenderer page fetch failed"),
                            PublicSourceTransportError("tenderer page still failed"),
                        ]
                    }
                ),
                config=tenderer_public_notice_page_adapter_config(),
            )
            failed = adapter.capture(self._tenderer_request(max_retries=1))

            self.assertEqual(failed.status, "DEGRADED")
            self.assertEqual(failed.failure_degrade["degrade_reason"], "fetch_failed")
            self.assertEqual(failed.source_health["last_failure_reason"], "fetch_failed")
            self.assertEqual(failed.source_health["notice_authority_role"], "owner")
            self.assertTrue(failed.failure_degrade["manual_review_required"])
            self.assertTrue(failed.failure_degrade["fail_closed"])
            self.assertTrue(failed.failure_degrade["no_broad_fallback"])
            self.assertEqual(failed.fetch_audit["attempt_count"], 2)

        degraded_cases = [
            (
                self._tenderer_request(boundary_flags={"weak_structure": True}),
                "weak_structure",
            ),
            (
                self._tenderer_request(
                    lineage_refs={"project_lineage_id": ""},
                ),
                "missing_key_lineage",
            ),
        ]
        for request, reason in degraded_cases:
            with self.subTest(reason=reason):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=tenderer_public_notice_page_adapter_config(),
                    )
                    degraded = adapter.capture(request)
                    self.assertEqual(degraded.status, "DEGRADED")
                    self.assertEqual(degraded.failure_degrade["degrade_reason"], reason)
                    self.assertTrue(degraded.failure_degrade["manual_review_required"])
                    self.assertTrue(degraded.failure_degrade["fail_closed"])
                    self.assertTrue(degraded.failure_degrade["no_broad_fallback"])
                    self.assertEqual(
                        degraded.fetch_audit["transport_mode"],
                        "not_called_due_to_preflight_degrade",
                    )
                    self.assertEqual(transport.call_log, [])

    def test_tenderer_boundary_sources_route_to_automated_challenge_or_block_before_transport(self) -> None:
        boundary_requests = [
            self._tenderer_request(source_registry_id="SRC-REG-TENDERER-UNKNOWN"),
            self._tenderer_request(
                source_family="unknown_source_family",
                source_registry_id=TENDERER_OWNER_NOTICE_REGISTRY_ID,
            ),
            self._tenderer_request(
                source_url="https://unlisted.example.local/tenderer/notice.html"
            ),
            self._tenderer_request(record_kind="unknown_tenderer_notice_record"),
            self._tenderer_request(source_visibility_state="LOGIN_REQUIRED"),
            self._tenderer_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._tenderer_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._tenderer_request(source_visibility_state="UNKNOWN"),
            self._tenderer_request(boundary_flags={"login_required": True}),
            self._tenderer_request(boundary_flags={"captcha_required": True}),
            self._tenderer_request(boundary_flags={"anti_bot_restricted": True}),
            self._tenderer_request(fetch_mode="live"),
            self._tenderer_request(fetch_mode="live_capture"),
            self._tenderer_request(fetch_mode="unapproved_live_capture"),
            self._tenderer_request(fetch_mode="unregistered_capture"),
            self._tenderer_request(fetch_mode="real_provider"),
        ]

        for request in boundary_requests:
            with self.subTest(
                source_url=request.source_url,
                state=request.source_visibility_state,
                mode=request.fetch_mode,
                record_kind=request.record_kind,
            ):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=tenderer_public_notice_page_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertFalse(raised.exception.carrier["unapproved_live_capture_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertEqual(transport.call_log, [])

    def test_industry_authority_filing_pages_capture_readback_replay_and_source_coverage_report(self) -> None:
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
            "authority_name_optional",
            "authority_site_domain_optional",
            "authority_level_optional",
            "authority_region_optional",
            "filing_type",
            "filing_record_id_optional",
            "project_lineage_id",
            "source_blueprint_batch_id",
            "source_coverage_report",
        }
        cases = [
            (
                INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL,
                INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_REGISTRY_ID,
                INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                b"<html><body>industry authority permit filing 114I</body></html>",
                "construction_permit",
                "114i-construction-permit-v1",
            ),
            (
                INDUSTRY_AUTHORITY_CONTRACT_FILING_URL,
                INDUSTRY_AUTHORITY_CONTRACT_FILING_REGISTRY_ID,
                INDUSTRY_AUTHORITY_CONTRACT_FILING_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                b"<html><body>industry authority contract filing 114I</body></html>",
                "contract_filing",
                "114i-contract-filing-v1",
            ),
            (
                INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_URL,
                INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_REGISTRY_ID,
                INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_FILING_RECORD_KIND,
                "PUBLIC_VISIBLE",
                "controlled_test_transport",
                b"<html><body>industry authority completion filing 114I</body></html>",
                "completion_acceptance",
                "114i-completion-acceptance-v1",
            ),
            (
                INDUSTRY_AUTHORITY_PERFORMANCE_FILING_URL,
                INDUSTRY_AUTHORITY_PERFORMANCE_FILING_REGISTRY_ID,
                INDUSTRY_AUTHORITY_PERFORMANCE_FILING_RECORD_KIND,
                "SANDBOX_LOCAL_MIRROR",
                "sandbox_local_mirror",
                b"<html><body>industry authority performance filing 114I</body></html>",
                "performance_filing",
                "114i-performance-filing-v1",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            service = Stage2Service()
            transport = StaticPublicSourceTransport(
                {
                    source_url: PublicSourceTransportResponse(
                        content=body,
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                    for source_url, _, _, _, _, body, _, _ in cases
                }
            )

            for source_url, registry_id, record_kind, visibility, fetch_mode, body, filing_type, version in cases:
                with self.subTest(record_kind=record_kind):
                    coverage_report = self._industry_authority_coverage_report()
                    capture = service.capture_public_source_snapshot(
                        self._industry_authority_request(
                            source_url=source_url,
                            source_registry_id=registry_id,
                            record_kind=record_kind,
                            source_visibility_state=visibility,
                            fetch_mode=fetch_mode,
                            snapshot_version=version,
                            filing_type=filing_type,
                            lineage_refs={
                                "filing_record_id_optional": f"{filing_type}-record-114I",
                                "source_coverage_report": coverage_report,
                            },
                        ),
                        repository=repo,
                        transport=transport,
                    )
                    replay = service.replay_public_source_snapshot(
                        capture.snapshot_id,
                        repository=repo,
                    )
                    metadata = capture.raw_snapshot_metadata

                    self.assertEqual(capture.status, "SNAPSHOT_CAPTURED")
                    self.assertEqual(capture.adapter_id, INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID)
                    self.assertTrue(capture.snapshot_id.startswith("SNAP-S2-114I-"))
                    self.assertIsNotNone(metadata)
                    self.assertTrue(required_metadata_keys.issubset(metadata))
                    self.assertEqual(metadata["adapter_id"], INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID)
                    self.assertEqual(metadata["source_family"], INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY)
                    self.assertEqual(metadata["record_kind"], record_kind)
                    self.assertEqual(metadata["source_registry_id"], registry_id)
                    self.assertEqual(metadata["source_url"], source_url)
                    self.assertEqual(metadata["source_visibility_state"], visibility)
                    self.assertEqual(metadata["content_type"], "text/html")
                    self.assertEqual(metadata["byte_size"], len(body))
                    self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(metadata["snapshot_version"], version)
                    self.assertEqual(metadata["lineage_refs"]["project_id"], "P-114I")
                    self.assertEqual(
                        metadata["lineage_refs"]["project_lineage_id"],
                        "PROJECT-LINEAGE-114I",
                    )
                    self.assertEqual(
                        metadata["lineage_refs"]["source_blueprint_batch_id"],
                        "PTL-I100-ROADMAP-01",
                    )
                    self.assertEqual(metadata["lineage_refs"]["filing_type"], filing_type)
                    self.assertEqual(
                        metadata["lineage_refs"]["source_coverage_report"],
                        coverage_report,
                    )
                    self.assertEqual(metadata["authority_name_optional"], "Example Industry Authority")
                    self.assertEqual(metadata["authority_site_domain_optional"], "public.example.local")
                    self.assertEqual(metadata["authority_level_optional"], "city")
                    self.assertEqual(metadata["authority_region_optional"], "Example Region")
                    self.assertEqual(metadata["filing_type"], filing_type)
                    self.assertEqual(
                        metadata["filing_record_id_optional"],
                        f"{filing_type}-record-114I",
                    )
                    self.assertEqual(metadata["project_lineage_id"], "PROJECT-LINEAGE-114I")
                    self.assertEqual(metadata["source_blueprint_batch_id"], "PTL-I100-ROADMAP-01")
                    self.assertEqual(metadata["source_coverage_report"], coverage_report)
                    self.assertEqual(metadata["source_coverage_report"]["coverage_state"], "COMPLETE")
                    self.assertEqual(metadata["source_coverage_report"]["missing_filing_types"], [])
                    self.assertEqual(metadata["source_coverage_report"]["duplicate_source_refs"], [])
                    self.assertFalse(metadata["source_coverage_report"]["manual_review_required"])
                    self.assertTrue(metadata["source_coverage_report"]["no_broad_fallback"])
                    self.assertEqual(metadata["fetched_at"], NOW)
                    self.assertEqual(metadata["captured_at"], NOW)
                    self.assertEqual(metadata["fetch_mode"], fetch_mode)
                    self.assertEqual(metadata["fetch_audit"]["transport_mode"], fetch_mode)
                    self.assertEqual(metadata["fetch_audit"]["record_kind"], record_kind)
                    self.assertEqual(metadata["source_health"]["source_health_state"], "HEALTHY")
                    self.assertEqual(metadata["source_health"]["record_kind"], record_kind)
                    self.assertEqual(metadata["source_health"]["filing_type"], filing_type)
                    self.assertEqual(
                        metadata["source_health"]["source_coverage_report"],
                        coverage_report,
                    )
                    self.assertFalse(metadata["source_health"]["manual_review_required"])
                    self.assertFalse(metadata["fetch_audit"]["unapproved_live_capture_enabled"])
                    self.assertFalse(metadata["fetch_audit"]["real_provider_connection_enabled"])
                    self.assertEqual(capture.readback["snapshot_kind"], "raw_html")
                    self.assertEqual(capture.readback["readback_state"], "READBACK_READY")
                    self.assertEqual(capture.readback["bytes"], body)
                    self.assertEqual(replay["bytes"], body)
                    self.assertEqual(
                        replay["manifest"]["raw_snapshot_metadata"]["source_coverage_report"],
                        coverage_report,
                    )
                    self.assertEqual(
                        replay["manifest"]["source_health"]["filing_type"],
                        filing_type,
                    )
                    self.assertEqual(repo.read_snapshot_bytes(capture.snapshot_id), body)

    def test_industry_authority_runtime_policy_resolver_and_adapter_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = self._adapter(
                self._repo(tmp_dir),
                StaticPublicSourceTransport({}),
                config=industry_authority_filing_page_adapter_config(),
            ).runtime_policy()

            self.assertEqual(policy["adapter_id"], INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID)
            self.assertEqual(
                policy["allowed_source_families"],
                [INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY],
            )
            self.assertEqual(
                set(policy["allowed_record_kinds"]),
                {
                    INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
                    INDUSTRY_AUTHORITY_CONTRACT_FILING_RECORD_KIND,
                    INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_FILING_RECORD_KIND,
                    INDUSTRY_AUTHORITY_PERFORMANCE_FILING_RECORD_KIND,
                },
            )
            self.assertEqual(
                set(policy["allowlisted_source_registry_ids"]),
                {
                    INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_REGISTRY_ID,
                    INDUSTRY_AUTHORITY_CONTRACT_FILING_REGISTRY_ID,
                    INDUSTRY_AUTHORITY_COMPLETION_ACCEPTANCE_REGISTRY_ID,
                    INDUSTRY_AUTHORITY_PERFORMANCE_FILING_REGISTRY_ID,
                },
            )
            self.assertEqual(
                policy["public_url_prefixes"],
                ["https://public.example.local/industry-authority-filing-pages/"],
            )
            self.assertEqual(
                policy["sandbox_url_prefixes"],
                ["sandbox://industry-authority-filing-pages/"],
            )
            self.assertFalse(policy["unapproved_live_capture_enabled"])
            self.assertFalse(policy["real_provider_connection_enabled"])

        resolver_cases = [
            self._industry_authority_request(),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family=INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
            ),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id=INDUSTRY_AUTHORITY_CONTRACT_FILING_REGISTRY_ID,
                source_family="PROCUREMENT_NOTICE",
            ),
            PublicSourceSnapshotRequest(
                source_url=PUBLIC_HTML_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
                record_kind=INDUSTRY_AUTHORITY_PERFORMANCE_FILING_RECORD_KIND,
            ),
            PublicSourceSnapshotRequest(
                source_url=INDUSTRY_AUTHORITY_PERFORMANCE_FILING_URL,
                source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
                source_family="PROCUREMENT_NOTICE",
            ),
        ]
        for request in resolver_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
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
            (self._government_procurement_request(), GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID),
            (self._tender_agency_request(), TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID),
            (self._tenderer_request(), TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID),
        ]
        for request, expected_adapter_id in old_adapter_cases:
            self.assertEqual(
                resolve_public_source_adapter_config(request).adapter_id,
                expected_adapter_id,
            )

    def test_industry_authority_retry_timeout_rate_limit_and_degrade_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL: [
                            PublicSourceTimeoutError("industry authority timeout once"),
                            PublicSourceTransportResponse(
                                content=b"<html>industry authority retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
                config=industry_authority_filing_page_adapter_config(),
            )
            retry_result = adapter.capture(
                self._industry_authority_request(max_retries=1)
            )

            self.assertEqual(retry_result.status, "SNAPSHOT_CAPTURED")
            self.assertEqual(retry_result.adapter_id, INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID)
            self.assertEqual(retry_result.fetch_audit["attempt_count"], 2)
            self.assertEqual(
                retry_result.fetch_audit["retry_events"][0]["reason"],
                "PublicSourceTimeoutError",
            )
            self.assertEqual(
                retry_result.fetch_audit["record_kind"],
                INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
            )
            self.assertEqual(retry_result.source_health["source_health_state"], "HEALTHY")
            self.assertEqual(retry_result.source_health["retry_count"], 1)
            self.assertEqual(retry_result.source_health["filing_type"], "construction_permit")
            self.assertFalse(retry_result.source_health["manual_review_required"])

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL: [
                            PublicSourceTimeoutError("industry authority timeout one"),
                            PublicSourceTimeoutError("industry authority timeout two"),
                        ]
                    }
                ),
                config=industry_authority_filing_page_adapter_config(),
            )
            timed_out = adapter.capture(
                self._industry_authority_request(max_retries=1)
            )

            self.assertEqual(timed_out.status, "DEGRADED")
            self.assertIsNone(timed_out.snapshot_id)
            self.assertEqual(timed_out.adapter_id, INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID)
            self.assertEqual(timed_out.source_health["source_health_state"], "DEGRADED")
            self.assertEqual(
                timed_out.source_health["record_kind"],
                INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
            )
            self.assertEqual(timed_out.source_health["last_failure_reason"], "fetch_timeout")
            self.assertEqual(timed_out.source_health["filing_type"], "construction_permit")
            self.assertTrue(timed_out.source_health["manual_review_required"])
            self.assertTrue(timed_out.source_health["fail_closed"])
            self.assertTrue(timed_out.source_health["no_broad_fallback"])
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

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL: PublicSourceTransportResponse(
                        content=b"<html>industry authority rate limit</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=industry_authority_filing_page_adapter_config(
                    min_interval_seconds=60
                ),
            )
            rate_adapter.capture(self._industry_authority_request())
            rate_limited = rate_adapter.capture(self._industry_authority_request())

            self.assertEqual(rate_limited.status, "DEGRADED")
            self.assertEqual(rate_limited.failure_degrade["degrade_reason"], "rate_limited")
            self.assertEqual(
                rate_limited.source_health["record_kind"],
                INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
            )
            self.assertEqual(rate_limited.source_health["filing_type"], "construction_permit")
            self.assertEqual(rate_limited.source_health["source_health_state"], "DEGRADED")
            self.assertTrue(rate_limited.source_health["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["manual_review_required"])
            self.assertTrue(rate_limited.failure_degrade["fail_closed"])
            self.assertTrue(rate_limited.failure_degrade["no_broad_fallback"])
            self.assertEqual(
                rate_limited.fetch_audit["transport_mode"],
                "not_called_due_to_rate_limit",
            )
            self.assertEqual(len(transport.call_log), 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_URL: [
                            PublicSourceTransportError("industry authority fetch failed"),
                            PublicSourceTransportError("industry authority still failed"),
                        ]
                    }
                ),
                config=industry_authority_filing_page_adapter_config(),
            )
            failed = adapter.capture(
                self._industry_authority_request(max_retries=1)
            )

            self.assertEqual(failed.status, "DEGRADED")
            self.assertEqual(failed.failure_degrade["degrade_reason"], "fetch_failed")
            self.assertEqual(failed.source_health["last_failure_reason"], "fetch_failed")
            self.assertEqual(failed.source_health["filing_type"], "construction_permit")
            self.assertTrue(failed.failure_degrade["manual_review_required"])
            self.assertTrue(failed.failure_degrade["fail_closed"])
            self.assertTrue(failed.failure_degrade["no_broad_fallback"])
            self.assertEqual(failed.fetch_audit["attempt_count"], 2)

        degraded_cases = [
            (
                self._industry_authority_request(
                    lineage_refs={"project_lineage_id": ""}
                ),
                "missing_key_lineage",
            ),
            (
                self._industry_authority_request(lineage_refs={"filing_type": ""}),
                "missing_filing_type",
            ),
            (
                self._industry_authority_request(
                    lineage_refs={
                        "source_coverage_report": self._industry_authority_coverage_report(
                            coverage_state="PARTIAL",
                            captured_filing_types=["construction_permit"],
                            missing_filing_types=["contract_filing"],
                            manual_review_required=True,
                        )
                    }
                ),
                "weak_coverage",
            ),
            (
                self._industry_authority_request(boundary_flags={"weak_coverage": True}),
                "weak_coverage",
            ),
        ]
        for request, reason in degraded_cases:
            with self.subTest(reason=reason):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=industry_authority_filing_page_adapter_config(),
                    )
                    degraded = adapter.capture(request)
                    self.assertEqual(degraded.status, "DEGRADED")
                    self.assertEqual(degraded.failure_degrade["degrade_reason"], reason)
                    self.assertTrue(degraded.failure_degrade["manual_review_required"])
                    self.assertTrue(degraded.failure_degrade["fail_closed"])
                    self.assertTrue(degraded.failure_degrade["no_broad_fallback"])
                    self.assertTrue(degraded.source_health["manual_review_required"])
                    self.assertTrue(degraded.source_health["fail_closed"])
                    self.assertTrue(degraded.source_health["no_broad_fallback"])
                    self.assertEqual(
                        degraded.fetch_audit["transport_mode"],
                        "not_called_due_to_preflight_degrade",
                    )
                    self.assertEqual(transport.call_log, [])

    def test_industry_authority_boundary_sources_route_to_automated_challenge_or_block_before_transport(self) -> None:
        boundary_requests = [
            self._industry_authority_request(
                source_registry_id="SRC-REG-INDUSTRY-AUTHORITY-UNKNOWN"
            ),
            self._industry_authority_request(
                source_family="unknown_source_family",
                source_registry_id=INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_REGISTRY_ID,
            ),
            self._industry_authority_request(
                source_url="https://unlisted.example.local/industry-authority/filing.html"
            ),
            self._industry_authority_request(record_kind="unknown_industry_authority_record"),
            self._industry_authority_request(source_visibility_state="LOGIN_REQUIRED"),
            self._industry_authority_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._industry_authority_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._industry_authority_request(source_visibility_state="UNKNOWN"),
            self._industry_authority_request(boundary_flags={"login_required": True}),
            self._industry_authority_request(boundary_flags={"captcha_required": True}),
            self._industry_authority_request(boundary_flags={"anti_bot_restricted": True}),
            self._industry_authority_request(fetch_mode="live"),
            self._industry_authority_request(fetch_mode="live_capture"),
            self._industry_authority_request(fetch_mode="unapproved_live_capture"),
            self._industry_authority_request(fetch_mode="unregistered_capture"),
            self._industry_authority_request(fetch_mode="real_provider"),
        ]

        for request in boundary_requests:
            with self.subTest(
                source_url=request.source_url,
                state=request.source_visibility_state,
                mode=request.fetch_mode,
                record_kind=request.record_kind,
            ):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(
                        self._repo(tmp_dir),
                        transport,
                        config=industry_authority_filing_page_adapter_config(),
                    )
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertFalse(raised.exception.carrier["unapproved_live_capture_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
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

    def test_public_web_adaptive_failure_diagnosis_classifies_common_failure_modes(self) -> None:
        cases = [
            ("dom_structure_changed", "DOM_STRUCTURE_CHANGED"),
            ("js_shell_detected", "JS_SHELL_DETECTED"),
            ("pagination_redirect_required", "PAGINATION_OR_REDIRECT_REQUIRED"),
            ("attachment_discovery_missing", "ATTACHMENT_DISCOVERY_MISSING"),
            ("encoding_error", "ENCODING_ERROR"),
            ("parser_template_drift", "PARSER_TEMPLATE_DRIFT"),
            ("source_health_degraded", "SOURCE_HEALTH_DEGRADED"),
        ]
        for flag_name, expected_class in cases:
            with self.subTest(flag_name=flag_name), tempfile.TemporaryDirectory() as tmp_dir:
                transport = StaticPublicSourceTransport(
                    {
                        PROVINCIAL_HTML_URL: PublicSourceTransportResponse(
                            content=b"<html>unused due to preflight diagnosis</html>",
                            content_type="text/html",
                            fetched_at=NOW,
                            captured_at=NOW,
                        )
                    }
                )
                adapter = self._adapter(
                    self._repo(tmp_dir),
                    transport,
                    config=provincial_bidding_platform_adapter_config(),
                )
                result = adapter.capture(
                    self._provincial_request(boundary_flags={flag_name: True})
                )

                self.assertEqual(result.status, "DEGRADED")
                self.assertEqual(transport.call_log, [])
                diagnosis = result.failure_degrade["failure_diagnosis"]
                self.assertEqual(diagnosis["failure_class"], expected_class)
                for key in ("why_retry", "why_backoff", "why_degrade", "why_suspend"):
                    self.assertIn(key, diagnosis)
                    self.assertIsInstance(diagnosis[key], list)
                self.assertFalse(diagnosis["manual_restart_as_primary_flow"])
                self.assertFalse(result.failure_degrade["manual_restart_required"])
                self.assertTrue(diagnosis["public_boundary_preserved"])
                self.assertTrue(diagnosis["no_duplicate_stage2_pipeline"])
                self.assertEqual(
                    result.fetch_audit["adaptive_capture_strategy"]["state"],
                    "AUTO_DEGRADE_OR_RETRY_PLANNED",
                )

    def test_public_web_adaptive_retry_backoff_and_rate_limit_diagnostics_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            adapter = self._adapter(
                repo,
                StaticPublicSourceTransport(
                    {
                        PUBLIC_HTML_URL: [
                            PublicSourceTimeoutError("local timeout once"),
                            PublicSourceTransportResponse(
                                content=b"<html>retry success</html>",
                                content_type="text/html",
                                fetched_at=NOW,
                                captured_at=NOW,
                            ),
                        ]
                    }
                ),
            )

            result = adapter.capture(self._request(max_retries=1))

            retry_diagnosis = result.fetch_audit["retry_events"][0]["failure_diagnosis"]
            self.assertEqual(retry_diagnosis["failure_class"], "TIMEOUT")
            self.assertIn("timeout_is_retryable_within_budget", retry_diagnosis["why_retry"])
            self.assertIn("backoff_before_next_transport_attempt", retry_diagnosis["why_backoff"])
            self.assertEqual(
                result.fetch_audit["adaptive_capture_strategy"]["state"],
                "AUTO_RECOVERED_AFTER_RETRY",
            )
            self.assertFalse(
                result.source_health["adaptive_capture_strategy"]["manual_restart_as_primary_flow"]
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            transport = StaticPublicSourceTransport(
                {
                    PUBLIC_HTML_URL: PublicSourceTransportResponse(
                        content=b"<html>rate limit seed</html>",
                        content_type="text/html",
                        fetched_at=NOW,
                        captured_at=NOW,
                    )
                }
            )
            rate_adapter = self._adapter(
                repo,
                transport,
                config=PublicSourceAdapterConfig(min_interval_seconds=60),
            )
            rate_adapter.capture(self._request())
            rate_limited = rate_adapter.capture(self._request())

            diagnosis = rate_limited.failure_degrade["failure_diagnosis"]
            self.assertEqual(diagnosis["failure_class"], "RATE_LIMITED")
            self.assertIn("rate_limit_policy_requires_wait", diagnosis["why_backoff"])
            self.assertFalse(diagnosis["manual_restart_as_primary_flow"])
            self.assertTrue(diagnosis["public_boundary_preserved"])

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

    def test_source_visibility_review_login_captcha_antibot_route_to_automated_challenge_and_unknown_sources_block(self) -> None:
        boundary_visibility_states = [
            "LOGIN_REQUIRED",
            "CAPTCHA_REQUIRED",
            "ANTI_BOT_RESTRICTED",
            "UNKNOWN",
        ]
        for visibility_state in boundary_visibility_states:
            with self.subTest(visibility_state=visibility_state):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(self._repo(tmp_dir), transport)
                    request = self._request(source_visibility_state=visibility_state)
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(transport.call_log, [])

        challenge_flag_sets = [
            {"login_required": True},
            {"captcha_required": True},
            {"anti_bot_restricted": True},
        ]
        for flags in challenge_flag_sets:
            with self.subTest(flags=flags):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(self._repo(tmp_dir), transport)
                    request = self._request(boundary_flags=flags)
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(request)
                    self._assert_boundary_status(raised, request)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
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

    def test_provincial_unknown_unlisted_source_visibility_review_login_captcha_antibot_route_to_automated_challenge_before_transport(self) -> None:
        boundary_requests = [
            self._provincial_request(source_registry_id="SRC-REG-PROV-BID-UNKNOWN"),
            self._provincial_request(source_url="https://unlisted.example.local/provincial/notice.html"),
            self._provincial_request(source_visibility_state="LOGIN_REQUIRED"),
            self._provincial_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._provincial_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._provincial_request(boundary_flags={"login_required": True}),
            self._provincial_request(boundary_flags={"captcha_required": True}),
            self._provincial_request(boundary_flags={"anti_bot_restricted": True}),
        ]

        for request in boundary_requests:
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
                    self._assert_boundary_status(raised, request)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertEqual(transport.call_log, [])

    def test_national_construction_market_unknown_unlisted_source_visibility_review_login_captcha_antibot_route_to_automated_challenge_before_transport(self) -> None:
        boundary_requests = [
            self._national_request(source_registry_id="SRC-REG-NCMP-UNKNOWN"),
            self._national_request(source_url="https://unlisted.example.local/ncmp/enterprise.html"),
            self._national_request(record_kind="unknown_public_record"),
            self._national_request(source_visibility_state="LOGIN_REQUIRED"),
            self._national_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._national_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._national_request(boundary_flags={"login_required": True}),
            self._national_request(boundary_flags={"captcha_required": True}),
            self._national_request(boundary_flags={"anti_bot_restricted": True}),
        ]

        for request in boundary_requests:
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
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertEqual(transport.call_log, [])

    def test_credit_china_unknown_unlisted_source_visibility_review_login_captcha_antibot_route_to_automated_challenge_before_transport(self) -> None:
        boundary_requests = [
            self._credit_china_request(source_registry_id="SRC-REG-CREDIT-CHINA-UNKNOWN"),
            self._credit_china_request(source_url="https://unlisted.example.local/credit-china/record.html"),
            self._credit_china_request(record_kind="unknown_credit_record"),
            self._credit_china_request(source_visibility_state="LOGIN_REQUIRED"),
            self._credit_china_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._credit_china_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._credit_china_request(boundary_flags={"login_required": True}),
            self._credit_china_request(boundary_flags={"captcha_required": True}),
            self._credit_china_request(boundary_flags={"anti_bot_restricted": True}),
            self._credit_china_request(fetch_mode="live_capture"),
            self._credit_china_request(fetch_mode="unapproved_live_capture"),
            self._credit_china_request(fetch_mode="real_provider"),
        ]

        for request in boundary_requests:
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
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(raised.exception.carrier["adapter_id"], CREDIT_CHINA_ADAPTER_ID)
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertFalse(raised.exception.carrier["unapproved_live_capture_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertEqual(transport.call_log, [])

    def test_national_enterprise_credit_publicity_system_boundary_sources_route_to_automated_challenge_or_block_before_transport(self) -> None:
        boundary_requests = [
            self._necps_request(source_registry_id="SRC-REG-NECPS-UNKNOWN"),
            self._necps_request(
                source_family="unknown_source_family",
                source_registry_id=NECPS_PUBLIC_REGISTRY_ID,
            ),
            self._necps_request(
                source_url="https://unlisted.example.local/necps/record.html"
            ),
            self._necps_request(record_kind="unknown_enterprise_record"),
            self._necps_request(source_visibility_state="LOGIN_REQUIRED"),
            self._necps_request(source_visibility_state="CAPTCHA_REQUIRED"),
            self._necps_request(source_visibility_state="ANTI_BOT_RESTRICTED"),
            self._necps_request(source_visibility_state="UNKNOWN"),
            self._necps_request(boundary_flags={"login_required": True}),
            self._necps_request(boundary_flags={"captcha_required": True}),
            self._necps_request(boundary_flags={"anti_bot_restricted": True}),
            self._necps_request(fetch_mode="live"),
            self._necps_request(fetch_mode="live_capture"),
            self._necps_request(fetch_mode="unapproved_live_capture"),
            self._necps_request(fetch_mode="real_provider"),
        ]

        for request in boundary_requests:
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
                    self._assert_boundary_status(raised, request)
                    self.assertEqual(
                        raised.exception.carrier["adapter_id"],
                        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
                    )
                    self.assertEqual(raised.exception.carrier["record_kind"], request.record_kind)
                    self.assertTrue(raised.exception.carrier["source_boundary"]["boundary_reason"])
                    self.assertFalse(raised.exception.carrier["unapproved_live_capture_enabled"])
                    self.assertFalse(raised.exception.carrier["real_provider_connection_enabled"])
                    self.assertEqual(transport.call_log, [])

    def test_uncontrolled_live_capture_adapter_modes_are_blocked_before_transport(self) -> None:
        for fetch_mode in ("live_capture", "unapproved_live_capture", "real_provider"):
            with self.subTest(fetch_mode=fetch_mode):
                transport = StaticPublicSourceTransport({})
                with tempfile.TemporaryDirectory() as tmp_dir:
                    adapter = self._adapter(self._repo(tmp_dir), transport)
                    with self.assertRaises(PublicSourceBoundaryError) as raised:
                        adapter.capture(self._request(fetch_mode=fetch_mode))
                    self.assertIn("blocked_fetch_mode", raised.exception.reason)
                    self.assertEqual(transport.call_log, [])
                    self.assertFalse(adapter.runtime_policy()["unapproved_live_capture_enabled"])
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
