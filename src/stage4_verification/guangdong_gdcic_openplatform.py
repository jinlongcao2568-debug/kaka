from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from shared.utils import build_id, utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


ADAPTER_ID = "stage4.guangdong_gdcic_openplatform.v1"
API_BASE = "https://skypt.gdcic.net/api"
REFERER = "https://skypt.gdcic.net/openplatform/"
SNAPSHOT_KIND = "guangdong_gdcic_openplatform_api_json_snapshot"
USER_AGENT = "AX9S-GuangdongGdcicOpenPlatform/0.1 (+public-readonly-validation)"


JsonGetter = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


@dataclass(frozen=True)
class QuerySpec:
    source_type: str
    query_role: str
    endpoint: str
    project_code_param: str = "projectCode"
    project_name_param: str = "projectName"
    company_param: str = ""
    use_project_code: bool = True
    use_company: bool = False


PROJECT_LOOKUP_SPEC = QuerySpec(
    source_type="project_public_record",
    query_role="project_code_lookup",
    endpoint="/openplatform/project/list",
    use_project_code=False,
)

PROJECT_SOURCE_SPECS = (
    QuerySpec(
        source_type="construction_permit",
        query_role="construction_permit_lookup",
        endpoint="/openplatform/constructionPermit/list",
    ),
    QuerySpec(
        source_type="contract_public_info",
        query_role="contract_public_info_lookup",
        endpoint="/openplatform/projectContract/list",
    ),
    QuerySpec(
        source_type="completion_filing",
        query_role="completion_archive_lookup",
        endpoint="/openplatform/projectAcceptanceArchive/list",
    ),
    QuerySpec(
        source_type="completion_filing",
        query_role="finish_check_lookup",
        endpoint="/openplatform/finishCheck/list",
    ),
    QuerySpec(
        source_type="personnel_public_record",
        query_role="member_involved_project_lookup",
        endpoint="/openplatform/memberInvolvedProject/list",
    ),
    QuerySpec(
        source_type="performance_public_record",
        query_role="performance_public_record_lookup",
        endpoint="/openplatform/performance/list",
        project_code_param="prjNum",
        project_name_param="perfName",
    ),
)

COMPANY_SOURCE_SPECS = (
    QuerySpec(
        source_type="administrative_penalty_public_record",
        query_role="enterprise_punishment_lookup",
        endpoint="/openplatform/enterprisePunishment/list",
        company_param="entName",
        use_project_code=False,
        use_company=True,
    ),
    QuerySpec(
        source_type="complaint_or_supervision_decision",
        query_role="enterprise_backpay_complaint_lookup",
        endpoint="/openplatform/enterpriseBackpay/list",
        company_param="entName",
        use_project_code=False,
        use_company=True,
    ),
    QuerySpec(
        source_type="credit_penalty_blacklist",
        query_role="enterprise_blacklist_lookup",
        endpoint="/openplatform/enterpriseBlacklist/list",
        company_param="entName",
        use_project_code=False,
        use_company=True,
    ),
)


def query_guangdong_gdcic_openplatform_hard_defect_sources(
    candidate: Mapping[str, Any],
    *,
    repository: ObjectStorageRepository | None = None,
    http_get_json: JsonGetter | None = None,
    now: str | None = None,
    max_project_codes: int = 2,
    page_size: int = 5,
) -> dict[str, Any]:
    region_code = str(candidate.get("region_code") or "").upper()
    if region_code and region_code != "CN-GD":
        return {
            "adapter_id": ADAPTER_ID,
            "readback_state": "NOT_APPLICABLE",
            "region_code": region_code,
            "covered_source_types": [],
            "source_results": [],
            "failure_reasons": ["region_not_guangdong"],
        }

    getter = http_get_json or _default_http_get_json
    captured_at = now or utc_now_iso()
    project_name = _clean_text(candidate.get("project_name"))
    company_name = _clean_text(
        candidate.get("candidate_company")
        or candidate.get("winner_name")
        or candidate.get("first_rank_company")
    )
    run_id = build_id(
        "GDGDCICRUN",
        candidate.get("project_id") or project_name or "UNKNOWN",
        hashlib.sha1((project_name + company_name).encode("utf-8")).hexdigest()[:12],
    )

    source_results: list[dict[str, Any]] = []
    failure_reasons: list[str] = []
    project_codes: list[str] = _candidate_project_codes(candidate)

    if project_name:
        lookup = _execute_query(
            spec=PROJECT_LOOKUP_SPEC,
            params={"projectName": project_name, "pageNo": "1", "pageSize": str(page_size)},
            candidate=candidate,
            repository=repository,
            getter=getter,
            captured_at=captured_at,
        )
        source_results.append(lookup)
        project_codes = [
            *project_codes,
            *_extract_project_codes(lookup.get("matched_records_preview") or lookup.get("rows") or []),
        ]
    else:
        failure_reasons.append("project_name_missing_for_gdcic_project_lookup")

    project_codes = list(dict.fromkeys(project_codes))[: max(1, max_project_codes)]
    if not project_codes and project_name:
        failure_reasons.append("gdcic_project_code_not_resolved")

    for spec in PROJECT_SOURCE_SPECS:
        if project_codes:
            for project_code in project_codes:
                params = {
                    spec.project_code_param: project_code,
                    "pageNo": "1",
                    "pageSize": str(page_size),
                }
                source_results.append(
                    _execute_query(
                        spec=spec,
                        params=params,
                        candidate=candidate,
                        repository=repository,
                        getter=getter,
                        captured_at=captured_at,
                        project_codes=project_codes,
                    )
                )
        elif project_name:
            params = {
                spec.project_name_param: project_name,
                "pageNo": "1",
                "pageSize": str(page_size),
            }
            source_results.append(
                _execute_query(
                    spec=spec,
                    params=params,
                    candidate=candidate,
                    repository=repository,
                    getter=getter,
                    captured_at=captured_at,
                    project_codes=project_codes,
                )
            )
        else:
            source_results.append(_skipped_result(spec, "project_name_missing"))

    for spec in COMPANY_SOURCE_SPECS:
        if not company_name:
            source_results.append(_skipped_result(spec, "candidate_company_missing"))
            continue
        source_results.append(
            _execute_query(
                spec=spec,
                params={spec.company_param: company_name, "pageNo": "1", "pageSize": str(page_size)},
                candidate={**dict(candidate), "candidate_company": company_name},
                repository=repository,
                getter=getter,
                captured_at=captured_at,
                project_codes=project_codes,
            )
        )

    covered = sorted(
        {
            str(result.get("source_type"))
            for result in source_results
            if result.get("coverage_state") == "COVERED" and result.get("source_type")
        }
    )
    queried = sorted(
        {
            str(result.get("source_type"))
            for result in source_results
            if result.get("readback_state") == "READBACK_READY" and result.get("source_type")
        }
    )
    query_failures = [
        reason
        for result in source_results
        for reason in list(result.get("failure_reasons") or [])
        if reason
    ]
    failure_reasons = _dedupe([*failure_reasons, *query_failures])
    identity_completion = _responsible_role_identity_completion(source_results, candidate=candidate)
    return {
        "source_readback_id": run_id,
        "adapter_id": ADAPTER_ID,
        "adapter_version": "v1",
        "region_code": "CN-GD",
        "source_name": "广东建设信息网三库一平台数据开放平台",
        "source_url": REFERER,
        "readback_state": "READBACK_READY" if queried else "REVIEW_REQUIRED",
        "source_query_state": "QUERIED" if queried else "NO_REPLAYABLE_SOURCE_QUERY",
        "query_context": {
            "project_name": project_name,
            "candidate_company": company_name,
            "project_codes": project_codes,
        },
        "project_codes": project_codes,
        "covered_source_types": covered,
        "queried_source_types": queried,
        "source_results": source_results,
        "responsible_role_identity_completion": identity_completion,
        "failure_reasons": failure_reasons,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "no_no-risk_inference_without_sources": True,
    }


def _responsible_role_identity_completion(
    source_results: list[dict[str, Any]],
    *,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    expected_role = _expected_responsible_role(candidate)
    candidates: list[dict[str, Any]] = []
    for result in source_results:
        if result.get("source_type") not in {"personnel_public_record", "performance_public_record"}:
            continue
        for row in list(result.get("matched_records_preview") or []):
            identity = _role_identity_preview(
                row,
                expected_role=expected_role,
                source_type=str(result.get("source_type") or ""),
                source_url=str(result.get("source_url") or ""),
                snapshot_id=str(result.get("snapshot_id") or ""),
            )
            if identity:
                candidates.append(identity)
    unique_candidates = _unique_identity_candidates(candidates)
    if unique_candidates:
        state = "RESPONSIBLE_ROLE_CANDIDATE_FOUND"
        next_action = "write_back_responsible_role_then_run_company_first_identifier_resolution"
    else:
        state = "RESPONSIBLE_ROLE_NOT_FOUND_IN_QUERIED_PROJECT_RECORDS"
        next_action = "continue_jzsc_company_first_or_local_professional_registration_lookup"
    return {
        "completion_state": state,
        "expected_responsible_role": expected_role,
        "candidate_count": len(unique_candidates),
        "identity_candidates": unique_candidates[:5],
        "required_writeback_fields": [
            "primary_responsible_person_name",
            "project_manager_name",
            "chief_supervision_engineer_name",
            "design_lead_name",
            "survey_lead_name",
            "project_manager_public_identifier_optional",
            "project_manager_certificate_no_optional",
            "source_url",
            "source_snapshot_id",
        ],
        "next_action": next_action,
        "no_name_only_final_proof": True,
    }


def _expected_responsible_role(candidate: Mapping[str, Any]) -> str:
    explicit = _clean_text(
        candidate.get("primary_responsible_role")
        or candidate.get("target_responsible_role")
        or ""
    )
    if explicit:
        if explicit == "chief_supervision_engineer":
            return "chief_supervision_engineer"
        if explicit in {"design_lead", "survey_lead", "survey_design_project_lead"}:
            return "design_or_survey_lead"
        if explicit in {"project_manager", "construction_project_manager"}:
            return "project_manager"
        return explicit
    expected_field = _clean_text(candidate.get("expected_responsible_role_field"))
    if "chief_supervision" in expected_field or "总监" in expected_field:
        return "chief_supervision_engineer"
    if "design" in expected_field or "survey" in expected_field or "设计" in expected_field or "勘察" in expected_field:
        return "design_or_survey_lead"
    return "project_manager"


def _role_identity_preview(
    row: Mapping[str, Any],
    *,
    expected_role: str,
    source_type: str,
    source_url: str,
    snapshot_id: str,
) -> dict[str, Any]:
    person_name = _clean_text(
        row.get("memberName")
        or row.get("personName")
        or row.get("projectManager")
        or row.get("directorName")
    )
    role_text = _clean_text(row.get("position") or row.get("role") or row.get("postName"))
    if not person_name:
        return {}
    if role_text and not _role_text_matches(expected_role, role_text):
        return {}
    return {
        "person_name": person_name,
        "role_text": role_text,
        "expected_role": expected_role,
        "registered_or_project_unit": _clean_text(row.get("orgName") or row.get("entName") or row.get("corpName")),
        "source_type": source_type,
        "source_url": source_url,
        "source_snapshot_id": snapshot_id,
        "identity_state": "CANDIDATE_REQUIRES_DISAMBIGUATION",
    }


def _role_text_matches(expected_role: str, role_text: str) -> bool:
    if expected_role == "chief_supervision_engineer":
        return any(token in role_text for token in ("总监", "监理"))
    if expected_role == "design_or_survey_lead":
        return any(token in role_text for token in ("设计", "勘察", "负责人", "专业负责人"))
    return any(token in role_text for token in ("项目经理", "项目负责人", "施工负责人", "建造师", "负责人"))


def _unique_identity_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = "|".join(
            (
                str(candidate.get("person_name") or ""),
                str(candidate.get("role_text") or ""),
                str(candidate.get("registered_or_project_unit") or ""),
                str(candidate.get("source_type") or ""),
            )
        )
        if key and key not in unique:
            unique[key] = candidate
    return list(unique.values())


def _execute_query(
    *,
    spec: QuerySpec,
    params: Mapping[str, str],
    candidate: Mapping[str, Any],
    repository: ObjectStorageRepository | None,
    getter: JsonGetter,
    captured_at: str,
    project_codes: list[str] | None = None,
) -> dict[str, Any]:
    url = API_BASE + spec.endpoint
    try:
        payload = dict(getter(url, params))
    except Exception as exc:
        return {
            "source_type": spec.source_type,
            "query_role": spec.query_role,
            "endpoint": spec.endpoint,
            "source_url": _url_with_query(url, params),
            "readback_state": "FAIL_CLOSED_QUERY_ERROR",
            "coverage_state": "NOT_COVERED",
            "row_count": 0,
            "matched_count": 0,
            "failure_reasons": [f"gdcic_query_error:{type(exc).__name__}"],
        }
    rows = _rows(payload)
    matched = _matched_rows(
        rows,
        candidate=candidate,
        source_type=spec.source_type,
        project_codes=project_codes or [],
    )
    snapshot_id = _save_query_snapshot(
        payload,
        spec=spec,
        params=params,
        candidate=candidate,
        repository=repository,
        captured_at=captured_at,
    )
    failure_reasons = []
    if not matched:
        failure_reasons.append(f"{spec.source_type}_no_project_level_match")
    return {
        "source_type": spec.source_type,
        "query_role": spec.query_role,
        "endpoint": spec.endpoint,
        "source_url": _url_with_query(url, params),
        "readback_state": "READBACK_READY",
        "coverage_state": "COVERED" if matched else "QUERY_REPLAYABLE_NO_MATCH",
        "api_code": payload.get("code"),
        "api_message": payload.get("msg"),
        "total": payload.get("total"),
        "row_count": len(rows),
        "matched_count": len(matched),
        "snapshot_id": snapshot_id,
        "snapshot_refs": [
            {
                "snapshot_id": snapshot_id,
                "replayable": bool(repository),
                "source_url": _url_with_query(url, params),
            }
        ],
        "matched_records_preview": [_record_preview(row) for row in matched[:3]],
        "failure_reasons": failure_reasons,
    }


def _default_http_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    request = Request(
        _url_with_query(url, params),
        headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _save_query_snapshot(
    payload: Mapping[str, Any],
    *,
    spec: QuerySpec,
    params: Mapping[str, str],
    candidate: Mapping[str, Any],
    repository: ObjectStorageRepository | None,
    captured_at: str,
) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot_id = build_id(
        "SNAP-GDGDCIC",
        candidate.get("project_id") or candidate.get("project_name") or "UNKNOWN",
        "-".join(
            (
                spec.query_role,
                hashlib.sha1(
                    raw + json.dumps(dict(params), sort_keys=True).encode("utf-8")
                ).hexdigest()[:12],
            )
        ),
    )
    if repository is not None:
        repository.save_snapshot(
            raw,
            snapshot_id=snapshot_id,
            snapshot_kind=SNAPSHOT_KIND,
            content_type="application/json; charset=utf-8",
            source_url_optional=_url_with_query(API_BASE + spec.endpoint, params),
            source_family_optional="industry_authority_filing_page",
            lineage_refs={
                "project_id": str(candidate.get("project_id") or ""),
                "project_name": str(candidate.get("project_name") or ""),
                "source_type": spec.source_type,
                "adapter_id": ADAPTER_ID,
            },
            adapter_id=ADAPTER_ID,
            source_visibility_state="PUBLIC_VISIBLE",
            snapshot_version="v1",
            fetched_at=captured_at,
            captured_at=captured_at,
            fetch_mode="GUANGDONG_GDCIC_OPENPLATFORM_PUBLIC_API",
            fetch_audit={
                "public_only": True,
                "customer_visible": False,
                "no_legal_conclusion": True,
            },
            raw_snapshot_metadata={
                "source_url": _url_with_query(API_BASE + spec.endpoint, params),
                "source_family": "industry_authority_filing_page",
                "query_role": spec.query_role,
                "source_type": spec.source_type,
            },
        )
    return snapshot_id


def _matched_rows(
    rows: list[Mapping[str, Any]],
    *,
    candidate: Mapping[str, Any],
    source_type: str,
    project_codes: list[str],
) -> list[Mapping[str, Any]]:
    project_name = _normalize(candidate.get("project_name"))
    company_name = _normalize(candidate.get("candidate_company"))
    normalized_codes = {_normalize(code) for code in project_codes if _normalize(code)}
    matched = []
    for row in rows:
        row_code = _normalize(
            row.get("projectCode")
            or row.get("projectId")
            or row.get("prjNum")
            or row.get("project_code")
        )
        row_project = _normalize(row.get("projectName") or row.get("perfName"))
        row_company = _normalize(
            row.get("entName")
            or row.get("corpName")
            or row.get("contractOrgName")
            or row.get("biddingOrgName")
            or row.get("orgName")
        )
        code_match = bool(row_code and row_code in normalized_codes)
        project_match = bool(project_name and row_project and (project_name in row_project or row_project in project_name))
        company_match = bool(company_name and row_company and (company_name in row_company or row_company in company_name))
        if source_type in {
            "administrative_penalty_public_record",
            "complaint_or_supervision_decision",
            "credit_penalty_blacklist",
        }:
            if company_match:
                matched.append(row)
            continue
        if code_match or project_match or company_match:
            matched.append(row)
    return matched


def _extract_project_codes(rows: Any) -> list[str]:
    codes: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        for key in ("projectCode", "projectId", "prjNum"):
            value = str(row.get(key) or "").strip()
            if value:
                codes.append(value)
                break
    return list(dict.fromkeys(codes))


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    data = payload.get("data")
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, Mapping)]
    return []


def _record_preview(row: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "projectId",
        "projectCode",
        "projectName",
        "prjNum",
        "perfName",
        "constructionPermitCode",
        "provinceContractCode",
        "provinceArchiveCode",
        "archiveCode",
        "entName",
        "corpName",
        "entCode",
        "punishOrg",
        "punishTime",
        "happenTime",
        "publishTime",
        "memberName",
        "personName",
        "orgName",
        "position",
    )
    return {key: row.get(key) for key in allowed if row.get(key) not in (None, "")}


def _skipped_result(spec: QuerySpec, reason: str) -> dict[str, Any]:
    return {
        "source_type": spec.source_type,
        "query_role": spec.query_role,
        "endpoint": spec.endpoint,
        "readback_state": "SKIPPED",
        "coverage_state": "NOT_COVERED",
        "row_count": 0,
        "matched_count": 0,
        "failure_reasons": [reason],
    }


def _url_with_query(url: str, params: Mapping[str, str]) -> str:
    clean = {str(key): str(value) for key, value in dict(params).items() if value not in (None, "")}
    return f"{url}?{urlencode(clean)}" if clean else url


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _candidate_project_codes(candidate: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in (
        "projectCode",
        "project_code",
        "source_project_code",
        "gdcic_project_code",
        "project_public_code",
    ):
        value = _clean_text(candidate.get(key))
        if value:
            codes.append(value)
    source_url = str(candidate.get("source_url") or "")
    if source_url:
        parsed_url = urlparse(source_url)
        query_texts = [parsed_url.query]
        if "?" in parsed_url.fragment:
            query_texts.append(parsed_url.fragment.split("?", 1)[1])
        query: dict[str, list[str]] = {}
        for query_text in query_texts:
            for key, values in parse_qs(query_text).items():
                query.setdefault(key, []).extend(values)
        for key in ("projectCode", "project_code", "prjNum", "projectId"):
            for value in query.get(key, []):
                cleaned = _clean_text(value)
                if cleaned:
                    codes.append(cleaned)
    return list(dict.fromkeys(codes))


def _normalize(value: Any) -> str:
    return _clean_text(value).lower().replace(" ", "")


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


__all__ = [
    "ADAPTER_ID",
    "query_guangdong_gdcic_openplatform_hard_defect_sources",
]
