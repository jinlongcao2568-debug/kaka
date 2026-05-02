# Stage: stage4_verification
# Readback-only carrier for project-manager active-project conflict screening.

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping

from stage4_verification.verification_scope_policy import (
    build_stage45_verification_scope_policy,
    scope_rule_by_key,
)
from stage4_verification.verification import PUBLIC_VERIFICATION_PROVIDER


OVERLAP_RISK = "OVERLAP_RISK"
NO_PUBLIC_OVERLAP_EVIDENCE = "NO_PUBLIC_OVERLAP_EVIDENCE"
INSUFFICIENT_PUBLIC_EVIDENCE = "INSUFFICIENT_PUBLIC_EVIDENCE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

PUBLIC_VISIBLE_STATES = frozenset(
    {
        "PUBLIC",
        "PUBLIC_VISIBLE",
        "PUBLIC_SOURCE",
        "SANDBOX_LOCAL_MIRROR",
    }
)

COMPLETION_PROVEN_STATES = frozenset(
    {
        "COMPLETED",
        "ACCEPTED",
        "COMPLETION_ACCEPTED",
        "PUBLIC_COMPLETION_ACCEPTED",
        "PUBLIC_ACCEPTANCE_CONFIRMED",
    }
)

ACTIVE_OR_UNPROVEN_COMPLETION_STATES = frozenset(
    {
        "ACTIVE",
        "IN_PROGRESS",
        "NOT_COMPLETED",
        "NOT_ACCEPTED",
        "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
        "PUBLIC_COMPLETION_NOT_FOUND",
    }
)


@dataclass(frozen=True)
class ProjectManagerActiveConflictCarrier:
    active_conflict_run_id: str
    current_project: dict[str, Any]
    candidate_company: dict[str, Any]
    project_manager: dict[str, Any]
    manager_identity_resolution: dict[str, Any]
    manager_identity_public_refs: list[dict[str, Any]]
    registered_unit_verification: dict[str, Any]
    registration_timeline_verification: dict[str, Any]
    possible_conflicting_projects: list[dict[str, Any]]
    conflict_time_window: dict[str, Any]
    current_project_time_window: dict[str, Any]
    overlap_judgement: str
    same_name_disambiguation: dict[str, Any]
    public_evidence_chain: list[dict[str, Any]]
    evidence_strength: dict[str, Any]
    manual_review_recommendation: dict[str, Any]
    objection_value_summary: dict[str, Any]
    verification_scope_policy: dict[str, Any]
    failure_reasons: list[str]
    review_required: bool
    public_only: bool = True
    customer_visible: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["current_project"] = dict(self.current_project)
        payload["candidate_company"] = dict(self.candidate_company)
        payload["project_manager"] = dict(self.project_manager)
        payload["manager_identity_resolution"] = dict(self.manager_identity_resolution)
        payload["manager_identity_public_refs"] = [dict(ref) for ref in self.manager_identity_public_refs]
        payload["registered_unit_verification"] = dict(self.registered_unit_verification)
        payload["registration_timeline_verification"] = dict(
            self.registration_timeline_verification
        )
        payload["possible_conflicting_projects"] = [
            dict(project) for project in self.possible_conflicting_projects
        ]
        payload["conflict_time_window"] = dict(self.conflict_time_window)
        payload["current_project_time_window"] = dict(self.current_project_time_window)
        payload["same_name_disambiguation"] = dict(self.same_name_disambiguation)
        payload["public_evidence_chain"] = [dict(ref) for ref in self.public_evidence_chain]
        payload["evidence_strength"] = dict(self.evidence_strength)
        payload["manual_review_recommendation"] = dict(self.manual_review_recommendation)
        payload["objection_value_summary"] = dict(self.objection_value_summary)
        payload["verification_scope_policy"] = dict(self.verification_scope_policy)
        payload["failure_reasons"] = list(self.failure_reasons)
        return payload


def evaluate_project_manager_active_conflict(
    parsed_context: Mapping[str, Any] | Any,
    *,
    public_verification_carriers: list[Mapping[str, Any]] | None = None,
    possible_conflicting_projects: list[Mapping[str, Any]] | None = None,
) -> ProjectManagerActiveConflictCarrier:
    context = _stage3_context(parsed_context)
    conflicts = [_mapping(project) for project in _as_list(possible_conflicting_projects)]
    carriers = _collect_verification_carriers(public_verification_carriers, conflicts)
    derived_manager_identifier = _matched_personnel_field_value(
        carriers,
        (
            "project_manager_public_identifier_optional",
            "resolved_public_identifier_optional",
            "project_manager_certificate_no_optional",
            "registration_no",
            "person_public_id_optional",
        ),
    )
    derived_registered_unit = _matched_personnel_field_value(
        carriers,
        (
            "project_manager_registered_unit_optional",
            "registered_unit_name_optional",
        ),
    )
    if derived_manager_identifier and not context.get("project_manager_public_identifier_optional"):
        context = dict(context)
        context["project_manager_public_identifier_optional"] = derived_manager_identifier
        context["project_manager_public_identifier_source"] = (
            "matched_enterprise_personnel_public_record"
        )
    if derived_registered_unit and not context.get("project_manager_registered_unit_optional"):
        context = dict(context)
        context["project_manager_registered_unit_optional"] = derived_registered_unit

    current_window = _coerce_time_window(
        context.get("current_project_time_window")
        or _window_from_fields(context, "current_project")
    )
    current_project = {
        "current_project_id": context.get("current_project_id"),
        "current_project_name": context.get("current_project_name"),
    }
    candidate_company = {
        "candidate_company_name": context.get("candidate_company_name"),
    }
    project_manager = {
        "project_manager_name": context.get("project_manager_name"),
        "project_manager_public_identifier_optional": context.get(
            "project_manager_public_identifier_optional"
        ),
        "registered_unit_optional": context.get("project_manager_registered_unit_optional")
        or context.get("candidate_company_name"),
    }
    verification_scope_policy = build_stage45_verification_scope_policy(
        {
            "project_id": current_project.get("current_project_id"),
            "project_name": current_project.get("current_project_name"),
            "candidate_company": candidate_company.get("candidate_company_name"),
            "project_manager_name": project_manager.get("project_manager_name"),
            "region_code": context.get("region_code"),
        }
    )
    active_conflict_scope = scope_rule_by_key(
        verification_scope_policy,
        "project_manager_active_conflict",
    )
    active_conflict_region_discovery = _active_conflict_region_discovery_summary(
        conflicts,
        current_region_code=str(context.get("region_code") or ""),
    )

    public_evidence_chain = _public_evidence_chain(carriers)
    manager_public_refs = [
        _evidence_ref(carrier)
        for carrier in carriers
        if _target_type(carrier) == "personnel_public_record"
    ]
    matched_manager_public_refs = [
        _evidence_ref(carrier)
        for carrier in carriers
        if _target_type(carrier) == "personnel_public_record"
        and _carrier_match_ready(carrier)
    ]
    registered_unit_verification = _verification_summary(
        _first_carrier(
            carriers,
            target_types=("enterprise_public_record", "enterprise_qualification"),
            roles=("registered_unit_verification", "candidate_registered_unit"),
        )
    )
    manager_identity_resolution = _manager_identity_resolution(
        context=context,
        carriers=carriers,
        manager_public_refs=manager_public_refs,
        matched_manager_public_refs=matched_manager_public_refs,
        registered_unit_verification=registered_unit_verification,
    )
    registration_timeline_verification = _registration_timeline_verification(
        context=context,
        carriers=carriers,
        current_window=current_window,
    )

    failure_reasons: list[str] = []
    if _live_provider_requested(parsed_context, carriers, conflicts):
        failure_reasons.append("provider_reserved_not_live")
    if not _is_complete_time_window(current_window):
        failure_reasons.append("current_project_time_window_missing")
    if not matched_manager_public_refs:
        failure_reasons.append(
            "manager_personnel_public_record_unmatched_or_review_required"
            if manager_public_refs
            else "manager_personnel_public_record_verification_missing"
        )
    if registered_unit_verification.get("verification_result") != "MATCHED":
        failure_reasons.append("registered_unit_verification_missing_or_unmatched")
    if manager_identity_resolution.get("resolution_state") != "MATCHED":
        failure_reasons.extend(
            _as_str_list(manager_identity_resolution.get("failure_reasons"))
        )
    if registration_timeline_verification.get("verification_result") != "PASS":
        failure_reasons.extend(
            _as_str_list(registration_timeline_verification.get("failure_reasons"))
        )
    for carrier in carriers:
        if not _carrier_is_public(carrier):
            failure_reasons.append("visibility_or_non_replayable_verification_ref")
            break

    project_summaries: list[dict[str, Any]] = []
    disambiguations: list[dict[str, Any]] = []
    saw_overlap_risk = False
    saw_ambiguous_overlap = False
    saw_missing_time = False
    saw_missing_completion = False

    for project in conflicts:
        summary = _conflicting_project_summary(
            project,
            current_window=current_window,
            current_context=context,
            all_carriers=carriers,
        )
        project_summaries.append(summary)
        disambiguations.append(dict(summary["same_name_disambiguation"]))
        failure_reasons.extend(_as_str_list(summary.get("failure_reasons")))
        if summary["time_window_missing"]:
            saw_missing_time = True
        if summary["completion_acceptance_missing"]:
            saw_missing_completion = True
        if (
            summary["overlap_with_current"]
            and summary["identity_sufficient_for_risk"]
            and summary["public_evidence_refs"]
        ):
            saw_overlap_risk = True
        if summary["overlap_with_current"] and (
            not summary["identity_sufficient_for_risk"]
            or not summary["public_evidence_refs"]
        ):
            saw_ambiguous_overlap = True

    if not conflicts:
        failure_reasons.append("possible_conflicting_project_public_record_missing")
        failure_reasons.append("company_manager_project_region_discovery_missing")
    if saw_missing_time:
        failure_reasons.append("conflicting_project_time_window_missing")
    if saw_missing_completion:
        failure_reasons.append("completion_acceptance_status_missing")

    failure_reasons = _unique(failure_reasons)
    overlap_judgement = _overlap_judgement(
        failure_reasons=failure_reasons,
        saw_overlap_risk=saw_overlap_risk,
        saw_ambiguous_overlap=saw_ambiguous_overlap,
        saw_missing_time=saw_missing_time,
        has_conflicts=bool(conflicts),
    )
    same_name_disambiguation = _aggregate_disambiguation(disambiguations)
    conflict_time_window = _aggregate_conflict_time_window(project_summaries)
    review_required = (
        bool(failure_reasons)
        or overlap_judgement in {OVERLAP_RISK, INSUFFICIENT_PUBLIC_EVIDENCE, REVIEW_REQUIRED}
        or same_name_disambiguation.get("public_identifier_missing") is True
    )

    evidence_strength = _evidence_strength(public_evidence_chain, failure_reasons, overlap_judgement)
    manual_review_recommendation = {
        "review_required": review_required,
        "review_lane": "PROJECT_MANAGER_ACTIVE_CONFLICT",
        "reasons": list(failure_reasons),
        "recommended_next_step": (
            "human_review_public_records_before_any_external_use"
            if review_required
            else "no_manual_review_required_for_readback"
        ),
    }
    objection_value_summary = _objection_value_summary(
        overlap_judgement=overlap_judgement,
        evidence_strength=evidence_strength,
        review_required=review_required,
    )
    return ProjectManagerActiveConflictCarrier(
        active_conflict_run_id=_stable_id(
            "ST4AC",
            current_project.get("current_project_id"),
            current_project.get("current_project_name"),
            candidate_company.get("candidate_company_name"),
            project_manager.get("project_manager_name"),
            [ref.get("verification_run_id") for ref in public_evidence_chain],
        ),
        current_project=current_project,
        candidate_company=candidate_company,
        project_manager=project_manager,
        manager_identity_resolution=manager_identity_resolution,
        manager_identity_public_refs=manager_public_refs,
        registered_unit_verification=registered_unit_verification,
        registration_timeline_verification=registration_timeline_verification,
        possible_conflicting_projects=project_summaries,
        conflict_time_window=conflict_time_window,
        current_project_time_window=current_window,
        overlap_judgement=overlap_judgement,
        same_name_disambiguation=same_name_disambiguation,
        public_evidence_chain=public_evidence_chain,
        evidence_strength=evidence_strength,
        manual_review_recommendation=manual_review_recommendation,
        objection_value_summary=objection_value_summary,
        verification_scope_policy={
            **verification_scope_policy,
            "active_conflict_scope_mode": active_conflict_scope.get(
                "scope_mode",
                "NATIONAL_DISCOVERY_THEN_TARGETED_REGIONAL_VERIFICATION",
            ),
            "current_region_only_is_insufficient": bool(
                active_conflict_scope.get("current_region_only_is_insufficient", True)
            ),
            "targeted_region_verification_required": bool(
                active_conflict_scope.get("targeted_region_verification_required", True)
            ),
            "all_region_bruteforce_required": bool(
                active_conflict_scope.get("all_region_bruteforce_required", False)
            ),
            "active_conflict_region_discovery": active_conflict_region_discovery,
        },
        failure_reasons=failure_reasons,
        review_required=review_required,
    )


def build_project_manager_active_conflict_readback(carrier: Mapping[str, Any]) -> dict[str, Any]:
    required_fields = (
        "active_conflict_run_id",
        "current_project",
        "candidate_company",
        "project_manager",
        "manager_identity_resolution",
        "possible_conflicting_projects",
        "current_project_time_window",
        "overlap_judgement",
        "same_name_disambiguation",
        "public_evidence_chain",
        "evidence_strength",
    )
    missing = [field_name for field_name in required_fields if carrier.get(field_name) in (None, "", [], {})]
    evidence_chain = [_mapping(ref) for ref in _as_list(carrier.get("public_evidence_chain"))]
    public_refs = all(
        ref.get("public_visibility_state") in PUBLIC_VISIBLE_STATES
        for ref in evidence_chain
    )
    replayable = (
        not missing
        and public_refs
        and bool(carrier.get("public_only", True))
        and not bool(carrier.get("customer_visible", False))
        and bool(carrier.get("no_legal_conclusion", True))
    )
    return {
        "readback_state": (
            "READBACK_READY" if replayable else "FAIL_CLOSED_INCOMPLETE_OR_NON_PUBLIC"
        ),
        "replayable": replayable,
        "fail_closed": not replayable,
        "no_broad_fallback": True,
        "public_only": bool(carrier.get("public_only", True)),
        "customer_visible": False,
        "no_legal_conclusion": True,
        "missing_required_fields": missing,
        "active_conflict_run_id": carrier.get("active_conflict_run_id"),
        "overlap_judgement": carrier.get("overlap_judgement"),
        "review_required": bool(carrier.get("review_required")),
        "manager_identity_resolution": dict(
            _mapping(carrier.get("manager_identity_resolution"))
        ),
        "registration_timeline_verification": dict(
            _mapping(carrier.get("registration_timeline_verification"))
        ),
        "verification_scope_policy": dict(
            _mapping(carrier.get("verification_scope_policy"))
        ),
        "active_conflict_scope_mode": _mapping(
            carrier.get("verification_scope_policy")
        ).get("active_conflict_scope_mode"),
        "current_region_only_is_insufficient": bool(
            _mapping(carrier.get("verification_scope_policy")).get(
                "current_region_only_is_insufficient",
                True,
            )
        ),
        "targeted_region_verification_required": bool(
            _mapping(carrier.get("verification_scope_policy")).get(
                "targeted_region_verification_required",
                True,
            )
        ),
        "all_region_bruteforce_required": bool(
            _mapping(carrier.get("verification_scope_policy")).get(
                "all_region_bruteforce_required",
                False,
            )
        ),
        "active_conflict_region_discovery": dict(
            _mapping(carrier.get("verification_scope_policy")).get(
                "active_conflict_region_discovery",
                {},
            )
        ),
        "project_timeline_evidence_refs": _project_timeline_evidence_refs(evidence_chain),
        "risk_signal_evidence_refs": _risk_signal_evidence_refs(evidence_chain),
        "failure_reasons": list(_as_str_list(carrier.get("failure_reasons"))),
    }


def _stage3_context(parsed_context: Mapping[str, Any] | Any) -> dict[str, Any]:
    root = _mapping(parsed_context)
    inputs = _mapping(getattr(parsed_context, "inputs", None) or root.get("inputs"))
    handoff = _mapping(getattr(parsed_context, "handoff", None) or root.get("handoff"))
    records = _mapping(getattr(parsed_context, "records", None) or root.get("records"))
    project_base = _record_mapping(records.get("project_base") or root.get("project_base"))
    bidder_candidate = _record_mapping(records.get("bidder_candidate") or root.get("bidder_candidate"))
    project_manager = _record_mapping(records.get("project_manager") or root.get("project_manager"))
    parsed_fields = _parsed_field_values(
        root.get("parsed_fields")
        or inputs.get("parsed_fields")
        or _mapping(root.get("stage3_parser_carrier")).get("parsed_fields")
    )

    sources = (root, inputs, handoff, project_base, bidder_candidate, project_manager, parsed_fields)

    def first(*names: str) -> Any:
        for name in names:
            for source in sources:
                value = source.get(name)
                if value not in (None, "", []):
                    return value
        return None

    return {
        "current_project_id": first("current_project_id", "project_id"),
        "current_project_name": first("current_project_name", "project_name"),
        "candidate_company_name": first(
            "candidate_company_name",
            "bidder_name",
            "candidate_company",
            "company_name",
        ),
        "region_code": first("region_code", "current_project_region_code", "project_region_code"),
        "project_manager_name": first("project_manager_name", "manager_name"),
        "project_manager_public_identifier_optional": first(
            "project_manager_public_identifier_optional",
            "public_identifier_optional",
            "public_identifier",
            "project_manager_public_identifier",
        ),
        "project_manager_registered_unit_optional": first(
            "project_manager_registered_unit_optional",
            "project_manager_cert_unit",
            "registered_unit_name",
        ),
        "current_project_time_window": first("current_project_time_window", "project_time_window"),
        "current_project_start_at": first(
            "current_project_start_at",
            "current_project_start_date",
            "current_action_start_at_optional",
        ),
        "current_project_end_at": first(
            "current_project_end_at",
            "current_project_end_date",
            "current_action_deadline_at_optional",
        ),
        "project_manager_registration_at": first(
            "project_manager_registration_at",
            "project_manager_registered_at",
            "registration_at",
            "registered_at",
            "certificate_registered_at",
        ),
        "project_manager_registration_changed_at": first(
            "project_manager_registration_changed_at",
            "project_manager_unit_changed_at",
            "registration_changed_at",
            "unit_changed_at",
        ),
        "project_manager_certificate_valid_from": first(
            "project_manager_certificate_valid_from",
            "certificate_valid_from",
            "valid_from",
        ),
        "project_manager_certificate_valid_until": first(
            "project_manager_certificate_valid_until",
            "certificate_valid_until",
            "valid_until",
            "certificate_end_at",
        ),
    }


def _manager_identity_resolution(
    *,
    context: Mapping[str, Any],
    carriers: list[dict[str, Any]],
    manager_public_refs: list[dict[str, Any]],
    matched_manager_public_refs: list[dict[str, Any]],
    registered_unit_verification: Mapping[str, Any],
) -> dict[str, Any]:
    enterprise_carrier = _first_carrier(
        carriers,
        target_types=("enterprise_public_record", "enterprise_qualification"),
        roles=("registered_unit_verification", "candidate_registered_unit"),
    )
    personnel_carrier = _first_carrier(
        carriers,
        target_types=("personnel_public_record",),
        roles=("manager_identity_verification", "enterprise_personnel_resolution"),
    )
    enterprise_verified = registered_unit_verification.get("verification_result") == "MATCHED"
    personnel_verified = bool(matched_manager_public_refs)
    failure_reasons: list[str] = []
    if not enterprise_verified:
        failure_reasons.append("enterprise_first_record_missing_or_unmatched")
    if not personnel_verified:
        failure_reasons.append(
            "enterprise_personnel_record_unmatched_or_review_required"
            if manager_public_refs
            else "enterprise_personnel_record_missing"
        )

    route_steps = [
        "candidate_enterprise_public_record",
        "enterprise_personnel_list_scan",
        "personnel_detail_identity_match",
        "registration_timeline_readback",
    ]
    return {
        "resolution_route": "ENTERPRISE_FIRST_PERSONNEL_DETAIL",
        "route_steps": route_steps,
        "enterprise_first_required": True,
        "broad_name_search_allowed_as_final_proof": False,
        "same_name_only_accepted": False,
        "candidate_company_name": context.get("candidate_company_name"),
        "project_manager_name": context.get("project_manager_name"),
        "enterprise_record_verified": enterprise_verified,
        "personnel_record_verified": personnel_verified,
        "enterprise_verification_run_id": (
            enterprise_carrier.get("verification_run_id") if enterprise_carrier else None
        ),
        "personnel_verification_run_id": (
            personnel_carrier.get("verification_run_id") if personnel_carrier else None
        ),
        "personnel_verification_result": (
            personnel_carrier.get("verification_result") if personnel_carrier else None
        ),
        "personnel_review_required": (
            bool(personnel_carrier.get("review_required")) if personnel_carrier else True
        ),
        "resolved_public_identifier_optional": context.get(
            "project_manager_public_identifier_optional"
        ),
        "resolved_public_identifier_source": context.get(
            "project_manager_public_identifier_source"
        ),
        "resolution_state": "MATCHED" if enterprise_verified and personnel_verified else "REVIEW",
        "failure_reasons": failure_reasons,
        "review_required": bool(failure_reasons),
    }


def _registration_timeline_verification(
    *,
    context: Mapping[str, Any],
    carriers: list[dict[str, Any]],
    current_window: Mapping[str, Any],
) -> dict[str, Any]:
    registration_at = _first_non_empty(
        context.get("project_manager_registration_at"),
        _carrier_field_value(
            carriers,
            (
                "project_manager_registration_at",
                "project_manager_registered_at",
                "registration_at",
                "registered_at",
                "certificate_registered_at",
            ),
        ),
    )
    registration_changed_at = _first_non_empty(
        context.get("project_manager_registration_changed_at"),
        _carrier_field_value(
            carriers,
            (
                "project_manager_registration_changed_at",
                "project_manager_unit_changed_at",
                "registration_changed_at",
                "unit_changed_at",
            ),
        ),
    )
    valid_from = _first_non_empty(
        context.get("project_manager_certificate_valid_from"),
        _carrier_field_value(
            carriers,
            (
                "project_manager_certificate_valid_from",
                "certificate_valid_from",
                "valid_from",
            ),
        ),
    )
    valid_until = _first_non_empty(
        context.get("project_manager_certificate_valid_until"),
        _carrier_field_value(
            carriers,
            (
                "project_manager_certificate_valid_until",
                "certificate_valid_until",
                "valid_until",
                "certificate_end_at",
            ),
        ),
    )
    current_start = _parse_date(current_window.get("start_at"))
    current_end = _parse_date(current_window.get("end_at"))
    registration_date = _parse_date(registration_at)
    changed_date = _parse_date(registration_changed_at)
    valid_from_date = _parse_date(valid_from)
    valid_until_date = _parse_date(valid_until)

    failure_reasons: list[str] = []
    if not registration_date:
        failure_reasons.append("project_manager_registration_timeline_missing")
    if current_start and registration_date and registration_date > current_start:
        failure_reasons.append("project_manager_registration_after_current_project_start")
    if current_start and changed_date and changed_date > current_start:
        failure_reasons.append("project_manager_registered_unit_changed_after_current_project_start")
    if current_start and valid_from_date and valid_from_date > current_start:
        failure_reasons.append("project_manager_certificate_valid_after_current_project_start")
    if current_end and valid_until_date and valid_until_date < current_end:
        failure_reasons.append("project_manager_certificate_expires_before_current_project_end")

    return {
        "verification_scope": "PROJECT_MANAGER_REGISTRATION_TIMELINE",
        "registration_at": _date_text(registration_at),
        "registration_changed_at": _date_text(registration_changed_at),
        "certificate_valid_from": _date_text(valid_from),
        "certificate_valid_until": _date_text(valid_until),
        "current_project_start_at": _date_text(current_window.get("start_at")),
        "current_project_end_at": _date_text(current_window.get("end_at")),
        "verification_result": "PASS" if not failure_reasons else "REVIEW",
        "failure_reasons": failure_reasons,
        "review_required": bool(failure_reasons),
        "no_legal_conclusion": True,
    }


def _conflicting_project_summary(
    project: Mapping[str, Any],
    *,
    current_window: Mapping[str, Any],
    current_context: Mapping[str, Any],
    all_carriers: list[dict[str, Any]],
) -> dict[str, Any]:
    project_id = _first_non_empty(project.get("project_id"), project.get("conflicting_project_id"))
    project_name = _first_non_empty(project.get("project_name"), project.get("conflicting_project_name"))
    registered_unit_name = _first_non_empty(
        project.get("registered_unit_name"),
        project.get("contractor_name"),
        project.get("candidate_company_name"),
    )
    manager_name = _first_non_empty(project.get("project_manager_name"), project.get("manager_name"))
    manager_identifier = _first_non_empty(
        project.get("project_manager_public_identifier_optional"),
        project.get("manager_public_identifier_optional"),
        project.get("public_identifier_optional"),
    )
    time_window = _coerce_time_window(
        project.get("contract_time_window")
        or project.get("construction_time_window")
        or project.get("time_window")
        or _window_from_fields(project, "conflict_project")
    )
    completion_status = _normalize_status(
        _first_non_empty(
            project.get("completion_acceptance_status"),
            project.get("completion_status"),
            project.get("acceptance_status"),
        )
    )
    overlap = _windows_overlap(current_window, time_window)
    same_name_disambiguation = _same_name_disambiguation(
        current_context=current_context,
        conflict_manager_name=manager_name,
        conflict_manager_identifier=manager_identifier,
        conflict_registered_unit=registered_unit_name,
        manager_verified=bool(
            _first_matched_carrier(all_carriers, target_types=("personnel_public_record",))
        ),
    )
    identity_sufficient = bool(
        same_name_disambiguation["public_identifier_match"]
        or (
            same_name_disambiguation["registered_unit_match"]
            and not same_name_disambiguation["same_name_only"]
        )
    )
    project_carriers = _collect_project_carriers(project)
    matched_project_carriers = [
        carrier for carrier in project_carriers if _carrier_match_ready(carrier)
    ]
    evidence_refs = _public_evidence_chain(matched_project_carriers)
    completion_missing = completion_status in (None, "")
    time_missing = not _is_complete_time_window(time_window)
    failure_reasons: list[str] = []
    if time_missing:
        failure_reasons.append("conflicting_project_time_window_missing")
    if completion_missing:
        failure_reasons.append("completion_acceptance_status_missing")
    if overlap and not identity_sufficient:
        failure_reasons.append("overlap_but_project_manager_identity_ambiguous")
    if not evidence_refs:
        failure_reasons.append(
            "conflicting_project_public_record_unmatched_or_review_required"
            if project_carriers
            else "conflicting_project_public_record_verification_missing"
        )

    return {
        "project_id": project_id,
        "project_name": project_name,
        "region_code": _first_non_empty(
            project.get("region_code"),
            project.get("project_region_code"),
            project.get("source_region_code"),
            project.get("province_code"),
        ),
        "registered_unit_name": registered_unit_name,
        "project_manager_name": manager_name,
        "project_manager_public_identifier_optional": manager_identifier,
        "time_window": time_window,
        "completion_acceptance_status": completion_status,
        "completion_acceptance_proven": completion_status in COMPLETION_PROVEN_STATES,
        "completion_acceptance_missing": completion_missing,
        "active_or_completion_unproven": (
            completion_missing or completion_status in ACTIVE_OR_UNPROVEN_COMPLETION_STATES
        ),
        "overlap_with_current": overlap,
        "time_window_missing": time_missing,
        "same_name_disambiguation": same_name_disambiguation,
        "identity_sufficient_for_risk": identity_sufficient,
        "public_evidence_refs": evidence_refs,
        "review_required": bool(failure_reasons) or overlap,
        "failure_reasons": failure_reasons,
    }


def _same_name_disambiguation(
    *,
    current_context: Mapping[str, Any],
    conflict_manager_name: str,
    conflict_manager_identifier: str,
    conflict_registered_unit: str,
    manager_verified: bool,
) -> dict[str, Any]:
    current_name = _normalize_text(current_context.get("project_manager_name"))
    conflict_name = _normalize_text(conflict_manager_name)
    current_identifier = _normalize_text(
        current_context.get("project_manager_public_identifier_optional")
    )
    current_unit = _normalize_text(
        current_context.get("project_manager_registered_unit_optional")
        or current_context.get("candidate_company_name")
    )
    conflict_unit = _normalize_text(conflict_registered_unit)
    same_name = bool(current_name and current_name == conflict_name)
    public_identifier_missing = not bool(current_identifier and conflict_manager_identifier)
    public_identifier_match = bool(
        current_identifier
        and conflict_manager_identifier
        and current_identifier == _normalize_text(conflict_manager_identifier)
    )
    registered_unit_match = bool(current_unit and conflict_unit and current_unit == conflict_unit)
    same_name_only = bool(same_name and not registered_unit_match and not public_identifier_match)

    reasons: list[str] = []
    if not same_name:
        reasons.append("manager_name_not_matched")
    if public_identifier_missing:
        reasons.append("public_identifier_missing")
    elif not public_identifier_match:
        reasons.append("public_identifier_mismatch")
    if not registered_unit_match:
        reasons.append("registered_unit_mismatch")
    if same_name_only:
        reasons.append("same_name_only_not_identity_conclusion")
    if not manager_verified:
        reasons.append("manager_public_record_verification_missing")

    if public_identifier_match and registered_unit_match and manager_verified:
        confidence = 0.95
    elif registered_unit_match and same_name and manager_verified:
        confidence = 0.72
    elif same_name:
        confidence = 0.35
    else:
        confidence = 0.15

    return {
        "same_name_only": same_name_only,
        "registered_unit_match": registered_unit_match,
        "public_identifier_match": public_identifier_match,
        "public_identifier_missing": public_identifier_missing,
        "ambiguity_reason": ";".join(_unique(reasons)) if reasons else "public_identity_refs_aligned",
        "confidence": confidence,
    }


def _aggregate_disambiguation(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "same_name_only": False,
            "registered_unit_match": False,
            "public_identifier_match": False,
            "public_identifier_missing": True,
            "ambiguity_reason": "no_conflicting_project_disambiguation_available",
            "confidence": 0.0,
            "per_project": [],
        }
    best = max(items, key=lambda item: float(item.get("confidence", 0.0)))
    return {
        "same_name_only": any(bool(item.get("same_name_only")) for item in items),
        "registered_unit_match": any(bool(item.get("registered_unit_match")) for item in items),
        "public_identifier_match": any(bool(item.get("public_identifier_match")) for item in items),
        "public_identifier_missing": any(bool(item.get("public_identifier_missing")) for item in items),
        "ambiguity_reason": best.get("ambiguity_reason"),
        "confidence": best.get("confidence", 0.0),
        "per_project": [dict(item) for item in items],
    }


def _active_conflict_region_discovery_summary(
    conflicts: list[Mapping[str, Any]],
    *,
    current_region_code: str,
) -> dict[str, Any]:
    region_codes = _unique(
        [
            _first_non_empty(
                project.get("region_code"),
                project.get("project_region_code"),
                project.get("source_region_code"),
                project.get("province_code"),
            )
            for project in conflicts
        ]
    )
    project_refs = [
        {
            "project_id": _first_non_empty(project.get("project_id"), project.get("conflicting_project_id")),
            "project_name": _first_non_empty(project.get("project_name"), project.get("conflicting_project_name")),
            "region_code": _first_non_empty(
                project.get("region_code"),
                project.get("project_region_code"),
                project.get("source_region_code"),
                project.get("province_code"),
            ),
        }
        for project in conflicts
    ]
    return {
        "scope_mode": "NATIONAL_DISCOVERY_THEN_TARGETED_REGIONAL_VERIFICATION",
        "discovery_completed": bool(conflicts),
        "candidate_company_first": True,
        "project_manager_identifier_assisted": True,
        "all_region_bruteforce_required": False,
        "targeted_region_verification_required": True,
        "current_project_region_code": current_region_code,
        "current_region_only_is_insufficient": True,
        "discovered_region_codes": region_codes,
        "discovered_project_count": len(conflicts),
        "discovered_project_refs": project_refs,
        "next_step_if_empty": (
            "run_company_manager_project_region_discovery_before_no_conflict_conclusion"
            if not conflicts
            else ""
        ),
    }


def _overlap_judgement(
    *,
    failure_reasons: list[str],
    saw_overlap_risk: bool,
    saw_ambiguous_overlap: bool,
    saw_missing_time: bool,
    has_conflicts: bool,
) -> str:
    boundary_failures = {
        "provider_reserved_not_live",
        "visibility_or_non_replayable_verification_ref",
        "current_project_time_window_missing",
    }
    if any(reason in boundary_failures for reason in failure_reasons):
        return REVIEW_REQUIRED
    if saw_ambiguous_overlap:
        return REVIEW_REQUIRED
    if saw_overlap_risk:
        return OVERLAP_RISK
    if saw_missing_time or not has_conflicts:
        return INSUFFICIENT_PUBLIC_EVIDENCE
    return NO_PUBLIC_OVERLAP_EVIDENCE


def _evidence_strength(
    evidence_chain: list[dict[str, Any]],
    failure_reasons: list[str],
    overlap_judgement: str,
) -> dict[str, Any]:
    grades = [str(ref.get("evidence_grade") or "") for ref in evidence_chain]
    confidences = [_float(ref.get("confidence"), 0.0) for ref in evidence_chain]
    if not evidence_chain:
        strength = "NO_PUBLIC_EVIDENCE"
    elif failure_reasons:
        strength = "PUBLIC_EVIDENCE_REVIEW_REQUIRED"
    elif overlap_judgement == OVERLAP_RISK:
        strength = "PUBLIC_REPLAYABLE_OVERLAP_SIGNAL"
    else:
        strength = "PUBLIC_REPLAYABLE_NO_OVERLAP_SIGNAL"
    return {
        "strength": strength,
        "evidence_ref_count": len(evidence_chain),
        "minimum_confidence": min(confidences) if confidences else 0.0,
        "evidence_grades": _unique(grades),
        "failure_reasons": list(failure_reasons),
    }


def _objection_value_summary(
    *,
    overlap_judgement: str,
    evidence_strength: Mapping[str, Any],
    review_required: bool,
) -> dict[str, Any]:
    if overlap_judgement == OVERLAP_RISK:
        value_signal = "HIGH_REVIEW_VALUE"
        summary = "public records indicate active-project overlap risk; human review required"
    elif overlap_judgement == REVIEW_REQUIRED:
        value_signal = "REVIEW_VALUE_UNCERTAIN"
        summary = "public records are ambiguous or boundary-limited; fail closed to review"
    elif overlap_judgement == INSUFFICIENT_PUBLIC_EVIDENCE:
        value_signal = "INSUFFICIENT_PUBLIC_EVIDENCE"
        summary = "public evidence is incomplete for active-conflict screening"
    else:
        value_signal = "NO_PUBLIC_OVERLAP_SIGNAL"
        summary = "no public overlap evidence was found in the supplied readback carriers"
    return {
        "value_signal": value_signal,
        "summary": summary,
        "review_required": review_required,
        "evidence_strength": evidence_strength.get("strength"),
        "internal_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def _collect_verification_carriers(
    public_verification_carriers: list[Mapping[str, Any]] | None,
    conflicts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    carriers = [_mapping(carrier) for carrier in _as_list(public_verification_carriers)]
    for project in conflicts:
        carriers.extend(_collect_project_carriers(project))
    return _dedupe_carriers(carriers)


def _collect_project_carriers(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    carriers: list[dict[str, Any]] = []
    for key in (
        "public_verification_carriers",
        "verification_carriers",
        "stage4_verification_carriers",
    ):
        carriers.extend(_mapping(carrier) for carrier in _as_list(project.get(key)))
    for key in (
        "manager_public_record_verification",
        "registered_unit_verification",
        "project_public_record_verification",
        "contract_public_record_verification",
        "permit_public_record_verification",
        "completion_acceptance_public_record_verification",
    ):
        value = project.get(key)
        if isinstance(value, Mapping):
            carriers.append(_mapping(value))
    return _dedupe_carriers(carriers)


def _public_evidence_chain(carriers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for carrier in carriers:
        ref = _evidence_ref(carrier)
        if ref.get("verification_run_id") or ref.get("source_snapshot_id"):
            refs.append(ref)
    return _dedupe_refs(refs)


def _project_timeline_evidence_refs(evidence_chain: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    project_timeline_types = {
        "award_result_notice",
        "bid_candidate_notice",
        "construction_permit",
        "contract_public_info",
        "completion_filing",
        "performance_public_record",
        "project_manager_change_notice",
    }
    return [
        dict(ref)
        for ref in evidence_chain
        if str(ref.get("verification_target_type") or "") in project_timeline_types
    ]


def _risk_signal_evidence_refs(evidence_chain: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    risk_signal_types = {
        "administrative_penalty_public_record",
        "credit_penalty_blacklist",
        "court_execution_public_record",
        "complaint_or_supervision_decision",
    }
    return [
        dict(ref)
        for ref in evidence_chain
        if str(ref.get("verification_target_type") or "") in risk_signal_types
    ]


def _evidence_ref(carrier: Mapping[str, Any]) -> dict[str, Any]:
    source_refs = [_mapping(ref) for ref in _as_list(carrier.get("source_refs"))]
    snapshot_refs = [_mapping(ref) for ref in _as_list(carrier.get("snapshot_refs"))]
    source_ref = source_refs[0] if source_refs else {}
    snapshot_ref = snapshot_refs[0] if snapshot_refs else {}
    return {
        "source_url": _first_non_empty(carrier.get("source_url"), source_ref.get("source_url")),
        "source_snapshot_id": _first_non_empty(
            carrier.get("source_snapshot_id"),
            source_ref.get("source_snapshot_id"),
            snapshot_ref.get("snapshot_id"),
        ),
        "verification_run_id": carrier.get("verification_run_id"),
        "verification_target_type": carrier.get("verification_target_type"),
        "evidence_grade": carrier.get("evidence_grade"),
        "confidence": _float(carrier.get("confidence"), 0.0),
        "public_visibility_state": _first_non_empty(
            carrier.get("public_visibility_state"),
            source_ref.get("public_visibility_state"),
        ),
    }


def _verification_summary(carrier: Mapping[str, Any] | None) -> dict[str, Any]:
    if not carrier:
        return {
            "verification_result": "MISSING",
            "review_required": True,
            "evidence_ref": {},
        }
    return {
        "verification_run_id": carrier.get("verification_run_id"),
        "verification_target_type": carrier.get("verification_target_type"),
        "verification_result": carrier.get("verification_result"),
        "evidence_grade": carrier.get("evidence_grade"),
        "confidence": _float(carrier.get("confidence"), 0.0),
        "review_required": bool(carrier.get("review_required")),
        "evidence_ref": _evidence_ref(carrier),
    }


def _first_carrier(
    carriers: list[dict[str, Any]],
    *,
    target_types: tuple[str, ...],
    roles: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    for carrier in carriers:
        role = str(carrier.get("verification_role") or carrier.get("verification_purpose") or "")
        if role in roles:
            return carrier
    for carrier in carriers:
        if _target_type(carrier) in target_types:
            return carrier
    return None


def _first_matched_carrier(
    carriers: list[dict[str, Any]],
    *,
    target_types: tuple[str, ...],
    roles: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    for carrier in carriers:
        role = str(carrier.get("verification_role") or carrier.get("verification_purpose") or "")
        if role in roles and _carrier_match_ready(carrier):
            return carrier
    for carrier in carriers:
        if _target_type(carrier) in target_types and _carrier_match_ready(carrier):
            return carrier
    return None


def _target_type(carrier: Mapping[str, Any]) -> str:
    return str(carrier.get("verification_target_type") or carrier.get("target_type") or "")


def _carrier_match_ready(carrier: Mapping[str, Any]) -> bool:
    return (
        _carrier_is_public(carrier)
        and carrier.get("verification_result") == "MATCHED"
        and not bool(carrier.get("review_required"))
    )


def _carrier_is_public(carrier: Mapping[str, Any]) -> bool:
    ref = _evidence_ref(carrier)
    return (
        bool(carrier.get("public_only", True))
        and bool(ref.get("source_url"))
        and bool(ref.get("source_snapshot_id"))
        and ref.get("public_visibility_state") in PUBLIC_VISIBLE_STATES
        and carrier.get("verification_provider", PUBLIC_VERIFICATION_PROVIDER) == PUBLIC_VERIFICATION_PROVIDER
    )


def _live_provider_requested(*values: Any) -> bool:
    for value in values:
        if isinstance(value, list):
            if _live_provider_requested(*value):
                return True
            continue
        data = _mapping(value)
        if not data:
            continue
        if data.get("live_provider_requested") or data.get("real_provider_requested"):
            return True
        requested_provider = data.get("requested_provider") or data.get("verification_provider")
        if requested_provider not in (None, "", PUBLIC_VERIFICATION_PROVIDER):
            return True
        nested = [
            data.get("public_verification_carriers"),
            data.get("verification_carriers"),
            data.get("stage4_verification_carriers"),
        ]
        if _live_provider_requested(*nested):
            return True
    return False


def _coerce_time_window(value: Any) -> dict[str, Any]:
    data = _mapping(value)
    if not data and isinstance(value, (list, tuple)) and len(value) >= 2:
        data = {"start_at": value[0], "end_at": value[1]}
    start = _first_non_empty(
        data.get("start_at"),
        data.get("start_date"),
        data.get("contract_start_at"),
        data.get("construction_start_at"),
    )
    end = _first_non_empty(
        data.get("end_at"),
        data.get("end_date"),
        data.get("contract_end_at"),
        data.get("construction_end_at"),
    )
    return {
        "start_at": start,
        "end_at": end,
        "start_date": _date_text(start),
        "end_date": _date_text(end),
        "complete": bool(_parse_date(start) and _parse_date(end)),
    }


def _window_from_fields(data: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    if prefix == "current_project":
        return {
            "start_at": data.get("current_project_start_at") or data.get("current_project_start_date"),
            "end_at": data.get("current_project_end_at") or data.get("current_project_end_date"),
        }
    return {
        "start_at": data.get("conflict_project_start_at") or data.get("contract_start_at"),
        "end_at": data.get("conflict_project_end_at") or data.get("contract_end_at"),
    }


def _is_complete_time_window(window: Mapping[str, Any]) -> bool:
    start = _parse_date(window.get("start_at"))
    end = _parse_date(window.get("end_at"))
    return bool(start and end and start <= end)


def _windows_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_start = _parse_date(left.get("start_at"))
    left_end = _parse_date(left.get("end_at"))
    right_start = _parse_date(right.get("start_at"))
    right_end = _parse_date(right.get("end_at"))
    if not all((left_start, left_end, right_start, right_end)):
        return False
    if left_end < left_start or right_end < right_start:
        return False
    return bool(left_start <= right_end and right_start <= left_end)


def _aggregate_conflict_time_window(projects: list[Mapping[str, Any]]) -> dict[str, Any]:
    windows = [_mapping(project.get("time_window")) for project in projects]
    dates = [
        (_parse_date(window.get("start_at")), _parse_date(window.get("end_at")))
        for window in windows
    ]
    complete_dates = [(start, end) for start, end in dates if start and end]
    if not complete_dates:
        return {"projects": windows, "complete": False}
    return {
        "start_at": min(start for start, _ in complete_dates).isoformat(),
        "end_at": max(end for _, end in complete_dates).isoformat(),
        "projects": windows,
        "complete": True,
    }


def _date_text(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").split("T", 1)[0]
    text = re.sub(r"\s+", "", text)
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parsed_field_values(value: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in _as_list(value):
        data = _mapping(field)
        field_name = data.get("field_name")
        if not field_name:
            continue
        field_value = data.get("field_value_optional")
        if field_value not in (None, ""):
            values[str(field_name)] = field_value
    return values


def _record_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    data = getattr(value, "data", None)
    return dict(data) if isinstance(data, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    data = getattr(value, "data", None)
    return dict(data) if isinstance(data, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_str_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item not in (None, "")]


def _carrier_field_value(carriers: list[dict[str, Any]], field_names: tuple[str, ...]) -> str:
    for carrier in carriers:
        for field_name in field_names:
            value = carrier.get(field_name)
            if value not in (None, ""):
                return str(value)
        for field_ref in _as_list(carrier.get("parsed_field_refs")):
            data = _mapping(field_ref)
            if data.get("field_name") in field_names and data.get("field_value_optional") not in (None, ""):
                return str(data.get("field_value_optional"))
        for field_ref in _as_list(carrier.get("parsed_fields")):
            data = _mapping(field_ref)
            if data.get("field_name") in field_names and data.get("field_value_optional") not in (None, ""):
                return str(data.get("field_value_optional"))
    return ""


def _matched_personnel_field_value(carriers: list[dict[str, Any]], field_names: tuple[str, ...]) -> str:
    for carrier in carriers:
        if _target_type(carrier) != "personnel_public_record" or not _carrier_match_ready(carrier):
            continue
        for field_name in field_names:
            value = carrier.get(field_name)
            if value not in (None, ""):
                return str(value)
        for matched_row in _as_list(carrier.get("matched_personnel_rows")):
            row = _mapping(matched_row)
            for field_name in field_names:
                value = row.get(field_name)
                if value not in (None, ""):
                    return str(value)
    return ""


def _normalize_status(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _normalize_text(value).upper().replace("-", "_").replace(" ", "_")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_carriers(carriers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    deduped: list[dict[str, Any]] = []
    for carrier in carriers:
        key = (carrier.get("verification_run_id"), carrier.get("source_snapshot_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(carrier)
    return deduped


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    deduped: list[dict[str, Any]] = []
    for ref in refs:
        key = (ref.get("verification_run_id"), ref.get("source_snapshot_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "|".join(str(part or "") for part in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:20]}"


__all__ = [
    "INSUFFICIENT_PUBLIC_EVIDENCE",
    "NO_PUBLIC_OVERLAP_EVIDENCE",
    "OVERLAP_RISK",
    "ProjectManagerActiveConflictCarrier",
    "REVIEW_REQUIRED",
    "build_project_manager_active_conflict_readback",
    "evaluate_project_manager_active_conflict",
]
