from __future__ import annotations

from typing import Any, Mapping

from shared.utils import build_id


NATIONAL_VERIFICATION_PROFILE_IDS = (
    "JZSC-NATIONAL-COMPANY",
    "JZSC-NATIONAL-PERSON",
    "JZSC-NATIONAL-PROJECT",
    "CREDITCHINA-HOME",
    "GSXT-HOME",
)
ACTIVE_CONFLICT_SCOPE_MODE = "NATIONAL_DISCOVERY_THEN_TARGETED_REGIONAL_VERIFICATION"


def build_stage45_verification_scope_policy(candidate: Mapping[str, Any]) -> dict[str, Any]:
    region_code = str(candidate.get("region_code") or candidate.get("current_project_region_code") or "").upper()
    if not region_code:
        region_code = "CN-NATIONAL"
    project_id = str(candidate.get("project_id") or candidate.get("current_project_id") or "GENERIC")
    policy_id = build_id("ST45SCOPE", project_id, region_code)
    return {
        "scope_policy_id": policy_id,
        "policy_version": "stage45-verification-scope-v1",
        "principle": "verification_scope_follows_target_object_not_search_region",
        "current_project_region_code": region_code,
        "current_project_region_is_not_person_conflict_boundary": True,
        "scope_rules": [
            _scope_rule(
                scope_key="current_project_notice_chain",
                scope_mode="CURRENT_PROJECT_JURISDICTION_ONLY",
                source_types=(
                    "public_notice_timeline",
                    "bid_candidate_notice",
                    "award_result_notice",
                ),
                primary_regions=(region_code,),
                rationale="Current notice validity is governed by the project source jurisdiction.",
            ),
            _scope_rule(
                scope_key="current_project_permit_contract_completion",
                scope_mode="CURRENT_PROJECT_JURISDICTION_ONLY",
                source_types=(
                    "construction_permit",
                    "contract_public_info",
                    "completion_filing",
                ),
                primary_regions=(region_code,),
                rationale="The current project's permit, contract filing and completion records belong to the project jurisdiction.",
            ),
            _scope_rule(
                scope_key="project_manager_identity",
                scope_mode="NATIONAL_PLUS_REGISTERED_UNIT_LOCAL_SUPPLEMENT",
                source_types=(
                    "personnel_public_record",
                    "enterprise_public_record",
                    "enterprise_qualification",
                ),
                primary_regions=("CN-NATIONAL",),
                supplementary_regions=(region_code,),
                primary_profiles=NATIONAL_VERIFICATION_PROFILE_IDS[:3],
                cross_region_required=True,
                rationale="Project manager identity must be resolved by person/company identity, not by the current project province.",
            ),
            _scope_rule(
                scope_key="company_manager_project_region_discovery",
                scope_mode=ACTIVE_CONFLICT_SCOPE_MODE,
                source_types=(
                    "bid_candidate_notice",
                    "award_result_notice",
                    "performance_public_record",
                    "construction_permit",
                    "contract_public_info",
                    "completion_filing",
                    "project_manager_change_notice",
                ),
                primary_regions=("CN-NATIONAL",),
                supplementary_regions=(region_code,),
                primary_profiles=NATIONAL_VERIFICATION_PROFILE_IDS[:3],
                cross_region_required=True,
                current_region_only_is_insufficient=True,
                targeted_region_verification_required=True,
                all_region_bruteforce_required=False,
                query_sequence=(
                    "candidate_company_first",
                    "resolved_project_manager_identifier_or_certificate",
                    "disambiguated_project_manager_name_fallback",
                ),
                discovery_outputs=(
                    "appeared_region_codes",
                    "appeared_project_refs",
                    "candidate_conflict_time_windows",
                    "company_project_history_refs",
                ),
                rationale="Discover where the company and resolved project manager actually appeared before deep-checking regional overlap; national scope is an index-and-target strategy, not a brute-force sweep of every province.",
            ),
            _scope_rule(
                scope_key="project_manager_active_conflict",
                scope_mode=ACTIVE_CONFLICT_SCOPE_MODE,
                source_types=(
                    "personnel_public_record",
                    "performance_public_record",
                    "contract_public_info",
                    "completion_filing",
                    "project_manager_change_notice",
                ),
                primary_regions=("CN-NATIONAL",),
                supplementary_regions=(region_code,),
                primary_profiles=NATIONAL_VERIFICATION_PROFILE_IDS[:3],
                cross_region_required=True,
                current_region_only_is_insufficient=True,
                targeted_region_verification_required=True,
                all_region_bruteforce_required=False,
                required_prior_scope_keys=("company_manager_project_region_discovery",),
                rationale="A project manager may have active projects outside the current province; first discover actual company/manager appearance regions, then verify those regional records for overlap.",
            ),
            _scope_rule(
                scope_key="bidder_company_credit_and_penalty",
                scope_mode="NATIONAL_PLUS_LOCAL_SUPPLEMENT",
                source_types=(
                    "credit_penalty_blacklist",
                    "administrative_penalty_public_record",
                    "complaint_or_supervision_decision",
                ),
                primary_regions=("CN-NATIONAL",),
                supplementary_regions=(region_code,),
                primary_profiles=("CREDITCHINA-HOME", "GSXT-HOME"),
                cross_region_required=True,
                rationale="Company credit and penalties may be registered nationally or in other operating regions; local project-region penalty lists are supplementary.",
            ),
            _scope_rule(
                scope_key="current_project_manager_change",
                scope_mode="CURRENT_PROJECT_JURISDICTION_PRIMARY_WITH_NATIONAL_HISTORY_SUPPLEMENT",
                source_types=("project_manager_change_notice",),
                primary_regions=(region_code,),
                supplementary_regions=("CN-NATIONAL",),
                cross_region_required=False,
                rationale="Change notice for the current project is local, while the manager's historical responsibility chain still needs national context.",
            ),
        ],
        "fixed_scope_keys": [
            "current_project_notice_chain",
            "current_project_permit_contract_completion",
            "current_project_manager_change",
        ],
        "expanded_scope_keys": [
            "project_manager_identity",
            "company_manager_project_region_discovery",
            "project_manager_active_conflict",
            "bidder_company_credit_and_penalty",
        ],
        "no_conflict_conclusion_requires": [
            "project_manager_identity_resolved",
            "company_manager_project_region_discovery_completed",
            "discovered_regions_targeted_or_fail_closed",
            "current_project_time_window_resolved",
            "conflicting_project_completion_or_change_status_resolved",
            "all_evidence_refs_replayable",
        ],
    }


def _scope_rule(
    *,
    scope_key: str,
    scope_mode: str,
    source_types: tuple[str, ...],
    primary_regions: tuple[str, ...],
    rationale: str,
    supplementary_regions: tuple[str, ...] = (),
    primary_profiles: tuple[str, ...] = (),
    cross_region_required: bool = False,
    current_region_only_is_insufficient: bool = False,
    targeted_region_verification_required: bool = False,
    all_region_bruteforce_required: bool = False,
    query_sequence: tuple[str, ...] = (),
    discovery_outputs: tuple[str, ...] = (),
    required_prior_scope_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "scope_mode": scope_mode,
        "source_types": list(source_types),
        "primary_regions": list(primary_regions),
        "supplementary_regions": list(supplementary_regions),
        "primary_profile_ids": list(primary_profiles),
        "cross_region_required": cross_region_required,
        "current_region_only_is_insufficient": current_region_only_is_insufficient,
        "targeted_region_verification_required": targeted_region_verification_required,
        "all_region_bruteforce_required": all_region_bruteforce_required,
        "query_sequence": list(query_sequence),
        "discovery_outputs": list(discovery_outputs),
        "required_prior_scope_keys": list(required_prior_scope_keys),
        "rationale": rationale,
    }


def scope_rule_by_key(policy: Mapping[str, Any], scope_key: str) -> dict[str, Any]:
    for rule in list(policy.get("scope_rules", []) or []):
        if isinstance(rule, Mapping) and rule.get("scope_key") == scope_key:
            return dict(rule)
    return {}


__all__ = [
    "ACTIVE_CONFLICT_SCOPE_MODE",
    "NATIONAL_VERIFICATION_PROFILE_IDS",
    "build_stage45_verification_scope_policy",
    "scope_rule_by_key",
]
