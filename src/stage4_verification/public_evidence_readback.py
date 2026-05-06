# Unified Stage4 public evidence readbacks consumed by Stage5 rule gates.

from __future__ import annotations

from typing import Any, Iterable, Mapping


PUBLIC_EVIDENCE_RULE_CODES = frozenset(
    {"CREDIT-001", "REL-001", "ENG-001", "ENG-002", "PERF-001"}
)

CREDIT_TARGET_TYPES = frozenset(
    {
        "credit_penalty_blacklist",
        "administrative_penalty_public_record",
        "court_execution_public_record",
        "abnormal_operation_record",
        "building_market_credit_record",
    }
)
CREDIT_SOURCE_FAMILIES = frozenset(
    {
        "credit_china",
        "national_enterprise_credit_publicity_system",
        "court_execution_publicity",
        "building_market_credit_publicity",
        "local_housing_administrative_penalty",
        "local_credit_public_record",
        "credit_penalty_public_notice",
    }
)

RELATION_TARGET_TYPES = frozenset(
    {
        "enterprise_relation_public_record",
        "subject_relation_public_record",
        "enterprise_public_record_relation",
    }
)
RELATION_GSXT_FAMILIES = frozenset({"national_enterprise_credit_publicity_system"})

ENGINEERING_TARGETS_BY_RULE = {
    "ENG-001": frozenset({"construction_permit", "completion_filing"}),
    "ENG-002": frozenset({"contract_public_info"}),
    "PERF-001": frozenset({"performance_public_record"}),
}
ENGINEERING_NATIONAL_FAMILIES = frozenset(
    {
        "national_construction_market_platform",
        "jzsc_company_first",
        "jzsc_project_public_record",
    }
)

ACTIVE_STATUS_VALUES = frozenset(
    {
        "ACTIVE",
        "CURRENT",
        "EFFECTIVE",
        "VALID",
        "VALID_WITHIN_PERIOD",
        "IN_EFFECT",
        "PUBLIC_RECORD_FOUND",
        "UNREPAIRED_ACTIVE",
    }
)
UNREPAIRED_STATUS_VALUES = frozenset(
    {
        "ACTIVE",
        "IN_EFFECT",
        "NONE",
        "NO_REPAIR_RECORD",
        "NOT_REPAIRED",
        "NOT_REMOVED",
        "UNREPAIRED",
        "UNREPAIRED_ACTIVE",
    }
)
AUDITED_DATA_STATES = frozenset(
    {
        "A",
        "B",
        "AUDITED",
        "CONFIRMED",
        "DATA_LEVEL_A",
        "DATA_LEVEL_B",
        "GOVERNMENT_CONFIRMED",
        "OFFICIAL_CONFIRMED",
        "VERIFIED",
        "审核确认",
        "主管部门审核",
    }
)


def build_public_evidence_readback(
    *,
    readback_id: str,
    verification_target_type: str,
    source_family: str,
    source_url: str,
    source_snapshot_id: str,
    snapshot_hash: str,
    official_source: bool = True,
    subject_identifier: str,
    field_extracts: Mapping[str, Any] | None = None,
    validity_or_status: str,
    repair_or_release_state: str,
    data_grade_or_audit_state: str,
    review_required: bool = False,
    failure_reasons: Iterable[str] | None = None,
    public_only: bool = True,
    customer_visible: bool = False,
    no_legal_conclusion: bool = True,
) -> dict[str, Any]:
    return {
        "readback_id": readback_id,
        "verification_target_type": verification_target_type,
        "source_family": source_family,
        "source_url": source_url,
        "source_snapshot_id": source_snapshot_id,
        "snapshot_hash": snapshot_hash,
        "official_source": official_source,
        "subject_identifier": subject_identifier,
        "field_extracts": dict(field_extracts or {}),
        "validity_or_status": validity_or_status,
        "repair_or_release_state": repair_or_release_state,
        "data_grade_or_audit_state": data_grade_or_audit_state,
        "review_required": review_required,
        "failure_reasons": [str(reason) for reason in failure_reasons or [] if reason],
        "public_only": public_only,
        "customer_visible": customer_visible,
        "no_legal_conclusion": no_legal_conclusion,
    }


def normalize_public_evidence_readbacks(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, Mapping):
            continue
        if "readback_id" in item or "verification_target_type" in item:
            result.append(dict(item))
            continue
        for key in (
            "stage4_public_evidence_readbacks",
            "public_evidence_readbacks",
            "credit_public_readbacks",
            "engineering_public_readbacks",
            "relation_public_readbacks",
        ):
            nested = item.get(key)
            if nested not in (None, "", [], {}):
                result.extend(normalize_public_evidence_readbacks(nested))
    return _dedupe_readbacks(result)


def public_evidence_source_refs(readbacks: Any) -> list[str]:
    refs: list[str] = []
    for readback in normalize_public_evidence_readbacks(readbacks):
        for key in (
            "readback_id",
            "verification_run_id",
            "verification_target_type",
            "source_snapshot_id",
            "snapshot_hash",
            "source_url",
            "subject_identifier",
        ):
            value = readback.get(key)
            if value not in (None, "", [], {}):
                refs.append(str(value))
        field_extracts = readback.get("field_extracts")
        if isinstance(field_extracts, Mapping):
            for key in ("source_slice_sha256", "source_file_ref", "field_ref", "project_code"):
                value = field_extracts.get(key)
                if value not in (None, "", [], {}):
                    refs.append(str(value))
    return list(dict.fromkeys(refs))


def evaluate_public_evidence_gate(rule_code: str, readbacks: Any) -> dict[str, Any]:
    normalized = normalize_public_evidence_readbacks(readbacks)
    if rule_code not in PUBLIC_EVIDENCE_RULE_CODES:
        return _gate_result("PASS", [], [], [])
    if not normalized:
        return _gate_result(
            "REVIEW",
            [f"{rule_code}: public evidence readback missing"],
            [],
            [],
        )
    if rule_code == "CREDIT-001":
        return _evaluate_credit_gate(rule_code, normalized)
    if rule_code == "REL-001":
        return _evaluate_relation_gate(rule_code, normalized)
    return _evaluate_engineering_gate(rule_code, normalized)


def _evaluate_credit_gate(rule_code: str, readbacks: list[Mapping[str, Any]]) -> dict[str, Any]:
    relevant = [
        readback
        for readback in readbacks
        if _target_type(readback) in CREDIT_TARGET_TYPES or _source_family(readback) in CREDIT_SOURCE_FAMILIES
    ]
    reasons = _missing_relevant_reason(rule_code, relevant, "credit public source")
    passed: list[Mapping[str, Any]] = []
    for readback in relevant:
        readback_reasons = _common_readback_reasons(rule_code, readback)
        if _source_family(readback) not in CREDIT_SOURCE_FAMILIES:
            readback_reasons.append(f"{rule_code}: credit source family not supported")
        if not _status_in(readback, ACTIVE_STATUS_VALUES):
            readback_reasons.append(f"{rule_code}: credit validity/current status missing or inactive")
        if not _repair_state_in(readback, UNREPAIRED_STATUS_VALUES):
            readback_reasons.append(f"{rule_code}: credit repair/removal state missing or repaired")
        if readback_reasons:
            reasons.extend(_tag_readback_reasons(readback, readback_reasons))
        else:
            passed.append(readback)
    if passed:
        return _gate_result("PASS", [], passed, relevant)
    return _gate_result("REVIEW", reasons, [], relevant)


def _evaluate_relation_gate(rule_code: str, readbacks: list[Mapping[str, Any]]) -> dict[str, Any]:
    relevant = [
        readback
        for readback in readbacks
        if _target_type(readback) in RELATION_TARGET_TYPES
        or _source_family(readback) in RELATION_GSXT_FAMILIES
        or _field_extracts(readback).get("project_file_relation_evidence") is True
    ]
    reasons = _missing_relevant_reason(rule_code, relevant, "relation public source")
    qualified: list[Mapping[str, Any]] = []
    for readback in relevant:
        readback_reasons = _common_readback_reasons(rule_code, readback)
        fields = _field_extracts(readback)
        if fields.get("name_similarity_only") is True:
            readback_reasons.append(f"{rule_code}: name similarity only cannot support relation clue")
        if not _text(fields.get("relationship_type")):
            readback_reasons.append(f"{rule_code}: relationship type missing")
        if not _text(fields.get("counterparty_identifier") or fields.get("related_subject_identifier")):
            readback_reasons.append(f"{rule_code}: relationship counterparty identifier missing")
        if readback_reasons:
            reasons.extend(_tag_readback_reasons(readback, readback_reasons))
        else:
            qualified.append(readback)
    source_families = _source_families_with_support(qualified)
    has_gsxt = bool(source_families & RELATION_GSXT_FAMILIES)
    has_second_source = bool(source_families - RELATION_GSXT_FAMILIES) or any(
        _field_extracts(readback).get("project_file_relation_evidence") is True
        for readback in qualified
    )
    if qualified and has_gsxt and has_second_source:
        return _gate_result("PASS", [], qualified, relevant)
    if not has_gsxt:
        reasons.append(f"{rule_code}: GSXT relation evidence missing")
    if not has_second_source:
        reasons.append(f"{rule_code}: second public source or project-file relation evidence missing")
    return _gate_result("REVIEW", reasons, qualified, relevant)


def _evaluate_engineering_gate(rule_code: str, readbacks: list[Mapping[str, Any]]) -> dict[str, Any]:
    target_types = ENGINEERING_TARGETS_BY_RULE[rule_code]
    relevant = [readback for readback in readbacks if _target_type(readback) in target_types]
    reasons = _missing_relevant_reason(rule_code, relevant, "engineering public source")
    qualified: list[Mapping[str, Any]] = []
    for readback in relevant:
        readback_reasons = _common_readback_reasons(rule_code, readback)
        if not _status_in(readback, ACTIVE_STATUS_VALUES):
            readback_reasons.append(f"{rule_code}: engineering public record status missing")
        if not _audit_state_ok(readback):
            readback_reasons.append(f"{rule_code}: data grade or audit confirmation missing")
        if not _engineering_project_identity_ok(readback):
            readback_reasons.append(f"{rule_code}: project identity or company match missing")
        if not _engineering_date_ok(readback):
            readback_reasons.append(f"{rule_code}: required engineering date field missing")
        if readback_reasons:
            reasons.extend(_tag_readback_reasons(readback, readback_reasons))
        else:
            qualified.append(readback)
    source_families = _source_families_with_support(qualified)
    has_national = bool(source_families & ENGINEERING_NATIONAL_FAMILIES)
    has_local_or_provincial = bool(source_families - ENGINEERING_NATIONAL_FAMILIES)
    if qualified and has_national and has_local_or_provincial:
        return _gate_result("PASS", [], qualified, relevant)
    if not has_national:
        reasons.append(f"{rule_code}: JZSC/national project readback missing")
    if not has_local_or_provincial:
        reasons.append(f"{rule_code}: provincial/local engineering readback missing")
    return _gate_result("REVIEW", reasons, qualified, relevant)


def _common_readback_reasons(rule_code: str, readback: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in (
        "readback_id",
        "verification_target_type",
        "source_family",
        "source_url",
        "source_snapshot_id",
        "snapshot_hash",
        "subject_identifier",
        "field_extracts",
        "validity_or_status",
        "repair_or_release_state",
        "data_grade_or_audit_state",
    ):
        if readback.get(key) in (None, "", [], {}):
            reasons.append(f"{rule_code}: {key} missing")
    if not bool(readback.get("official_source")):
        reasons.append(f"{rule_code}: official source flag missing")
    if bool(readback.get("review_required")):
        reasons.append(f"{rule_code}: readback review required")
    if readback.get("failure_reasons") not in (None, "", [], {}):
        reasons.append(f"{rule_code}: readback failure reasons present")
    if not bool(readback.get("public_only", True)):
        reasons.append(f"{rule_code}: readback not public-only")
    if bool(readback.get("customer_visible", False)):
        reasons.append(f"{rule_code}: readback marked customer-visible")
    if not bool(readback.get("no_legal_conclusion", True)):
        reasons.append(f"{rule_code}: readback allows legal conclusion")
    return reasons


def _engineering_project_identity_ok(readback: Mapping[str, Any]) -> bool:
    fields = _field_extracts(readback)
    if fields.get("project_identity_resolved") is True:
        return True
    project_ref = _text(fields.get("project_code") or fields.get("project_id"))
    company_state = _normalize(fields.get("company_match_state") or fields.get("candidate_company_match_state"))
    company_bool = fields.get("candidate_company_match") is True or fields.get("company_matched") is True
    return bool(project_ref and (company_bool or company_state in {"MATCHED", "CONFIRMED", "PASS"}))


def _engineering_date_ok(readback: Mapping[str, Any]) -> bool:
    fields = _field_extracts(readback)
    target_type = _target_type(readback)
    keys_by_type = {
        "construction_permit": ("permit_date", "construction_start_at", "construction_end_at"),
        "contract_public_info": ("contract_date", "contract_start_at", "contract_end_at"),
        "completion_filing": ("completion_acceptance_at", "completion_filing_at"),
        "performance_public_record": (
            "performance_record_date",
            "contract_start_at",
            "contract_end_at",
            "completion_acceptance_at",
        ),
    }
    return any(_text(fields.get(key)) for key in keys_by_type.get(target_type, ()))


def _audit_state_ok(readback: Mapping[str, Any]) -> bool:
    return _normalize(readback.get("data_grade_or_audit_state")) in {_normalize(value) for value in AUDITED_DATA_STATES}


def _status_in(readback: Mapping[str, Any], allowed: frozenset[str]) -> bool:
    return _normalize(readback.get("validity_or_status")) in {_normalize(value) for value in allowed}


def _repair_state_in(readback: Mapping[str, Any], allowed: frozenset[str]) -> bool:
    return _normalize(readback.get("repair_or_release_state")) in {_normalize(value) for value in allowed}


def _source_families_with_support(readbacks: Iterable[Mapping[str, Any]]) -> set[str]:
    families: set[str] = set()
    for readback in readbacks:
        family = _source_family(readback)
        if family:
            families.add(family)
        fields = _field_extracts(readback)
        for key in ("supporting_source_families", "cross_check_source_families"):
            for value in _as_list(fields.get(key)):
                text = _text(value)
                if text:
                    families.add(text)
    return families


def _field_extracts(readback: Mapping[str, Any]) -> Mapping[str, Any]:
    value = readback.get("field_extracts")
    return value if isinstance(value, Mapping) else {}


def _target_type(readback: Mapping[str, Any]) -> str:
    return _text(readback.get("verification_target_type"))


def _source_family(readback: Mapping[str, Any]) -> str:
    return _text(readback.get("source_family"))


def _missing_relevant_reason(rule_code: str, relevant: list[Mapping[str, Any]], label: str) -> list[str]:
    return [] if relevant else [f"{rule_code}: {label} readback missing"]


def _tag_readback_reasons(readback: Mapping[str, Any], reasons: list[str]) -> list[str]:
    readback_id = _text(readback.get("readback_id")) or "unknown_readback"
    return [f"{reason} [{readback_id}]" for reason in reasons]


def _gate_result(
    status: str,
    reasons: list[str],
    passed_readbacks: Iterable[Mapping[str, Any]],
    relevant_readbacks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    passed = [dict(readback) for readback in passed_readbacks]
    relevant = [dict(readback) for readback in relevant_readbacks]
    return {
        "gate_status": status,
        "review_required": status != "PASS",
        "reasons": list(dict.fromkeys(reason for reason in reasons if reason)),
        "readback_ids": [_text(readback.get("readback_id")) for readback in relevant if _text(readback.get("readback_id"))],
        "passed_readback_ids": [
            _text(readback.get("readback_id")) for readback in passed if _text(readback.get("readback_id"))
        ],
        "source_refs": public_evidence_source_refs(relevant),
        "no_legal_conclusion": True,
        "customer_visible": False,
    }


def _dedupe_readbacks(readbacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for readback in readbacks:
        key = (
            _text(readback.get("readback_id")),
            _text(readback.get("verification_target_type")),
            _text(readback.get("source_snapshot_id")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(readback)
    return result


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _normalize(value: Any) -> str:
    return _text(value).strip().upper()


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "PUBLIC_EVIDENCE_RULE_CODES",
    "build_public_evidence_readback",
    "evaluate_public_evidence_gate",
    "normalize_public_evidence_readbacks",
    "public_evidence_source_refs",
]
