from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from typing import Any, Callable, Mapping

from stage4_verification.provider_registry import NATURAL_RESOURCE_REGISTERED_SURVEYOR


NATURAL_RESOURCE_REGISTERED_SURVEYOR_ADAPTER_ID = "stage4.natural_resource_registered_surveyor.v1"
REGISTERED_SURVEYOR_REGISTRY_URL = "https://rsurveyor.ch.mnr.gov.cn/XZSP/Classification.html"
REGISTERED_SURVEYOR_REGISTRY_BASE_URL = "https://rsurveyor.ch.mnr.gov.cn/XZSP/"

MATCHED = "MATCHED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
PENDING_IMPLEMENTATION_REVIEW = "PENDING_IMPLEMENTATION_REVIEW"

TextGetter = Callable[[str, Mapping[str, str]], str]


def run_natural_resource_registered_surveyor_provider_task(
    payload: Mapping[str, Any],
    *,
    snapshot_html: str | None = None,
    snapshot_source_url: str = "",
    snapshot_ref: str = "",
    enable_live_entry_readback: bool = False,
    http_get_text: TextGetter | None = None,
) -> dict[str, Any]:
    """Verify a design/survey responsible person against a public registered surveyor snapshot.

    The national registered-surveyor site can be dynamic. This handler therefore
    treats local/manual public snapshots as the field-level evidence source and
    keeps live entry reads as entry diagnostics only, not as a person match.
    """

    task = dict(payload or {})
    target = _target(task)
    source_task = task.get("source_public_registry_task") if isinstance(task.get("source_public_registry_task"), Mapping) else {}
    source_entry = _source_entry(target, source_task)
    html = snapshot_html or _clean_text(task.get("manual_snapshot_html") or target.get("manual_snapshot_html"))
    source_url = snapshot_source_url or _clean_text(
        task.get("manual_snapshot_source_url")
        or target.get("manual_snapshot_source_url")
        or source_entry.get("entry_url")
    )
    snapshot_id = snapshot_ref or _clean_text(task.get("manual_snapshot_ref") or target.get("manual_snapshot_ref"))
    snapshot_type = _clean_text(task.get("manual_snapshot_type") or target.get("manual_snapshot_type") or "HTML_OR_TEXT")

    if html:
        return _result_from_snapshot(
            task,
            target=target,
            source_entry=source_entry,
            html=html,
            source_url=source_url,
            snapshot_ref=snapshot_id,
            snapshot_type=snapshot_type,
        )

    if enable_live_entry_readback:
        return _entry_readback_only_result(
            task,
            target=target,
            source_entry=source_entry,
            http_get_text=http_get_text,
        )

    return _pending_result(
        task,
        target=target,
        source_entry=source_entry,
        reason="registered_surveyor_public_snapshot_or_authorized_live_adapter_missing",
        next_action="provide_public_snapshot_or_enable_authorized_registered_surveyor_live_adapter",
    )


def parse_registered_surveyor_snapshot(html: str, target: Mapping[str, Any]) -> dict[str, Any]:
    text = _html_or_json_to_text(html)
    rows = _candidate_rows(html, text)
    person = _clean_text(target.get("responsible_person_name"))
    cert = _clean_text(target.get("certificate_no_optional") or target.get("certificate_no"))
    companies = _target_companies(target)

    parsed_records: list[dict[str, Any]] = []
    for row in rows:
        row_text = _clean_text(row)
        if not row_text:
            continue
        if person and person not in row_text and not (cert and cert in row_text):
            continue
        parsed_records.append(_record_from_row(row_text, target_companies=companies, target_person=person, target_cert=cert))

    if not parsed_records and person and person in text:
        parsed_records.append(_record_from_row(_clip(text, 1600), target_companies=companies, target_person=person, target_cert=cert))

    best = _best_record(parsed_records, person=person, companies=companies, cert=cert)
    return {
        "snapshot_text_sha256": _sha256(text),
        "redacted_text_probe": _clip(_redact_sensitive(text), 600),
        "parsed_public_registry_records": parsed_records[:10],
        "best_record": best,
        "target_person_name": person,
        "target_companies": companies,
        "target_certificate_no_optional": cert,
        "record_count": len(parsed_records),
        "match_assessment": _match_assessment(best, person=person, companies=companies, cert=cert),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _result_from_snapshot(
    task: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    source_entry: Mapping[str, Any],
    html: str,
    source_url: str,
    snapshot_ref: str,
    snapshot_type: str,
) -> dict[str, Any]:
    parsed = parse_registered_surveyor_snapshot(html, target)
    assessment = dict(parsed.get("match_assessment") or {})
    matched = assessment.get("verification_result") == MATCHED
    best = dict(parsed.get("best_record") or {})
    identity_fields = {
        "person_name": best.get("person_name") or target.get("responsible_person_name", ""),
        "registered_unit_name": best.get("registered_unit_name", ""),
        "certificate_no_or_registration_no": best.get("certificate_no_or_registration_no", ""),
        "certificate_type": best.get("certificate_type", "注册测绘师" if best else ""),
        "registration_status": best.get("registration_status", ""),
        "source_url_or_snapshot_id": snapshot_ref or source_url,
    }
    return {
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": task.get("provider_role") or "registered_surveyor_person_company_certificate_identity",
        "adapter_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR_ADAPTER_ID,
        "provider_result_state": "READBACK_READY",
        "readback_state": "READBACK_READY",
        "verification_result": MATCHED if matched else REVIEW_REQUIRED,
        "identity_resolution_state": "MATCHED_PERSON_COMPANY" if matched else REVIEW_REQUIRED,
        "target": target,
        "identity_fields": identity_fields,
        "public_registry_readback": {
            "source_entry": dict(source_entry),
            "source_url": source_url,
            "snapshot_ref": snapshot_ref,
            "snapshot_type": snapshot_type or "HTML_OR_TEXT",
            "snapshot_html_sha256": _sha256(html),
            "snapshot_text_sha256": parsed.get("snapshot_text_sha256"),
            "redacted_text_probe": parsed.get("redacted_text_probe", ""),
            "parsed_public_registry_records": parsed.get("parsed_public_registry_records", []),
            "best_record": best,
        },
        "source_refs": [
            {
                "source_url": source_url,
                "source_snapshot_id": snapshot_ref,
                "source_role": "registered_surveyor_public_snapshot",
                "public_visible": True,
            }
        ],
        "failure_reasons": [],
        "review_reasons": _dedupe_strings(assessment.get("review_reasons")),
        "policy": _policy(),
        "customer_sellable_evidence_ready": False,
    }


def _entry_readback_only_result(
    task: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    source_entry: Mapping[str, Any],
    http_get_text: TextGetter | None,
) -> dict[str, Any]:
    entry_url = _clean_text(source_entry.get("entry_url")) or REGISTERED_SURVEYOR_REGISTRY_URL
    if http_get_text is None:
        return _pending_result(
            task,
            target=target,
            source_entry=source_entry,
            reason="registered_surveyor_live_entry_http_getter_missing",
            next_action="provide_public_snapshot_or_wire_authorized_browser_adapter",
        )
    try:
        text = str(http_get_text(entry_url, {"Accept": "text/html,application/xhtml+xml"}))
    except Exception as exc:  # pragma: no cover - defensive boundary
        return _fail_closed_result(
            task,
            target=target,
            source_entry=source_entry,
            reason=f"registered_surveyor_entry_readback_error:{type(exc).__name__}",
        )
    return {
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": task.get("provider_role") or "registered_surveyor_person_company_certificate_identity",
        "adapter_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR_ADAPTER_ID,
        "provider_result_state": PENDING_IMPLEMENTATION_REVIEW,
        "readback_state": "ENTRY_READBACK_READY_PERSON_SEARCH_NOT_EXECUTED",
        "verification_result": REVIEW_REQUIRED,
        "identity_resolution_state": REVIEW_REQUIRED,
        "target": target,
        "identity_fields": {},
        "public_registry_readback": {
            "source_entry": dict(source_entry),
            "source_url": entry_url,
            "entry_html_sha256": _sha256(text),
            "redacted_text_probe": _clip(_redact_sensitive(_html_or_json_to_text(text)), 600),
        },
        "source_refs": [{"source_url": entry_url, "source_role": "registered_surveyor_entry_page", "public_visible": True}],
        "failure_reasons": [],
        "review_reasons": ["entry_reachability_is_not_field_success", "registered_surveyor_person_search_runtime_not_executed"],
        "next_action": "provide_person_result_public_snapshot_or_wire_authorized_browser_adapter",
        "policy": _policy(),
        "customer_sellable_evidence_ready": False,
    }


def _pending_result(
    task: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    source_entry: Mapping[str, Any],
    reason: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": task.get("provider_role") or "registered_surveyor_person_company_certificate_identity",
        "adapter_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR_ADAPTER_ID,
        "provider_result_state": PENDING_IMPLEMENTATION_REVIEW,
        "readback_state": "PUBLIC_SNAPSHOT_OR_RUNTIME_ADAPTER_REQUIRED",
        "verification_result": REVIEW_REQUIRED,
        "identity_resolution_state": REVIEW_REQUIRED,
        "target": target,
        "identity_fields": {},
        "public_registry_readback": {"source_entry": dict(source_entry)},
        "source_refs": [],
        "failure_reasons": [],
        "review_reasons": [reason],
        "next_action": next_action,
        "policy": _policy(),
        "customer_sellable_evidence_ready": False,
    }


def _fail_closed_result(
    task: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    source_entry: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": task.get("provider_role") or "registered_surveyor_person_company_certificate_identity",
        "adapter_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR_ADAPTER_ID,
        "provider_result_state": "FAIL_CLOSED_QUERY_ERROR",
        "readback_state": "FAIL_CLOSED_QUERY_ERROR",
        "verification_result": REVIEW_REQUIRED,
        "identity_resolution_state": REVIEW_REQUIRED,
        "target": target,
        "identity_fields": {},
        "public_registry_readback": {"source_entry": dict(source_entry)},
        "source_refs": [],
        "failure_reasons": [reason],
        "review_reasons": ["registered_surveyor_public_registry_readback_failed_no_clearance_claim"],
        "policy": _policy(),
        "customer_sellable_evidence_ready": False,
    }


def _match_assessment(
    record: Mapping[str, Any],
    *,
    person: str,
    companies: list[str],
    cert: str,
) -> dict[str, Any]:
    if not record:
        return {
            "verification_result": REVIEW_REQUIRED,
            "review_reasons": ["registered_surveyor_person_not_found_in_snapshot"],
        }
    row_text = str(record.get("row_text") or "")
    person_matched = bool(person and person in row_text)
    company_matched = any(company and company in row_text for company in companies)
    cert_matched = not cert or cert in row_text
    reasons: list[str] = []
    if not person_matched:
        reasons.append("registered_surveyor_person_name_not_matched")
    if not company_matched:
        reasons.append("registered_surveyor_registered_unit_not_matched_to_candidate_company")
    if cert and not cert_matched:
        reasons.append("registered_surveyor_certificate_no_not_matched")
    if person_matched and not company_matched:
        reasons.append("name_only_is_not_final_proof")
    return {
        "verification_result": MATCHED if person_matched and company_matched and cert_matched else REVIEW_REQUIRED,
        "person_name_matched": person_matched,
        "registered_unit_matched": company_matched,
        "certificate_no_matched_or_not_required": cert_matched,
        "review_reasons": reasons,
    }


def _record_from_row(
    row_text: str,
    *,
    target_companies: list[str],
    target_person: str,
    target_cert: str,
) -> dict[str, Any]:
    registered_unit = next((company for company in target_companies if company and company in row_text), "")
    return {
        "person_name": target_person if target_person and target_person in row_text else _label_value(row_text, ("姓名", "注册人员")),
        "registered_unit_name": registered_unit
        or _label_value(row_text, ("注册单位", "聘用单位", "执业单位", "所在单位", "单位名称")),
        "certificate_no_or_registration_no": target_cert if target_cert and target_cert in row_text else _certificate_from_row(row_text),
        "certificate_type": "注册测绘师" if "注册测绘师" in row_text else _label_value(row_text, ("资格名称", "证书类型", "注册类别")),
        "registration_status": _status_from_row(row_text),
        "row_text": _clip(_redact_sensitive(row_text), 900),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _best_record(records: list[Mapping[str, Any]], *, person: str, companies: list[str], cert: str) -> dict[str, Any]:
    if not records:
        return {}

    def score(record: Mapping[str, Any]) -> tuple[int, int, int, int]:
        text = str(record.get("row_text") or "")
        return (
            int(bool(person and person in text)),
            int(any(company and company in text for company in companies)),
            int(bool(cert and cert in text)),
            len(text),
        )

    return dict(sorted(records, key=score, reverse=True)[0])


def _candidate_rows(raw: str, plain_text: str) -> list[str]:
    rows: list[str] = []
    for match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", raw or "", flags=re.IGNORECASE | re.DOTALL):
        rows.append(_html_or_json_to_text(match.group(1)))
    if not rows:
        rows = [line.strip() for line in re.split(r"[\r\n]+", plain_text) if line.strip()]
    if len(rows) <= 1 and len(plain_text) > 0:
        chunks = re.split(r"(?=姓名|注册单位|聘用单位|执业单位|注册证号|证书编号|注册测绘师)", plain_text)
        rows = _dedupe_strings([plain_text, *[chunk.strip() for chunk in chunks if chunk.strip()]])
    return rows


def _html_or_json_to_text(value: Any) -> str:
    text = str(value or "")
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return _clean_text(_flatten_json(json.loads(stripped)))
        except json.JSONDecodeError:
            pass
    text = re.sub(r"(?i)<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?i)</(?:td|th|tr|p|li|div|span|br|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(unescape(text))


def _flatten_json(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_flatten_json(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_json(item) for item in value)
    return str(value or "")


def _label_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^\s,，;；|｜]+)", text)
        if match:
            return match.group(1).strip()
    return ""


def _certificate_from_row(text: str) -> str:
    labelled = _label_value(text, ("注册证号", "注册编号", "证书编号", "资格证书号", "证书号"))
    if labelled:
        return labelled
    for pattern in (
        r"(?:CH|RS|国测|测绘|粤测绘|京测绘|沪测绘|浙测绘|苏测绘)[A-Za-z0-9\-第字号]{4,}",
        r"\b[A-Z]{1,4}\d[A-Za-z0-9\-]{5,}\b",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return ""


def _status_from_row(text: str) -> str:
    for value in ("有效", "准予注册", "初始注册", "延续注册", "变更注册", "注销", "失效", "撤销"):
        if value in text:
            return value
    return _label_value(text, ("注册状态", "状态"))


def _target(task: Mapping[str, Any]) -> dict[str, Any]:
    target = task.get("target") if isinstance(task.get("target"), Mapping) else {}
    out = dict(target)
    source_task = task.get("source_public_registry_task") if isinstance(task.get("source_public_registry_task"), Mapping) else {}
    query_fields = source_task.get("query_fields") if isinstance(source_task.get("query_fields"), Mapping) else {}
    out.setdefault("candidate_company_name", query_fields.get("registered_unit_or_candidate_company", ""))
    out.setdefault("responsible_person_name", query_fields.get("person_name", ""))
    out.setdefault("certificate_no_optional", query_fields.get("certificate_no_optional", ""))
    out.setdefault("candidate_group_members", query_fields.get("candidate_group_members", []))
    return out


def _source_entry(target: Mapping[str, Any], source_task: Mapping[str, Any]) -> dict[str, Any]:
    source_entry = source_task.get("source_entry") if isinstance(source_task.get("source_entry"), Mapping) else {}
    target_entry = target.get("source_entry") if isinstance(target.get("source_entry"), Mapping) else {}
    return {
        "source_name": "注册测绘师注册管理系统/注册人员查询",
        "source_family": "natural_resource_registered_surveyor_public_registry",
        "entry_url": REGISTERED_SURVEYOR_REGISTRY_URL,
        "fallback_entry_url": REGISTERED_SURVEYOR_REGISTRY_BASE_URL,
        **dict(source_entry),
        **dict(target_entry),
    }


def _target_companies(target: Mapping[str, Any]) -> list[str]:
    values = [target.get("candidate_company_name")]
    values.extend(_list(target.get("candidate_group_members")))
    return _dedupe_strings(values)


def _policy() -> dict[str, Any]:
    return {
        "not_found_is_review_not_negative_fact": True,
        "no_name_only_final_proof": True,
        "entry_reachability_is_not_field_success": True,
        "flow08_dossier_is_current_binding_only_not_public_registration_proof": True,
        "public_only": True,
        "no_legal_conclusion": True,
    }


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _dedupe_strings(values: Any) -> list[str]:
    raw = values if isinstance(values, list | tuple | set) else [values]
    out: list[str] = []
    for value in raw:
        text = _clean_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _redact_sensitive(text: str) -> str:
    text = re.sub(r"\b\d{6}(?:19|20)\d{2}\d{2}\d{2}\d{3}[\dXx]\b", "[ID_CARD_REDACTED]", text)
    text = re.sub(r"\b\d{11}\b", "[PHONE_REDACTED]", text)
    return text


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


def _sha256(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


__all__ = [
    "NATURAL_RESOURCE_REGISTERED_SURVEYOR_ADAPTER_ID",
    "REGISTERED_SURVEYOR_REGISTRY_URL",
    "parse_registered_surveyor_snapshot",
    "run_natural_resource_registered_surveyor_provider_task",
]
