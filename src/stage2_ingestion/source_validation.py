from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from stage2_ingestion.public_source_adapters import (
    CREDIT_CHINA_ADAPTER_ID,
    CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
    CREDIT_CHINA_SOURCE_FAMILY,
    GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
    GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
    INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
    INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
    INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
    LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
    NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
    NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
    PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
    PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
    PublicSourceSnapshotRequest,
    TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID,
    TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY,
    TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
    TENDERER_OWNER_NOTICE_RECORD_KIND,
    TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID,
    TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY,
)


VALIDATION_BUCKET_SUPPORTED = "supported"
VALIDATION_BUCKET_WEAK = "weak"
VALIDATION_BUCKET_FAILING = "failing"
VALIDATION_BUCKET_SUSPENDED = "suspended"
VALIDATION_BUCKET_REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True)
class PublicSourceValidationSample:
    sample_id: str
    packet_ref: str
    adapter_id: str
    source_family: str
    source_registry_id: str
    source_url: str
    source_visibility_state: str
    expected_bucket: str
    target_type: str
    target_identifier: str
    content_type: str = "text/html; charset=utf-8"
    record_kind: str | None = None
    snapshot_version: str | None = None
    sample_mode: str = "CONTROLLED_MANUAL_PUBLIC_SNAPSHOT"
    content_text: str = ""
    lineage_refs: Mapping[str, Any] = field(default_factory=dict)
    boundary_flags: Mapping[str, Any] = field(default_factory=dict)

    def content_bytes(self) -> bytes:
        return self.content_text.encode("utf-8")


@dataclass(frozen=True)
class PublicSourceValidationResult:
    sample_id: str
    packet_ref: str
    adapter_id: str
    source_family: str
    source_registry_id: str
    source_url: str
    sample_mode: str
    expected_bucket: str
    observed_bucket: str
    capture_state: str
    snapshot_id_optional: str | None
    sha256_optional: str | None
    lineage_preserved: bool
    parse_state: str
    parsed_field_names: tuple[str, ...]
    parsed_field_count: int
    verification_result: str
    evidence_grade: str
    review_required: bool
    fail_closed: bool
    no_broad_fallback: bool
    blocked_reason_optional: str | None = None

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parsed_field_names"] = list(self.parsed_field_names)
        return payload


def source_validation_samples() -> tuple[PublicSourceValidationSample, ...]:
    return SOURCE_VALIDATION_SAMPLE_MATRIX


def build_validation_request(sample: PublicSourceValidationSample) -> PublicSourceSnapshotRequest:
    return PublicSourceSnapshotRequest(
        source_url=sample.source_url,
        source_registry_id=sample.source_registry_id,
        source_family=sample.source_family,
        record_kind=sample.record_kind,
        source_visibility_state=sample.source_visibility_state,
        fetch_mode="controlled_test_transport",
        lineage_refs=dict(sample.lineage_refs),
        snapshot_version=sample.snapshot_version or sample.sample_id.lower(),
        content_type_hint=sample.content_type,
        timeout_seconds=5,
        max_retries=1,
        boundary_flags=dict(sample.boundary_flags),
    )


def build_supported_validation_result(
    sample: PublicSourceValidationSample,
    *,
    capture: Mapping[str, Any] | Any,
    parsed_carrier: Mapping[str, Any],
    verification_carrier: Mapping[str, Any],
) -> PublicSourceValidationResult:
    capture_payload = capture.as_payload() if hasattr(capture, "as_payload") else dict(capture)
    raw_metadata = dict(capture_payload.get("raw_snapshot_metadata") or {})
    parsed_fields = [
        dict(field)
        for field in parsed_carrier.get("parsed_fields", [])
        if isinstance(field, Mapping)
    ]
    field_names = tuple(sorted({str(field.get("field_name")) for field in parsed_fields}))
    parse_state = str(parsed_carrier.get("parse_state") or "UNKNOWN")
    verification_result = str(verification_carrier.get("verification_result") or "UNKNOWN")
    evidence_grade = str(verification_carrier.get("evidence_grade") or "UNKNOWN")
    review_required = bool(
        parsed_carrier.get("review_required") or verification_carrier.get("review_required")
    )
    lineage_refs = dict(raw_metadata.get("lineage_refs") or {})
    lineage_preserved = bool(
        lineage_refs.get("project_id")
        and lineage_refs.get("stage1_handoff_intent_id")
        and raw_metadata.get("sha256")
    )
    observed_bucket = _observed_bucket(
        expected_bucket=sample.expected_bucket,
        parse_state=parse_state,
        verification_result=verification_result,
        review_required=review_required,
        parsed_field_count=len(parsed_fields),
    )
    return PublicSourceValidationResult(
        sample_id=sample.sample_id,
        packet_ref=sample.packet_ref,
        adapter_id=sample.adapter_id,
        source_family=sample.source_family,
        source_registry_id=sample.source_registry_id,
        source_url=sample.source_url,
        sample_mode=sample.sample_mode,
        expected_bucket=sample.expected_bucket,
        observed_bucket=observed_bucket,
        capture_state=str(capture_payload.get("result_state") or "CAPTURED"),
        snapshot_id_optional=str(capture_payload.get("snapshot_id") or raw_metadata.get("snapshot_id")),
        sha256_optional=str(capture_payload.get("sha256") or raw_metadata.get("sha256")),
        lineage_preserved=lineage_preserved,
        parse_state=parse_state,
        parsed_field_names=field_names,
        parsed_field_count=len(parsed_fields),
        verification_result=verification_result,
        evidence_grade=evidence_grade,
        review_required=review_required,
        fail_closed=observed_bucket in {
            VALIDATION_BUCKET_WEAK,
            VALIDATION_BUCKET_FAILING,
            VALIDATION_BUCKET_SUSPENDED,
            VALIDATION_BUCKET_REVIEW_REQUIRED,
        },
        no_broad_fallback=True,
    )


def build_blocked_validation_result(
    sample: PublicSourceValidationSample,
    *,
    blocked_reason: str,
    blocked_carrier: Mapping[str, Any] | None = None,
) -> PublicSourceValidationResult:
    carrier = dict(blocked_carrier or {})
    return PublicSourceValidationResult(
        sample_id=sample.sample_id,
        packet_ref=sample.packet_ref,
        adapter_id=sample.adapter_id,
        source_family=sample.source_family,
        source_registry_id=sample.source_registry_id,
        source_url=sample.source_url,
        sample_mode=sample.sample_mode,
        expected_bucket=sample.expected_bucket,
        observed_bucket=VALIDATION_BUCKET_SUSPENDED,
        capture_state=str(carrier.get("result_state") or "BLOCKED_BEFORE_TRANSPORT"),
        snapshot_id_optional=None,
        sha256_optional=None,
        lineage_preserved=False,
        parse_state="NOT_PARSED",
        parsed_field_names=(),
        parsed_field_count=0,
        verification_result="NOT_RUN",
        evidence_grade="NOT_GRADED",
        review_required=True,
        fail_closed=True,
        no_broad_fallback=True,
        blocked_reason_optional=blocked_reason,
    )


def build_degraded_validation_result(
    sample: PublicSourceValidationSample,
    *,
    capture: Mapping[str, Any] | Any,
) -> PublicSourceValidationResult:
    capture_payload = capture.as_payload() if hasattr(capture, "as_payload") else dict(capture)
    source_health = dict(capture_payload.get("source_health") or {})
    failure_degrade = dict(capture_payload.get("failure_degrade") or {})
    reason = str(
        failure_degrade.get("degrade_reason")
        or source_health.get("last_failure_reason")
        or "degraded_capture"
    )
    return PublicSourceValidationResult(
        sample_id=sample.sample_id,
        packet_ref=sample.packet_ref,
        adapter_id=sample.adapter_id,
        source_family=sample.source_family,
        source_registry_id=sample.source_registry_id,
        source_url=sample.source_url,
        sample_mode=sample.sample_mode,
        expected_bucket=sample.expected_bucket,
        observed_bucket=VALIDATION_BUCKET_FAILING,
        capture_state=str(capture_payload.get("status") or "DEGRADED"),
        snapshot_id_optional=None,
        sha256_optional=None,
        lineage_preserved=bool(source_health.get("project_id")),
        parse_state="NOT_PARSED",
        parsed_field_names=(),
        parsed_field_count=0,
        verification_result="NOT_RUN",
        evidence_grade="NOT_GRADED",
        review_required=True,
        fail_closed=True,
        no_broad_fallback=bool(
            failure_degrade.get("no_broad_fallback", source_health.get("no_broad_fallback", True))
        ),
        blocked_reason_optional=reason,
    )


def build_source_coverage_report(
    results: Iterable[PublicSourceValidationResult | Mapping[str, Any]],
) -> dict[str, Any]:
    payloads = [
        result.as_payload() if isinstance(result, PublicSourceValidationResult) else dict(result)
        for result in results
    ]
    by_bucket: dict[str, int] = {
        VALIDATION_BUCKET_SUPPORTED: 0,
        VALIDATION_BUCKET_WEAK: 0,
        VALIDATION_BUCKET_FAILING: 0,
        VALIDATION_BUCKET_SUSPENDED: 0,
        VALIDATION_BUCKET_REVIEW_REQUIRED: 0,
    }
    for payload in payloads:
        bucket = str(payload.get("observed_bucket") or VALIDATION_BUCKET_REVIEW_REQUIRED)
        by_bucket[bucket] = by_bucket.get(bucket, 0) + 1

    supported_results = [
        payload for payload in payloads if payload.get("observed_bucket") == VALIDATION_BUCKET_SUPPORTED
    ]
    return {
        "report_id": "PTL-I100-128-real-public-source-field-validation-report",
        "packet_ref": "PTL-I100-128-real-public-source-field-validation-and-coverage",
        "sample_mode": "CONTROLLED_MANUAL_PUBLIC_SNAPSHOT",
        "sample_count": len(payloads),
        "supported_source_family_count": len(
            {payload.get("source_family") for payload in supported_results}
        ),
        "source_families_validated": sorted(
            {
                str(payload.get("source_family"))
                for payload in supported_results
                if payload.get("source_family")
            }
        ),
        "coverage_buckets": by_bucket,
        "field_coverage": {
            "required_fields": [
                "project_name",
                "tenderer_or_purchaser",
                "announcement_date",
            ],
            "supported_samples_with_required_fields": sum(
                _has_required_fields(payload) for payload in supported_results
            ),
            "weak_or_review_required_samples": by_bucket.get(VALIDATION_BUCKET_WEAK, 0)
            + by_bucket.get(VALIDATION_BUCKET_REVIEW_REQUIRED, 0),
        },
        "verification_coverage": {
            "matched_public_verification_count": sum(
                payload.get("verification_result") == "MATCHED" for payload in supported_results
            ),
            "review_or_fail_closed_count": sum(
                bool(payload.get("fail_closed")) for payload in payloads
            ),
        },
        "controlled_opening_boundaries": {
            "private_or_gray_source_used": False,
            "login_bypass_used": False,
            "captcha_bypass_used": False,
            "anti_bot_bypass_used": False,
            "uncontrolled_live_crawler_used": False,
            "real_provider_call_executed": False,
        },
        "results": payloads,
    }


def _observed_bucket(
    *,
    expected_bucket: str,
    parse_state: str,
    verification_result: str,
    review_required: bool,
    parsed_field_count: int,
) -> str:
    if expected_bucket in {VALIDATION_BUCKET_FAILING, VALIDATION_BUCKET_SUSPENDED}:
        return expected_bucket
    if parsed_field_count == 0 or parse_state == "REVIEW_REQUIRED":
        return VALIDATION_BUCKET_WEAK
    if review_required or verification_result != "MATCHED":
        return VALIDATION_BUCKET_REVIEW_REQUIRED
    return VALIDATION_BUCKET_SUPPORTED


def _has_required_fields(payload: Mapping[str, Any]) -> bool:
    names = set(payload.get("parsed_field_names") or [])
    return {"project_name", "tenderer_or_purchaser", "announcement_date"}.issubset(names)


def _html(project_name: str, tenderer: str, date: str) -> str:
    return (
        "<html><head><title>{project}</title></head><body>"
        "<table>"
        "<tr><td>项目名称</td><td>{project}</td></tr>"
        "<tr><td>招标人</td><td>{tenderer}</td></tr>"
        "<tr><td>公告日期</td><td>{date}</td></tr>"
        "</table>"
        "<p>公开来源样本，仅用于受控手工 snapshot 验证。</p>"
        "</body></html>"
    ).format(project=project_name, tenderer=tenderer, date=date)


SOURCE_VALIDATION_SAMPLE_MATRIX: tuple[PublicSourceValidationSample, ...] = (
    PublicSourceValidationSample(
        sample_id="S2-128-114A-LOCAL-PRTC",
        packet_ref="PTL-I100-114A-local-public-resource-trading-centers",
        adapter_id=LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
        source_family="PROCUREMENT_NOTICE",
        source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
        source_url="https://public.example.local/local-public-resource-trading-centers/128/local.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="contract_public_info",
        target_identifier="128 Local Public Resource Project",
        content_text=_html("128 Local Public Resource Project", "Local Tenderer", "2026-04-01"),
        lineage_refs={"project_id": "P-128-114A", "stage1_handoff_intent_id": "HINT-128-114A"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114B-PROVINCIAL",
        packet_ref="PTL-I100-114B-provincial-bidding-platforms",
        adapter_id=PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
        source_family=PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
        source_registry_id="SRC-REG-PROV-BID-ANNOUNCEMENT-HTML",
        source_url="https://public.example.local/provincial-bidding-platforms/128/provincial.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="contract_public_info",
        target_identifier="128 Provincial Bidding Project",
        content_text=_html("128 Provincial Bidding Project", "Provincial Tenderer", "2026-04-02"),
        lineage_refs={"project_id": "P-128-114B", "stage1_handoff_intent_id": "HINT-128-114B"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114C-NCMP",
        packet_ref="PTL-I100-114C-national-construction-market-platform",
        adapter_id=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ADAPTER_ID,
        source_family=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_SOURCE_FAMILY,
        source_registry_id="SRC-REG-NCMP-ENTERPRISE-PUBLIC-RECORD",
        source_url="https://public.example.local/national-construction-market-platform/128/enterprise.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="enterprise_public_record",
        target_identifier="128 NCMP Enterprise Project",
        record_kind=NATIONAL_CONSTRUCTION_MARKET_PLATFORM_ENTERPRISE_RECORD_KIND,
        content_text=_html("128 NCMP Enterprise Project", "NCMP Enterprise", "2026-04-03"),
        lineage_refs={"project_id": "P-128-114C", "stage1_handoff_intent_id": "HINT-128-114C"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114D-CREDIT-CHINA",
        packet_ref="PTL-I100-114D-credit-china",
        adapter_id=CREDIT_CHINA_ADAPTER_ID,
        source_family=CREDIT_CHINA_SOURCE_FAMILY,
        source_registry_id="SRC-REG-CREDIT-CHINA-PUBLIC-RECORD",
        source_url="https://public.example.local/credit-china/128/credit.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="credit_penalty_blacklist",
        target_identifier="128 Credit China Project",
        record_kind=CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
        content_text=_html("128 Credit China Project", "Credit Public Entity", "2026-04-04"),
        lineage_refs={"project_id": "P-128-114D", "stage1_handoff_intent_id": "HINT-128-114D"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114E-NECPS",
        packet_ref="PTL-I100-114E-national-enterprise-credit-publicity-system",
        adapter_id=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ADAPTER_ID,
        source_family=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_SOURCE_FAMILY,
        source_registry_id="SRC-REG-NECPS-ENTERPRISE-PUBLIC-RECORD",
        source_url="https://public.example.local/national-enterprise-credit-publicity-system/128/enterprise.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="enterprise_public_record",
        target_identifier="128 NECPS Enterprise Project",
        record_kind=NATIONAL_ENTERPRISE_CREDIT_PUBLICITY_SYSTEM_ENTERPRISE_PUBLIC_RECORD_KIND,
        content_text=_html("128 NECPS Enterprise Project", "NECPS Enterprise", "2026-04-05"),
        lineage_refs={"project_id": "P-128-114E", "stage1_handoff_intent_id": "HINT-128-114E"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114F-GOV-PROC",
        packet_ref="PTL-I100-114F-government-procurement-public-sites",
        adapter_id=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_ADAPTER_ID,
        source_family=GOVERNMENT_PROCUREMENT_PUBLIC_SITE_SOURCE_FAMILY,
        source_registry_id="SRC-REG-GOV-PROCUREMENT-NOTICE",
        source_url="https://public.example.local/government-procurement-public-sites/128/notice.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="contract_public_info",
        target_identifier="128 Government Procurement Project",
        record_kind=GOVERNMENT_PROCUREMENT_NOTICE_RECORD_KIND,
        content_text=_html("128 Government Procurement Project", "Government Purchaser", "2026-04-06"),
        lineage_refs={"project_id": "P-128-114F", "stage1_handoff_intent_id": "HINT-128-114F"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114G-TENDER-AGENCY",
        packet_ref="PTL-I100-114G-tender-agency-public-sites",
        adapter_id=TENDER_AGENCY_PUBLIC_SITE_ADAPTER_ID,
        source_family=TENDER_AGENCY_PUBLIC_SITE_SOURCE_FAMILY,
        source_registry_id="SRC-REG-TENDER-AGENCY-TENDER-NOTICE",
        source_url="https://public.example.local/tender-agency-public-sites/128/tender.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="contract_public_info",
        target_identifier="128 Tender Agency Project",
        record_kind=TENDER_AGENCY_TENDER_NOTICE_RECORD_KIND,
        content_text=_html("128 Tender Agency Project", "Agency Tenderer", "2026-04-07"),
        lineage_refs={"project_id": "P-128-114G", "stage1_handoff_intent_id": "HINT-128-114G"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114H-TENDERER",
        packet_ref="PTL-I100-114H-tenderer-public-notice-pages",
        adapter_id=TENDERER_PUBLIC_NOTICE_PAGE_ADAPTER_ID,
        source_family=TENDERER_PUBLIC_NOTICE_PAGE_SOURCE_FAMILY,
        source_registry_id="SRC-REG-TENDERER-OWNER-NOTICE",
        source_url="https://public.example.local/tenderer-public-notice-pages/128/owner.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="contract_public_info",
        target_identifier="128 Tenderer Owner Project",
        record_kind=TENDERER_OWNER_NOTICE_RECORD_KIND,
        content_text=_html("128 Tenderer Owner Project", "Owner Tenderer", "2026-04-08"),
        lineage_refs={
            "project_id": "P-128-114H",
            "stage1_handoff_intent_id": "HINT-128-114H",
            "notice_authority_role": "tenderer",
            "project_lineage_id": "PROJECT-LINEAGE-128-114H",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
        },
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-114I-INDUSTRY-AUTHORITY",
        packet_ref="PTL-I100-114I-industry-authority-filing-pages",
        adapter_id=INDUSTRY_AUTHORITY_FILING_PAGE_ADAPTER_ID,
        source_family=INDUSTRY_AUTHORITY_FILING_PAGE_SOURCE_FAMILY,
        source_registry_id="SRC-REG-INDUSTRY-AUTHORITY-CONSTRUCTION-PERMIT",
        source_url="https://public.example.local/industry-authority-filing-pages/128/permit.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_SUPPORTED,
        target_type="construction_permit",
        target_identifier="128 Industry Authority Permit Project",
        record_kind=INDUSTRY_AUTHORITY_CONSTRUCTION_PERMIT_FILING_RECORD_KIND,
        content_text=_html("128 Industry Authority Permit Project", "Industry Authority", "2026-04-09"),
        lineage_refs={
            "project_id": "P-128-114I",
            "stage1_handoff_intent_id": "HINT-128-114I",
            "project_lineage_id": "PROJECT-LINEAGE-128-114I",
            "source_blueprint_batch_id": "PTL-I100-ROADMAP-01",
            "filing_type": "construction_permit",
            "source_coverage_report": {
                "coverage_state": "COMPLETE",
                "expected_filing_types": [
                    "construction_permit",
                    "contract_filing",
                    "completion_acceptance",
                    "performance_filing",
                ],
                "captured_filing_types": [
                    "construction_permit",
                    "contract_filing",
                    "completion_acceptance",
                    "performance_filing",
                ],
                "missing_filing_types": [],
                "duplicate_source_refs": [],
                "manual_review_required": False,
                "no_broad_fallback": True,
            },
        },
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-WEAK-MANUAL-REVIEW",
        packet_ref="PTL-I100-128-real-public-source-field-validation-and-coverage",
        adapter_id=LOCAL_PUBLIC_RESOURCE_TRADING_CENTER_ADAPTER_ID,
        source_family="PROCUREMENT_NOTICE",
        source_registry_id="SRC-REG-PROC-NATIONAL-HTML",
        source_url="https://public.example.local/local-public-resource-trading-centers/128/weak.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_WEAK,
        target_type="contract_public_info",
        target_identifier="Weak Public Project",
        content_text="<html><body><p>weak public sample without stable field labels</p></body></html>",
        lineage_refs={"project_id": "P-128-WEAK", "stage1_handoff_intent_id": "HINT-128-WEAK"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-FAILING-TRANSPORT",
        packet_ref="PTL-I100-128-real-public-source-field-validation-and-coverage",
        adapter_id=PROVINCIAL_BIDDING_PLATFORM_ADAPTER_ID,
        source_family=PROVINCIAL_BIDDING_PLATFORM_SOURCE_FAMILY,
        source_registry_id="SRC-REG-PROV-BID-ANNOUNCEMENT-HTML",
        source_url="https://public.example.local/provincial-bidding-platforms/128/failing.html",
        source_visibility_state="PUBLIC_VISIBLE",
        expected_bucket=VALIDATION_BUCKET_FAILING,
        target_type="contract_public_info",
        target_identifier="Failing Public Project",
        lineage_refs={"project_id": "P-128-FAIL", "stage1_handoff_intent_id": "HINT-128-FAIL"},
    ),
    PublicSourceValidationSample(
        sample_id="S2-128-SUSPENDED-CAPTCHA",
        packet_ref="PTL-I100-128-real-public-source-field-validation-and-coverage",
        adapter_id=CREDIT_CHINA_ADAPTER_ID,
        source_family=CREDIT_CHINA_SOURCE_FAMILY,
        source_registry_id="SRC-REG-CREDIT-CHINA-PUBLIC-RECORD",
        source_url="https://public.example.local/credit-china/128/captcha.html",
        source_visibility_state="CAPTCHA_REQUIRED",
        expected_bucket=VALIDATION_BUCKET_SUSPENDED,
        target_type="credit_penalty_blacklist",
        target_identifier="Suspended Captcha Project",
        record_kind=CREDIT_CHINA_CREDIT_PUBLIC_RECORD_KIND,
        lineage_refs={"project_id": "P-128-SUSP", "stage1_handoff_intent_id": "HINT-128-SUSP"},
    ),
)


__all__ = [
    "PublicSourceValidationResult",
    "PublicSourceValidationSample",
    "SOURCE_VALIDATION_SAMPLE_MATRIX",
    "VALIDATION_BUCKET_FAILING",
    "VALIDATION_BUCKET_REVIEW_REQUIRED",
    "VALIDATION_BUCKET_SUPPORTED",
    "VALIDATION_BUCKET_SUSPENDED",
    "VALIDATION_BUCKET_WEAK",
    "build_blocked_validation_result",
    "build_degraded_validation_result",
    "build_source_coverage_report",
    "build_supported_validation_result",
    "build_validation_request",
    "source_validation_samples",
]
