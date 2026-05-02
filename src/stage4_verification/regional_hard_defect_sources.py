from __future__ import annotations

from typing import Any, Mapping

from shared.utils import build_id


GUANGDONG_HARD_DEFECT_REQUIRED_SOURCE_TYPES = (
    "construction_permit",
    "contract_public_info",
    "completion_filing",
    "project_manager_change_notice",
    "personnel_public_record",
    "credit_penalty_blacklist",
    "administrative_penalty_public_record",
    "complaint_or_supervision_decision",
)


def build_regional_hard_defect_source_plan(
    candidate: Mapping[str, Any],
    *,
    covered_source_types: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    region_code = str(candidate.get("region_code") or "").upper()
    if region_code == "CN-GD":
        return _build_guangdong_source_plan(candidate, covered_source_types=covered_source_types)
    return _build_generic_source_plan(candidate, covered_source_types=covered_source_types)


def _query_context(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(candidate.get("project_id") or ""),
        "project_name": str(candidate.get("project_name") or ""),
        "candidate_company": str(candidate.get("candidate_company") or ""),
        "project_manager_name": str(candidate.get("project_manager_name") or ""),
        "project_manager_certificate_no": str(candidate.get("project_manager_certificate_no") or ""),
        "source_url": str(candidate.get("source_url") or ""),
    }


def _build_guangdong_source_plan(
    candidate: Mapping[str, Any],
    *,
    covered_source_types: list[str] | tuple[str, ...] | set[str] | None,
) -> dict[str, Any]:
    covered = _normalized_source_types(covered_source_types)
    required = set(GUANGDONG_HARD_DEFECT_REQUIRED_SOURCE_TYPES)
    missing = sorted(required - covered)
    plan_id = build_id("ST4REGSRC", candidate.get("project_id") or "GD", "CN-GD")
    return {
        "source_plan_id": plan_id,
        "region_code": "CN-GD",
        "region_name": "广东",
        "plan_state": "ENTRY_SOURCES_IDENTIFIED_PROJECT_LEVEL_QUERY_PENDING",
        "coverage_state": "PARTIAL" if missing else "COMPLETE",
        "query_context": _query_context(candidate),
        "required_source_types": sorted(required),
        "covered_source_types": sorted(covered),
        "missing_source_types": missing,
        "source_entries": [
            {
                "entry_id": "GD-GDCIC-SKYPT-PROJECT",
                "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                "source_name": "广东建设信息网 / 三库一平台项目信息",
                "source_url": "https://skypt.gdcic.net/openplatform/",
                "official_parent_url": "https://www.gdcic.net/",
                "source_family": "industry_authority_filing_page",
                "target_source_types": [
                    "construction_permit",
                    "contract_public_info",
                    "completion_filing",
                    "personnel_public_record",
                ],
                "query_keys": [
                    "project_name",
                    "candidate_company",
                    "project_manager_name",
                    "project_manager_certificate_no",
                    "construction_permit_no",
                ],
                "runtime_status": "PUBLIC_API_ENDPOINT_VERIFIED_PROJECT_QUERY_AVAILABLE",
                "next_adapter": "guangdong_gdcic_openplatform_public_api_query",
            },
            {
                "entry_id": "GD-GDCIC-CONTRACT-PERFORMANCE",
                "source_profile_id": "GUANGDONG-GDCIC-HOME",
                "source_name": "广东建设信息网 / 招投标及合同履约监管系统",
                "source_url": "http://210.76.80.152:8008",
                "official_parent_url": "https://www.gdcic.net/",
                "source_family": "industry_authority_filing_page",
                "target_source_types": ["contract_public_info", "project_manager_change_notice"],
                "query_keys": [
                    "project_name",
                    "candidate_company",
                    "project_code",
                    "contract_filing_no",
                ],
                "runtime_status": "ENTRY_PORTAL_LISTED_PROJECT_QUERY_ADAPTER_PENDING",
                "next_adapter": "guangdong_contract_performance_query_adapter",
            },
            {
                "entry_id": "GD-TZXM-PROJECT-PROGRESS",
                "source_profile_id": "GUANGDONG-TZXM-HOME",
                "source_name": "广东省投资项目在线审批监管平台",
                "source_url": "https://tzxm.gd.gov.cn/",
                "source_family": "investment_project_approval_platform",
                "target_source_types": ["construction_permit", "completion_filing"],
                "query_keys": ["project_name", "project_code", "approval_receipt_no"],
                "runtime_status": "ENTRY_PORTAL_VERIFIED_CODE_OR_CAPTCHA_QUERY_REQUIRED",
                "next_adapter": "guangdong_investment_project_progress_query_adapter",
            },
            {
                "entry_id": "GD-ZFCXJST-PENALTY",
                "source_profile_id": "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY",
                "source_name": "广东省住房和城乡建设厅行政处罚公示",
                "source_url": "https://zfcxjst.gd.gov.cn/xxgk/sgs/",
                "source_family": "local_housing_administrative_penalty",
                "target_source_types": [
                    "credit_penalty_blacklist",
                    "administrative_penalty_public_record",
                    "complaint_or_supervision_decision",
                ],
                "query_keys": ["candidate_company", "project_manager_name", "unified_social_credit_code"],
                "runtime_status": "ENTRY_PORTAL_VERIFIED_LIST_QUERY_ADAPTER_PENDING",
                "next_adapter": "guangdong_housing_penalty_list_query_adapter",
            },
            {
                "entry_id": "GD-CREDIT-GD",
                "source_profile_id": "GUANGDONG-CREDIT-GD-HOME",
                "source_name": "信用广东",
                "source_url": "https://credit.gd.gov.cn/",
                "source_family": "local_credit_public_record",
                "target_source_types": ["credit_penalty_blacklist"],
                "query_keys": ["candidate_company", "unified_social_credit_code"],
                "runtime_status": "ENTRY_PORTAL_PENDING_PROJECT_SUBJECT_QUERY",
                "next_adapter": "guangdong_credit_subject_query_adapter",
            },
        ],
        "no_no-risk_inference_without_sources": True,
        "next_required_runtime_adapters": [
            "guangdong_contract_performance_query_adapter",
            "guangdong_investment_project_progress_query_adapter",
            "guangdong_housing_penalty_list_query_adapter",
            "guangdong_credit_subject_query_adapter",
        ],
    }


def _build_generic_source_plan(
    candidate: Mapping[str, Any],
    *,
    covered_source_types: list[str] | tuple[str, ...] | set[str] | None,
) -> dict[str, Any]:
    covered = _normalized_source_types(covered_source_types)
    required = set(GUANGDONG_HARD_DEFECT_REQUIRED_SOURCE_TYPES)
    missing = sorted(required - covered)
    region_code = str(candidate.get("region_code") or "CN-NATIONAL").upper()
    return {
        "source_plan_id": build_id("ST4REGSRC", candidate.get("project_id") or "GENERIC", region_code),
        "region_code": region_code,
        "region_name": str(candidate.get("region_name") or region_code),
        "plan_state": "GENERIC_SOURCE_BLUEPRINT_PENDING_REGION_ADAPTER",
        "coverage_state": "PARTIAL" if missing else "COMPLETE",
        "query_context": _query_context(candidate),
        "required_source_types": sorted(required),
        "covered_source_types": sorted(covered),
        "missing_source_types": missing,
        "source_entries": [],
        "no_no-risk_inference_without_sources": True,
        "next_required_runtime_adapters": ["region_specific_hard_defect_source_adapter"],
    }


def _normalized_source_types(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    return {str(value) for value in (values or []) if str(value).strip()}


__all__ = [
    "GUANGDONG_HARD_DEFECT_REQUIRED_SOURCE_TYPES",
    "build_regional_hard_defect_source_plan",
]
