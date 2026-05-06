# Stage: stage4_verification
# Browser-rendered readback parser for JZSC public personnel table rows.

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping

from stage4_verification.verification import PUBLIC_VERIFICATION_PROVIDER


JZSC_PERSONNEL_RENDERED_READBACK_VERSION = "jzsc-personnel-rendered-readback-v1"
JZSC_COMPANY_SEARCH_ENTRY_URL = "https://jzsc.mohurd.gov.cn/data/company"
MATCHED = "MATCHED"
NOT_MATCHED = "NOT_MATCHED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
AMBIGUOUS_PUBLIC_MATCH = "AMBIGUOUS_PUBLIC_MATCH"
SOURCE_SNAPSHOT_MISSING = "source_snapshot_missing"
SOURCE_URL_MISSING = "source_url_missing"
REGISTERED_UNIT_CONFLICT = "registered_unit_name_conflicts_with_target_company"
ANNOUNCED_CERTIFICATE_NOT_FOUND_IN_SAME_COMPANY_ROWS = (
    "announced_certificate_no_not_found_in_same_company_personnel_rows"
)
SAME_COMPANY_PERSON_FOUND_BUT_NOT_FIRST_CLASS_CONSTRUCTOR = (
    "same_company_person_found_but_not_first_class_constructor"
)
MATCHED_CERTIFICATE_CATEGORY_CONFLICTS_WITH_REQUIREMENT = (
    "matched_certificate_category_conflicts_with_requirement"
)
REQUIRED_REGISTRATION_PROFESSION_NOT_PUBLICLY_CONFIRMED = (
    "required_registration_profession_not_publicly_confirmed_in_captured_rows"
)
MATCHED_CERTIFICATE_PROFESSION_CONFLICTS_WITH_REQUIREMENT = (
    "matched_certificate_profession_conflicts_with_requirement"
)


def build_jzsc_company_first_capture_plan(
    *,
    target_company_name: str,
    target_project_manager_name: str,
    target_identifier: str | None = None,
    entry_url: str = JZSC_COMPANY_SEARCH_ENTRY_URL,
    max_personnel_pages: int = 20,
    max_project_pages: int = 20,
) -> dict[str, Any]:
    plan_id = _stable_id(
        "JZSC-CAPTURE-PLAN",
        target_company_name,
        target_project_manager_name,
        target_identifier,
        max_personnel_pages,
        max_project_pages,
    )
    return {
        "capture_plan_id": plan_id,
        "capture_plan_type": "JZSC_COMPANY_FIRST_PROJECT_MANAGER_VERIFICATION",
        "source_family": "national_construction_market_platform",
        "entry_url": entry_url,
        "browser_required": True,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "automated_challenge_resolution_first": True,
        "resume_requires_human_input": False,
        "target": {
            "company_name": target_company_name,
            "project_manager_name": target_project_manager_name,
            "target_identifier_optional": target_identifier,
        },
        "stable_identity_key_policy": {
            "company_first_required": True,
            "broad_name_search_allowed_as_final_proof": False,
            "same_name_only_accepted": False,
            "identifier_precedence": [
                "registration_no",
                "person_public_id",
                "masked_identity_no",
            ],
            "downstream_targets_must_use_resolved_identifier": [
                "personnel_public_record",
                "performance_public_record",
                "contract_public_info",
                "completion_filing",
            ],
        },
        "capture_steps": [
            {
                "step_id": "open_company_search_entry",
                "action": "OPEN_URL",
                "url": entry_url,
                "snapshot_role": "jzsc_company_search_entry",
            },
            {
                "step_id": "query_exact_company",
                "action": "SEARCH_EXACT_COMPANY",
                "input_value": target_company_name,
                "match_policy": "exact_or_review",
                "snapshot_role": "jzsc_company_search_results",
            },
            {
                "step_id": "open_company_detail",
                "action": "OPEN_MATCHED_COMPANY_DETAIL",
                "snapshot_role": "jzsc_company_detail",
            },
            {
                "step_id": "capture_registered_personnel_rows",
                "action": "PAGINATE_AND_CAPTURE_RENDERED_TABLE_ROWS",
                "tab_or_section": "registered_personnel",
                "parser": "parse_jzsc_personnel_rows",
                "max_pages": max_personnel_pages,
                "target_name": target_project_manager_name,
                "snapshot_role": "jzsc_company_registered_personnel",
            },
            {
                "step_id": "resolve_project_manager_identifier",
                "action": "DERIVE_IDENTIFIER_FROM_UNIQUE_COMPANY_PERSONNEL_ROW",
                "accepted_identifier_fields": [
                    "registration_no",
                    "person_public_id",
                    "masked_identity_no",
                ],
                "review_if": [
                    "matched_personnel_row_count != 1",
                    "registration_no_missing_and_person_public_id_missing",
                    "registered_unit_name_conflicts_with_target_company",
                ],
            },
            {
                "step_id": "open_personnel_detail",
                "action": "OPEN_PERSONNEL_DETAIL_FROM_MATCHED_ROW",
                "required_before_downstream": True,
                "snapshot_role": "jzsc_personnel_detail",
            },
            {
                "step_id": "capture_personnel_project_rows",
                "action": "PAGINATE_AND_CAPTURE_RENDERED_TABLE_ROWS",
                "tab_or_section": "personnel_projects",
                "parser": "parse_jzsc_personnel_project_rows",
                "max_pages": max_project_pages,
                "snapshot_role": "jzsc_personnel_project_records",
            },
            {
                "step_id": "emit_stage4_company_first_readback",
                "action": "CALL_STAGE4_SERVICE",
                "service_method": "build_jzsc_project_manager_company_first_readback",
                "expected_outputs": [
                    "personnel_carrier",
                    "conflict_records",
                    "evidence_risk_hard_defect_strategy",
                    "project_manager_active_conflict_readback",
                ],
            },
        ],
        "fail_closed_conditions": [
            "company_detail_not_found",
            "challenge_unresolved_before_capture",
            "rendered_personnel_rows_missing",
            "name_only_match_cannot_pass",
            "same_company_same_name_ambiguous",
            "personnel_detail_unavailable",
            "source_snapshot_missing",
        ],
        "expected_carriers": [
            "personnel_public_record",
            "enterprise_public_record",
            "performance_public_record",
            "contract_public_info",
            "completion_filing",
        ],
    }


def parse_jzsc_personnel_rows(rendered_rows: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_row in rendered_rows:
        row_payload = _row_payload(raw_row)
        text = _clean_text(row_payload.get("row_text"))
        if not text:
            continue
        parts = text.split(" ")
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        row = {
            "row_no": int(parts[0]),
            "person_name": parts[1],
            "masked_identity_no": parts[2],
            "registration_category": " ".join(parts[3:-1]),
            "registration_no": parts[-1],
            "raw_row": text,
        }
        for source_key, target_key in (
            ("detail_url", "personnel_detail_url_optional"),
            ("personnel_detail_url", "personnel_detail_url_optional"),
            ("person_public_id", "person_public_id_optional"),
            ("registered_unit_name", "registered_unit_name_optional"),
            ("registration_at", "project_manager_registration_at"),
            ("registered_at", "project_manager_registration_at"),
            ("registration_changed_at", "project_manager_registration_changed_at"),
            ("certificate_valid_from", "project_manager_certificate_valid_from"),
            ("certificate_valid_until", "project_manager_certificate_valid_until"),
            ("certificate_status", "project_manager_certificate_status_optional"),
        ):
            value = row_payload.get(source_key)
            if value not in (None, ""):
                row[target_key] = value
        profession = _first_non_empty(
            row_payload.get("registration_profession"),
            row_payload.get("registration_profession_optional"),
            row_payload.get("REG_PROF_NAME"),
            row_payload.get("reg_prof_name"),
            row_payload.get("注册专业"),
            (row_payload.get("raw_source_row") or {}).get("REG_PROF_NAME")
            if isinstance(row_payload.get("raw_source_row"), Mapping)
            else None,
        )
        if profession not in (None, ""):
            row["registration_profession_optional"] = profession
        rows.append(row)
    return rows


def build_jzsc_personnel_list_carrier(
    rendered_rows: Iterable[Any],
    *,
    target_name: str,
    target_identifier: str | None = None,
    target_company_name: str | None = None,
    source_url: str,
    source_snapshot_id: str,
    page_no: int = 1,
    required_registration_category: str | None = None,
    required_registration_profession_keywords: Iterable[str] | None = None,
) -> dict[str, Any]:
    rows = parse_jzsc_personnel_rows(rendered_rows)
    normalized_target_name = _normalize(target_name)
    normalized_identifier = _normalize(target_identifier)
    name_matches = [
        row for row in rows if _normalize(row.get("person_name")) == normalized_target_name
    ]
    identifier_matches = [
        row
        for row in name_matches
        if normalized_identifier
        and (
            _normalize(row.get("registration_no")) == normalized_identifier
            or _normalize(row.get("masked_identity_no")) == normalized_identifier
        )
    ]
    matched_rows = identifier_matches if normalized_identifier else name_matches
    source_failures = _source_failures(
        source_url=source_url,
        source_snapshot_id=source_snapshot_id,
    )
    resolved_identifier = _resolved_identifier(matched_rows)
    matched_row = matched_rows[0] if len(matched_rows) == 1 else {}
    company_failures = _company_failures(
        matched_row=matched_row,
        target_company_name=target_company_name,
    )
    review_failures = source_failures + company_failures
    identity_diagnostics = _identity_diagnostics(
        name_matches=name_matches,
        identifier_matches=identifier_matches,
        normalized_identifier=normalized_identifier,
    )
    requirement_failures = _requirement_failures(
        matched_rows=matched_rows,
        required_registration_category=required_registration_category,
        required_registration_profession_keywords=required_registration_profession_keywords,
    )
    review_failures = review_failures + requirement_failures

    failure_reason: str | None = None
    if not matched_rows:
        result = NOT_MATCHED
        if normalized_identifier and name_matches:
            failure_reason = ANNOUNCED_CERTIFICATE_NOT_FOUND_IN_SAME_COMPANY_ROWS
        else:
            failure_reason = "personnel_public_record_not_found_in_rendered_rows"
    elif len(matched_rows) > 1 and not normalized_identifier:
        result = REVIEW_REQUIRED
        failure_reason = AMBIGUOUS_PUBLIC_MATCH
    elif review_failures:
        result = REVIEW_REQUIRED
        failure_reason = review_failures[0]
    else:
        result = MATCHED

    review_required = result != MATCHED
    failure_reasons = _dedupe_strings(
        review_failures
        + identity_diagnostics
        + ([failure_reason] if failure_reason else [])
    )
    run_id = _stable_id(
        "ST4JZSC",
        source_snapshot_id,
        target_name,
        target_identifier,
        [row.get("raw_row") for row in matched_rows],
    )
    return {
        "verification_run_id": run_id,
        "verification_target_id": _stable_id("TARGET-JZSC-PERSON", target_name, target_identifier),
        "verification_target_type": "personnel_public_record",
        "verification_role": "enterprise_personnel_resolution",
        "source_snapshot_id": source_snapshot_id,
        "source_url": source_url,
        "source_family": "national_construction_market_platform",
        "public_visibility_state": "PUBLIC_VISIBLE",
        "verification_provider": PUBLIC_VERIFICATION_PROVIDER,
        "provider_version": JZSC_PERSONNEL_RENDERED_READBACK_VERSION,
        "verification_route": "COMPANY_FIRST_PERSONNEL_LIST",
        "verification_result": result,
        "evidence_grade": "PUBLIC_RENDERED_TABLE_FIELD_MATCH" if result == MATCHED else "PUBLIC_RENDERED_TABLE_REVIEW",
        "confidence": 0.9 if result == MATCHED else 0.49,
        "review_required": review_required,
        "failure_reason_optional": failure_reason,
        "failure_reasons": failure_reasons,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "page_no": page_no,
        "target_name": target_name,
        "target_company_name_optional": target_company_name,
        "target_identifier_optional": target_identifier,
        "required_registration_category_optional": required_registration_category,
        "required_registration_profession_keywords": _dedupe_strings(
            required_registration_profession_keywords or []
        ),
        "requirement_check": {
            "required_registration_category": required_registration_category,
            "required_registration_profession_keywords": _dedupe_strings(
                required_registration_profession_keywords or []
            ),
            "requirement_failures": requirement_failures,
            "captured_registration_categories": _dedupe_strings(
                row.get("registration_category") for row in matched_rows or name_matches
            ),
            "captured_registration_professions": _dedupe_strings(
                row.get("registration_profession_optional") for row in matched_rows or name_matches
            ),
        },
        "resolved_public_identifier_optional": resolved_identifier,
        "project_manager_public_identifier_optional": resolved_identifier,
        "project_manager_certificate_no_optional": _first_non_empty(
            matched_row.get("registration_no"),
            resolved_identifier,
        ),
        "project_manager_registered_unit_optional": matched_row.get("registered_unit_name_optional"),
        "personnel_detail_url_optional": matched_row.get("personnel_detail_url_optional"),
        "person_public_id_optional": matched_row.get("person_public_id_optional"),
        "project_manager_registration_at": matched_row.get("project_manager_registration_at"),
        "project_manager_registration_changed_at": matched_row.get("project_manager_registration_changed_at"),
        "project_manager_certificate_valid_from": matched_row.get("project_manager_certificate_valid_from"),
        "project_manager_certificate_valid_until": matched_row.get("project_manager_certificate_valid_until"),
        "project_manager_certificate_status_optional": matched_row.get(
            "project_manager_certificate_status_optional"
        ),
        "identifier_resolution": {
            "company_first_query": True,
            "target_identifier_supplied": bool(normalized_identifier),
            "derived_identifier_from_matched_row": bool(resolved_identifier and not normalized_identifier),
            "same_company_same_name_count": len(name_matches),
            "matched_row_count": len(matched_rows),
            "resolution_state": result,
            "failure_reason_optional": failure_reason,
            "failure_reasons": failure_reasons,
        },
        "parsed_personnel_rows": rows,
        "name_matched_personnel_rows": name_matches,
        "identifier_mismatch_personnel_rows": (
            name_matches if normalized_identifier and name_matches and not identifier_matches else []
        ),
        "matched_personnel_rows": matched_rows,
        "source_refs": [
            {
                "source_url": source_url,
                "source_snapshot_id": source_snapshot_id,
                "public_visibility_state": "PUBLIC_VISIBLE",
                "source_family": "national_construction_market_platform",
            }
        ],
        "snapshot_refs": [
            {
                "snapshot_id": source_snapshot_id,
                "replayable": True,
                "rendered_browser_snapshot": True,
            }
        ],
    }


def build_jzsc_company_personnel_resolution_carrier(
    rendered_rows: Iterable[Any],
    *,
    target_company_name: str,
    target_name: str,
    target_identifier: str | None = None,
    source_url: str,
    source_snapshot_id: str,
    page_no: int = 1,
    required_registration_category: str | None = None,
    required_registration_profession_keywords: Iterable[str] | None = None,
) -> dict[str, Any]:
    return build_jzsc_personnel_list_carrier(
        rendered_rows,
        target_name=target_name,
        target_identifier=target_identifier,
        target_company_name=target_company_name,
        source_url=source_url,
        source_snapshot_id=source_snapshot_id,
        page_no=page_no,
        required_registration_category=required_registration_category,
        required_registration_profession_keywords=required_registration_profession_keywords,
    )


def parse_jzsc_personnel_project_rows(rendered_rows: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_row in rendered_rows:
        payload = _row_payload(raw_row)
        row_text = _clean_text(payload.get("row_text"))
        project_name = _first_non_empty(payload.get("project_name"), payload.get("工程名称"))
        project_id = _first_non_empty(
            payload.get("project_id"),
            payload.get("project_code"),
            payload.get("项目编码"),
        )
        if not project_name and row_text:
            parts = row_text.split(" ")
            if len(parts) >= 2 and parts[0].isdigit():
                project_name = parts[1]
                if len(parts) >= 3:
                    project_id = parts[2]
        if not project_name:
            continue
        rows.append(
            {
                "row_no": _int_or_none(payload.get("row_no")),
                "project_id": project_id,
                "project_name": project_name,
                "registered_unit_name": _first_non_empty(
                    payload.get("registered_unit_name"),
                    payload.get("contractor_name"),
                    payload.get("承建单位"),
                ),
                "project_manager_name": _first_non_empty(
                    payload.get("project_manager_name"),
                    payload.get("manager_name"),
                    payload.get("项目经理"),
                ),
                "project_manager_public_identifier_optional": _first_non_empty(
                    payload.get("project_manager_public_identifier_optional"),
                    payload.get("registration_no"),
                    payload.get("certificate_no"),
                    payload.get("注册号"),
                ),
                "role": _first_non_empty(payload.get("role"), payload.get("担任角色")),
                "contract_time_window": {
                    "start_at": _first_non_empty(
                        payload.get("contract_start_at"),
                        payload.get("construction_start_at"),
                        payload.get("start_at"),
                        payload.get("开工日期"),
                    ),
                    "end_at": _first_non_empty(
                        payload.get("contract_end_at"),
                        payload.get("construction_end_at"),
                        payload.get("end_at"),
                        payload.get("竣工日期"),
                    ),
                },
                "completion_acceptance_status": _first_non_empty(
                    payload.get("completion_acceptance_status"),
                    payload.get("completion_status"),
                    payload.get("acceptance_status"),
                    payload.get("竣工验收状态"),
                ),
                "detail_url_optional": _first_non_empty(
                    payload.get("detail_url"),
                    payload.get("project_detail_url"),
                    payload.get("项目详情URL"),
                ),
                "raw_row": row_text,
            }
        )
    return rows


def build_jzsc_personnel_project_conflict_records(
    rendered_rows: Iterable[Any],
    *,
    project_manager_name: str,
    project_manager_identifier: str,
    registered_unit_name: str,
    source_url: str,
    source_snapshot_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in enumerate(parse_jzsc_personnel_project_rows(rendered_rows), start=1):
        project_id = _first_non_empty(row.get("project_id"), _stable_id("JZSC-PROJECT", source_snapshot_id, index))
        project_name = row.get("project_name")
        row_unit = _first_non_empty(row.get("registered_unit_name"), registered_unit_name)
        row_manager_name = _first_non_empty(row.get("project_manager_name"), project_manager_name)
        row_identifier = _first_non_empty(
            row.get("project_manager_public_identifier_optional"),
            project_manager_identifier,
        )
        row_source_url = _first_non_empty(row.get("detail_url_optional"), source_url)
        record = {
            "project_id": project_id,
            "project_name": project_name,
            "registered_unit_name": row_unit,
            "project_manager_name": row_manager_name,
            "project_manager_public_identifier_optional": row_identifier,
            "contract_time_window": dict(row.get("contract_time_window") or {}),
            "completion_acceptance_status": row.get("completion_acceptance_status"),
            "source_url": row_source_url,
            "verification_carriers": [
                _project_record_carrier(
                    target_type="performance_public_record",
                    source_url=row_source_url,
                    source_snapshot_id=source_snapshot_id,
                    project_id=str(project_id),
                    project_name=str(project_name),
                    project_manager_identifier=str(row_identifier),
                    row=row,
                ),
                _project_record_carrier(
                    target_type="contract_public_info",
                    source_url=row_source_url,
                    source_snapshot_id=source_snapshot_id,
                    project_id=str(project_id),
                    project_name=str(project_name),
                    project_manager_identifier=str(row_identifier),
                    row=row,
                ),
                _project_record_carrier(
                    target_type="completion_filing",
                    source_url=row_source_url,
                    source_snapshot_id=source_snapshot_id,
                    project_id=str(project_id),
                    project_name=str(project_name),
                    project_manager_identifier=str(row_identifier),
                    row=row,
                ),
            ],
        }
        records.append(record)
    return records


def _project_record_carrier(
    *,
    target_type: str,
    source_url: str,
    source_snapshot_id: str,
    project_id: str,
    project_name: str,
    project_manager_identifier: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    run_id = _stable_id(
        "ST4JZSCPROJ",
        source_snapshot_id,
        target_type,
        project_id,
        project_manager_identifier,
    )
    source_failures = _source_failures(
        source_url=source_url,
        source_snapshot_id=source_snapshot_id,
    )
    result = REVIEW_REQUIRED if source_failures else MATCHED
    return {
        "verification_run_id": run_id,
        "verification_target_id": _stable_id("TARGET-JZSC-PROJECT", target_type, project_id),
        "verification_target_type": target_type,
        "verification_role": "personnel_project_record",
        "source_snapshot_id": source_snapshot_id,
        "source_url": source_url,
        "source_family": "national_construction_market_platform",
        "public_visibility_state": "PUBLIC_VISIBLE",
        "verification_provider": PUBLIC_VERIFICATION_PROVIDER,
        "provider_version": JZSC_PERSONNEL_RENDERED_READBACK_VERSION,
        "verification_result": result,
        "evidence_grade": (
            "PUBLIC_RENDERED_TABLE_REVIEW"
            if source_failures
            else "PUBLIC_RENDERED_TABLE_FIELD_MATCH"
        ),
        "confidence": 0.49 if source_failures else 0.88,
        "review_required": bool(source_failures),
        "failure_reason_optional": source_failures[0] if source_failures else None,
        "failure_reasons": source_failures,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "project_id": project_id,
        "project_name": project_name,
        "project_manager_public_identifier_optional": project_manager_identifier,
        "contract_time_window": dict(row.get("contract_time_window") or {}),
        "completion_acceptance_status": row.get("completion_acceptance_status"),
        "source_refs": [
            {
                "source_url": source_url,
                "source_snapshot_id": source_snapshot_id,
                "public_visibility_state": "PUBLIC_VISIBLE",
                "source_family": "national_construction_market_platform",
            }
        ],
        "snapshot_refs": [
            {
                "snapshot_id": source_snapshot_id,
                "replayable": True,
                "rendered_browser_snapshot": True,
            }
        ],
    }


def _row_payload(raw_row: Any) -> dict[str, Any]:
    if isinstance(raw_row, Mapping):
        row_text = _first_non_empty(
            raw_row.get("row_text"),
            raw_row.get("text"),
            raw_row.get("raw_row"),
        )
        payload = dict(raw_row)
        payload["row_text"] = row_text
        return payload
    return {"row_text": raw_row}


def _source_failures(*, source_url: str | None, source_snapshot_id: str | None) -> list[str]:
    failures: list[str] = []
    if not _clean_text(source_url):
        failures.append(SOURCE_URL_MISSING)
    if not _clean_text(source_snapshot_id):
        failures.append(SOURCE_SNAPSHOT_MISSING)
    return failures


def _company_failures(
    *,
    matched_row: Mapping[str, Any],
    target_company_name: str | None,
) -> list[str]:
    row_unit = _normalize(matched_row.get("registered_unit_name_optional"))
    target_unit = _normalize(target_company_name)
    if row_unit and target_unit and row_unit != target_unit:
        return [REGISTERED_UNIT_CONFLICT]
    return []


def _resolved_identifier(rows: list[dict[str, Any]]) -> str | None:
    if len(rows) != 1:
        return None
    row = rows[0]
    return _first_non_empty(
        row.get("registration_no"),
        row.get("person_public_id_optional"),
        row.get("masked_identity_no"),
    )


def _identity_diagnostics(
    *,
    name_matches: list[dict[str, Any]],
    identifier_matches: list[dict[str, Any]],
    normalized_identifier: str,
) -> list[str]:
    diagnostics: list[str] = []
    if normalized_identifier and name_matches and not identifier_matches:
        diagnostics.append(ANNOUNCED_CERTIFICATE_NOT_FOUND_IN_SAME_COMPANY_ROWS)
        if _looks_like_first_class_constructor_registration_no(
            normalized_identifier
        ) and not any(_is_first_class_constructor_row(row) for row in name_matches):
            diagnostics.append(SAME_COMPANY_PERSON_FOUND_BUT_NOT_FIRST_CLASS_CONSTRUCTOR)
    return diagnostics


def _requirement_failures(
    *,
    matched_rows: list[dict[str, Any]],
    required_registration_category: str | None,
    required_registration_profession_keywords: Iterable[str] | None,
) -> list[str]:
    failures: list[str] = []
    if not matched_rows:
        return failures
    required_category = _clean_text(required_registration_category)
    if required_category and not any(
        required_category in _clean_text(row.get("registration_category"))
        for row in matched_rows
    ):
        failures.append(MATCHED_CERTIFICATE_CATEGORY_CONFLICTS_WITH_REQUIREMENT)

    keywords = [
        _clean_text(value)
        for value in list(required_registration_profession_keywords or [])
        if _clean_text(value)
    ]
    if keywords:
        professions = [
            _clean_text(row.get("registration_profession_optional"))
            for row in matched_rows
            if _clean_text(row.get("registration_profession_optional"))
        ]
        if not professions:
            failures.append(REQUIRED_REGISTRATION_PROFESSION_NOT_PUBLICLY_CONFIRMED)
        elif not any(
            any(keyword in profession for keyword in keywords)
            for profession in professions
        ):
            failures.append(MATCHED_CERTIFICATE_PROFESSION_CONFLICTS_WITH_REQUIREMENT)
    return failures


def _looks_like_first_class_constructor_registration_no(value: Any) -> bool:
    text = _normalize(value)
    return bool(re.match(r"^[\u4e00-\u9fff]1\d{14,18}$", text))


def _is_first_class_constructor_row(row: Mapping[str, Any]) -> bool:
    category = _clean_text(row.get("registration_category"))
    return "一级注册建造师" in category or "一级建造师" in category


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: Any) -> str:
    return _clean_text(value).upper()


def _stable_id(prefix: str, *values: Any) -> str:
    payload = repr(values).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:20]
    return f"{prefix}-{digest}"


__all__ = [
    "AMBIGUOUS_PUBLIC_MATCH",
    "JZSC_COMPANY_SEARCH_ENTRY_URL",
    "JZSC_PERSONNEL_RENDERED_READBACK_VERSION",
    "REGISTERED_UNIT_CONFLICT",
    "SOURCE_SNAPSHOT_MISSING",
    "SOURCE_URL_MISSING",
    "build_jzsc_company_first_capture_plan",
    "build_jzsc_company_personnel_resolution_carrier",
    "build_jzsc_personnel_project_conflict_records",
    "build_jzsc_personnel_list_carrier",
    "parse_jzsc_personnel_project_rows",
    "parse_jzsc_personnel_rows",
]
