# Stage: stage4_verification
# Local provider handlers for repeatable Stage4 queue execution.

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Mapping

from stage4_verification.provider_registry import (
    COMPLETION_FILING,
    CONSTRUCTION_PERMIT,
    CONTRACT_FILING,
    GUANGDONG_THREE_LIBRARY,
    JZSC_PERSON_IDENTITY,
    LOCAL_HOUSING_CONSTRUCTION,
    NATURAL_RESOURCE_REGISTERED_SURVEYOR,
    PENALTY_CREDIT,
    PROJECT_MANAGER_CHANGE,
    SUPPLIER_QUALIFICATION_CREDIT,
)


MATCHED = "MATCHED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
PENDING_IMPLEMENTATION_REVIEW = "PENDING_IMPLEMENTATION_REVIEW"

GDCIC_BACKED_PROVIDER_IDS = frozenset(
    {
        GUANGDONG_THREE_LIBRARY,
        LOCAL_HOUSING_CONSTRUCTION,
        CONSTRUCTION_PERMIT,
        CONTRACT_FILING,
        COMPLETION_FILING,
        PROJECT_MANAGER_CHANGE,
        PENALTY_CREDIT,
    }
)

GDCIC_SOURCE_TYPES_BY_PROVIDER = {
    GUANGDONG_THREE_LIBRARY: {
        "personnel_public_record",
        "performance_public_record",
        "local_person_directory",
    },
    LOCAL_HOUSING_CONSTRUCTION: {
        "local_person_directory",
        "personnel_public_record",
        "performance_public_record",
    },
    CONSTRUCTION_PERMIT: {"construction_permit", "personnel_public_record"},
    CONTRACT_FILING: {"contract_public_info"},
    COMPLETION_FILING: {"completion_filing"},
    PROJECT_MANAGER_CHANGE: {
        "personnel_public_record",
        "construction_permit",
        "contract_public_info",
        "completion_filing",
    },
    PENALTY_CREDIT: {
        "administrative_penalty_public_record",
        "complaint_or_supervision_decision",
        "credit_penalty_blacklist",
    },
}


ProviderHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
JsonGetter = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


def build_stage4_provider_handlers(
    *,
    enable_live_gdcic: bool = False,
    http_get_json: JsonGetter | None = None,
    repository: Any | None = None,
) -> dict[str, ProviderHandler]:
    """Build provider handlers with explicit live-source opt in.

    The queue should always be able to run and produce a truthful state. For
    sources whose live browser/API adapter is not wired in, the handler returns
    a review/pending result instead of pretending that absence is a defect.
    """

    gdcic_cache: dict[str, dict[str, Any]] = {}
    gdcic_person_directory_cache: dict[str, dict[str, Any]] = {}

    def gdcic_handler(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return run_gdcic_backed_provider_task(
            payload,
            enable_live_gdcic=enable_live_gdcic,
            http_get_json=http_get_json,
            repository=repository,
            cache=gdcic_cache,
            person_directory_cache=gdcic_person_directory_cache,
        )

    return {
        JZSC_PERSON_IDENTITY: run_jzsc_identity_provider_task,
        GUANGDONG_THREE_LIBRARY: gdcic_handler,
        LOCAL_HOUSING_CONSTRUCTION: gdcic_handler,
        CONSTRUCTION_PERMIT: gdcic_handler,
        CONTRACT_FILING: gdcic_handler,
        COMPLETION_FILING: gdcic_handler,
        PROJECT_MANAGER_CHANGE: gdcic_handler,
        PENALTY_CREDIT: gdcic_handler,
        NATURAL_RESOURCE_REGISTERED_SURVEYOR: run_pending_provider_task,
        SUPPLIER_QUALIFICATION_CREDIT: run_pending_provider_task,
    }


def run_jzsc_identity_provider_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    task = dict(payload or {})
    target = _target(task)
    record = _source_stage4_record(task)
    normalized_outcome = str(
        record.get("normalized_stage4_outcome")
        or record.get("stage4_outcome")
        or ""
    ).strip()
    matched = normalized_outcome == "JZSC_PERSON_COMPANY_CERT_MATCHED"
    has_record = bool(record)

    failure_reasons = _dedupe_strings(record.get("fail_closed_reasons"))
    review_reasons = []
    if not has_record:
        review_reasons.append("source_stage4_jzsc_record_missing")
    elif not matched:
        review_reasons.append(
            normalized_outcome or "jzsc_identity_not_matched_requires_review"
        )
    review_reasons.extend(failure_reasons)
    review_reasons.extend(_dedupe_strings(record.get("nonfatal_diagnostics")))

    identity_fields = {
        "matched_company_name": _clean_text(record.get("matched_company_name")),
        "matched_company_public_id": _clean_text(record.get("matched_company_public_id")),
        "registered_unit_name": _clean_text(record.get("jzsc_registered_unit")),
        "certificate_no": _clean_text(
            record.get("jzsc_certificate_no")
            or record.get("announcement_certificate_no")
            or target.get("certificate_no_optional")
        ),
        "person_public_id": _clean_text(
            record.get("person_public_id")
            or target.get("person_public_id_optional")
        ),
        "personnel_detail_url": _clean_text(record.get("personnel_detail_url")),
    }

    return {
        "provider_id": JZSC_PERSON_IDENTITY,
        "provider_role": task.get("provider_role"),
        "provider_result_state": "READBACK_READY" if has_record else PENDING_IMPLEMENTATION_REVIEW,
        "verification_result": MATCHED if matched else REVIEW_REQUIRED,
        "identity_resolution_state": MATCHED if matched else REVIEW_REQUIRED,
        "target": target,
        "identity_fields": identity_fields,
        "source_stage4_record_ref": _record_ref(record),
        "source_refs": _jzsc_source_refs(record),
        "failure_reasons": failure_reasons,
        "review_reasons": _dedupe_strings(review_reasons),
        "policy": {
            "use_for_person_company_cert_identity": True,
            "use_for_performance_conflict": False,
            "jzsc_project_records_used_for_performance_conflict": False,
            "not_found_is_review_not_negative_fact": True,
            "no_name_only_final_proof": True,
            "public_only": True,
            "no_legal_conclusion": True,
        },
        "customer_sellable_evidence_ready": False,
    }


def run_gdcic_backed_provider_task(
    payload: Mapping[str, Any],
    *,
    enable_live_gdcic: bool = False,
    http_get_json: JsonGetter | None = None,
    repository: Any | None = None,
    cache: dict[str, dict[str, Any]] | None = None,
    person_directory_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task = dict(payload or {})
    provider_id = _clean_text(task.get("provider_id"))
    target = _target(task)
    record = _source_stage4_record(task)
    candidate = _candidate_context(task, record)

    if not enable_live_gdcic:
        return _pending_result(
            task,
            reason="live_gdcic_adapter_not_enabled",
            next_action="rerun_with_EnableLiveGdcic_or_wire_authorized_runtime_adapter",
        )

    readback = _cached_gdcic_readback(
        candidate,
        http_get_json=http_get_json,
        repository=repository,
        cache=cache,
    )
    person_directory_readback: dict[str, Any] = {}
    if provider_id in {GUANGDONG_THREE_LIBRARY, LOCAL_HOUSING_CONSTRUCTION}:
        person_directory_readback = _cached_gdcic_person_directory_readback(
            candidate,
            http_get_json=http_get_json,
            repository=repository,
            cache=person_directory_cache,
        )
    wanted_source_types = GDCIC_SOURCE_TYPES_BY_PROVIDER.get(provider_id, set())
    all_source_results = [
        *list(readback.get("source_results") or []),
        *list(person_directory_readback.get("source_results") or []),
    ]
    relevant_results = [
        dict(result)
        for result in all_source_results
        if result.get("source_type") in wanted_source_types
    ]
    covered = [
        result
        for result in relevant_results
        if result.get("coverage_state") == "COVERED"
    ]
    query_errors = [
        result
        for result in relevant_results
        if str(result.get("readback_state") or "").startswith("FAIL_CLOSED")
    ]
    identity_completion = dict(readback.get("responsible_role_identity_completion") or {})

    verification_result = REVIEW_REQUIRED
    provider_result_state = "READBACK_READY"
    review_reasons: list[str] = []
    if provider_id == GUANGDONG_THREE_LIBRARY:
        if identity_completion.get("completion_state") == "RESPONSIBLE_ROLE_CANDIDATE_FOUND":
            verification_result = MATCHED
        else:
            review_reasons.append(
                identity_completion.get("completion_state")
                or "gdcic_responsible_role_identity_not_found"
            )
    elif provider_id == LOCAL_HOUSING_CONSTRUCTION:
        same_company_count = int(person_directory_readback.get("same_company_candidate_count") or 0)
        role_candidate_count = int(identity_completion.get("candidate_count") or 0)
        if query_errors:
            provider_result_state = "FAIL_CLOSED_QUERY_ERROR"
            review_reasons.append("local_housing_construction_query_error")
        elif same_company_count > 0 or role_candidate_count > 0:
            verification_result = MATCHED
        else:
            review_reasons.append(
                person_directory_readback.get("identity_resolution_state")
                or identity_completion.get("completion_state")
                or "local_housing_construction_person_not_found_review"
            )
    elif provider_id == PROJECT_MANAGER_CHANGE:
        change_readback = _project_manager_change_readback(
            relevant_results,
            identity_completion=identity_completion,
            project_codes=list(readback.get("project_codes") or []),
            failure_reasons=_dedupe_strings(readback.get("failure_reasons")),
        )
        if query_errors:
            provider_result_state = "FAIL_CLOSED_QUERY_ERROR"
            review_reasons.append("project_manager_change_query_error")
        elif change_readback["project_code_resolution_state"] == "PROJECT_CODE_NOT_RESOLVED":
            provider_result_state = "FAIL_CLOSED_PROJECT_CODE_NOT_RESOLVED"
            review_reasons.append("project_manager_change_project_code_not_resolved")
        elif change_readback["change_candidate_count"] > 0:
            verification_result = "PUBLIC_RECORD_FOUND_REVIEW"
            review_reasons.append("project_manager_change_public_record_found_review")
        elif change_readback["identity_candidate_count"] > 0:
            verification_result = MATCHED
        else:
            review_reasons.append("project_manager_change_public_record_not_matched_review")
    elif provider_id == PENALTY_CREDIT:
        if query_errors:
            provider_result_state = "FAIL_CLOSED_QUERY_ERROR"
            review_reasons.append("gdcic_penalty_credit_query_error")
        elif covered:
            verification_result = "PUBLIC_RECORD_FOUND_REVIEW"
            review_reasons.append("gdcic_penalty_or_credit_public_record_found_review")
        else:
            review_reasons.append(
                "gdcic_penalty_credit_sources_queried_no_match_no_no_risk_inference"
            )
    else:
        if query_errors:
            provider_result_state = "FAIL_CLOSED_QUERY_ERROR"
            review_reasons.append(f"{provider_id.lower()}_query_error")
        elif covered:
            verification_result = MATCHED
        else:
            review_reasons.append(f"{provider_id.lower()}_public_record_not_matched_review")

    failure_reasons = _dedupe_strings(readback.get("failure_reasons"))
    failure_reasons.extend(_dedupe_strings(person_directory_readback.get("failure_reasons")))
    for result in relevant_results:
        failure_reasons.extend(_dedupe_strings(result.get("failure_reasons")))
    qualification_cross_check = _gdcic_person_directory_qualification_cross_check(person_directory_readback)
    response = {
        "provider_id": provider_id,
        "provider_role": task.get("provider_role"),
        "provider_result_state": provider_result_state,
        "verification_result": verification_result,
        "target": target,
        "candidate_context": candidate,
        "source_readback": {
            key: readback.get(key)
            for key in (
                "source_readback_id",
                "adapter_id",
                "adapter_version",
                "source_name",
                "source_url",
                "readback_state",
                "source_query_state",
                "project_codes",
                "covered_source_types",
                "queried_source_types",
            )
        },
        "responsible_role_identity_completion": identity_completion,
        "person_directory_readback": person_directory_readback,
        "qualification_cross_check": qualification_cross_check,
        "relevant_source_results": relevant_results,
        "covered_count": len(covered),
        "failure_reasons": _dedupe_strings(failure_reasons),
        "review_reasons": _dedupe_strings(review_reasons),
        "policy": {
            "not_found_is_review_not_negative_fact": True,
            "no_no_risk_inference_without_sources": True,
            "public_only": True,
            "no_legal_conclusion": True,
        },
        "customer_sellable_evidence_ready": False,
    }
    if provider_id == PROJECT_MANAGER_CHANGE:
        response["project_manager_change_readback"] = _project_manager_change_readback(
            relevant_results,
            identity_completion=identity_completion,
            project_codes=list(readback.get("project_codes") or []),
            failure_reasons=_dedupe_strings(readback.get("failure_reasons")),
        )
    if provider_id == LOCAL_HOUSING_CONSTRUCTION:
        response["local_housing_construction_readback"] = {
            "same_company_candidate_count": int(
                person_directory_readback.get("same_company_candidate_count") or 0
            ),
            "same_company_candidates": list(
                person_directory_readback.get("same_company_candidates") or []
            )[:5],
            "name_only_candidate_count": int(
                person_directory_readback.get("name_only_candidate_count") or 0
            ),
            "identity_resolution_state": person_directory_readback.get(
                "identity_resolution_state"
            ),
            "certificate_verification_state": person_directory_readback.get(
                "certificate_verification_state"
            ),
            "responsible_role_identity_completion": identity_completion,
            "safety_b_certificate_substitution_allowed": False,
        }
    return response


def run_pending_provider_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    task = dict(payload or {})
    provider_id = _clean_text(task.get("provider_id"))
    reason = {
        LOCAL_HOUSING_CONSTRUCTION: "local_housing_construction_runtime_adapter_not_implemented",
        NATURAL_RESOURCE_REGISTERED_SURVEYOR: "natural_resource_registered_surveyor_runtime_adapter_not_implemented",
        PROJECT_MANAGER_CHANGE: "project_manager_change_notice_runtime_adapter_not_implemented",
        SUPPLIER_QUALIFICATION_CREDIT: "supplier_qualification_credit_runtime_adapter_not_implemented",
    }.get(provider_id, "stage4_provider_runtime_adapter_not_implemented")
    return _pending_result(task, reason=reason)


def _project_manager_change_readback(
    relevant_results: list[Mapping[str, Any]],
    *,
    identity_completion: Mapping[str, Any],
    project_codes: list[str],
    failure_reasons: list[str],
) -> dict[str, Any]:
    change_candidates: list[dict[str, Any]] = []
    for result in relevant_results:
        for row in list(result.get("matched_records_preview") or []):
            if not isinstance(row, Mapping):
                continue
            if _row_has_change_signal(row):
                change_candidates.append(
                    {
                        "source_type": _clean_text(result.get("source_type")),
                        "source_url": _clean_text(result.get("source_url")),
                        "project_name": _clean_text(row.get("projectName") or row.get("perfName")),
                        "person_name": _clean_text(
                            row.get("memberName")
                            or row.get("personName")
                            or row.get("projectManager")
                            or row.get("afterProjectManager")
                            or row.get("newProjectManager")
                        ),
                        "role_text": _clean_text(row.get("position") or row.get("role") or row.get("postName")),
                        "change_type": _clean_text(row.get("changeType") or row.get("changeReason")),
                        "change_date": _clean_text(row.get("changeDate")),
                        "before_project_manager": _clean_text(
                            row.get("beforeProjectManager")
                            or row.get("oldProjectManager")
                            or row.get("oldMemberName")
                        ),
                        "after_project_manager": _clean_text(
                            row.get("afterProjectManager")
                            or row.get("newProjectManager")
                            or row.get("newMemberName")
                        ),
                    }
                )
    identity_candidates = list(identity_completion.get("identity_candidates") or [])
    project_code_unresolved = any(
        reason == "gdcic_project_code_not_resolved" for reason in failure_reasons
    )
    return {
        "project_code_resolution_state": (
            "PROJECT_CODE_RESOLVED"
            if project_codes
            else "PROJECT_CODE_NOT_RESOLVED"
            if project_code_unresolved
            else "PROJECT_CODE_NOT_REQUIRED_OR_NOT_PUBLIC"
        ),
        "project_codes": project_codes,
        "identity_candidate_count": int(identity_completion.get("candidate_count") or 0),
        "identity_candidates": identity_candidates[:5],
        "change_candidate_count": len(change_candidates),
        "change_candidates": change_candidates[:5],
        "failure_reasons": failure_reasons,
        "not_found_is_review_not_negative_fact": True,
        "no_legal_conclusion": True,
    }


def _row_has_change_signal(row: Mapping[str, Any]) -> bool:
    keys = {
        "changeType",
        "changeDate",
        "beforeProjectManager",
        "afterProjectManager",
        "oldProjectManager",
        "newProjectManager",
        "oldMemberName",
        "newMemberName",
        "changeReason",
    }
    for key in keys:
        if _clean_text(row.get(key)):
            return True
    return any("变更" in _clean_text(value) for value in row.values())


def _cached_gdcic_readback(
    candidate: Mapping[str, Any],
    *,
    http_get_json: JsonGetter | None,
    repository: Any | None,
    cache: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    cache_key = _stable_json_key(candidate)
    if cache is not None and cache_key in cache:
        return dict(cache[cache_key])
    from stage4_verification.guangdong_gdcic_openplatform import (
        query_guangdong_gdcic_openplatform_hard_defect_sources,
    )

    readback = query_guangdong_gdcic_openplatform_hard_defect_sources(
        candidate,
        repository=repository,
        http_get_json=http_get_json,
    )
    if cache is not None:
        cache[cache_key] = dict(readback)
    return dict(readback)


def _cached_gdcic_person_directory_readback(
    candidate: Mapping[str, Any],
    *,
    http_get_json: JsonGetter | None,
    repository: Any | None,
    cache: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    cache_key = _stable_json_key({"person_directory": dict(candidate)})
    if cache is not None and cache_key in cache:
        return dict(cache[cache_key])
    from stage4_verification.guangdong_gdcic_openplatform import (
        query_guangdong_gdcic_openplatform_person_directory,
    )

    readback = query_guangdong_gdcic_openplatform_person_directory(
        candidate,
        repository=repository,
        http_get_json=http_get_json,
    )
    if cache is not None:
        cache[cache_key] = dict(readback)
    return dict(readback)


def _gdcic_person_directory_qualification_cross_check(readback: Mapping[str, Any]) -> dict[str, Any]:
    if not readback:
        return {
            "verification_result": "NOT_CONFIRMED",
            "review_required": True,
            "failure_reasons": ["gdcic_person_directory_readback_missing"],
            "no_legal_conclusion": True,
        }
    certificate_confirmed = (
        readback.get("certificate_verification_state")
        == "ANNOUNCED_CERTIFICATE_NO_FOUND_IN_GDCIC_PERSON_DIRECTORY_ROWS"
    )
    failure_reasons = _dedupe_strings(readback.get("failure_reasons"))
    return {
        "verification_result": "PASS" if certificate_confirmed else "NOT_CONFIRMED",
        "review_required": not certificate_confirmed,
        "same_company_candidate_count": int(readback.get("same_company_candidate_count") or 0),
        "name_only_candidate_count": int(readback.get("name_only_candidate_count") or 0),
        "certificate_verification_state": readback.get("certificate_verification_state"),
        "safety_b_certificate_substitution_allowed": bool(
            readback.get("safety_b_certificate_substitution_allowed")
        ),
        "failure_reasons": failure_reasons,
        "no_legal_conclusion": True,
        "not_found_is_review_not_negative_fact": True,
    }


def _pending_result(
    task: Mapping[str, Any],
    *,
    reason: str,
    next_action: str = "wire_authorized_runtime_adapter_then_rerun_provider_queue",
) -> dict[str, Any]:
    provider_id = _clean_text(task.get("provider_id"))
    return {
        "provider_id": provider_id,
        "provider_role": task.get("provider_role"),
        "provider_result_state": PENDING_IMPLEMENTATION_REVIEW,
        "verification_result": REVIEW_REQUIRED,
        "target": _target(task),
        "expected_output_fields": list(task.get("expected_output_fields") or []),
        "review_reasons": [reason],
        "failure_reasons": [],
        "next_action": next_action,
        "policy": {
            "not_found_is_review_not_negative_fact": True,
            "public_only": True,
            "no_legal_conclusion": True,
        },
        "customer_sellable_evidence_ready": False,
    }


def _target(task: Mapping[str, Any]) -> dict[str, Any]:
    target = task.get("target")
    return dict(target) if isinstance(target, Mapping) else {}


def _source_stage4_record(task: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("source_stage4_jzsc_record", "source_record", "stage4_jzsc_record"):
        value = task.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    target = task.get("target")
    if isinstance(target, Mapping):
        value = target.get("source_stage4_jzsc_record")
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _candidate_context(task: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    target = _target(task)
    priority_class = _clean_text(
        target.get("opportunity_priority_class")
        or record.get("type")
        or record.get("opportunity_priority_class")
    )
    project_name = _clean_project_name(
        record.get("project_name")
        or record.get("title")
        or target.get("project_name")
    )
    candidate: dict[str, Any] = {
        "project_id": _clean_text(record.get("project_id") or f"GZ-CANDIDATE-{record.get('idx') or ''}"),
        "project_name": project_name,
        "candidate_company": _clean_text(
            target.get("candidate_company_name")
            or record.get("candidate_company")
            or record.get("matched_company_name")
        ),
        "project_manager_certificate_no": _clean_text(
            target.get("certificate_no")
            or target.get("certificate_no_optional")
            or target.get("project_manager_certificate_no")
            or record.get("announcement_certificate_no")
            or record.get("jzsc_certificate_no")
        ),
        "safety_b_certificate_no": _clean_text(
            target.get("safety_b_certificate_no")
            or target.get("safety_b_certificate_no_optional")
            or record.get("safety_b_certificate_no")
        ),
        "responsible_person_name": _clean_text(
            target.get("responsible_person_name") or record.get("responsible_person")
        ),
        "region_code": "CN-GD",
        "source_url": _clean_text(
            record.get("notice_url")
            or record.get("source_url")
            or target.get("source_url")
        ),
        "opportunity_priority_class": priority_class,
        "expected_responsible_role_field": _expected_responsible_role_field(priority_class),
    }
    if priority_class == "A_HIGH_CONSTRUCTION_EPC":
        candidate["project_manager_name"] = candidate["responsible_person_name"]
    elif priority_class == "B_HIGH_SUPERVISION":
        candidate["chief_supervision_engineer_name"] = candidate["responsible_person_name"]
        candidate["target_responsible_role"] = "chief_supervision_engineer"
    elif priority_class == "C_MEDIUM_DESIGN_SURVEY":
        candidate["design_lead_name"] = candidate["responsible_person_name"]
        candidate["target_responsible_role"] = "design_or_survey_lead"
    if record.get("idx") not in (None, ""):
        candidate["source_candidate_idx"] = record.get("idx")
    return candidate


def _expected_responsible_role_field(priority_class: str) -> str:
    if priority_class == "B_HIGH_SUPERVISION":
        return "chief_supervision_engineer_name"
    if priority_class == "C_MEDIUM_DESIGN_SURVEY":
        return "design_lead_name_or_survey_lead_name"
    return "project_manager_name"


def _clean_project_name(value: Any) -> str:
    text = _clean_text(value)
    suffixes = (
        "中标候选人及中标结果公示",
        "中标候选人公示",
        "评标报告",
    )
    for suffix in suffixes:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _record_ref(record: Mapping[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    return {
        "idx": record.get("idx"),
        "type": record.get("type"),
        "title": record.get("title"),
        "notice_url": record.get("notice_url"),
        "stage4_outcome": record.get("stage4_outcome"),
        "normalized_stage4_outcome": record.get("normalized_stage4_outcome"),
        "source_stage4_report": record.get("source_stage4_report"),
    }


def _jzsc_source_refs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for key in ("company_personnel_source_url", "personnel_detail_url", "personnel_project_source_url"):
        url = _clean_text(record.get(key))
        if url:
            refs.append({"source_url": url, "source_role": key, "public_visible": True})
    return refs


def _dedupe_strings(values: Any) -> list[str]:
    if values in (None, ""):
        return []
    if isinstance(values, str):
        raw = [values]
    elif isinstance(values, list | tuple | set):
        raw = list(values)
    else:
        raw = [str(values)]
    return list(dict.fromkeys(_clean_text(item) for item in raw if _clean_text(item)))


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_json_key(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "GDCIC_BACKED_PROVIDER_IDS",
    "PENDING_IMPLEMENTATION_REVIEW",
    "build_stage4_provider_handlers",
    "run_gdcic_backed_provider_task",
    "run_jzsc_identity_provider_task",
    "run_pending_provider_task",
]
