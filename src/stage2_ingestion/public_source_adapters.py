from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from shared.utils import utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID = (
    "stage2.local_public_resource_trading_center.v1"
)
PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID = "stage2.provincial_bidding_platform.v1"
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID = (
    "stage2.national_construction_market_platform.v1"
)
CREDIT_CHINA_ADAPTER_ID = "stage2.credit_china.v1"
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID = (
    "stage2.national_enterprise_credit_publicity_system.v1"
)
GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID = (
    "stage2.government_procurement_public_site.v1"
)
TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID = "stage2.tender_agency_public_site.v1"
TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID = (
    "stage2.tenderer_public_notice_page.v1"
)
LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_SOURCE_FAMILY = "local_public_resource_trading_center"
PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY = "provincial_bidding_platform"
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY = (
    "national_construction_market_platform"
)
CREDIT_CHINA_SOURCE_FAMILY = "credit_china"
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY = (
    "national_enterprise_credit_publicity_system"
)
GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY = "government_procurement_public_site"
TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY = "tender_agency_public_site"
TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY = "tenderer_public_notice_page"
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND = "enterprise_public_record"
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PERSONNEL_RECORD_KIND = "personnel_public_record"
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PROJECT_RECORD_KIND = "project_public_record"
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_RECORD_KINDS = frozenset(
    {
        NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
        NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PERSONNEL_RECORD_KIND,
        NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PROJECT_RECORD_KIND,
    }
)
CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND = "credit_public_record"
CREDIT_CHINA_ADMINISTRATIVE_PENALTY_RECORD_KIND = "administrative_penalty_record"
CREDIT_CHINA_CREDIT_EXCEPTION_RECORD_KIND = "credit_exception_record"
CREDIT_CHINA_RECORD_KINDS = frozenset(
    {
        CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
        CREDIT_CHINA_ADMINISTRATIVE_PENALTY_RECORD_KIND,
        CREDIT_CHINA_CREDIT_EXCEPTION_RECORD_KIND,
    }
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND = (
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND = (
    "enterprise_registration_record"
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND = (
    "enterprise_abnormal_operation_record"
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_RECORD_KINDS = frozenset(
    {
        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND,
        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND,
    }
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_UNIQUE_RECORD_KINDS = frozenset(
    {
        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND,
        NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND,
    }
)
GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND = "government_procurement_notice_record"
GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND = "government_procurement_result_record"
GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND = "government_procurement_attachment_record"
GOVERNMENT_PROCUREMENT_PUBLIC_SITE_RECORD_KINDS = frozenset(
    {
        GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
        GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND,
        GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND,
    }
)
TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND = "tender_agency_tender_notice_record"
TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND = "tender_agency_correction_notice_record"
TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND = "tender_agency_candidate_notice_record"
TENDER_AGENCY_AWARD_RESULT_RECORD_KIND = "tender_agency_award_result_record"
TENDER_AGENCY_PUBLIC_SITE_RECORD_KINDS = frozenset(
    {
        TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
        TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND,
        TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND,
        TENDER_AGENCY_AWARD_RESULT_RECORD_KIND,
    }
)
TENDER_AGENCY_NOTICE_TYPES_BY_RECORD_KIND = {
    TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND: "tender",
    TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND: "correction",
    TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND: "candidate",
    TENDER_AGENCY_AWARD_RESULT_RECORD_KIND: "award_result",
}
TENDERER_OWNER_NOTICE_RECORD_KIND = "tenderer_owner_notice_record"
TENDERER_CORRECTION_NOTICE_RECORD_KIND = "tenderer_correction_notice_record"
TENDERER_CANDIDATE_NOTICE_RECORD_KIND = "tenderer_candidate_notice_record"
TENDERER_AWARD_RESULT_RECORD_KIND = "tenderer_award_result_record"
TENDERER_PUBLIC_NOTICE_PAGE_RECORD_KINDS = frozenset(
    {
        TENDERER_OWNER_NOTICE_RECORD_KIND,
        TENDERER_CORRECTION_NOTICE_RECORD_KIND,
        TENDERER_CANDIDATE_NOTICE_RECORD_KIND,
        TENDERER_AWARD_RESULT_RECORD_KIND,
    }
)
TENDERER_NOTICE_TYPES_BY_RECORD_KIND = {
    TENDERER_OWNER_NOTICE_RECORD_KIND: "owner_notice",
    TENDERER_CORRECTION_NOTICE_RECORD_KIND: "correction_notice",
    TENDERER_CANDIDATE_NOTICE_RECORD_KIND: "candidate_notice",
    TENDERER_AWARD_RESULT_RECORD_KIND: "award_result",
}

LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-PROC-NATIONAL-HTML",
        "SRC-REG-PROC-CITY-PDF",
        "SRC-REG-AWARD-CITY-HTML",
    }
)
PROVINCIAL_BIDDING_PLATFORM_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-PROV-BID-ANNOUNCEMENT-HTML",
        "SRC-REG-PROV-BID-ANNOUNCEMENT-PDF",
        "SRC-REG-PROV-BID-ATTACHMENT",
    }
)
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-NCMP-ENTERPRISE-PUBLIC-RECORD",
        "SRC-REG-NCMP-PERSONNEL-PUBLIC-RECORD",
        "SRC-REG-NCMP-PROJECT-PUBLIC-RECORD",
    }
)
CREDIT_CHINA_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-CREDIT-CHINA-PUBLIC-RECORD",
        "SRC-REG-CREDIT-CHINA-ADMINISTRATIVE-PENALTY",
        "SRC-REG-CREDIT-CHINA-CREDIT-EXCEPTION",
    }
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-NECPS-ENTERPRISE-PUBLIC-RECORD",
        "SRC-REG-NECPS-ENTERPRISE-REGISTRATION",
        "SRC-REG-NECPS-ENTERPRISE-ABNORMAL-OPERATION",
    }
)
GOVERNMENT_PROCUREMENT_PUBLIC_SITE_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-GOV-PROCUREMENT-NOTICE",
        "SRC-REG-GOV-PROCUREMENT-RESULT",
        "SRC-REG-GOV-PROCUREMENT-ATTACHMENT",
    }
)
TENDER_AGENCY_PUBLIC_SITE_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-TENDER-AGENCY-TENDER-NOTICE",
        "SRC-REG-TENDER-AGENCY-CORRECTION-NOTICE",
        "SRC-REG-TENDER-AGENCY-CANDIDATE-NOTICE",
        "SRC-REG-TENDER-AGENCY-AWARD-RESULT",
    }
)
TENDERER_PUBLIC_NOTICE_PAGE_REGISTRY_IDS = frozenset(
    {
        "SRC-REG-TENDERER-OWNER-NOTICE",
        "SRC-REG-TENDERER-CORRECTION-NOTICE",
        "SRC-REG-TENDERER-CANDIDATE-NOTICE",
        "SRC-REG-TENDERER-AWARD-RESULT",
    }
)
LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/local-public-resource-trading-centers/",
    "https://public.example.local/procurement/",
    "https://public.example.local/award/",
)
LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_SANDBOX_URL_PREFIXES = (
    "sandbox://local-public-resource-trading-centers/",
)
PROVINCIAL_BIDDING_PLATFORM_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/provincial-bidding-platforms/",
    "https://public.example.local/provincial-bidding/",
)
PROVINCIAL_BIDDING_PLATFORM_SANDBOX_URL_PREFIXES = (
    "sandbox://provincial-bidding-platforms/",
)
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/national-construction-market-platform/",
    "https://public.example.local/national-construction-market/",
)
NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SANDBOX_URL_PREFIXES = (
    "sandbox://national-construction-market-platform/",
)
CREDIT_CHINA_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/credit-china/",
)
CREDIT_CHINA_SANDBOX_URL_PREFIXES = (
    "sandbox://credit-china/",
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/national-enterprise-credit-publicity-system/",
)
NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SANDBOX_URL_PREFIXES = (
    "sandbox://national-enterprise-credit-publicity-system/",
)
GOVERNMENT_PROCUREMENT_PUBLIC_SITE_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/government-procurement-public-sites/",
)
GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SANDBOX_URL_PREFIXES = (
    "sandbox://government-procurement-public-sites/",
)
TENDER_AGENCY_PUBLIC_SITE_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/tender-agency-public-sites/",
)
TENDER_AGENCY_PUBLIC_SITE_SANDBOX_URL_PREFIXES = (
    "sandbox://tender-agency-public-sites/",
)
TENDERER_PUBLIC_NOTICE_PAGE_PUBLIC_URL_PREFIXES = (
    "https://public.example.local/tenderer-public-notice-pages/",
)
TENDERER_PUBLIC_NOTICE_PAGE_SANDBOX_URL_PREFIXES = (
    "sandbox://tenderer-public-notice-pages/",
)

PUBLIC_VISIBLE_STATE = "PUBLIC_VISIBLE"
SANDBOX_LOCAL_MIRROR_STATE = "SANDBOX_LOCAL_MIRROR"
CONTROLLED_TEST_TRANSPORT_STATE = "CONTROLLED_TEST_TRANSPORT"

BLOCKED_VISIBILITY_STATES = frozenset(
    {
        "PRIVATE",
        "GRAY",
        "LOGIN_REQUIRED",
        "CAPTCHA_REQUIRED",
        "ANTI_BOT_RESTRICTED",
        "UNKNOWN",
    }
)

ALLOWED_VISIBILITY_STATES = frozenset(
    {
        PUBLIC_VISIBLE_STATE,
        SANDBOX_LOCAL_MIRROR_STATE,
        CONTROLLED_TEST_TRANSPORT_STATE,
    }
)

ALLOWED_FETCH_MODES = frozenset(
    {
        "controlled_test_transport",
        "sandbox_local_mirror",
        "public_url_metadata_only",
    }
)

BLOCKED_FETCH_MODES = frozenset(
    {
        "live",
        "live_crawl",
        "uncontrolled_live_crawl",
        "crawler",
        "real_provider",
    }
)


class PublicSourceAdapterError(RuntimeError):
    pass


class PublicSourceBoundaryError(PublicSourceAdapterError):
    def __init__(self, reason: str, *, carrier: Mapping[str, Any]) -> None:
        self.reason = reason
        self.carrier = dict(carrier)
        super().__init__(reason)


class PublicSourceTransportError(PublicSourceAdapterError):
    pass


class PublicSourceTimeoutError(PublicSourceTransportError):
    pass


class PublicSourceTransport(Protocol):
    controlled_transport: bool

    def fetch(self, source_url: str, *, timeout_seconds: float) -> "PublicSourceTransportResponse":
        ...


@dataclass(frozen=True)
class PublicSourceTransportResponse:
    content: bytes
    content_type: str
    status_code: int = 200
    fetched_at: str | None = None
    captured_at: str | None = None
    final_url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


class StaticPublicSourceTransport:
    """Deterministic transport for sandbox/local tests; never opens a network socket."""

    controlled_transport = True

    def __init__(
        self,
        responses: Mapping[str, PublicSourceTransportResponse | Exception | list[PublicSourceTransportResponse | Exception]],
    ) -> None:
        self._responses: dict[str, list[PublicSourceTransportResponse | Exception]] = {}
        for source_url, response in responses.items():
            if isinstance(response, list):
                values = list(response)
            else:
                values = [response]
            self._responses[str(source_url)] = values
        self.call_log: list[dict[str, Any]] = []

    def fetch(self, source_url: str, *, timeout_seconds: float) -> PublicSourceTransportResponse:
        self.call_log.append(
            {
                "source_url": source_url,
                "timeout_seconds": timeout_seconds,
                "transport": "static_controlled",
            }
        )
        queue = self._responses.get(source_url)
        if not queue:
            raise PublicSourceTransportError("source_not_available_in_controlled_transport")
        if len(queue) > 1:
            response = queue.pop(0)
        else:
            response = queue[0]
        if isinstance(response, Exception):
            raise response
        return response


@dataclass(frozen=True)
class PublicSourceSnapshotRequest:
    source_url: str
    source_registry_id: str
    source_family: str
    record_kind: str | None = None
    source_visibility_state: str = PUBLIC_VISIBLE_STATE
    fetch_mode: str = "controlled_test_transport"
    lineage_refs: Mapping[str, Any] = field(default_factory=dict)
    snapshot_version: str | None = None
    content_type_hint: str | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 2
    rate_limit_key: str | None = None
    boundary_flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicSourceAdapterConfig:
    adapter_id: str = LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID
    allowlisted_source_registry_ids: frozenset[str] = LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_REGISTRY_IDS
    allowed_source_families: frozenset[str] = frozenset(
        {
            LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_SOURCE_FAMILY,
            "PROCUREMENT_NOTICE",
            "AWARD_NOTICE",
        }
    )
    allowed_record_kinds: frozenset[str] = frozenset()
    allowed_public_url_prefixes: tuple[str, ...] = LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_PUBLIC_URL_PREFIXES
    allowed_sandbox_url_prefixes: tuple[str, ...] = LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_SANDBOX_URL_PREFIXES
    allowed_fetch_modes: frozenset[str] = ALLOWED_FETCH_MODES
    min_interval_seconds: float = 0.0
    uncontrolled_live_crawler_enabled: bool = False
    real_provider_connection_enabled: bool = False


def local_public_resource_trading_center_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(min_interval_seconds=min_interval_seconds)


def provincial_bidding_platform_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
        allowlisted_source_registry_ids=PROVINCIAL_BIDDING_PLATFORM_REGISTRY_IDS,
        allowed_source_families=frozenset({PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY}),
        allowed_public_url_prefixes=PROVINCIAL_BIDDING_PLATFORM_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=PROVINCIAL_BIDDING_PLATFORM_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def national_construction_market_platform_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID,
        allowlisted_source_registry_ids=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_REGISTRY_IDS,
        allowed_source_families=frozenset(
            {NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY}
        ),
        allowed_record_kinds=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_RECORD_KINDS,
        allowed_public_url_prefixes=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def credit_china_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=CREDIT_CHINA_ADAPTER_ID,
        allowlisted_source_registry_ids=CREDIT_CHINA_REGISTRY_IDS,
        allowed_source_families=frozenset({CREDIT_CHINA_SOURCE_FAMILY}),
        allowed_record_kinds=CREDIT_CHINA_RECORD_KINDS,
        allowed_public_url_prefixes=CREDIT_CHINA_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=CREDIT_CHINA_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def national_enterprise_credit_publicity_system_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
        allowlisted_source_registry_ids=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_REGISTRY_IDS,
        allowed_source_families=frozenset(
            {NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY}
        ),
        allowed_record_kinds=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_RECORD_KINDS,
        allowed_public_url_prefixes=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def government_procurement_public_site_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
        allowlisted_source_registry_ids=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_REGISTRY_IDS,
        allowed_source_families=frozenset(
            {GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY}
        ),
        allowed_record_kinds=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_RECORD_KINDS,
        allowed_public_url_prefixes=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def tender_agency_public_site_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID,
        allowlisted_source_registry_ids=TENDER_AGENCY_PUBLIC_SITE_REGISTRY_IDS,
        allowed_source_families=frozenset({TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY}),
        allowed_record_kinds=TENDER_AGENCY_PUBLIC_SITE_RECORD_KINDS,
        allowed_public_url_prefixes=TENDER_AGENCY_PUBLIC_SITE_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=TENDER_AGENCY_PUBLIC_SITE_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def tenderer_public_notice_page_adapter_config(
    *,
    min_interval_seconds: float = 0.0,
) -> PublicSourceAdapterConfig:
    return PublicSourceAdapterConfig(
        adapter_id=TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID,
        allowlisted_source_registry_ids=TENDERER_PUBLIC_NOTICE_PAGE_REGISTRY_IDS,
        allowed_source_families=frozenset({TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY}),
        allowed_record_kinds=TENDERER_PUBLIC_NOTICE_PAGE_RECORD_KINDS,
        allowed_public_url_prefixes=TENDERER_PUBLIC_NOTICE_PAGE_PUBLIC_URL_PREFIXES,
        allowed_sandbox_url_prefixes=TENDERER_PUBLIC_NOTICE_PAGE_SANDBOX_URL_PREFIXES,
        min_interval_seconds=min_interval_seconds,
    )


def resolve_public_source_adapter_config(
    request: PublicSourceSnapshotRequest,
) -> PublicSourceAdapterConfig:
    source_family = str(request.source_family or "").strip()
    record_kind = str(request.record_kind or "").strip()
    if (
        source_family == TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY
        or record_kind in TENDERER_PUBLIC_NOTICE_PAGE_RECORD_KINDS
        or request.source_registry_id in TENDERER_PUBLIC_NOTICE_PAGE_REGISTRY_IDS
        or request.source_url.startswith(TENDERER_PUBLIC_NOTICE_PAGE_PUBLIC_URL_PREFIXES)
        or request.source_url.startswith(TENDERER_PUBLIC_NOTICE_PAGE_SANDBOX_URL_PREFIXES)
    ):
        return tenderer_public_notice_page_adapter_config()
    if (
        source_family == CREDIT_CHINA_SOURCE_FAMILY
        or record_kind in CREDIT_CHINA_RECORD_KINDS
        or request.source_registry_id in CREDIT_CHINA_REGISTRY_IDS
        or request.source_url.startswith(CREDIT_CHINA_PUBLIC_URL_PREFIXES)
        or request.source_url.startswith(CREDIT_CHINA_SANDBOX_URL_PREFIXES)
    ):
        return credit_china_adapter_config()
    if (
        source_family == NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY
        or record_kind in NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_UNIQUE_RECORD_KINDS
        or request.source_registry_id in NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_REGISTRY_IDS
        or request.source_url.startswith(
            NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_PUBLIC_URL_PREFIXES
        )
        or request.source_url.startswith(
            NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SANDBOX_URL_PREFIXES
        )
    ):
        return national_enterprise_credit_publicity_system_adapter_config()
    if (
        source_family == GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY
        or record_kind in GOVERNMENT_PROCUREMENT_PUBLIC_SITE_RECORD_KINDS
        or request.source_registry_id in GOVERNMENT_PROCUREMENT_PUBLIC_SITE_REGISTRY_IDS
        or request.source_url.startswith(
            GOVERNMENT_PROCUREMENT_PUBLIC_SITE_PUBLIC_URL_PREFIXES
        )
        or request.source_url.startswith(
            GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SANDBOX_URL_PREFIXES
        )
    ):
        return government_procurement_public_site_adapter_config()
    if (
        source_family == TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY
        or record_kind in TENDER_AGENCY_PUBLIC_SITE_RECORD_KINDS
        or request.source_registry_id in TENDER_AGENCY_PUBLIC_SITE_REGISTRY_IDS
        or request.source_url.startswith(TENDER_AGENCY_PUBLIC_SITE_PUBLIC_URL_PREFIXES)
        or request.source_url.startswith(TENDER_AGENCY_PUBLIC_SITE_SANDBOX_URL_PREFIXES)
    ):
        return tender_agency_public_site_adapter_config()
    if (
        source_family == NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY
        or record_kind in NATIONAL_CONSTRUCTION_MARKET_PLATFORM_RECORD_KINDS
        or request.source_registry_id in NATIONAL_CONSTRUCTION_MARKET_PLATFORM_REGISTRY_IDS
        or request.source_url.startswith(NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PUBLIC_URL_PREFIXES)
        or request.source_url.startswith(NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SANDBOX_URL_PREFIXES)
    ):
        return national_construction_market_platform_adapter_config()
    if (
        source_family == PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY
        or request.source_registry_id in PROVINCIAL_BIDDING_PLATFORM_REGISTRY_IDS
        or request.source_url.startswith(PROVINCIAL_BIDDING_PLATFORM_PUBLIC_URL_PREFIXES)
        or request.source_url.startswith(PROVINCIAL_BIDDING_PLATFORM_SANDBOX_URL_PREFIXES)
    ):
        return provincial_bidding_platform_adapter_config()
    return local_public_resource_trading_center_adapter_config()


@dataclass(frozen=True)
class PublicSourceSnapshotResult:
    status: str
    adapter_id: str
    snapshot_id: str | None
    raw_snapshot_metadata: Mapping[str, Any] | None
    source_health: Mapping[str, Any]
    fetch_audit: Mapping[str, Any]
    readback: Mapping[str, Any] | None = None
    failure_degrade: Mapping[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.raw_snapshot_metadata is not None:
            payload["raw_snapshot_metadata"] = dict(self.raw_snapshot_metadata)
        payload["source_health"] = dict(self.source_health)
        payload["fetch_audit"] = dict(self.fetch_audit)
        if self.readback is not None:
            payload["readback"] = dict(self.readback)
        if self.failure_degrade is not None:
            payload["failure_degrade"] = dict(self.failure_degrade)
        return payload


class LocalPublicResourceTradingCenterSourceAdapter:
    def __init__(
        self,
        *,
        repository: ObjectStorageRepository,
        transport: PublicSourceTransport | None,
        config: PublicSourceAdapterConfig | None = None,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.repository = repository
        self.transport = transport
        self.config = config or PublicSourceAdapterConfig()
        self.clock = clock
        self._last_fetch_at_by_key: dict[str, str] = {}

    def runtime_policy(self) -> dict[str, Any]:
        return {
            "adapter_id": self.config.adapter_id,
            "allowed_fetch_modes": sorted(self.config.allowed_fetch_modes),
            "allowed_record_kinds": sorted(self.config.allowed_record_kinds),
            "allowed_source_families": sorted(self.config.allowed_source_families),
            "allowlisted_source_registry_ids": sorted(
                self.config.allowlisted_source_registry_ids
            ),
            "public_url_prefixes": list(self.config.allowed_public_url_prefixes),
            "sandbox_url_prefixes": list(self.config.allowed_sandbox_url_prefixes),
            "uncontrolled_live_crawler_enabled": False,
            "real_provider_connection_enabled": False,
            "private_or_gray_source_enabled": False,
            "login_bypass_enabled": False,
            "captcha_bypass_enabled": False,
            "anti_bot_bypass_enabled": False,
        }

    def capture(self, request: PublicSourceSnapshotRequest) -> PublicSourceSnapshotResult:
        now = self.clock()
        boundary = self._public_boundary(request)
        if not boundary["allowed"]:
            raise PublicSourceBoundaryError(
                str(boundary["blocked_reason"]),
                carrier=self._blocked_carrier(request, boundary=boundary),
            )

        preflight_degrade = self._preflight_degrade_reason(request)
        if preflight_degrade is not None:
            return self._degraded_result(
                request,
                reason=preflight_degrade,
                now=now,
                fetch_audit={
                    "attempt_count": 0,
                    "max_retries": request.max_retries,
                    "timeout_seconds": request.timeout_seconds,
                    "retry_events": [],
                    "rate_limit": self._rate_limit_state(request, now=now),
                    "transport_mode": "not_called_due_to_preflight_degrade",
                    "dedupe_state": "NOT_EVALUATED",
                    "uncontrolled_live_crawler_enabled": False,
                    "real_provider_connection_enabled": False,
                },
            )

        rate_limit = self._rate_limit_state(request, now=now)
        if not rate_limit["allowed"]:
            return self._degraded_result(
                request,
                reason="rate_limited",
                now=now,
                fetch_audit={
                    "attempt_count": 0,
                    "max_retries": request.max_retries,
                    "timeout_seconds": request.timeout_seconds,
                    "retry_events": [],
                    "rate_limit": rate_limit,
                    "transport_mode": "not_called_due_to_rate_limit",
                    "dedupe_state": "NOT_EVALUATED",
                    "uncontrolled_live_crawler_enabled": False,
                    "real_provider_connection_enabled": False,
                },
            )

        if self.transport is None or not bool(getattr(self.transport, "controlled_transport", False)):
            raise PublicSourceBoundaryError(
                "controlled_transport_required",
                carrier=self._blocked_carrier(
                    request,
                    boundary={
                        "allowed": False,
                        "blocked_reason": "controlled_transport_required",
                        "source_visibility_state": request.source_visibility_state,
                    },
                ),
            )

        retry_events: list[dict[str, Any]] = []
        last_error: Exception | None = None
        attempts = max(0, request.max_retries) + 1
        for attempt_index in range(1, attempts + 1):
            try:
                response = self.transport.fetch(
                    request.source_url,
                    timeout_seconds=request.timeout_seconds,
                )
                if response.status_code >= 400:
                    raise PublicSourceTransportError(f"http_status_{response.status_code}")
                self._last_fetch_at_by_key[self._rate_limit_key(request)] = now
                return self._persist_response(
                    request,
                    response=response,
                    rate_limit=rate_limit,
                    retry_events=retry_events,
                    attempt_count=attempt_index,
                    now=now,
                )
            except (PublicSourceTimeoutError, PublicSourceTransportError) as exc:
                last_error = exc
                retry_events.append(
                    {
                        "attempt_index": attempt_index,
                        "reason": exc.__class__.__name__,
                        "message": str(exc),
                        "will_retry": attempt_index < attempts,
                    }
                )

        reason = "fetch_timeout" if isinstance(last_error, PublicSourceTimeoutError) else "fetch_failed"
        return self._degraded_result(
            request,
            reason=reason,
            now=now,
            fetch_audit={
                "attempt_count": attempts,
                "max_retries": request.max_retries,
                "timeout_seconds": request.timeout_seconds,
                "retry_events": retry_events,
                "rate_limit": rate_limit,
                "transport_mode": request.fetch_mode,
                "dedupe_state": "NOT_EVALUATED",
                "uncontrolled_live_crawler_enabled": False,
                "real_provider_connection_enabled": False,
            },
        )

    def _persist_response(
        self,
        request: PublicSourceSnapshotRequest,
        *,
        response: PublicSourceTransportResponse,
        rate_limit: Mapping[str, Any],
        retry_events: list[dict[str, Any]],
        attempt_count: int,
        now: str,
    ) -> PublicSourceSnapshotResult:
        data = bytes(response.content)
        content_type = response.content_type or request.content_type_hint or "application/octet-stream"
        sha256 = hashlib.sha256(data).hexdigest()
        snapshot_version = request.snapshot_version or f"sha256:{sha256[:12]}"
        snapshot_id = self._snapshot_id(
            source_url=response.final_url or request.source_url,
            snapshot_version=snapshot_version,
            sha256=sha256,
        )
        object_key = f"stage2/public-source-snapshots/{sha256[:2]}/{sha256}"
        dedupe_existing = self.repository.get_object_metadata(object_key) is not None
        lineage_refs = self._lineage_refs(request, snapshot_version=snapshot_version)
        fetched_at = response.fetched_at or now
        captured_at = response.captured_at or fetched_at
        fetch_audit = {
            "attempt_count": attempt_count,
            "max_retries": request.max_retries,
            "timeout_seconds": request.timeout_seconds,
            "source_family": request.source_family,
            "record_kind": request.record_kind,
            "retry_events": retry_events,
            "rate_limit": dict(rate_limit),
            "transport_mode": request.fetch_mode,
            "dedupe_state": "DEDUPED_BY_SHA256_OBJECT_KEY"
            if dedupe_existing
            else "NEW_OBJECT_WRITTEN",
            "http_status": response.status_code,
            "uncontrolled_live_crawler_enabled": False,
            "real_provider_connection_enabled": False,
        }
        source_health = {
            "adapter_id": self.config.adapter_id,
            "source_family": request.source_family,
            "record_kind": request.record_kind,
            "source_registry_id": request.source_registry_id,
            "source_url": response.final_url or request.source_url,
            "source_health_state": "HEALTHY",
            "last_failure_reason": None,
            "failure_degrade_state": "NOT_DEGRADED",
            "rate_limit_state": dict(rate_limit),
            "retry_count": max(0, attempt_count - 1),
            "timeout_seconds": request.timeout_seconds,
            "manual_review_required": False,
        }
        self._copy_lineage_metadata(source_health, lineage_refs)
        raw_snapshot_metadata = {
            "adapter_id": self.config.adapter_id,
            "source_family": request.source_family,
            "record_kind": request.record_kind,
            "source_registry_id": request.source_registry_id,
            "source_url": response.final_url or request.source_url,
            "source_visibility_state": request.source_visibility_state,
            "content_type": content_type,
            "byte_size": len(data),
            "sha256": sha256,
            "snapshot_version": snapshot_version,
            "lineage_refs": lineage_refs,
            "fetched_at": fetched_at,
            "captured_at": captured_at,
            "fetch_mode": request.fetch_mode,
            "fetch_audit": fetch_audit,
            "source_health": source_health,
            "replay_state": "READBACK_READY",
            "snapshot_id": snapshot_id,
            "snapshot_kind": self._snapshot_kind(content_type),
            "object_key": object_key,
        }
        self._copy_lineage_metadata(raw_snapshot_metadata, lineage_refs)
        manifest = self.repository.save_snapshot(
            data,
            snapshot_id=snapshot_id,
            snapshot_kind=self._snapshot_kind(content_type),
            content_type=content_type,
            source_url_optional=response.final_url or request.source_url,
            source_family_optional=request.source_family,
            lineage_refs=lineage_refs,
            object_key=object_key,
            created_at=captured_at,
            adapter_id=self.config.adapter_id,
            source_visibility_state=request.source_visibility_state,
            snapshot_version=snapshot_version,
            fetched_at=fetched_at,
            captured_at=captured_at,
            fetch_mode=request.fetch_mode,
            fetch_audit=fetch_audit,
            replay_state="READBACK_READY",
            raw_snapshot_metadata=raw_snapshot_metadata,
            source_health=source_health,
        )
        readback = self.repository.replay_snapshot(manifest.snapshot_id)
        return PublicSourceSnapshotResult(
            status="SNAPSHOT_CAPTURED",
            adapter_id=self.config.adapter_id,
            snapshot_id=manifest.snapshot_id,
            raw_snapshot_metadata=raw_snapshot_metadata,
            source_health=source_health,
            fetch_audit=fetch_audit,
            readback=readback,
        )

    def _public_boundary(self, request: PublicSourceSnapshotRequest) -> dict[str, Any]:
        visibility_state = str(request.source_visibility_state or "").strip()
        fetch_mode = str(request.fetch_mode or "").strip()
        flags = {str(key): bool(value) for key, value in request.boundary_flags.items()}
        if visibility_state in BLOCKED_VISIBILITY_STATES:
            return self._boundary_block(request, f"blocked_visibility_state:{visibility_state}")
        if visibility_state not in ALLOWED_VISIBILITY_STATES:
            return self._boundary_block(request, f"unknown_visibility_state:{visibility_state}")
        for flag_name in ("private_source", "gray_source", "login_required", "captcha_required", "anti_bot_restricted"):
            if flags.get(flag_name):
                return self._boundary_block(request, flag_name)
        if fetch_mode in BLOCKED_FETCH_MODES:
            return self._boundary_block(request, f"blocked_fetch_mode:{fetch_mode}")
        if fetch_mode not in self.config.allowed_fetch_modes:
            return self._boundary_block(request, f"unregistered_fetch_mode:{fetch_mode}")
        if request.source_registry_id not in self.config.allowlisted_source_registry_ids:
            return self._boundary_block(
                request,
                f"unknown_or_unregistered_source:{request.source_registry_id}",
            )
        if request.source_family not in self.config.allowed_source_families:
            return self._boundary_block(
                request,
                f"unregistered_source_family:{request.source_family}",
            )
        if (
            self.config.allowed_record_kinds
            and request.record_kind not in self.config.allowed_record_kinds
        ):
            return self._boundary_block(
                request,
                f"unregistered_record_kind:{request.record_kind}",
            )
        if not self._url_is_allowlisted(request.source_url):
            return self._boundary_block(request, "source_url_not_allowlisted")
        return {
            "allowed": True,
            "blocked_reason": None,
            "source_visibility_state": visibility_state,
            "source_registry_id": request.source_registry_id,
            "record_kind": request.record_kind,
            "fetch_mode": fetch_mode,
            "public_visible_url": request.source_url.startswith("https://"),
            "sandbox_local_mirror": request.source_url.startswith("sandbox://"),
        }

    def _boundary_block(self, request: PublicSourceSnapshotRequest, reason: str) -> dict[str, Any]:
        return {
            "allowed": False,
            "blocked_reason": reason,
            "source_visibility_state": request.source_visibility_state,
            "source_registry_id": request.source_registry_id,
            "record_kind": request.record_kind,
            "fetch_mode": request.fetch_mode,
            "public_visible_url": False,
            "sandbox_local_mirror": False,
        }

    def _blocked_carrier(
        self,
        request: PublicSourceSnapshotRequest,
        *,
        boundary: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "adapter_id": self.config.adapter_id,
            "status": "BLOCKED",
            "source_url": request.source_url,
            "source_family": request.source_family,
            "source_registry_id": request.source_registry_id,
            "record_kind": request.record_kind,
            "source_boundary": dict(boundary),
            "fetch_mode": request.fetch_mode,
            "uncontrolled_live_crawler_enabled": False,
            "real_provider_connection_enabled": False,
            "private_or_gray_source_enabled": False,
            "login_bypass_enabled": False,
            "captcha_bypass_enabled": False,
            "anti_bot_bypass_enabled": False,
        }

    def _url_is_allowlisted(self, source_url: str) -> bool:
        return source_url.startswith(self.config.allowed_public_url_prefixes) or source_url.startswith(
            self.config.allowed_sandbox_url_prefixes
        )

    def _rate_limit_key(self, request: PublicSourceSnapshotRequest) -> str:
        return request.rate_limit_key or f"{self.config.adapter_id}:{request.source_registry_id}"

    def _rate_limit_state(self, request: PublicSourceSnapshotRequest, *, now: str) -> dict[str, Any]:
        key = self._rate_limit_key(request)
        last_fetch_at = self._last_fetch_at_by_key.get(key)
        min_interval = float(self.config.min_interval_seconds)
        allowed = True
        wait_seconds = 0.0
        if last_fetch_at and min_interval > 0:
            elapsed = _seconds_between(last_fetch_at, now)
            if elapsed is not None and elapsed < min_interval:
                allowed = False
                wait_seconds = min_interval - elapsed
        return {
            "policy_id": "STAGE2_PUBLIC_SOURCE_RATE_LIMIT_V1",
            "rate_limit_key": key,
            "allowed": allowed,
            "min_interval_seconds": min_interval,
            "last_fetch_at": last_fetch_at,
            "evaluated_at": now,
            "retry_after_seconds": round(wait_seconds, 6),
        }

    def _degraded_result(
        self,
        request: PublicSourceSnapshotRequest,
        *,
        reason: str,
        now: str,
        fetch_audit: Mapping[str, Any],
    ) -> PublicSourceSnapshotResult:
        resolved_fetch_audit = dict(fetch_audit)
        resolved_fetch_audit.setdefault("source_family", request.source_family)
        resolved_fetch_audit.setdefault("record_kind", request.record_kind)
        source_health = {
            "adapter_id": self.config.adapter_id,
            "source_family": request.source_family,
            "record_kind": request.record_kind,
            "source_registry_id": request.source_registry_id,
            "source_url": request.source_url,
            "source_health_state": "DEGRADED",
            "last_failure_reason": reason,
            "failure_degrade_state": "DEGRADED_TO_READBACK_CARRIER",
            "rate_limit_state": dict(resolved_fetch_audit.get("rate_limit", {})),
            "retry_count": max(0, int(resolved_fetch_audit.get("attempt_count", 0)) - 1),
            "timeout_seconds": request.timeout_seconds,
            "manual_review_required": True,
        }
        lineage_refs = self._lineage_refs(
            request,
            snapshot_version=request.snapshot_version or "DEGRADED",
        )
        self._copy_lineage_metadata(source_health, lineage_refs)
        failure_degrade = {
            "degrade_reason": reason,
            "degraded_at": now,
            "snapshot_persisted": False,
            "readback_state": "NO_SNAPSHOT_DUE_TO_DEGRADE",
            "manual_review_required": True,
            "no_broad_fallback": True,
            "fail_closed": True,
        }
        return PublicSourceSnapshotResult(
            status="DEGRADED",
            adapter_id=self.config.adapter_id,
            snapshot_id=None,
            raw_snapshot_metadata=None,
            source_health=source_health,
            fetch_audit=resolved_fetch_audit,
            readback=None,
            failure_degrade=failure_degrade,
        )

    def _snapshot_id(self, *, source_url: str, snapshot_version: str, sha256: str) -> str:
        digest = hashlib.sha256(
            f"{self.config.adapter_id}|{source_url}|{snapshot_version}|{sha256}".encode("utf-8")
        ).hexdigest()
        if self.config.adapter_id == PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID:
            packet_marker = "114B"
        elif self.config.adapter_id == NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID:
            packet_marker = "114C"
        elif self.config.adapter_id == CREDIT_CHINA_ADAPTER_ID:
            packet_marker = "114D"
        elif self.config.adapter_id == NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID:
            packet_marker = "114E"
        elif self.config.adapter_id == GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID:
            packet_marker = "114F"
        elif self.config.adapter_id == TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID:
            packet_marker = "114G"
        elif self.config.adapter_id == TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID:
            packet_marker = "114H"
        else:
            packet_marker = "114A"
        return f"SNAP-S2-{packet_marker}-{digest[:20]}"

    def _lineage_refs(
        self,
        request: PublicSourceSnapshotRequest,
        *,
        snapshot_version: str,
    ) -> dict[str, str]:
        refs = {
            str(key): str(value)
            for key, value in dict(request.lineage_refs).items()
            if value not in (None, "")
        }
        refs.update(
            {
                "stage_scope": "2",
                "adapter_id": self.config.adapter_id,
                "source_family": request.source_family,
                "source_registry_id": request.source_registry_id,
                "snapshot_version": snapshot_version,
            }
        )
        if request.record_kind not in (None, ""):
            refs["record_kind"] = str(request.record_kind)
        normalized_record_kind = str(request.record_kind or "")
        notice_type = TENDER_AGENCY_NOTICE_TYPES_BY_RECORD_KIND.get(
            normalized_record_kind
        ) or TENDERER_NOTICE_TYPES_BY_RECORD_KIND.get(normalized_record_kind)
        if notice_type and "notice_type" not in refs:
            refs["notice_type"] = notice_type
        return refs

    def _snapshot_kind(self, content_type: str) -> str:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized in {"text/html", "application/xhtml+xml"}:
            return "raw_html"
        if normalized == "application/pdf":
            return "raw_pdf"
        return "raw_attachment"

    def _copy_lineage_metadata(
        self,
        target: dict[str, Any],
        lineage_refs: Mapping[str, Any],
    ) -> None:
        for key in (
            "agency_name_optional",
            "agency_site_domain_optional",
            "tenderer_name_optional",
            "tenderer_site_domain_optional",
            "notice_authority_role",
            "notice_type",
            "project_lineage_id",
            "source_blueprint_batch_id",
        ):
            value = lineage_refs.get(key)
            if value not in (None, ""):
                target[key] = value

    def _preflight_degrade_reason(
        self,
        request: PublicSourceSnapshotRequest,
    ) -> str | None:
        if self.config.adapter_id == TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID:
            flags = {
                str(key): bool(value) for key, value in request.boundary_flags.items()
            }
            for flag_name in ("weak_structure", "weak_page_structure"):
                if flags.get(flag_name):
                    return "weak_structure"
            lineage = dict(request.lineage_refs)
            for key in (
                "notice_authority_role",
                "project_lineage_id",
                "source_blueprint_batch_id",
            ):
                if lineage.get(key) in (None, ""):
                    return "missing_key_lineage"
        return None


def _seconds_between(start: str, end: str) -> float | None:
    try:
        start_dt = _parse_iso_datetime(start)
        end_dt = _parse_iso_datetime(end)
    except ValueError:
        return None
    return (end_dt - start_dt).total_seconds()


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


__all__ = [
    "ALLOWED_FETCH_MODES",
    "ALLOWED_VISIBILITY_STATES",
    "BLOCKED_FETCH_MODES",
    "BLOCKED_VISIBILITY_STATES",
    "CONTROLLED_TEST_TRANSPORT_STATE",
    "CREDIT_CHINA_ADAPTER_ID",
    "CREDIT_CHINA_ADMINISTRATIVE_PENALTY_RECORD_KIND",
    "CREDIT_CHINA_CREDIT_EXCEPTION_RECORD_KIND",
    "CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND",
    "CREDIT_CHINA_PUBLIC_URL_PREFIXES",
    "CREDIT_CHINA_RECORD_KINDS",
    "CREDIT_CHINA_REGISTRY_IDS",
    "CREDIT_CHINA_SANDBOX_URL_PREFIXES",
    "CREDIT_CHINA_SOURCE_FAMILY",
    "GOVERNMENT_PROCUREMENT_ATTACHMENT_RECORD_KIND",
    "GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND",
    "GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID",
    "GOVERNMENT_PROCUREMENT_PUBLIC_SITE_PUBLIC_URL_PREFIXES",
    "GOVERNMENT_PROCUREMENT_PUBLIC_SITE_RECORD_KINDS",
    "GOVERNMENT_PROCUREMENT_PUBLIC_SITE_REGISTRY_IDS",
    "GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SANDBOX_URL_PREFIXES",
    "GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY",
    "GOVERNMENT_PROCUREMENT_RESULT_RECORD_KIND",
    "LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID",
    "LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_PUBLIC_URL_PREFIXES",
    "LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_REGISTRY_IDS",
    "LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_SANDBOX_URL_PREFIXES",
    "LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_SOURCE_FAMILY",
    "LocalPublicResourceTradingCenterSourceAdapter",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PERSONNEL_RECORD_KIND",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PROJECT_RECORD_KIND",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_PUBLIC_URL_PREFIXES",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_RECORD_KINDS",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_REGISTRY_IDS",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SANDBOX_URL_PREFIXES",
    "NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_ABNORMAL_OPERATION_RECORD_KIND",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_REGISTRATION_RECORD_KIND",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_PUBLIC_URL_PREFIXES",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_RECORD_KINDS",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_REGISTRY_IDS",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SANDBOX_URL_PREFIXES",
    "NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY",
    "PUBLIC_VISIBLE_STATE",
    "PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID",
    "PROVINCIAL_BIDDING_PLATFORM_PUBLIC_URL_PREFIXES",
    "PROVINCIAL_BIDDING_PLATFORM_REGISTRY_IDS",
    "PROVINCIAL_BIDDING_PLATFORM_SANDBOX_URL_PREFIXES",
    "PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY",
    "PublicSourceAdapterConfig",
    "PublicSourceAdapterError",
    "PublicSourceBoundaryError",
    "PublicSourceSnapshotRequest",
    "PublicSourceSnapshotResult",
    "PublicSourceTimeoutError",
    "PublicSourceTransportError",
    "PublicSourceTransportResponse",
    "SANDBOX_LOCAL_MIRROR_STATE",
    "StaticPublicSourceTransport",
    "TENDER_AGENCY_AWARD_RESULT_RECORD_KIND",
    "TENDER_AGENCY_CANDIDATE_NOTICE_RECORD_KIND",
    "TENDER_AGENCY_CORRECTION_NOTICE_RECORD_KIND",
    "TENDER_AGENCY_NOTICE_TYPES_BY_RECORD_KIND",
    "TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID",
    "TENDER_AGENCY_PUBLIC_SITE_PUBLIC_URL_PREFIXES",
    "TENDER_AGENCY_PUBLIC_SITE_RECORD_KINDS",
    "TENDER_AGENCY_PUBLIC_SITE_REGISTRY_IDS",
    "TENDER_AGENCY_PUBLIC_SITE_SANDBOX_URL_PREFIXES",
    "TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY",
    "TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND",
    "TENDERER_AWARD_RESULT_RECORD_KIND",
    "TENDERER_CANDIDATE_NOTICE_RECORD_KIND",
    "TENDERER_CORRECTION_NOTICE_RECORD_KIND",
    "TENDERER_NOTICE_TYPES_BY_RECORD_KIND",
    "TENDERER_OWNER_NOTICE_RECORD_KIND",
    "TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID",
    "TENDERER_PUBLIC_NOTICE_PAGE_PUBLIC_URL_PREFIXES",
    "TENDERER_PUBLIC_NOTICE_PAGE_RECORD_KINDS",
    "TENDERER_PUBLIC_NOTICE_PAGE_REGISTRY_IDS",
    "TENDERER_PUBLIC_NOTICE_PAGE_SANDBOX_URL_PREFIXES",
    "TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY",
    "credit_china_adapter_config",
    "government_procurement_public_site_adapter_config",
    "local_public_resource_trading_center_adapter_config",
    "national_enterprise_credit_publicity_system_adapter_config",
    "national_construction_market_platform_adapter_config",
    "provincial_bidding_platform_adapter_config",
    "resolve_public_source_adapter_config",
    "tender_agency_public_site_adapter_config",
    "tenderer_public_notice_page_adapter_config",
]
