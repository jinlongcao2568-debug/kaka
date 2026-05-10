from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stage2_ingestion.real_public_url_fetcher import REAL_PUBLIC_ENTRY_PROFILE_BY_ID


NATIONAL_DISCOVERY_PROFILE_IDS = (
    "GGZY-DEAL-LIST",
    "CCGP-CENTRAL-NOTICES",
    "CCGP-CENTRAL-AWARD-LIST",
)
NATIONAL_VERIFICATION_PROFILE_IDS = (
    "JZSC-NATIONAL-HOME",
    "JZSC-NATIONAL-COMPANY",
    "JZSC-NATIONAL-PROJECT",
    "CREDITCHINA-HOME",
    "GSXT-HOME",
)
DEFAULT_COVERAGE_GAP_SIGNALS = (
    "province_platform_missing_detail_or_attachment",
)
PRIMARY_FRIENDLY_SOURCE_PROFILE_IDS = {
    "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
    "ZHEJIANG-GGZY-JYXXGK-LIST",
    "SICHUAN-GGZY-TRANSACTION-INFO",
}
ACTIVE_WITH_CHALLENGE_SOURCE_PROFILE_IDS = {
    "JIANGSU-GGZY-HOME",
    "HUBEI-BIDCLOUD-JYXX-LIST",
}
QUARANTINED_SOURCE_PROFILE_IDS = {
    "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
}


@dataclass(frozen=True)
class RegionSourceAdapter:
    region_code: str
    region_name: str
    adapter_state: str
    entry_profile_ids: tuple[str, ...]
    fallback_entry_profile_ids: tuple[str, ...] = ()
    verification_profile_ids: tuple[str, ...] = NATIONAL_VERIFICATION_PROFILE_IDS
    coverage_gap_signals: tuple[str, ...] = DEFAULT_COVERAGE_GAP_SIGNALS
    dedicated_local_profiles: bool = False
    onboarding_required: bool = False
    commercial_pilot_region: bool = False
    source_quality_state: str = "OBSERVATION_NEEDS_SOURCE_ANALYSIS"
    notes: str = ""

    def as_payload(self) -> dict[str, Any]:
        unknown_profile_ids = [
            profile_id
            for profile_id in (
                *self.entry_profile_ids,
                *self.fallback_entry_profile_ids,
                *self.verification_profile_ids,
            )
            if profile_id not in REAL_PUBLIC_ENTRY_PROFILE_BY_ID
        ]
        primary_profile_id = (
            self.entry_profile_ids[0]
            if self.entry_profile_ids
            else self.fallback_entry_profile_ids[0]
            if self.fallback_entry_profile_ids
            else ""
        )
        return {
            "region_code": self.region_code,
            "region_name": self.region_name,
            "adapter_state": self.adapter_state,
            "searchable_now": bool(primary_profile_id) and not bool(unknown_profile_ids) and not self.onboarding_required,
            "primary_entry_profile_id": primary_profile_id,
            "entry_profile_ids": list(self.entry_profile_ids),
            "fallback_entry_profile_ids": list(self.fallback_entry_profile_ids),
            "verification_profile_ids": list(self.verification_profile_ids),
            "coverage_gap_signals": list(self.coverage_gap_signals),
            "dedicated_local_profiles": self.dedicated_local_profiles,
            "onboarding_required": self.onboarding_required,
            "commercial_pilot_region": self.commercial_pilot_region,
            "source_quality_state": self.source_quality_state,
            "source_quality_policy": resolve_source_quality_policy(primary_profile_id),
            "unknown_profile_ids": unknown_profile_ids,
            "notes": self.notes,
            "real_external_fetch_enabled_by_default": False,
            "manual_url_picker_primary_flow": False,
        }


REGION_SOURCE_ADAPTERS: tuple[RegionSourceAdapter, ...] = (
    RegionSourceAdapter(
        region_code="CN-NATIONAL",
        region_name="全国",
        adapter_state="NATIONAL_DISCOVERY_READY",
        entry_profile_ids=NATIONAL_DISCOVERY_PROFILE_IDS,
        fallback_entry_profile_ids=(),
        coverage_gap_signals=(),
        notes="全国公共资源和政府采购入口用于第一层发现与去重。",
    ),
    RegionSourceAdapter(
        region_code="CN-BJ",
        region_name="北京",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=(
            "BEIJING-PLATFORM-HOME",
            "BEIJING-GCJS-LIST",
            "BEIJING-BDA-HOME",
        ),
        dedicated_local_profiles=True,
        notes="北京用于技术回归和本地入口验证，不作为第一批商业试点省份。",
    ),
    RegionSourceAdapter(
        region_code="CN-GD",
        region_name="广东",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=(
            "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        ),
        verification_profile_ids=(
            *NATIONAL_VERIFICATION_PROFILE_IDS,
            "GUANGDONG-GDCIC-HOME",
            "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
            "GUANGDONG-TZXM-HOME",
            "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY",
            "GUANGDONG-CREDIT-GD-HOME",
        ),
        dedicated_local_profiles=True,
        commercial_pilot_region=True,
        source_quality_state="PRIMARY_FRIENDLY",
        coverage_gap_signals=("guangzhou_ywtb_full_tender_attachment_required",),
        notes="广东工程建设控标样本默认只使用广州交易集团/广州公共资源交易中心建设工程项目信息源；广东省公共资源交易平台 YGP 摘要和附件不完整，不再作为默认发现或校准来源。",
    ),
    RegionSourceAdapter(
        region_code="CN-SC",
        region_name="四川",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=("SICHUAN-GGZY-TRANSACTION-INFO",),
        dedicated_local_profiles=True,
        commercial_pilot_region=True,
        source_quality_state="PRIMARY_FRIENDLY",
        notes="四川按四川省公共资源交易信息网交易信息页作为省级实时入口；浏览器已验真可见当日全省公告。",
    ),
    RegionSourceAdapter(
        region_code="CN-JS",
        region_name="江苏",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=("JIANGSU-GGZY-HOME",),
        dedicated_local_profiles=True,
        commercial_pilot_region=True,
        source_quality_state="ACTIVE_WITH_CHALLENGE",
        notes="江苏按江苏省公共资源交易网作为省级实时入口；浏览器已验真可见近期交易信息。",
    ),
    RegionSourceAdapter(
        region_code="CN-ZJ",
        region_name="浙江",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=("ZHEJIANG-GGZY-JYXXGK-LIST",),
        dedicated_local_profiles=True,
        commercial_pilot_region=True,
        source_quality_state="PRIMARY_FRIENDLY",
        notes="浙江按浙江省公共资源交易服务平台交易信息公开页作为省级实时入口；浏览器已验真可见近期公告。",
    ),
    RegionSourceAdapter(
        region_code="CN-SD",
        region_name="山东",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=("SHANDONG-GGZY-JYXXGK-LIST",),
        dedicated_local_profiles=True,
        commercial_pilot_region=True,
        source_quality_state="OBSERVATION_NEEDS_SOURCE_ANALYSIS",
        notes="山东按山东省公共资源交易网交易公开页作为省级实时入口；浏览器已验真可见当日全省公告。",
    ),
    RegionSourceAdapter(
        region_code="CN-HB",
        region_name="湖北",
        adapter_state="LOCAL_PROFILE_READY",
        entry_profile_ids=("HUBEI-BIDCLOUD-JYXX-LIST",),
        dedicated_local_profiles=True,
        commercial_pilot_region=True,
        source_quality_state="ACTIVE_WITH_CHALLENGE",
        notes="湖北按湖北省公共资源交易云平台交易信息页作为省级实时入口；浏览器已验真可见近期公告。",
    ),
)

REGION_SOURCE_ADAPTER_BY_CODE = {
    adapter.region_code: adapter for adapter in REGION_SOURCE_ADAPTERS
}


def list_region_source_adapters() -> list[dict[str, Any]]:
    return [adapter.as_payload() for adapter in REGION_SOURCE_ADAPTERS]


def resolve_source_quality_policy(profile_id: str | None) -> dict[str, Any]:
    normalized = str(profile_id or "").strip()
    if normalized in QUARANTINED_SOURCE_PROFILE_IDS:
        state = "QUARANTINED"
        calibration_role = "EXCLUDED_FROM_ACTIVE_CALIBRATION"
        reason = "source_marked_pollution_or_incomplete_process"
    elif normalized in PRIMARY_FRIENDLY_SOURCE_PROFILE_IDS:
        state = "PRIMARY_FRIENDLY"
        calibration_role = "PRIMARY_CALIBRATION_SOURCE"
        reason = "professional_source_with_replayable_detail_and_attachment_path"
    elif normalized in ACTIVE_WITH_CHALLENGE_SOURCE_PROFILE_IDS:
        state = "ACTIVE_WITH_CHALLENGE"
        calibration_role = "SECONDARY_DIAGNOSTIC_SOURCE"
        reason = "public_source_available_but_challenge_or_attachment_stability_not_primary"
    elif normalized:
        state = "OBSERVATION_NEEDS_SOURCE_ANALYSIS"
        calibration_role = "OBSERVATION_ONLY_UNTIL_SOURCE_CONFIRMED"
        reason = "province_or_city_source_needs_human_source_assessment"
    else:
        state = "OBSERVATION_NEEDS_SOURCE_ANALYSIS"
        calibration_role = "UNRESOLVED_SOURCE"
        reason = "source_profile_missing"
    return {
        "source_quality_state": state,
        "source_calibration_role": calibration_role,
        "source_quality_reason": reason,
        "professional_source_priority": state == "PRIMARY_FRIENDLY",
        "active_discovery_allowed": state not in {"QUARANTINED", "HISTORICAL_ONLY"},
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def resolve_region_source_adapter(region_code: str | None) -> dict[str, Any]:
    normalized = str(region_code or "").strip().upper() or "CN-NATIONAL"
    adapter = REGION_SOURCE_ADAPTER_BY_CODE.get(normalized)
    if adapter is None:
        adapter = REGION_SOURCE_ADAPTER_BY_CODE["CN-NATIONAL"]
        payload = adapter.as_payload()
        payload["requested_region_code"] = normalized
        payload["fallback_reason"] = "unregistered_region_adapter"
        return payload
    return adapter.as_payload()


def resolve_entry_profile_for_region(
    region_code: str | None,
    *,
    requested_profile_id: str | None = None,
) -> dict[str, Any]:
    adapter = resolve_region_source_adapter(region_code)
    allowed_profile_ids = [
        *adapter.get("entry_profile_ids", []),
        *adapter.get("fallback_entry_profile_ids", []),
    ]
    requested = str(requested_profile_id or "").strip()
    if requested:
        if requested not in allowed_profile_ids:
            raise ValueError(
                f"profile_id_not_allowed_for_region:{adapter['region_code']}:{requested}"
            )
        profile_id = requested
    else:
        profile_id = str(adapter.get("primary_entry_profile_id") or "")
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID.get(profile_id)
    if profile is None:
        raise ValueError(f"region_adapter_profile_missing:{adapter['region_code']}:{profile_id}")
    return {
        "region_adapter": adapter,
        "entry_profile": {
            "profile_id": profile.profile_id,
            "url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "sample_detail_url": profile.sample_detail_url,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
        },
    }


__all__ = [
    "REGION_SOURCE_ADAPTERS",
    "RegionSourceAdapter",
    "list_region_source_adapters",
    "resolve_source_quality_policy",
    "resolve_entry_profile_for_region",
    "resolve_region_source_adapter",
]
