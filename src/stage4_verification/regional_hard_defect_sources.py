from __future__ import annotations

from typing import Any, Mapping

from shared.utils import build_id
from stage4_verification.verification_scope_policy import (
    build_stage45_verification_scope_policy,
    scope_rule_by_key,
)


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

MAJOR_TARGET_REGION_REQUIRED_SOURCE_TYPES = (
    "construction_permit",
    "contract_public_info",
    "completion_filing",
    "project_manager_change_notice",
    "personnel_public_record",
    "performance_public_record",
)

MAJOR_TARGET_REGION_SOURCE_CATALOG = (
    {
        "region_code": "CN-ZJ",
        "region_name": "浙江",
        "entry_id": "ZJ-JZSC-PUBLIC-SERVICE",
        "source_profile_id": "ZHEJIANG-JZSC-PUBLIC-SERVICE",
        "source_name": "浙江省建筑市场监管公共服务系统",
        "source_url": "https://jzsc.jst.zj.gov.cn/webserver/app/index.html",
        "official_reference_url": "https://jst.zj.gov.cn/art/2021/9/14/art_1229159345_58927639.html",
        "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
        "next_adapter": "zhejiang_construction_market_public_service_query_adapter",
    },
    {
        "region_code": "CN-SC",
        "region_name": "四川",
        "entry_id": "SC-JZSC-PUBLIC-SERVICE",
        "source_profile_id": "SICHUAN-JZSC-PUBLIC-SERVICE",
        "source_name": "四川省建筑市场监管公共服务平台",
        "source_url": "https://jst.sc.gov.cn/scjst/businesSys/sys_list.shtml",
        "official_reference_url": "https://jst.sc.gov.cn/scjst/c101428/2020/12/16/524a5e292df5461996313971cdf85f3f.shtml",
        "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
        "next_adapter": "sichuan_construction_market_public_service_query_adapter",
    },
    {
        "region_code": "CN-JS",
        "region_name": "江苏",
        "entry_id": "JS-JZSC-INTEGRATED-PLATFORM",
        "source_profile_id": "JIANGSU-JZSC-INTEGRATED-PLATFORM",
        "source_name": "江苏省建筑市场监管与诚信管理一体化平台",
        "source_url": "https://jsszfhcxjst.jiangsu.gov.cn/",
        "official_reference_url": "https://jsszfhcxjst.jiangsu.gov.cn/art/2025/2/20/art_49384_11496246.html",
        "runtime_status": "OFFICIAL_PLATFORM_REFERENCED_ADAPTER_PENDING",
        "next_adapter": "jiangsu_construction_market_integrated_platform_query_adapter",
    },
    {
        "region_code": "CN-HB",
        "region_name": "湖北",
        "entry_id": "HB-JZSC-INTEGRITY-PLATFORM",
        "source_profile_id": "HUBEI-JZSC-INTEGRITY-PLATFORM",
        "source_name": "湖北省建筑市场监督与诚信一体化平台",
        "source_url": "https://hbjz.hbcic.net.cn/",
        "official_reference_url": "https://hbjz.hbcic.net.cn/",
        "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
        "next_adapter": "hubei_construction_market_integrity_platform_query_adapter",
    },
    {
        "region_code": "CN-SD",
        "region_name": "山东",
        "entry_id": "SD-JZSC-CREDIT-SUPERVISION-PLATFORM",
        "source_profile_id": "SHANDONG-JZSC-CREDIT-SUPERVISION-PLATFORM",
        "source_name": "山东省住房城乡建设服务监管与信用信息综合平台 / 建筑市场监管与诚信信息一体化平台",
        "source_url": "https://zjt.shandong.gov.cn/",
        "official_reference_url": "https://zwfwzx.jining.gov.cn/art/2022/5/26/art_32745_2707826.html",
        "runtime_status": "SOURCE_ANALYSIS_REQUIRED_ADAPTER_PENDING",
        "next_adapter": "shandong_construction_market_credit_supervision_query_adapter",
    },
    {
        "region_code": "CN-HN",
        "region_name": "湖南",
        "entry_id": "HN-JZSC-PUBLIC-SERVICE",
        "source_profile_id": "HUNAN-JZSC-PUBLIC-SERVICE",
        "source_name": "湖南省建筑市场监管公共服务平台 / 智慧住建云",
        "source_url": "https://www.hunanjs.gov.cn/",
        "official_reference_url": "https://zjt.hunan.gov.cn/xxgk/xinxigongkaimulu/tzgg/tzgg2jzgl/201906/t20190614_5357245.html",
        "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
        "next_adapter": "hunan_construction_market_public_service_query_adapter",
    },
    {
        "region_code": "CN-HA",
        "region_name": "河南",
        "entry_id": "HA-JZSC-PUBLIC-SERVICE",
        "source_profile_id": "HENAN-JZSC-PUBLIC-SERVICE",
        "source_name": "河南省建筑市场监管公共服务平台",
        "source_url": "https://hngcjs.hnjs.henan.gov.cn/site/",
        "official_reference_url": "https://hngcjs.hnjs.henan.gov.cn/site/",
        "runtime_status": "ENTRY_PORTAL_VERIFIED_ADAPTER_PENDING",
        "next_adapter": "henan_construction_market_public_service_query_adapter",
    },
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
    scope_policy = build_stage45_verification_scope_policy({**dict(candidate), "region_code": "CN-GD"})
    region_discovery_scope = scope_rule_by_key(
        scope_policy,
        "company_manager_project_region_discovery",
    )
    active_conflict_scope = scope_rule_by_key(scope_policy, "project_manager_active_conflict")
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
        "verification_scope_policy": scope_policy,
        "expanded_scope_keys": list(scope_policy.get("expanded_scope_keys", []) or []),
        "fixed_scope_keys": list(scope_policy.get("fixed_scope_keys", []) or []),
        "scope_warnings": [
            "project_manager_active_conflict_requires_national_discovery_then_targeted_regions",
            "current_region_only_cannot_prove_no_active_conflict",
            "all_region_bruteforce_not_required",
            "major_region_source_catalog_is_plan_only_until_adapter_verified",
        ],
        "major_target_region_policy": _major_target_region_policy(),
        "major_target_region_source_entries": _major_target_region_source_entries(),
        "source_entries": [
            {
                "entry_id": "NATIONAL-JZSC-COMPANY-MANAGER-REGION-DISCOVERY",
                "source_profile_id": "JZSC-NATIONAL-COMPANY",
                "source_profile_ids": [
                    "JZSC-NATIONAL-COMPANY",
                    "JZSC-NATIONAL-PERSON",
                    "JZSC-NATIONAL-PROJECT",
                ],
                "source_name": "全国建筑市场监管公共服务平台 / 公司与项目经理出现地区发现",
                "source_url": "https://jzsc.mohurd.gov.cn/data/company",
                "source_family": "national_construction_market_platform",
                "target_source_types": list(region_discovery_scope.get("source_types", []) or []),
                "query_keys": [
                    "candidate_company",
                    "project_manager_name",
                    "project_manager_certificate_no",
                    "project_manager_public_identifier",
                ],
                "scope_mode": region_discovery_scope.get(
                    "scope_mode",
                    "NATIONAL_DISCOVERY_THEN_TARGETED_REGIONAL_VERIFICATION",
                ),
                "query_sequence": list(region_discovery_scope.get("query_sequence", []) or []),
                "discovery_outputs": list(region_discovery_scope.get("discovery_outputs", []) or []),
                "targeted_region_verification_required": True,
                "all_region_bruteforce_required": False,
                "current_region_only_is_insufficient": True,
                "runtime_status": "NATIONAL_DISCOVERY_ADAPTER_REQUIRED",
                "next_adapter": "jzsc_company_manager_project_region_discovery",
            },
            {
                "entry_id": "NATIONAL-JZSC-PM-ACTIVE-CONFLICT",
                "source_profile_id": "JZSC-NATIONAL-PERSON",
                "source_profile_ids": [
                    "JZSC-NATIONAL-COMPANY",
                    "JZSC-NATIONAL-PERSON",
                    "JZSC-NATIONAL-PROJECT",
                ],
                "source_name": "全国建筑市场监管公共服务平台 / 项目经理全国在建冲突",
                "source_url": "https://jzsc.mohurd.gov.cn/data/person",
                "source_family": "national_construction_market_platform",
                "target_source_types": list(active_conflict_scope.get("source_types", []) or []),
                "query_keys": [
                    "candidate_company",
                    "project_manager_name",
                    "project_manager_certificate_no",
                    "project_manager_public_identifier",
                    "discovered_region_codes",
                    "company_project_history_refs",
                ],
                "scope_mode": active_conflict_scope.get(
                    "scope_mode",
                    "NATIONAL_DISCOVERY_THEN_TARGETED_REGIONAL_VERIFICATION",
                ),
                "cross_region_required": True,
                "current_region_only_is_insufficient": True,
                "targeted_region_verification_required": True,
                "all_region_bruteforce_required": False,
                "runtime_status": "NATIONAL_DISCOVERY_PARTIAL_TARGETED_REGION_ADAPTER_PENDING",
                "next_adapter": "jzsc_company_first_project_manager_active_conflict_query",
            },
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
                "scope_mode": "CURRENT_PROJECT_JURISDICTION_ONLY_FOR_CURRENT_PROJECT_RECORDS",
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
                "scope_mode": "CURRENT_PROJECT_JURISDICTION_ONLY_FOR_CURRENT_PROJECT_CHANGE",
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
                "scope_mode": "CURRENT_PROJECT_JURISDICTION_ONLY",
                "query_keys": ["project_name", "project_code", "approval_receipt_no"],
                "runtime_status": "PUBLIC_API_ENDPOINT_VERIFIED_PROJECT_QUERY_AVAILABLE",
                "next_adapter": "guangdong_tzxm_project_approval_publicity_api_v1",
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
                "scope_mode": "LOCAL_SUPPLEMENT_TO_NATIONAL_CREDIT_SCOPE",
                "query_keys": ["candidate_company", "project_manager_name", "unified_social_credit_code"],
                "runtime_status": "PUBLIC_LIST_DETAIL_QUERY_ADAPTER_AVAILABLE",
                "next_adapter": "guangdong_zfcxjst_penalty_publicity_page_v1",
            },
            {
                "entry_id": "GD-CREDIT-GD",
                "source_profile_id": "GUANGDONG-CREDIT-GD-HOME",
                "source_name": "信用广东",
                "source_url": "https://credit.gd.gov.cn/",
                "source_family": "local_credit_public_record",
                "target_source_types": [
                    "credit_penalty_blacklist",
                    "administrative_license_public_record",
                    "administrative_penalty_public_record",
                ],
                "scope_mode": "LOCAL_SUPPLEMENT_TO_NATIONAL_CREDIT_SCOPE",
                "query_keys": ["candidate_company", "unified_social_credit_code"],
                "runtime_status": "PUBLIC_CREDIT_LIST_QUERY_ADAPTER_AVAILABLE_WITH_WAF_GUARD",
                "next_adapter": "guangdong_credit_gd_public_credit_query_v1",
            },
            {
                "entry_id": "GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
                "source_profile_id": "GUANGZHOU-ZFCJ-CREDIT-DOUBLE-PUBLICITY",
                "source_name": "广州市住房和城乡建设局 / 信用信息双公示",
                "source_url": "https://zfcj.gz.gov.cn/zfcj/xyxx/",
                "source_family": "current_city_housing_credit_publicity",
                "target_source_types": [
                    "construction_permit",
                    "contract_public_info",
                    "administrative_license_public_record",
                    "administrative_penalty_public_record",
                    "complaint_or_supervision_decision",
                ],
                "scope_mode": "CURRENT_PROJECT_CITY_SUPPLEMENT_WHEN_CITY_IS_GUANGZHOU",
                "query_keys": ["candidate_company", "project_manager_name", "unified_social_credit_code"],
                "runtime_status": "CITY_PUBLIC_API_QUERY_ADAPTER_AVAILABLE",
                "next_adapter": "guangzhou_zfcj_xyxx_api_query_v1",
            },
            *_major_target_region_source_entries(),
        ],
        "no_no-risk_inference_without_sources": True,
        "next_required_runtime_adapters": [
            "jzsc_company_manager_project_region_discovery",
            "jzsc_company_first_project_manager_active_conflict_query",
            "targeted_regional_project_overlap_verification_adapter",
            "guangdong_contract_performance_query_adapter",
            "national_credit_subject_query_adapter",
            *_major_target_region_next_adapters(),
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
    scope_policy = build_stage45_verification_scope_policy({**dict(candidate), "region_code": region_code})
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
        "verification_scope_policy": scope_policy,
        "expanded_scope_keys": list(scope_policy.get("expanded_scope_keys", []) or []),
        "fixed_scope_keys": list(scope_policy.get("fixed_scope_keys", []) or []),
        "scope_warnings": [
            "project_manager_active_conflict_requires_national_discovery_then_targeted_regions",
            "current_region_only_cannot_prove_no_active_conflict",
            "all_region_bruteforce_not_required",
            "major_region_source_catalog_is_plan_only_until_adapter_verified",
        ],
        "major_target_region_policy": _major_target_region_policy(),
        "major_target_region_source_entries": _major_target_region_source_entries(),
        "source_entries": _major_target_region_source_entries(),
        "no_no-risk_inference_without_sources": True,
        "next_required_runtime_adapters": [
            "jzsc_company_manager_project_region_discovery",
            "targeted_regional_project_overlap_verification_adapter",
            "region_specific_hard_defect_source_adapter",
            *_major_target_region_next_adapters(),
        ],
    }


def _major_target_region_policy() -> dict[str, Any]:
    return {
        "policy_id": "MAJOR-PROVINCE-TARGET-REGION-SOURCE-CATALOG-V1",
        "scope_mode": "NATIONAL_DISCOVERY_THEN_MAJOR_REGION_TARGETED_VERIFICATION",
        "purpose": "项目负责人业绩、在建和履约冲突不限定广东；先由全国平台发现人员和公司出现地区，再优先核验重点省份公开源。",
        "all_region_bruteforce_required": False,
        "target_region_codes": [str(item["region_code"]) for item in MAJOR_TARGET_REGION_SOURCE_CATALOG],
        "activation_conditions": [
            "candidate_company_registered_or_appeared_region_matches_catalog",
            "jzsc_discovered_region_codes_matches_catalog",
            "bid_file_or_candidate_notice_declared_performance_region_matches_catalog",
            "manual_target_region_requested",
        ],
        "default_execution_state": "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED",
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _major_target_region_source_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in MAJOR_TARGET_REGION_SOURCE_CATALOG:
        entries.append(
            {
                "entry_id": item["entry_id"],
                "region_code": item["region_code"],
                "region_name": item["region_name"],
                "source_profile_id": item["source_profile_id"],
                "source_name": item["source_name"],
                "source_url": item["source_url"],
                "official_reference_url": item["official_reference_url"],
                "source_family": "regional_construction_market_public_service",
                "target_source_types": list(MAJOR_TARGET_REGION_REQUIRED_SOURCE_TYPES),
                "scope_mode": "TARGETED_REGION_AFTER_NATIONAL_DISCOVERY_OR_DECLARED_PERFORMANCE",
                "query_keys": [
                    "candidate_company",
                    "project_manager_name",
                    "project_manager_certificate_no",
                    "declared_performance_project_name",
                    "discovered_region_codes",
                ],
                "runtime_status": item["runtime_status"],
                "next_adapter": item["next_adapter"],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    return entries


def _major_target_region_next_adapters() -> list[str]:
    return [str(item["next_adapter"]) for item in MAJOR_TARGET_REGION_SOURCE_CATALOG]


def _normalized_source_types(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    return {str(value) for value in (values or []) if str(value).strip()}


__all__ = [
    "GUANGDONG_HARD_DEFECT_REQUIRED_SOURCE_TYPES",
    "MAJOR_TARGET_REGION_SOURCE_CATALOG",
    "build_regional_hard_defect_source_plan",
]
