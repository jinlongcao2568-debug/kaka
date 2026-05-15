from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping


HIGHWAY_MARKET_PERSONNEL_ADAPTER_ID = "stage4.highway_market_personnel_query.v1"
HIGHWAY_MARKET_PERSON_INDEX_URL = "https://hwdms.mot.gov.cn/BMWebSite/person/index.do?type=2"
HIGHWAY_MARKET_PERSON_LIST_URL = "https://hwdms.mot.gov.cn/BMWebSite/person/getPersonListTab.do"
HIGHWAY_MARKET_PERSON_ACADEMIC_URL = "https://hwdms.mot.gov.cn/BMWebSite/person/getPersonAcademicList.do"

HttpPost = Callable[[str, Mapping[str, str], Mapping[str, str]], Mapping[str, Any]]


def query_highway_market_person_title(
    request: Mapping[str, Any],
    *,
    http_post: HttpPost | None = None,
    timeout_seconds: int = 12,
    retry_attempts: int = 2,
) -> dict[str, Any]:
    """Query the official highway market person/title readback.

    The adapter is intentionally narrow: it only records limited JSON fields needed
    for public registration matching and does not store raw HTML/blob payloads.
    """

    company = _clean_text(request.get("target_company_name") or request.get("candidate_company_name"))
    person = _clean_text(request.get("target_person_name") or request.get("responsible_person_name"))
    certificate = _clean_text(request.get("target_certificate_no") or request.get("certificate_no_optional"))
    if not company or not person:
        return _result(
            request=request,
            query_state="FAIL_CLOSED_TARGET_FIELDS_MISSING",
            fail_closed_reasons=["highway_market_target_company_or_person_missing"],
        )

    post = http_post or (lambda url, body, headers: _default_http_post(url, body, headers, timeout_seconds))
    headers = _default_headers()
    attempts: list[dict[str, Any]] = []
    list_payload, list_attempts = _post_with_retry(
        post,
        HIGHWAY_MARKET_PERSON_LIST_URL,
        {
            "page": "1",
            "rows": "20",
            "viewType": "1",
            "text": person,
            "isJob": "",
            "type": "2",
        },
        headers,
        route="person_name_query",
        retry_attempts=retry_attempts,
    )
    attempts.extend(list_attempts)
    if list_payload is None:
        return _result(
            request=request,
            query_state="FAIL_CLOSED_PUBLIC_QUERY_ERROR",
            fail_closed_reasons=[
                "highway_market_person_list_query_failed:"
                + str((list_attempts[-1] or {}).get("error") or "unknown")
            ],
            route_attempts=attempts,
        )
    list_rows = [row for row in list(list_payload.get("rows") or []) if isinstance(row, Mapping)]

    same_person_rows = [row for row in list_rows if _text_equal(row.get("name"), person)]
    exact_rows = [
        row
        for row in same_person_rows
        if _company_names_equivalent(row.get("company"), company)
    ]
    if not exact_rows:
        return _result(
            request=request,
            query_state="REVIEW_REQUIRED_PERSON_COMPANY_NOT_MATCHED",
            fail_closed_reasons=["highway_market_person_company_not_matched"],
            person_list_records=_limited_person_records(same_person_rows or list_rows),
            route_attempts=attempts,
        )

    matched_person = dict(exact_rows[0])
    person_id = _clean_text(matched_person.get("id") or matched_person.get("requestid"))
    company_id = _clean_text(matched_person.get("companyId"))
    academic_records: list[Mapping[str, Any]] = []
    academic_attempt: dict[str, Any] = {
        "route": "person_academic_query",
        "source_url": _academic_source_url(person_id),
        "status": "SKIPPED_PERSON_ID_MISSING" if not person_id else "NOT_RUN",
    }
    if person_id:
        academic_payload, academic_attempts = _post_with_retry(
            post,
            _academic_source_url(person_id),
            {"page": "1", "rows": "20"},
            {**headers, "Referer": _person_detail_url(person_id, company_id)},
            route="person_academic_query",
            retry_attempts=retry_attempts,
        )
        attempts.extend(academic_attempts)
        if academic_payload is not None:
            academic_records = [
                row for row in list(academic_payload.get("rows") or []) if isinstance(row, Mapping)
            ]
            academic_attempt = {
                "route": "person_academic_query",
                "source_url": _academic_source_url(person_id),
                "status": "READBACK_READY",
                "row_count": len(academic_records),
            }
        else:
            academic_attempt = {
                "route": "person_academic_query",
                "source_url": _academic_source_url(person_id),
                "status": "FAIL_CLOSED",
                "error": str((academic_attempts[-1] or {}).get("error") or "unknown"),
            }
        if not any(
            attempt.get("route") == "person_academic_query"
            and attempt.get("status") == academic_attempt["status"]
            and attempt.get("source_url") == academic_attempt["source_url"]
            for attempt in attempts
        ):
            attempts.append(academic_attempt)

    matched_academic = _pick_academic_record(academic_records, certificate)
    resolved_certificate = _clean_text((matched_academic or {}).get("academicID"))
    query_state = (
        "READBACK_READY_PERSON_COMPANY_CERTIFICATE_MATCHED"
        if resolved_certificate
        else "READBACK_READY_PERSON_COMPANY_MATCHED_CERTIFICATE_FIELD_MISSING"
    )
    fail_closed_reasons: list[str] = []
    if certificate and not resolved_certificate:
        query_state = "REVIEW_REQUIRED_CERTIFICATE_NOT_MATCHED"
        fail_closed_reasons.append("highway_market_certificate_not_matched")

    return _result(
        request=request,
        query_state=query_state,
        fail_closed_reasons=fail_closed_reasons,
        matched_person_record=_limited_person_record(matched_person),
        academic_records=_limited_academic_records(academic_records),
        matched_academic_record=_limited_academic_record(matched_academic or {}),
        resolved_certificate_no=resolved_certificate,
        person_public_id=person_id,
        company_public_id=company_id,
        registered_unit_name=_clean_text(matched_person.get("company")),
        route_attempts=attempts,
    )


def _default_http_post(
    url: str,
    body: Mapping[str, str],
    headers: Mapping[str, str],
    timeout_seconds: int,
) -> Mapping[str, Any]:
    data = urllib.parse.urlencode(dict(body)).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _post_with_retry(
    post: HttpPost,
    url: str,
    body: Mapping[str, str],
    headers: Mapping[str, str],
    *,
    route: str,
    retry_attempts: int,
) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for attempt_no in range(1, max(1, int(retry_attempts or 1)) + 1):
        try:
            payload = dict(post(url, body, headers))
            rows = list(payload.get("rows") or []) if isinstance(payload, Mapping) else []
            attempts.append(
                {
                    "route": route,
                    "source_url": url,
                    "attempt_no": attempt_no,
                    "status": "READBACK_READY",
                    "row_count": len(rows),
                }
            )
            return payload, attempts
        except Exception as exc:  # pragma: no cover - network defensive boundary
            attempts.append(
                {
                    "route": route,
                    "source_url": url,
                    "attempt_no": attempt_no,
                    "status": "FAIL_CLOSED",
                    "error": str(exc),
                }
            )
    return None, attempts


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": HIGHWAY_MARKET_PERSON_INDEX_URL,
        "Origin": "https://hwdms.mot.gov.cn",
        "X-Requested-With": "XMLHttpRequest",
    }


def _result(
    *,
    request: Mapping[str, Any],
    query_state: str,
    fail_closed_reasons: list[str] | None = None,
    matched_person_record: Mapping[str, Any] | None = None,
    person_list_records: list[Mapping[str, Any]] | None = None,
    academic_records: list[Mapping[str, Any]] | None = None,
    matched_academic_record: Mapping[str, Any] | None = None,
    resolved_certificate_no: str = "",
    person_public_id: str = "",
    company_public_id: str = "",
    registered_unit_name: str = "",
    route_attempts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "adapter_id": HIGHWAY_MARKET_PERSONNEL_ADAPTER_ID,
        "source_family": "national_highway_construction_market_credit_system",
        "source_profile_id": "MOT-HIGHWAY-MARKET-PERSON-DESIGN",
        "entry_url": HIGHWAY_MARKET_PERSON_INDEX_URL,
        "person_list_source_url": HIGHWAY_MARKET_PERSON_LIST_URL,
        "target_company_name": _clean_text(request.get("target_company_name") or request.get("candidate_company_name")),
        "target_person_name": _clean_text(request.get("target_person_name") or request.get("responsible_person_name")),
        "target_certificate_no_optional": _clean_text(request.get("target_certificate_no") or request.get("certificate_no_optional")),
        "query_state": query_state,
        "readback_state": "READBACK_READY" if query_state.startswith("READBACK_READY") else "REVIEW_REQUIRED",
        "verification_result": "MATCHED" if query_state.startswith("READBACK_READY") else "REVIEW_REQUIRED",
        "matched_company_name_optional": registered_unit_name,
        "matched_company_public_id_optional": company_public_id,
        "person_public_id_optional": person_public_id,
        "registered_unit_name_optional": registered_unit_name,
        "resolved_certificate_no_optional": resolved_certificate_no,
        "matched_person_record": dict(matched_person_record or {}),
        "person_list_records": [dict(item) for item in list(person_list_records or [])[:10]],
        "academic_records": [dict(item) for item in list(academic_records or [])[:20]],
        "matched_academic_record": dict(matched_academic_record or {}),
        "route_attempts": [dict(item) for item in list(route_attempts or [])],
        "fail_closed_reasons": list(dict.fromkeys(fail_closed_reasons or [])),
        "query_miss_is_not_clearance": True,
        "public_only": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "manifest_stores_raw_html_or_blob": False,
    }
    payload["readback_record_sha256"] = _fingerprint(payload)
    return payload


def _pick_academic_record(records: list[Mapping[str, Any]], certificate: str) -> Mapping[str, Any]:
    if not records:
        return {}
    if certificate:
        normalized_target = _normalize_certificate(certificate)
        for record in records:
            normalized_record = _normalize_certificate(record.get("academicID"))
            if normalized_target and (
                normalized_target == normalized_record
                or normalized_target in normalized_record
                or normalized_record in normalized_target
            ):
                return record
        return {}
    sorted_records = sorted(
        records,
        key=lambda record: (
            _date_key(record.get("acaIssueDate")),
            _date_key(record.get("updateTime")),
            _clean_text(record.get("academicID")),
        ),
        reverse=True,
    )
    for record in sorted_records:
        if _clean_text(record.get("academicID")):
            return record
    return sorted_records[0]


def _limited_person_records(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_limited_person_record(record) for record in records[:10]]


def _limited_person_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": _clean_text(record.get("name")),
        "company": _clean_text(record.get("company")),
        "person_public_id": _clean_text(record.get("id") or record.get("requestid")),
        "company_public_id": _clean_text(record.get("companyId")),
        "top_college": _clean_text(record.get("topCollege")),
        "top_education": _clean_text(record.get("topEducation")),
        "top_major": _clean_text(record.get("topMajor")),
        "person_type": _clean_text(record.get("type")),
    }


def _limited_academic_records(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_limited_academic_record(record) for record in records[:20]]


def _limited_academic_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    return {
        "academic_name": _clean_text(record.get("academicName")),
        "academic_id": _clean_text(record.get("academicID")),
        "academic_major": _clean_text(record.get("academicMajor")),
        "issue_authority": _clean_text(record.get("acaIssueAuthority")),
        "issue_date": _clean_text(record.get("acaIssueDate")),
        "update_time": _clean_text(record.get("updateTime")),
    }


def _person_detail_url(person_id: str, company_id: str) -> str:
    return (
        "https://hwdms.mot.gov.cn/BMWebSite/person/base.do"
        f"?id={urllib.parse.quote(person_id)}&type=2&companyid={urllib.parse.quote(company_id)}"
    )


def _academic_source_url(person_id: str) -> str:
    return (
        "https://hwdms.mot.gov.cn/BMWebSite/person/getPersonAcademicList.do"
        f"?perId={urllib.parse.quote(person_id)}"
    )


def _text_equal(left: Any, right: Any) -> bool:
    return _clean_text(left) == _clean_text(right)


def _company_names_equivalent(left: Any, right: Any) -> bool:
    return _normalize_company(left) == _normalize_company(right)


def _normalize_company(value: Any) -> str:
    text = _clean_text(value)
    text = text.replace("（", "(").replace("）", ")")
    for marker in ("(主)", "(成)", "主:", "成:", "联合体", "牵头方", "成员方"):
        text = text.replace(marker, "")
    return re.sub(r"[\s,，;；、:：()（）]+", "", text)


def _normalize_certificate(value: Any) -> str:
    text = _clean_text(value).upper()
    return re.sub(r"[^0-9A-Z]+", "", text)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split())


def _date_key(value: Any) -> str:
    text = _clean_text(value)
    match = re.search(r"(\d{4})[-/.年]?(\d{1,2})?[-/.月]?(\d{1,2})?", text)
    if not match:
        return ""
    year = match.group(1)
    month = (match.group(2) or "1").zfill(2)
    day = (match.group(3) or "1").zfill(2)
    return f"{year}{month}{day}"


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


__all__ = [
    "HIGHWAY_MARKET_PERSONNEL_ADAPTER_ID",
    "HIGHWAY_MARKET_PERSON_INDEX_URL",
    "query_highway_market_person_title",
]
