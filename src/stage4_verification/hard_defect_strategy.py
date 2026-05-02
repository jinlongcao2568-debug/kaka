# Stage: stage4_verification
# Internal readback carrier for evidence risk and hard-defect verification strategy.

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


READY_FOR_PUBLIC_VERIFICATION = "READY_FOR_PUBLIC_VERIFICATION"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
BLOCKED_INSUFFICIENT_STRATEGY_INPUT = "BLOCKED_INSUFFICIENT_STRATEGY_INPUT"

HARD_DEFECT_STRATEGY_VERSION = "stage4-hard-defect-strategy-v1"

FIELD_CONFIDENCE_REVIEW_THRESHOLD = 0.75

STRATEGY_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "strategy_key": "project_manager_active_conflict",
        "hard_defect_family": "PROJECT_MANAGER_ACTIVE_CONFLICT",
        "priority": 10,
        "required_field_aliases": (
            "project_manager_name",
            "manager_name",
            "project_manager_public_identifier_optional",
            "project_manager_public_identifier",
            "project_manager_certificate_type",
            "project_manager_cert_specialty",
            "project_manager_professional_title",
        ),
        "required_public_verifications": (
            "personnel_public_record",
            "enterprise_public_record",
            "enterprise_qualification",
            "performance_public_record",
            "contract_public_info",
            "completion_filing",
        ),
        "stage5_rule_codes": ("PM-001", "PM-002"),
        "preferred_source_families": (
            "public_resource_trading_platform",
            "local_housing_construction_permit_platform",
            "local_housing_contract_filing_platform",
            "local_housing_completion_filing_platform",
            "local_project_manager_change_notice",
            "national_construction_market_platform",
            "industry_authority_filing_page",
            "credit_china",
            "court_execution_publicity",
            "national_enterprise_credit_publicity_system",
            "local_administrative_penalty_publicity",
        ),
        "verification_chain_roles": (
            {
                "role": "award_commitment_chain",
                "source_family": "public_resource_trading_platform",
                "target_evidence": "bid_candidate_and_award_result_notices",
                "gate_use": "anchors committed project manager, bidder, award date, amount, and contract period expectation",
            },
            {
                "role": "performance_time_chain",
                "source_family": "local_housing_construction_permit_platform",
                "target_evidence": "construction_permit_contract_start_end_and_registered_manager",
                "gate_use": "proves real performance window instead of relying on award date only",
            },
            {
                "role": "contract_filing_chain",
                "source_family": "local_housing_contract_filing_platform",
                "target_evidence": "contract_filing_amount_period_and_parties",
                "gate_use": "cross-checks permit and award time window for overlap judgement",
            },
            {
                "role": "completion_release_chain",
                "source_family": "local_housing_completion_filing_platform",
                "target_evidence": "completion_acceptance_or_filing_release_record",
                "gate_use": "proves project release; missing release keeps conflict in review",
            },
            {
                "role": "manager_change_chain",
                "source_family": "local_project_manager_change_notice",
                "target_evidence": "project_manager_change_notice_and_change_date",
                "gate_use": "splits the manager responsibility window when a change is publicly recorded",
            },
            {
                "role": "identity_archive_chain",
                "source_family": "national_construction_market_platform",
                "target_evidence": "enterprise_personnel_project_archive",
                "gate_use": "disambiguates identity and supplements history; not sole no-risk proof",
            },
            {
                "role": "risk_signal_chain",
                "source_family": "credit_or_penalty_publicity",
                "target_evidence": "credit_penalty_execution_or_local_punishment_record",
                "gate_use": "feeds risk and commercial hook signals; can be valuable even when not a hard block",
            },
        ),
        "selection_reason": "project manager field exists; active-project conflict needs award, permit, contract, completion/release, manager-change, identity archive, and credit/penalty readback",
        "requires_identity_disambiguation": True,
    },
    {
        "strategy_key": "enterprise_qualification",
        "hard_defect_family": "QUALIFICATION_MISMATCH",
        "priority": 20,
        "required_field_aliases": (
            "qualification_certificate",
            "qualification_level",
            "enterprise_qualification",
            "bidder_qualification",
        ),
        "required_public_verifications": ("enterprise_qualification", "enterprise_public_record"),
        "stage5_rule_codes": ("QUAL-001",),
        "preferred_source_families": (
            "national_construction_market_platform",
            "national_enterprise_credit_publicity_system",
        ),
        "selection_reason": "qualification field exists; enterprise qualification and registry readback are required before any rule promotion",
    },
    {
        "strategy_key": "credit_penalty_blacklist",
        "hard_defect_family": "CREDIT_PENALTY_OR_BLACKLIST",
        "priority": 30,
        "required_field_aliases": (
            "credit_penalty_record",
            "credit_penalty",
            "credit_blacklist",
            "abnormal_operation_record",
        ),
        "required_public_verifications": ("credit_penalty_blacklist", "enterprise_public_record"),
        "stage5_rule_codes": ("CREDIT-001",),
        "preferred_source_families": (
            "credit_china",
            "court_execution_publicity",
            "national_enterprise_credit_publicity_system",
            "local_administrative_penalty_publicity",
        ),
        "verification_chain_roles": (
            {
                "role": "credit_penalty_chain",
                "source_family": "credit_or_penalty_publicity",
                "target_evidence": "credit_china_execution_gsxt_or_local_penalty_record",
                "gate_use": "creates risk evidence and commercial hook signal; source block fails closed to review",
            },
        ),
        "selection_reason": "credit or penalty field exists; public credit and enterprise registry readback are required",
    },
    {
        "strategy_key": "construction_permit",
        "hard_defect_family": "PERMIT_PUBLIC_RECORD_ANOMALY",
        "priority": 40,
        "required_field_aliases": (
            "construction_permit_no",
            "construction_permit",
            "permit_record_no",
            "permit_public_record",
        ),
        "required_public_verifications": ("construction_permit", "enterprise_public_record"),
        "stage5_rule_codes": ("ENG-001",),
        "preferred_source_families": ("industry_authority_filing_page",),
        "verification_chain_roles": (
            {
                "role": "performance_time_chain",
                "source_family": "local_housing_construction_permit_platform",
                "target_evidence": "construction_permit_contract_start_end_and_registered_manager",
                "gate_use": "proves actual work window and manager listed on permit",
            },
        ),
        "selection_reason": "permit field exists; construction permit filing readback is required",
    },
    {
        "strategy_key": "contract_public_info",
        "hard_defect_family": "CONTRACT_PUBLIC_RECORD_ANOMALY",
        "priority": 50,
        "required_field_aliases": (
            "contract_record_no",
            "contract_public_info",
            "contract_filing_no",
            "contract_performance_record",
        ),
        "required_public_verifications": ("contract_public_info", "enterprise_public_record"),
        "stage5_rule_codes": ("ENG-002",),
        "preferred_source_families": ("industry_authority_filing_page",),
        "verification_chain_roles": (
            {
                "role": "contract_filing_chain",
                "source_family": "local_housing_contract_filing_platform",
                "target_evidence": "contract_filing_amount_period_and_parties",
                "gate_use": "cross-checks award and permit performance dates",
            },
        ),
        "selection_reason": "contract field exists; contract public filing readback is required",
    },
    {
        "strategy_key": "completion_filing",
        "hard_defect_family": "COMPLETION_OR_ACCEPTANCE_ANOMALY",
        "priority": 60,
        "required_field_aliases": (
            "completion_filing_no",
            "completion_acceptance_status",
            "completion_filing",
            "acceptance_filing_no",
        ),
        "required_public_verifications": ("completion_filing", "enterprise_public_record"),
        "stage5_rule_codes": ("ENG-001",),
        "preferred_source_families": ("industry_authority_filing_page",),
        "verification_chain_roles": (
            {
                "role": "completion_release_chain",
                "source_family": "local_housing_completion_filing_platform",
                "target_evidence": "completion_acceptance_or_filing_release_record",
                "gate_use": "proves release from in-progress conflict; missing release is review, not no-risk",
            },
        ),
        "selection_reason": "completion or acceptance field exists; completion filing readback is required",
    },
    {
        "strategy_key": "performance_public_record",
        "hard_defect_family": "PERFORMANCE_OR_FILING_ANOMALY",
        "priority": 70,
        "required_field_aliases": (
            "performance_record_no",
            "performance_public_record",
            "performance_filing",
            "historical_performance",
        ),
        "required_public_verifications": ("performance_public_record", "enterprise_public_record"),
        "stage5_rule_codes": ("PERF-001",),
        "preferred_source_families": ("industry_authority_filing_page",),
        "selection_reason": "performance field exists; performance public readback is required",
    },
    {
        "strategy_key": "procedure_public_notice_timeline",
        "hard_defect_family": "PROCEDURAL_DEFECT",
        "priority": 80,
        "required_field_aliases": (
            "procedure_timeline_marker",
            "notice_publication_date",
            "bid_opening_time",
            "objection_deadline",
            "clock_conflict_state",
            "version_conflict_state",
        ),
        "required_public_verifications": ("public_notice_timeline",),
        "stage5_rule_codes": ("PROC-001", "PROC-002"),
        "preferred_source_families": ("public_resource_trading_platform", "government_procurement_public_site"),
        "selection_reason": "procedure or clock/version field exists; Stage5 procedural rules need public chain and clock/version refs",
    },
)


@dataclass(frozen=True)
class EvidenceRiskHardDefectStrategyCarrier:
    strategy_run_id: str
    strategy_version: str
    input_parse_run_id: str | None
    source_snapshot_id: str | None
    source_url: str | None
    strategy_targets: list[dict[str, Any]]
    verification_targets: list[dict[str, Any]]
    stage5_requested_rule_codes: list[str]
    stage5_supported_upstream_objects: list[str]
    evidence_risk_state: str
    public_verification_required: bool
    weak_evidence_fails_closed: bool
    review_required: bool
    fail_closed: bool
    fail_closed_reasons: list[str]
    evidence_risk_taxonomy: list[str]
    field_quality_summary: dict[str, Any]
    no_llm_fact_adjudication: bool = True
    llm_allowed_for_verification_decision: bool = False
    public_only: bool = True
    customer_visible: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["strategy_targets"] = [dict(target) for target in self.strategy_targets]
        payload["verification_targets"] = [dict(target) for target in self.verification_targets]
        payload["stage5_requested_rule_codes"] = list(self.stage5_requested_rule_codes)
        payload["stage5_supported_upstream_objects"] = list(self.stage5_supported_upstream_objects)
        payload["fail_closed_reasons"] = list(self.fail_closed_reasons)
        payload["evidence_risk_taxonomy"] = list(self.evidence_risk_taxonomy)
        payload["field_quality_summary"] = dict(self.field_quality_summary)
        return payload


def build_evidence_risk_hard_defect_strategy(
    parsed_context: Mapping[str, Any] | Any,
    *,
    existing_public_verification_carriers: list[Mapping[str, Any]] | None = None,
) -> EvidenceRiskHardDefectStrategyCarrier:
    context = _stage3_context(parsed_context)
    parsed_fields = context["parsed_fields"]
    carriers = [_mapping(carrier) for carrier in _as_list(existing_public_verification_carriers)]
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
    if derived_manager_identifier and not context.get("project_manager_public_identifier_optional"):
        context = dict(context)
        context["project_manager_public_identifier_optional"] = derived_manager_identifier
        context["project_manager_public_identifier_source"] = (
            "matched_enterprise_personnel_public_record"
        )
    selected = _select_strategy_targets(parsed_fields, context)
    verification_targets = _verification_targets(
        selected,
        context=context,
        parsed_fields=parsed_fields,
        carriers=carriers,
    )
    stage5_rule_codes = _dedupe(
        rule_code
        for target in selected
        for rule_code in target.get("stage5_rule_codes", [])
    )

    quality = _field_quality_summary(
        parsed_fields=parsed_fields,
        selected_targets=selected,
        context=context,
        carriers=carriers,
    )
    fail_closed_reasons = _fail_closed_reasons(
        selected_targets=selected,
        verification_targets=verification_targets,
        field_quality_summary=quality,
        context=context,
    )
    risk_state = _risk_state(selected, fail_closed_reasons)
    review_required = risk_state != READY_FOR_PUBLIC_VERIFICATION

    return EvidenceRiskHardDefectStrategyCarrier(
        strategy_run_id=_stable_id(
            "ST4HDS",
            context.get("parse_run_id"),
            context.get("source_snapshot_id"),
            [target["strategy_key"] for target in selected],
            fail_closed_reasons,
        ),
        strategy_version=HARD_DEFECT_STRATEGY_VERSION,
        input_parse_run_id=context.get("parse_run_id"),
        source_snapshot_id=context.get("source_snapshot_id"),
        source_url=context.get("source_url"),
        strategy_targets=selected,
        verification_targets=verification_targets,
        stage5_requested_rule_codes=stage5_rule_codes,
        stage5_supported_upstream_objects=_stage5_supported_upstream_objects(selected),
        evidence_risk_state=risk_state,
        public_verification_required=bool(verification_targets),
        weak_evidence_fails_closed=True,
        review_required=review_required,
        fail_closed=review_required,
        fail_closed_reasons=fail_closed_reasons,
        evidence_risk_taxonomy=_evidence_risk_taxonomy(fail_closed_reasons),
        field_quality_summary=quality,
    )


def build_evidence_risk_hard_defect_strategy_readback(carrier: Mapping[str, Any]) -> dict[str, Any]:
    required_fields = (
        "strategy_run_id",
        "strategy_version",
        "strategy_targets",
        "stage5_requested_rule_codes",
        "evidence_risk_state",
        "field_quality_summary",
    )
    missing = [
        field_name
        for field_name in required_fields
        if carrier.get(field_name) in (None, "", [], {})
    ]
    boundary_safe = (
        bool(carrier.get("public_only", True))
        and not bool(carrier.get("customer_visible", False))
        and bool(carrier.get("no_legal_conclusion", True))
        and bool(carrier.get("no_llm_fact_adjudication", True))
        and not bool(carrier.get("llm_allowed_for_verification_decision", False))
    )
    fail_closed = (
        bool(missing)
        or not boundary_safe
        or bool(carrier.get("fail_closed", False))
        or bool(carrier.get("review_required", False))
        or carrier.get("evidence_risk_state") != READY_FOR_PUBLIC_VERIFICATION
    )
    return {
        "readback_state": (
            "READBACK_READY" if not missing and boundary_safe else "FAIL_CLOSED_INCOMPLETE_OR_BOUNDARY_UNSAFE"
        ),
        "replayable": bool(not missing and boundary_safe),
        "fail_closed": fail_closed,
        "no_broad_fallback": True,
        "public_only": bool(carrier.get("public_only", True)),
        "customer_visible": False,
        "no_legal_conclusion": True,
        "no_llm_fact_adjudication": bool(carrier.get("no_llm_fact_adjudication", True)),
        "llm_allowed_for_verification_decision": False,
        "missing_required_fields": missing,
        "strategy_run_id": carrier.get("strategy_run_id"),
        "strategy_version": carrier.get("strategy_version"),
        "evidence_risk_state": carrier.get("evidence_risk_state"),
        "public_verification_required": bool(carrier.get("public_verification_required")),
        "weak_evidence_fails_closed": bool(carrier.get("weak_evidence_fails_closed", True)),
        "review_required": bool(carrier.get("review_required")) or fail_closed,
        "fail_closed_reasons": list(_as_list(carrier.get("fail_closed_reasons"))),
        "evidence_risk_taxonomy": list(_as_list(carrier.get("evidence_risk_taxonomy"))),
        "stage5_requested_rule_codes": [
            str(value) for value in _as_list(carrier.get("stage5_requested_rule_codes")) if value
        ],
        "stage5_supported_upstream_objects": [
            str(value) for value in _as_list(carrier.get("stage5_supported_upstream_objects")) if value
        ],
        "verification_target_count": len(_as_list(carrier.get("verification_targets"))),
        "strategy_target_count": len(_as_list(carrier.get("strategy_targets"))),
    }


def _select_strategy_targets(parsed_fields: list[dict[str, Any]], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for definition in STRATEGY_DEFINITIONS:
        refs = _matching_field_refs(parsed_fields, definition["required_field_aliases"])
        if not refs and not _context_triggers_definition(context, definition):
            continue
        selected.append(
            {
                "strategy_key": definition["strategy_key"],
                "hard_defect_family": definition["hard_defect_family"],
                "priority": definition["priority"],
                "required_public_verifications": list(definition["required_public_verifications"]),
                "stage5_rule_codes": list(definition["stage5_rule_codes"]),
                "preferred_source_families": list(definition["preferred_source_families"]),
                "verification_chain_roles": [
                    dict(role)
                    for role in definition.get("verification_chain_roles", ())
                ],
                "matched_field_refs": refs,
                "public_verification_required": bool(definition["required_public_verifications"]),
                "selection_reason": definition["selection_reason"],
                "requires_identity_disambiguation": bool(definition.get("requires_identity_disambiguation", False)),
            }
        )
    return sorted(selected, key=lambda item: int(item["priority"]))


def _verification_targets(
    selected_targets: list[dict[str, Any]],
    *,
    context: Mapping[str, Any],
    parsed_fields: list[dict[str, Any]],
    carriers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for strategy in selected_targets:
        for target_type in strategy["required_public_verifications"]:
            identifier = _target_identifier(target_type, context, parsed_fields)
            existing = _first_carrier_for_type(carriers, target_type)
            targets.append(
                {
                    "verification_target_id": _stable_id(
                        "ST4HDT",
                        strategy["strategy_key"],
                        target_type,
                        identifier,
                        context.get("source_snapshot_id"),
                    ),
                    "verification_target_type": target_type,
                    "target_identifier": identifier,
                    "strategy_key": strategy["strategy_key"],
                    "hard_defect_family": strategy["hard_defect_family"],
                    "public_verification_required": True,
                    "preferred_source_families": list(strategy["preferred_source_families"]),
                    "verification_chain_roles": [
                        dict(role)
                        for role in strategy.get("verification_chain_roles", [])
                    ],
                    "existing_verification_run_id_optional": existing.get("verification_run_id"),
                    "existing_verification_result_optional": existing.get("verification_result"),
                    "missing_identifier": not bool(identifier),
                }
            )
    return _dedupe_targets(targets)


def _field_quality_summary(
    *,
    parsed_fields: list[dict[str, Any]],
    selected_targets: list[dict[str, Any]],
    context: Mapping[str, Any],
    carriers: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_refs = {
        ref.get("field_ref")
        for target in selected_targets
        for ref in target.get("matched_field_refs", [])
        if ref.get("field_ref")
    }
    selected_fields = [
        field for field in parsed_fields if _field_ref(field) in selected_refs
    ] or parsed_fields
    confidences = [_float(field.get("confidence"), 0.0) for field in selected_fields]
    weak_fields = [
        _field_ref(field)
        for field in selected_fields
        if _float(field.get("confidence"), 0.0) < FIELD_CONFIDENCE_REVIEW_THRESHOLD
        or bool(field.get("review_required"))
    ]
    missing_source_slice = [
        _field_ref(field)
        for field in selected_fields
        if field.get("source_slice_sha256") in (None, "")
    ]
    missing_source_file = [
        _field_ref(field)
        for field in selected_fields
        if field.get("source_file_ref") in (None, "")
    ]
    carrier_failures = [
        carrier.get("verification_run_id") or carrier.get("verification_target_type")
        for carrier in carriers
        if carrier.get("review_required")
        or carrier.get("verification_result") in {"REVIEW_REQUIRED", "CONFLICT", "INSUFFICIENT_PUBLIC_EVIDENCE"}
        or carrier.get("failure_reason_optional") not in (None, "")
    ]
    return {
        "field_count": len(parsed_fields),
        "selected_field_count": len(selected_fields),
        "minimum_confidence": min(confidences) if confidences else 0.0,
        "weak_field_refs": [ref for ref in weak_fields if ref],
        "missing_source_slice_refs": [ref for ref in missing_source_slice if ref],
        "missing_source_file_refs": [ref for ref in missing_source_file if ref],
        "source_snapshot_present": bool(context.get("source_snapshot_id")),
        "field_conflict_state": context.get("conflict_state") or "UNKNOWN",
        "lineage_status": context.get("lineage_status") or "UNKNOWN",
        "carrier_failure_refs": [str(value) for value in carrier_failures if value],
    }


def _fail_closed_reasons(
    *,
    selected_targets: list[dict[str, Any]],
    verification_targets: list[dict[str, Any]],
    field_quality_summary: Mapping[str, Any],
    context: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not selected_targets:
        reasons.append("no_hard_defect_field_candidate")
    if not verification_targets:
        reasons.append("public_verification_target_missing")
    if not field_quality_summary.get("source_snapshot_present"):
        reasons.append("missing_snapshot")
    if field_quality_summary.get("weak_field_refs"):
        reasons.append("weak_field_confidence")
    if field_quality_summary.get("missing_source_slice_refs"):
        reasons.append("missing_source_slice")
    if field_quality_summary.get("missing_source_file_refs"):
        reasons.append("missing_source_file_ref")
    if field_quality_summary.get("carrier_failure_refs"):
        reasons.append("existing_public_verification_requires_review")
    if field_quality_summary.get("field_conflict_state") not in (None, "", "CONSISTENT", "UNKNOWN"):
        reasons.append("field_conflict")
    if field_quality_summary.get("lineage_status") not in (None, "", "NORMALIZED", "UNKNOWN"):
        reasons.append("lineage_not_normalized")
    if any(target.get("missing_identifier") for target in verification_targets):
        reasons.append("target_identifier_missing")
    if any(target.get("strategy_key") == "project_manager_active_conflict" for target in selected_targets):
        if not context.get("project_manager_public_identifier_optional"):
            reasons.append("same_name_not_disambiguated")
    return _dedupe(reasons)


def _risk_state(selected_targets: list[dict[str, Any]], fail_closed_reasons: list[str]) -> str:
    if not selected_targets:
        return BLOCKED_INSUFFICIENT_STRATEGY_INPUT
    if fail_closed_reasons:
        return REVIEW_REQUIRED
    return READY_FOR_PUBLIC_VERIFICATION


def _evidence_risk_taxonomy(reasons: list[str]) -> list[str]:
    taxonomy: list[str] = []
    if "weak_field_confidence" in reasons:
        taxonomy.append("WEAK_EVIDENCE")
    if "same_name_not_disambiguated" in reasons:
        taxonomy.append("SAME_NAME_NOT_DISAMBIGUATED")
    if "field_conflict" in reasons:
        taxonomy.append("FIELD_CONFLICT")
    if "missing_snapshot" in reasons or "missing_source_slice" in reasons or "missing_source_file_ref" in reasons:
        taxonomy.append("MISSING_SNAPSHOT_OR_SOURCE_SLICE")
    if "target_identifier_missing" in reasons:
        taxonomy.append("TARGET_IDENTIFIER_MISSING")
    if "existing_public_verification_requires_review" in reasons:
        taxonomy.append("PUBLIC_VERIFICATION_REVIEW_REQUIRED")
    if not taxonomy and reasons:
        taxonomy.append("INSUFFICIENT_PUBLIC_STRATEGY_INPUT")
    return taxonomy


def _stage5_supported_upstream_objects(selected_targets: list[dict[str, Any]]) -> list[str]:
    supported = {
        "clock_chain_profile",
        "coverage_registry",
        "evidence_grade_profile",
        "field_lineage_record",
        "focus_bidder_verification_profile",
        "notice_version_chain",
        "project_base",
        "project_manager",
        "public_attack_surface",
        "public_chain",
        "qualification_clause_profile",
    }
    if any(target["strategy_key"] == "project_manager_active_conflict" for target in selected_targets):
        supported.add("project_manager_active_conflict_readback")
    return sorted(supported)


def _stage3_context(parsed_context: Mapping[str, Any] | Any) -> dict[str, Any]:
    root = _mapping(parsed_context)
    inputs = _mapping(getattr(parsed_context, "inputs", None) or root.get("inputs"))
    handoff = _mapping(getattr(parsed_context, "handoff", None) or root.get("handoff"))
    records = _mapping(getattr(parsed_context, "records", None) or root.get("records"))
    project_base = _record_mapping(records.get("project_base") or root.get("project_base"))
    bidder_candidate = _record_mapping(records.get("bidder_candidate") or root.get("bidder_candidate"))
    project_manager = _record_mapping(records.get("project_manager") or root.get("project_manager"))
    field_lineage = _record_mapping(records.get("field_lineage_record") or root.get("field_lineage_record"))
    parsed_fields = _parsed_fields(
        root.get("parsed_fields")
        or inputs.get("parsed_fields")
        or _mapping(root.get("stage3_parser_carrier")).get("parsed_fields")
    )
    field_values = _parsed_field_values(parsed_fields)
    sources = (root, inputs, handoff, project_base, bidder_candidate, project_manager, field_lineage, field_values)

    def first(*names: str) -> Any:
        for name in names:
            for source in sources:
                value = source.get(name)
                if value not in (None, "", []):
                    return value
        return None

    return {
        "parse_run_id": first("parse_run_id"),
        "source_snapshot_id": first("source_snapshot_id", "snapshot_id", "source_document_ref"),
        "source_url": first("source_url"),
        "project_id": first("project_id", "current_project_id"),
        "project_name": first("project_name", "current_project_name"),
        "candidate_company_name": first(
            "candidate_company_name",
            "bidder_name",
            "candidate_company",
            "company_name",
        ),
        "project_manager_name": first("project_manager_name", "manager_name"),
        "project_manager_public_identifier_optional": first(
            "project_manager_public_identifier_optional",
            "project_manager_public_identifier",
            "public_identifier_optional",
            "public_identifier",
        ),
        "project_manager_certificate_type": first("project_manager_certificate_type"),
        "project_manager_cert_specialty": first("project_manager_cert_specialty"),
        "project_manager_professional_title": first("project_manager_professional_title"),
        "lineage_status": first("lineage_status"),
        "conflict_state": first("conflict_state"),
        "parsed_fields": parsed_fields,
    }


def _parsed_fields(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, field in enumerate(_as_list(value)):
        data = _mapping(field)
        if not data:
            continue
        data.setdefault("field_ref", _field_ref(data, fallback_index=index))
        result.append(data)
    return result


def _parsed_field_values(fields: list[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in fields:
        field_name = field.get("field_name")
        if not field_name:
            continue
        value = field.get("field_value_optional")
        if value not in (None, ""):
            values[str(field_name)] = value
    return values


def _matching_field_refs(fields: list[dict[str, Any]], aliases: tuple[str, ...]) -> list[dict[str, Any]]:
    aliases_normalized = {_normalize_key(alias) for alias in aliases}
    refs: list[dict[str, Any]] = []
    for field in fields:
        field_name = _normalize_key(field.get("field_name"))
        if field_name not in aliases_normalized:
            continue
        refs.append(
            {
                "field_ref": _field_ref(field),
                "field_name": field.get("field_name"),
                "field_value_optional": field.get("field_value_optional"),
                "source_file_ref": field.get("source_file_ref"),
                "source_slice_sha256": field.get("source_slice_sha256"),
                "confidence": _float(field.get("confidence"), 0.0),
                "review_required": bool(field.get("review_required")),
            }
        )
    return refs


def _context_triggers_definition(context: Mapping[str, Any], definition: Mapping[str, Any]) -> bool:
    key = definition.get("strategy_key")
    if key == "project_manager_active_conflict":
        return bool(context.get("project_manager_name"))
    if key in {"enterprise_qualification", "credit_penalty_blacklist", "performance_public_record"}:
        return bool(context.get("candidate_company_name"))
    if key in {"construction_permit", "contract_public_info", "completion_filing"}:
        return False
    if key == "procedure_public_notice_timeline":
        return context.get("conflict_state") not in (None, "", "CONSISTENT")
    return False


def _target_identifier(
    target_type: str,
    context: Mapping[str, Any],
    parsed_fields: list[Mapping[str, Any]],
) -> str:
    by_type = {
        "personnel_public_record": (
            context.get("project_manager_public_identifier_optional")
            or context.get("project_manager_name")
        ),
        "enterprise_public_record": context.get("candidate_company_name"),
        "enterprise_qualification": _first_field_value(
            parsed_fields,
            ("qualification_certificate", "qualification_level", "enterprise_qualification", "bidder_qualification"),
        )
        or context.get("candidate_company_name"),
        "credit_penalty_blacklist": _first_field_value(
            parsed_fields,
            ("credit_penalty_record", "credit_penalty", "credit_blacklist", "abnormal_operation_record"),
        )
        or context.get("candidate_company_name"),
        "construction_permit": _first_field_value(
            parsed_fields,
            ("construction_permit_no", "construction_permit", "permit_record_no", "permit_public_record"),
        ),
        "contract_public_info": _first_field_value(
            parsed_fields,
            ("contract_record_no", "contract_public_info", "contract_filing_no", "contract_performance_record"),
        )
        or context.get("project_manager_public_identifier_optional")
        or context.get("project_manager_name")
        or context.get("candidate_company_name"),
        "completion_filing": _first_field_value(
            parsed_fields,
            ("completion_filing_no", "completion_acceptance_status", "completion_filing", "acceptance_filing_no"),
        )
        or context.get("project_manager_public_identifier_optional")
        or context.get("project_manager_name")
        or context.get("candidate_company_name"),
        "performance_public_record": _first_field_value(
            parsed_fields,
            ("performance_record_no", "performance_public_record", "performance_filing", "historical_performance"),
        )
        or context.get("project_manager_public_identifier_optional")
        or context.get("project_manager_name")
        or context.get("candidate_company_name"),
        "public_notice_timeline": (
            context.get("project_id")
            or context.get("project_name")
            or context.get("source_snapshot_id")
        ),
    }
    value = by_type.get(target_type)
    return str(value) if value not in (None, "") else ""


def _first_field_value(fields: list[Mapping[str, Any]], aliases: tuple[str, ...]) -> Any:
    aliases_normalized = {_normalize_key(alias) for alias in aliases}
    for field in fields:
        if _normalize_key(field.get("field_name")) in aliases_normalized:
            value = field.get("field_value_optional")
            if value not in (None, ""):
                return value
    return None


def _first_carrier_for_type(carriers: list[dict[str, Any]], target_type: str) -> dict[str, Any]:
    for carrier in carriers:
        if carrier.get("verification_target_type") == target_type:
            return carrier
    return {}


def _matched_personnel_field_value(carriers: list[dict[str, Any]], field_names: tuple[str, ...]) -> str:
    for carrier in carriers:
        if (
            carrier.get("verification_target_type") != "personnel_public_record"
            or carrier.get("verification_result") != "MATCHED"
            or bool(carrier.get("review_required"))
        ):
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


def _field_ref(field: Mapping[str, Any], fallback_index: int = 0) -> str:
    explicit = field.get("field_ref")
    if explicit not in (None, ""):
        return str(explicit)
    return _stable_id(
        "ST3FIELD",
        fallback_index,
        field.get("field_name"),
        field.get("source_file_ref"),
        field.get("source_slice_sha256"),
    )


def _dedupe_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    result: list[dict[str, Any]] = []
    for target in targets:
        key = (
            target.get("strategy_key"),
            target.get("verification_target_type"),
            target.get("target_identifier"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(target)
    return result


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


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower())


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "|".join(str(part or "") for part in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:20]}"


__all__ = [
    "BLOCKED_INSUFFICIENT_STRATEGY_INPUT",
    "EvidenceRiskHardDefectStrategyCarrier",
    "HARD_DEFECT_STRATEGY_VERSION",
    "READY_FOR_PUBLIC_VERIFICATION",
    "REVIEW_REQUIRED",
    "build_evidence_risk_hard_defect_strategy",
    "build_evidence_risk_hard_defect_strategy_readback",
]
