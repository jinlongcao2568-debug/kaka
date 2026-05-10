from __future__ import annotations

import hashlib
import json
import re
import time
from html import unescape
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage2_ingestion.service import Stage2Service
from stage3_parsing.ocr_text import extract_pdf_text_with_ocr
from stage3_parsing.service import Stage3Service
from storage.db import PersistedOperatorAction
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.operator_action_repo import OperatorActionRepository


REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID = "operator-real-candidate-stage2-captures"
REAL_CANDIDATE_STAGE2_CAPTURE_MODE = "REAL_PUBLIC_CANDIDATE_DETAIL_CAPTURE"
DEFAULT_DETAIL_CAPTURE_LIMIT: int | None = None
DEFAULT_ATTACHMENT_CAPTURE_LIMIT: int | None = None
DEFAULT_DETAIL_CAPTURE_TIME_BUDGET_SECONDS = 90.0
SECTION_MARKERS = {
    "qualification_section_found": ("资格条件", "资格要求", "投标人资格", "供应商资格", "投标人资格要求"),
    "scoring_section_found": ("评分办法", "评标办法", "评分标准", "综合评分", "综合评估法"),
    "technical_section_found": (
        "技术参数",
        "技术要求",
        "采购需求",
        "服务要求",
        "技术标准和要求",
        "设计任务书",
        "发包人要求",
        "设计要求",
    ),
}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    basis = str(candidate.get("candidate_key") or candidate.get("source_url") or candidate.get("notice_id") or "")
    return hashlib.sha1(basis.lower().encode("utf-8")).hexdigest()[:24]


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(text).split())


def _extract_html_element_by_id(value: Any, element_id: str) -> str:
    text = str(value or "")
    pattern = re.compile(
        r"<(?P<tag>[a-zA-Z0-9]+)\b(?=[^>]*\bid\s*=\s*['\"]"
        + re.escape(element_id)
        + r"['\"])[^>]*>(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group("body") if match else ""


def _preferred_detail_text(candidate: Mapping[str, Any], readback_text: str) -> tuple[str, str]:
    source_profile_id = str(candidate.get("source_profile_id") or "")
    if source_profile_id == "SICHUAN-GGZY-TRANSACTION-INFO":
        news_text = _clean_text(_extract_html_element_by_id(readback_text, "newsText"))
        if len(news_text) >= 120:
            return news_text, "sichuan_news_text"
    return _clean_text(readback_text), "full_detail_readback"


def _guangzhou_ywtb_download_diagnostics(detail_carrier: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = dict(detail_carrier.get("attachment_discovery_diagnostics") or {})
    rendered = diagnostics.get("guangzhou_ywtb_rendered")
    static = diagnostics.get("guangzhou_ywtb")
    if isinstance(rendered, Mapping) and rendered.get("guangzhou_ywtb_download_discovery_state"):
        return dict(rendered)
    if isinstance(static, Mapping):
        return dict(static)
    return {}


def _guangzhou_ywtb_failure_from_state(state: str) -> str:
    mapping = {
        "NO_PUBLIC_DOWNLOAD_ENDPOINT": "guangzhou_public_download_endpoint_missing",
        "LOGIN_OR_CA_REQUIRED": "guangzhou_login_or_ca_required",
        "CHALLENGE_REQUIRED": "guangzhou_challenge_required",
        "SCRIPT_ENDPOINT_UNRESOLVED": "guangzhou_script_endpoint_unresolved",
        "SCRIPT_ENDPOINT_CAPTURED": "guangzhou_script_endpoint_captured_without_download_url",
        "EPPOINT_CHALLENGE_DETECTED": "guangzhou_epoint_challenge_detected",
        "EPPOINT_CHALLENGE_FAILED": "guangzhou_epoint_challenge_failed",
    }
    return mapping.get(str(state or ""), "")


def _guangzhou_ywtb_attachment_challenge_state(attachment_captures: list[Mapping[str, Any]]) -> tuple[str, list[str]]:
    attempted = False
    failed = False
    detected = False
    states: list[str] = []
    for capture in attachment_captures:
        if not isinstance(capture, Mapping):
            continue
        state = str(capture.get("automated_challenge_resolution_state") or "")
        blocker = str(capture.get("attachment_blocker_reason") or "")
        taxonomy = " ".join(str(item or "") for item in list(capture.get("attachment_failure_taxonomy") or []))
        degraded = " ".join(str(item or "") for item in list(capture.get("attachment_degraded_reasons") or []))
        if state:
            states.append(state)
        if capture.get("automated_challenge_resolution_attempted") or state:
            attempted = True
        if state == "RESOLVED_AND_SNAPSHOT_CAPTURED" and capture.get("attachment_snapshot_id_optional"):
            return "EPPOINT_CHALLENGE_RESOLVED", states
        if state.startswith("FAILED"):
            failed = True
        challenge_text = f"{blocker} {taxonomy} {degraded}".lower()
        if any(token in challenge_text for token in ("captcha", "pageverify", "verification", "blockpuzzle")):
            detected = True
    if attempted and failed:
        return "EPPOINT_CHALLENGE_FAILED", states
    if detected:
        return "EPPOINT_CHALLENGE_DETECTED", states
    return "", states


def _clip_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[TRUNCATED]"


def _section_flags_for_text(value: Any) -> dict[str, Any]:
    text = str(value or "")
    flags = {
        field_name: any(marker in text for marker in markers)
        for field_name, markers in SECTION_MARKERS.items()
    }
    found = [field_name for field_name, present in flags.items() if present]
    if len(found) == len(SECTION_MARKERS):
        state = "SECTION_COMPLETE"
    elif found == ["qualification_section_found"]:
        state = "SECTION_PARTIAL_QUALIFICATION_ONLY"
    elif found:
        state = "SECTION_PARTIAL"
    else:
        state = "SECTION_NOT_FOUND"
    return {**flags, "section_analysis_state": state}


def _file_parse_attribution(
    *,
    project_id: str,
    snapshot_id: str,
    source_url: str,
    file_role: str,
    parse_state: str,
    text: str,
) -> dict[str, Any]:
    cleaned = _clean_text(text)
    return {
        "project_id": str(project_id or ""),
        "snapshot_id": str(snapshot_id or ""),
        "source_url": str(source_url or ""),
        "file_role": str(file_role or ""),
        "parse_state": str(parse_state or ""),
        "section_flags": _section_flags_for_text(cleaned),
        "text_sha256": hashlib.sha256(cleaned.encode("utf-8")).hexdigest() if cleaned else "",
        "text_probe": _clip_text(cleaned),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _decode_snapshot_text(readback: Mapping[str, Any]) -> str:
    data = readback.get("bytes")
    if not isinstance(data, (bytes, bytearray)):
        return ""
    for encoding in ("utf-8", "gb18030"):
        try:
            return bytes(data).decode(encoding)
        except UnicodeDecodeError:
            continue
    return bytes(data).decode("utf-8", errors="replace")


def _extract_pdf_text(data: bytes) -> tuple[str, str]:
    if not data.startswith(b"%PDF"):
        return "", "NOT_PDF"
    result = extract_pdf_text_with_ocr(data)
    state = result.state
    if result.text and result.warnings:
        state = f"{state}:{':'.join(result.warnings)}"
    return result.text, state


def _attachment_parsed_field_text(parser_carrier: Mapping[str, Any]) -> str:
    values: list[str] = []
    audit = dict(parser_carrier.get("parser_audit") or {})
    markitdown_probe = _clean_text(audit.get("markitdown_text_probe"))
    if markitdown_probe:
        values.append(markitdown_probe)
    for field in list(parser_carrier.get("parsed_fields") or []):
        if not isinstance(field, Mapping):
            continue
        value = _clean_text(field.get("field_value_optional"))
        if not value:
            continue
        name = _clean_text(field.get("field_name"))
        values.append(f"{name}: {value}" if name else value)
        raw_text = _clean_text(field.get("raw_text"))
        if raw_text and raw_text != value:
            values.append(raw_text)
    return "\n".join(_dedupe_texts(values))


def _attachment_snapshot_ref(
    *,
    attachment: Mapping[str, Any],
    snapshot_id: str,
    parse_state: str,
    attachment_type: str,
    parse_error_taxonomy: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "attachment_url": str(attachment.get("attachment_url") or ""),
        "attachment_filename": str(attachment.get("attachment_filename") or ""),
        "content_type": str(attachment.get("content_type") or ""),
        "parse_state": parse_state,
        "attachment_type": attachment_type,
        "attachment_role_type": str(
            attachment.get("attachment_role_type")
            or _infer_attachment_role_type(attachment)
        ),
        "parse_error_taxonomy": list(parse_error_taxonomy or []),
    }


def _infer_attachment_role_type(attachment: Mapping[str, Any]) -> str:
    text = " ".join(
        str(attachment.get(key) or "")
        for key in (
            "attachment_link_text",
            "attachment_filename",
            "attachment_url",
            "content_type",
        )
    ).lower()
    if any(keyword in text for keyword in ("补遗", "澄清", "答疑", "更正", "变更")):
        return "CLARIFICATION_OR_ADDENDUM"
    if any(keyword in text for keyword in ("评标报告", "定标报告", "评审报告")):
        return "EVALUATION_REPORT"
    if any(
        keyword in text
        for keyword in (
            "中标候选",
            "成交候选",
            "候选人",
            "中标公告",
            "成交公告",
            "中标结果",
            "中标信息",
            "成交结果",
            "结果公告",
            "结果文件",
        )
    ):
        return "CANDIDATE_OR_AWARD_NOTICE"
    if any(keyword in text for keyword in ("图纸", "清单", "工程量", "控制价", "cad", "bill")):
        return "DRAWING_OR_BILL_OF_QUANTITIES"
    if any(
        keyword in text
        for keyword in (
            "招标文件",
            "采购文件",
            "磋商文件",
            "谈判文件",
            "询价文件",
            "资格要求",
            "招标公告",
        )
    ):
        return "TENDER_DOCUMENT"
    return "UNKNOWN_ATTACHMENT_ROLE"


def _attachment_format_type(attachment: Mapping[str, Any]) -> str:
    declared = str(attachment.get("attachment_type") or "").strip()
    if declared:
        return declared
    text = " ".join(
        str(attachment.get(key) or "")
        for key in ("attachment_filename", "attachment_url", "content_type")
    ).lower()
    if "pdf" in text:
        return "PDF"
    if ".docx" in text or "wordprocessingml" in text:
        return "WORD_DOCX"
    if ".doc" in text:
        return "WORD_DOC"
    if ".xlsx" in text or "spreadsheetml" in text:
        return "EXCEL_XLSX"
    if ".xls" in text:
        return "EXCEL_XLS"
    if ".zip" in text or "zip" in text:
        return "ZIP"
    if "html" in text or ".htm" in text:
        return "HTML"
    return "UNKNOWN_ATTACHMENT"


def _download_archive_manifest_summary(
    *,
    capture: Mapping[str, Any],
    attachment_snapshot_refs: list[Mapping[str, Any]],
    attachment_captures: list[Mapping[str, Any]],
    attachment_parse_states_by_snapshot: Mapping[str, str],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    detail_snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
    if detail_snapshot_id:
        detail_failure_reasons = [
            str(item)
            for item in list(capture.get("detail_degraded_reasons", []) or [])
            if str(item or "").strip()
        ]
        items.append(
            {
                "item_role": "DETAIL_PAGE",
                "snapshot_id": detail_snapshot_id,
                "url": str(capture.get("source_url") or ""),
                "filename": "",
                "content_type": str(capture.get("detail_content_type") or ""),
                "file_format_type": "HTML",
                "attachment_role_type": "DETAIL_PAGE",
                "parse_state": str(capture.get("stage3_parse_state") or "NOT_RUN"),
                "failure_reasons": detail_failure_reasons,
            }
        )

    refs_by_snapshot = {
        str(ref.get("snapshot_id") or ""): dict(ref)
        for ref in attachment_snapshot_refs
        if isinstance(ref, Mapping) and str(ref.get("snapshot_id") or "")
    }
    refs_by_url = {
        str(ref.get("attachment_url") or ""): dict(ref)
        for ref in attachment_snapshot_refs
        if isinstance(ref, Mapping) and str(ref.get("attachment_url") or "")
    }
    for attachment in attachment_captures:
        if not isinstance(attachment, Mapping):
            continue
        snapshot_id = str(attachment.get("attachment_snapshot_id_optional") or "")
        attachment_url = str(attachment.get("attachment_url") or "")
        ref = refs_by_snapshot.get(snapshot_id) or refs_by_url.get(attachment_url) or {}
        failure_reasons = [
            str(item)
            for item in list(attachment.get("attachment_degraded_reasons", []) or [])
            if str(item or "").strip()
        ]
        failure_reasons.extend(
            str(item)
            for item in list(attachment.get("attachment_failure_taxonomy", []) or [])
            if str(item or "").strip()
        )
        for key in ("attachment_blocker_class", "attachment_blocker_reason", "attachment_capture_status"):
            value = str(attachment.get(key) or "")
            if value and not _attachment_status_is_success_or_neutral(value):
                failure_reasons.append(value)
        if snapshot_id and not ref:
            failure_reasons.append("attachment_snapshot_readback_missing")
        role_type = str(
            ref.get("attachment_role_type")
            or attachment.get("attachment_role_type")
            or _infer_attachment_role_type(attachment)
        )
        items.append(
            {
                "item_role": "ATTACHMENT",
                "snapshot_id": snapshot_id,
                "url": attachment_url,
                "filename": str(attachment.get("attachment_filename") or ""),
                "content_type": str(attachment.get("content_type") or ""),
                "file_format_type": str(
                    ref.get("attachment_type")
                    or attachment.get("attachment_type")
                    or _attachment_format_type(attachment)
                ),
                "attachment_role_type": role_type,
                "parse_state": str(
                    ref.get("parse_state")
                    or attachment_parse_states_by_snapshot.get(snapshot_id)
                    or (
                        "NOT_CAPTURED"
                        if not snapshot_id
                        else "ATTACHMENT_SNAPSHOT_READBACK_MISSING"
                        if snapshot_id and not ref
                        else "NOT_RUN"
                    )
                ),
                "parse_error_taxonomy": list(ref.get("parse_error_taxonomy") or attachment.get("parse_error_taxonomy") or []),
                "failure_reasons": list(dict.fromkeys(failure_reasons)),
            }
        )

    quality_summary = _download_archive_quality_summary(items)
    return {
        "manifest_state": "READY" if items else "EMPTY",
        "manifest_quality_state": quality_summary["manifest_quality_state"],
        "quality_reasons": quality_summary["quality_reasons"],
        "quality_counts": quality_summary["quality_counts"],
        "item_count": len(items),
        "items": items,
        "source": "stage2_detail_and_attachment_capture_summary",
        "customer_visible": False,
    }


def _download_archive_quality_summary(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    counts = {
        "unknown_attachment_format_count": 0,
        "unknown_attachment_role_count": 0,
        "not_captured_count": 0,
        "ocr_required_count": 0,
        "ocr_engine_unavailable_count": 0,
        "parse_review_count": 0,
        "failure_reason_count": 0,
    }
    for item in items:
        item_role = str(item.get("item_role") or "")
        parse_state = str(item.get("parse_state") or "")
        file_format = str(item.get("file_format_type") or "")
        role_type = str(item.get("attachment_role_type") or "")
        failure_reasons = [str(reason) for reason in list(item.get("failure_reasons") or []) if str(reason)]
        parse_errors = [str(reason) for reason in list(item.get("parse_error_taxonomy") or []) if str(reason)]
        joined = " ".join([parse_state, file_format, role_type, *failure_reasons, *parse_errors])
        if item_role == "ATTACHMENT" and file_format in {"", "UNKNOWN_ATTACHMENT"}:
            counts["unknown_attachment_format_count"] += 1
            reasons.append("unknown_attachment_format")
        if item_role == "ATTACHMENT" and role_type in {"", "UNKNOWN_ATTACHMENT_ROLE"}:
            counts["unknown_attachment_role_count"] += 1
            reasons.append("unknown_attachment_role")
        if parse_state == "NOT_CAPTURED":
            counts["not_captured_count"] += 1
            reasons.append("attachment_not_captured")
        if "ATTACHMENT_SNAPSHOT_READBACK_MISSING" in joined or "MISSING_MANIFEST" in joined or "MISSING_OBJECT" in joined:
            counts["parse_review_count"] += 1
            reasons.append("attachment_snapshot_readback_missing")
        if "OCR_REQUIRED" in joined:
            counts["ocr_required_count"] += 1
            reasons.append("ocr_required")
        if "OCR_ENGINE_UNAVAILABLE" in joined:
            counts["ocr_engine_unavailable_count"] += 1
            reasons.append("ocr_engine_unavailable")
        if (
            parse_state
            and not parse_state.startswith("PARSED")
            and "TEXT_EXTRACTED" not in parse_state
            and parse_state not in {"NOT_RUN", "UNKNOWN"}
        ):
            counts["parse_review_count"] += 1
            reasons.append(f"parse_state_review={parse_state}")
        if failure_reasons:
            counts["failure_reason_count"] += len(failure_reasons)
            reasons.append("capture_failure_or_blocker_present")
    deduped_reasons = list(dict.fromkeys(reasons))
    return {
        "manifest_quality_state": "REVIEW_REQUIRED" if deduped_reasons else "READY",
        "quality_reasons": deduped_reasons,
        "quality_counts": counts,
    }


def _notice_version_chain_state(
    *,
    detail_snapshot_id: str,
    link_count: int,
    snapshot_count: int,
    attachment_role_types: list[str],
) -> str:
    if not detail_snapshot_id:
        return "DETAIL_MISSING_REVIEW_REQUIRED"
    if link_count == 0:
        return "DETAIL_ONLY"
    if snapshot_count < link_count:
        return "VERSION_REVIEW_REQUIRED"
    if "CLARIFICATION_OR_ADDENDUM" in attachment_role_types:
        return "CLARIFICATION_OR_ADDENDUM_PRESENT"
    return "ATTACHMENTS_LINKED"


def _qualification_text_candidate_blocks(text: str) -> list[str]:
    normalized = _clean_text(text)
    if not normalized:
        return []
    pattern = re.compile(
        r"[^。；;\n\r]{0,80}(?:项目负责人|施工负责人|勘察负责人|设计负责人|咨询负责人|拟派|资格|证书|注册|建造师|注册土木工程师|注册建筑师|注册结构工程师|高级工程师|安全生产考核|安全\s*B|B\s*类)[^。；;\n\r]{0,120}",
        re.I,
    )
    return [_clean_text(match.group(0)) for match in pattern.finditer(normalized) if _clean_text(match.group(0))]


def _dedupe_texts(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _parser_fields_by_name(parser_carrier: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for field in list(parser_carrier.get("parsed_fields", []) or []):
        if not isinstance(field, Mapping):
            continue
        name = str(field.get("field_name") or "")
        if name and name not in fields:
            fields[name] = dict(field)
    return fields


def _field_value(fields: Mapping[str, Mapping[str, Any]], *names: str) -> str:
    for name in names:
        field = fields.get(name)
        if not field:
            continue
        value = str(field.get("field_value_optional") or "").strip()
        if value:
            return value
    return ""


def _extract_amount(text: str) -> tuple[float | None, str]:
    normalized = text.replace(",", "")
    labeled_patterns = (
        r"(?:中标|成交|预算|采购|合同|估算|招标控制价|最高限价)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)\s*(?:人民币|中标|成交|预算|合同|估算)",
    )
    for pattern in labeled_patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        number = _as_float(match.group(1))
        if number is None:
            continue
        unit = match.group(2)
        return (number * 10000 if unit in {"万", "万元"} else number), "DETAIL_TEXT"
    return None, "DETAIL_TEXT_NOT_FOUND"


def _infer_notice_stage(text: str, fallback: str) -> str:
    if any(token in text for token in ("中标候选人", "成交候选人", "候选人公示")):
        return "candidate_notice"
    if any(token in text for token in ("中标公告", "成交公告", "结果公告", "中标结果", "成交结果")):
        return "award_result"
    if any(token in text for token in ("更正公告", "变更公告", "澄清公告")):
        return "correction_notice"
    if any(token in text for token in ("招标公告", "采购公告", "竞争性谈判公告", "磋商公告")):
        return "tender_notice"
    return str(fallback or "procurement_notice")


def _extract_candidate_company(text: str) -> tuple[str, str]:
    summary_table = _extract_candidate_summary_table(text)
    if summary_table.get("candidate_company"):
        return str(summary_table["candidate_company"]), str(summary_table["parse_state"])
    unit_name_section = _section_between(
        text,
        start_tokens=("单位名称", "投标人名称", "候选人名称"),
        end_tokens=("公告附件", "相关附件", "异议受理", "公示时间", "公示结束", "附件"),
    )
    if unit_name_section:
        company = _first_company_like_text(unit_name_section)
        if company:
            return company, "DETAIL_TEXT_UNIT_NAME_TABLE"
    candidate_section = _section_between(
        text,
        start_tokens=("第一中标候选人", "第一成交候选人", "第一候选人"),
        end_tokens=("第二中标候选人", "第二成交候选人", "第二候选人", "中标候选人响应招标文件要求的资格能力条件"),
    )
    if candidate_section:
        normalized_section = re.sub(
            r"(?:投标报价|报价|评标情况|质量承诺|工期|资质资格|业绩|资格能力条件|拟派项目负责人姓名|项目负责人姓名|注册编号|注册编\s*号)",
            " ",
            candidate_section,
        )
        company = _first_company_like_text(normalized_section)
        if company:
            return company, "DETAIL_TEXT_CANDIDATE_TABLE"
    patterns = (
        r"(?:中标|成交)\s*(?:供应商|单位|人|候选人)(?:名称)?[:：\s]+([^，。,；;\n\r]{2,80})",
        r"第一(?:中标|成交)?候选人[:：\s]+([^，。,；;\n\r]{2,80})",
        r"(?:供应商名称|中标人名称|成交人名称)[:：\s]+([^，。,；;\n\r]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = _clean_company_value(_clean_text(match.group(1)))
        if value:
            return value, "DETAIL_TEXT"
    return "", "DETAIL_TEXT_NOT_FOUND"


def _section_between(text: str, *, start_tokens: tuple[str, ...], end_tokens: tuple[str, ...]) -> str:
    start_positions = [text.find(token) for token in start_tokens if text.find(token) >= 0]
    if not start_positions:
        return ""
    start = min(start_positions)
    end_candidates = [
        text.find(token, start + 1)
        for token in end_tokens
        if text.find(token, start + 1) >= 0
    ]
    end = min(end_candidates) if end_candidates else min(len(text), start + 900)
    return text[start:end]


def _first_company_like_text(text: str) -> str:
    pattern = _company_like_pattern()
    for match in re.finditer(pattern, text):
        value = _clean_company_value(_clean_text(match.group(1)))
        if value and not any(
            token in value
            for token in (
                "投标报价",
                "质量承诺",
                "工期",
                "资质资格",
                "项目负责人",
                "资格要求",
                "可由",
                "须无",
                "截标",
                "系统上所报",
            )
        ):
            return value
    return ""


def _company_like_pattern() -> str:
    company_suffix = (
        r"设计院\s*有限(?:\s*责任)?\s*公司",
        r"研究院\s*有限(?:\s*责任)?\s*公司",
        r"有限\s*责任\s*公司",
        r"股份\s*有限公司",
        r"集团\s*有限公司",
        r"工程建设\s*有限公司",
        r"建设管理\s*有限公司",
        r"工程咨询\s*有限公司",
        r"监理\s*有限公司",
        r"有限\s*公司",
        r"集团",
        r"设计院(?!\s*有限(?:\s*责任)?\s*公司)",
        r"研究院(?!\s*有限(?:\s*责任)?\s*公司)",
        r"事务所",
        r"联合体",
    )
    suffix_pattern = "|".join(company_suffix)
    return rf"((?:（主）|\(主\))?[\u4e00-\u9fffA-Za-z0-9（）()·\-]{{2,80}}?(?:{suffix_pattern}))"


def _infer_engineering_work_lane(
    text: str,
    fallback_project_type: str,
    *,
    title: str = "",
) -> dict[str, str]:
    title_text = _clean_text(title)
    title_lane = _engineering_lane_from_text(title_text, parse_state="DETAIL_TITLE_ROLE_LANE")
    if title_lane["engineering_work_lane"] != "unknown_engineering":
        return title_lane
    haystack = _clean_text(text)
    text_lane = _engineering_lane_from_text(haystack, parse_state="DETAIL_TEXT_ROLE_LANE")
    if text_lane["engineering_work_lane"] != "unknown_engineering":
        return text_lane
    project_type = str(fallback_project_type or "").strip().lower()
    if project_type in {"construction", "municipal", "highway", "water", "water_conservancy", "building"}:
        return {
            "engineering_work_lane": "construction_or_epc",
            "engineering_work_lane_parse_state": "PROJECT_TYPE_FALLBACK_LANE",
            "engineering_role_route": "project_manager_identity_chain",
        }
    if project_type in {"procurement", "goods", "service"}:
        return {
            "engineering_work_lane": "supplier_service",
            "engineering_work_lane_parse_state": "PROJECT_TYPE_FALLBACK_LANE",
            "engineering_role_route": "supplier_qualification_credit_chain",
        }
    return {
        "engineering_work_lane": "unknown_engineering",
        "engineering_work_lane_parse_state": "DETAIL_TEXT_NOT_CLASSIFIED",
        "engineering_role_route": "review_required_before_role_gate",
    }


def _engineering_lane_from_text(text: str, *, parse_state: str) -> dict[str, str]:
    if not text:
        return {
            "engineering_work_lane": "unknown_engineering",
            "engineering_work_lane_parse_state": "DETAIL_TEXT_NOT_CLASSIFIED",
            "engineering_role_route": "review_required_before_role_gate",
        }
    if any(token in text for token in ("勘察设计施工总承包", "设计施工总承包", "EPC", "工程总承包", "施工总承包")):
        return {
            "engineering_work_lane": "construction_or_epc",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "project_manager_identity_chain",
        }
    if any(token in text for token in ("施工监理", "工程监理", "监理服务", "总监理工程师", "注册监理工程师", "总监")):
        return {
            "engineering_work_lane": "supervision",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "chief_supervision_engineer_identity_chain",
        }
    if _looks_like_supplier_or_service_lane(text):
        return {
            "engineering_work_lane": "supplier_service",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "supplier_qualification_credit_chain",
        }
    if "勘察设计" in text or ("勘察" in text and "设计" in text and "施工" not in text):
        return {
            "engineering_work_lane": "survey_design",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "survey_design_responsible_person_identity_chain",
        }
    if "勘察" in text:
        return {
            "engineering_work_lane": "survey",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "survey_lead_identity_chain",
        }
    if "设计" in text:
        return {
            "engineering_work_lane": "design",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "design_lead_identity_chain",
        }
    if any(token in text for token in ("施工", "建安", "安装", "装修")):
        return {
            "engineering_work_lane": "construction_or_epc",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "project_manager_identity_chain",
        }
    if any(token in text for token in ("设备", "材料")):
        return {
            "engineering_work_lane": "supplier_service",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "supplier_qualification_credit_chain",
        }
    return {
        "engineering_work_lane": "unknown_engineering",
        "engineering_work_lane_parse_state": "DETAIL_TEXT_NOT_CLASSIFIED",
        "engineering_role_route": "review_required_before_role_gate",
    }


def _looks_like_supplier_or_service_lane(text: str) -> bool:
    supplier_tokens = (
        "造价咨询",
        "第三方监测",
        "第三方检测",
        "检测服务",
        "监测服务",
        "监测及检测",
        "咨询服务",
        "技术服务",
        "普通服务",
        "保险采购",
        "综合保险",
        "年度综合保险",
        "采购项目",
        "设备采购",
        "附属设备",
        "实验室设备",
        "材料采购",
        "防水材料",
        "甲供物资",
        "建设单位管理甲供物资",
        "桥梁伸缩装置",
        "特殊桥梁支座",
        "货物采购",
        "电力电缆",
        "船舶",
        "海船",
        "集装箱船",
        "集装箱海船",
    )
    digital_tokens = (
        "数字化",
        "信息化",
        "智慧系统",
        "智慧平台",
        "管理系统",
        "软件系统",
        "信息系统",
        "系统建设项目",
        "平台建设项目",
    )
    return any(token in text for token in supplier_tokens + digital_tokens)


def _extract_role_name_by_patterns(text: str, patterns: tuple[str, ...]) -> tuple[str, str]:
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate_name = _clean_text(match.group("name") if "name" in match.groupdict() else match.group(1))
        candidate_name = candidate_name.strip(" ：:，,；;。")
        if not _looks_like_person_name(candidate_name):
            continue
        return candidate_name, "DETAIL_TEXT_ROLE_CONTEXT"
    return "", "DETAIL_TEXT_NOT_FOUND"


def _extract_candidate_table_responsible_person(text: str) -> dict[str, str]:
    company_pattern = _company_like_pattern()
    patterns = (
        rf"(?:项目总负责人姓名及资格证书\s*编号|项目总负责人姓名及资格证书编号|"
        rf"项目负责人姓名及资格证书\s*编号|项目负责人姓名及资格证书编号|项目负责人姓名/资格证书编号)"
        rf".{{0,260}}?{company_pattern}.{{0,260}}?"
        rf"(?P<name>[\u4e00-\u9fff·]{{2,8}})\s*/\s*(?P<cert>[\u4e00-\u9fff]{{0,4}}[A-Za-z0-9][A-Za-z0-9\-]{{3,39}})",
        rf"(?:项目总负责人姓名|项目总负责人|项目负责人姓名|项目负责人).{{0,220}}?{company_pattern}.{{0,220}}?"
        rf"(?P<name>[\u4e00-\u9fff·]{{2,8}})\s*/\s*(?P<cert>[\u4e00-\u9fff]{{0,4}}[A-Za-z0-9][A-Za-z0-9\-]{{3,39}})",
    )
    body_result = _extract_candidate_role_table_body(text)
    if body_result.get("primary_responsible_person_name"):
        return body_result
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        name = _clean_text(match.group("name")).strip(" ：:，,；;。")
        cert = _clean_certificate_no_value(match.group("cert"))
        if not _looks_like_person_name(name):
            continue
        company = _clean_company_value(_clean_text(match.group(1))) if match.lastindex else ""
        if not _looks_like_table_candidate_company(company):
            continue
        return {
            "candidate_company": company,
            "primary_responsible_person_name": name,
            "project_manager_certificate_no": cert,
            "parse_state": "DETAIL_TEXT_CANDIDATE_ROLE_CERT_TABLE",
        }
    return {
        "candidate_company": "",
        "primary_responsible_person_name": "",
        "project_manager_certificate_no": "",
        "parse_state": "DETAIL_TEXT_NOT_FOUND",
    }


def _extract_candidate_role_table_body(text: str) -> dict[str, str]:
    body_pattern = (
        r"(?:项目总负责人姓名及资格证书\s*编号|项目总负责人姓名及资格证书编号|"
        r"项目负责人姓名及资格证书\s*编号|项目负责人姓名及资格证书编号|项目负责人姓名/资格证书编号|"
        r"拟派项目负责人|拟派项目经理姓名|项目负责人资质|项目负责人资格情况|项目总负责人|项目负责人)"
        r"(?P<body>.{0,4500})"
    )
    for body_match in re.finditer(body_pattern, text):
        context_start = max(0, body_match.start() - 180)
        context = text[context_start : body_match.start()] + body_match.group("body")[:160]
        if not any(token in context for token in ("中标候选", "成交候选", "定标候选", "评标结果", "候选人名称", "无排序")):
            continue
        body = _normalize_candidate_role_table_body(body_match.group("body"))
        company_matches = list(re.finditer(_candidate_role_company_pattern(), body))
        if not company_matches:
            continue
        second_candidate_pos = min(
            [pos for pos in (body.find("第二中标候选人"), body.find("第二成交候选人"), body.find("第二候选人")) if pos >= 0],
            default=-1,
        )
        if 0 <= second_candidate_pos < company_matches[0].start():
            continue
        for company_match in company_matches:
            company = _clean_company_value(_clean_text(company_match.group("company")))
            if not _looks_like_table_candidate_company(company):
                continue
            structured_role = _extract_candidate_publicity_role_after_company(
                body,
                company_match=company_match,
                company_matches=company_matches,
            )
            if structured_role.get("primary_responsible_person_name"):
                return {
                    "candidate_company": company,
                    **structured_role,
                    "parse_state": "DETAIL_TEXT_CANDIDATE_ROLE_CERT_TABLE"
                    if structured_role.get("project_manager_certificate_no")
                    else "DETAIL_TEXT_CANDIDATE_PUBLICITY_ROLE_TABLE",
                }
            tail = body[company_match.end() : company_match.end() + 360]
            for role_match in re.finditer(_candidate_role_amount_person_pattern(), tail):
                name = _clean_text(role_match.group("name")).strip(" ：:，,；;。")
                if not _looks_like_person_name(name):
                    continue
                cert = _clean_certificate_no_value(role_match.group("cert") or "")
                return {
                    "candidate_company": company,
                    "primary_responsible_person_name": name,
                    "project_manager_certificate_no": cert,
                    "parse_state": "DETAIL_TEXT_CANDIDATE_ROLE_CERT_TABLE"
                    if cert
                    else "DETAIL_TEXT_CANDIDATE_ROLE_TABLE",
                }
        for match in re.finditer(
            _candidate_role_table_row_pattern(),
            body,
        ):
            name = _clean_text(match.group("name")).strip(" ：:，,；;。")
            if not _looks_like_person_name(name):
                continue
            cert = _clean_certificate_no_value(match.group("cert") or "")
            company = _clean_company_value(_clean_text(match.group("company")))
            if not _looks_like_table_candidate_company(company):
                continue
            return {
                "candidate_company": company,
                "primary_responsible_person_name": name,
                "project_manager_certificate_no": cert,
                "parse_state": "DETAIL_TEXT_CANDIDATE_ROLE_TABLE",
            }
    return {
        "candidate_company": "",
        "primary_responsible_person_name": "",
        "project_manager_certificate_no": "",
        "parse_state": "DETAIL_TEXT_NOT_FOUND",
    }


def _normalize_candidate_role_table_body(body: str) -> str:
    text = str(body or "")
    text = re.sub(r"(有限|股份|集团)\s+(公司)", r"\1\2", text)
    text = re.sub(r"(设计院|研究院|勘测院|勘察院|规划院)\s+(有限(?:责任)?公司)", r"\1\2", text)
    text = re.sub(r"(勘测|勘察|规划|设计)\s+(院)", r"\1\2", text)
    text = re.sub(r"(工程)\s+(技术有限公司)", r"\1\2", text)
    return text


def _extract_candidate_publicity_role_after_company(
    body: str,
    *,
    company_match: re.Match[str],
    company_matches: list[re.Match[str]],
) -> dict[str, str]:
    next_company_start = min(
        [match.start() for match in company_matches if match.start() > company_match.start()],
        default=min(company_match.end() + 520, len(body)),
    )
    row_text = body[company_match.end() : next_company_start]
    extended_row_text = body[company_match.end() : min(company_match.end() + 620, len(body))]
    row_text_candidates = [row_text]
    if extended_row_text and extended_row_text != row_text:
        row_text_candidates.append(extended_row_text)
    guangzhou_publicity_role = _extract_guangzhou_candidate_publicity_row_role(row_text)
    if guangzhou_publicity_role.get("primary_responsible_person_name"):
        return guangzhou_publicity_role
    role_cert_patterns = (
        r"(?P<name>[\u4e00-\u9fff·]{2,8})\s+"
        r"(?P<cert_type>[\u4e00-\u9fffA-Za-z（）()]{0,30}(?:注册)?监理工程师|"
        r"[\u4e00-\u9fffA-Za-z（）()]{0,30}(?:一级注册建造师|二级注册建造师|一级建造师|二级建造师|"
        r"注册建筑师|注册结构工程师|注册土木工程师(?:[（(]岩土[）)])?|注册电气工程师|"
        r"注册公用设备工程师|高级工程师|工程师))"
        r"\s*[/／]\s*(?P<cert>[\u4e00-\u9fff]{0,4}[A-Za-z0-9][A-Za-z0-9\-]{3,39})",
        r"(?P<name>[\u4e00-\u9fff·]{2,8})\s*[/／]\s*(?P<cert>[\u4e00-\u9fff]{0,4}[A-Za-z0-9][A-Za-z0-9\-]{3,39})",
    )
    for candidate_row_text in row_text_candidates:
        for pattern in role_cert_patterns:
            for match in re.finditer(pattern, candidate_row_text):
                name = _clean_text(match.group("name")).strip(" ：:，,；;。")
                if not _looks_like_person_name(name):
                    continue
                return {
                    "primary_responsible_person_name": name,
                    "project_manager_certificate_no": _clean_certificate_no_value(match.group("cert")),
                }
    role_only_patterns = (
        r"(?:拟派项目负责人|项目负责人|总监理工程师|设计负责人|勘察负责人)\s*[:：]?\s*(?P<name>[\u4e00-\u9fff·]{2,8})",
    )
    for pattern in role_only_patterns:
        for match in re.finditer(pattern, row_text):
            name = _clean_text(match.group("name")).strip(" ：:，,；;。")
            if _looks_like_person_name(name):
                return {
                    "primary_responsible_person_name": name,
                    "project_manager_certificate_no": "",
                }
    return {
        "primary_responsible_person_name": "",
        "project_manager_certificate_no": "",
    }


def _extract_guangzhou_candidate_publicity_row_role(row_text: str) -> dict[str, str]:
    text = _normalize_candidate_role_table_body(row_text)
    text = re.sub(r"&nbsp;|\u00a0", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return {
            "primary_responsible_person_name": "",
            "project_manager_certificate_no": "",
        }

    cert_after_name_pattern = (
        r"\s+(?P<cert_desc>[^/／。；;\n\r]{0,90}?"
        r"(?:一级注册建造师|二级注册建造师|一级建造师|二级建造师|注册建造师|"
        r"注册土木工程师(?:[（(][^）)]{1,20}[）)])?|注册监理工程师|监理工程师|"
        r"一级注册建筑师|二级注册建筑师|注册建筑师|注册结构工程师|"
        r"注册电气工程师|注册公用设备工程师|高级工程师|工程师)"
        r"[^/／。；;\n\r]{0,70}?)"
        r"(?:[/／]\s*|注册编号\s*[：:]\s*)"
        r"(?P<cert>[\u4e00-\u9fff]{0,4}\s*[A-Za-z0-9][A-Za-z0-9\s\-]{3,49})"
    )
    parenthesized_cert_after_name_pattern = (
        r"\s+[^。；;\n\r]{0,90}?（\s*注册编号\s*[：:]"
        r"\s*(?P<cert>[\u4e00-\u9fff]{0,4}\s*[A-Za-z0-9][A-Za-z0-9\s\-]{3,49})\s*）"
    )
    for name_match in re.finditer(r"(?<![\u4e00-\u9fff])(?P<name>[\u4e00-\u9fff·]{2,4})(?![\u4e00-\u9fff])", text):
        name = _clean_text(name_match.group("name")).strip(" ：:，,；;。")
        if not _looks_like_person_name(name):
            continue
        tail = text[name_match.end() : name_match.end() + 180]
        cert_match = re.match(cert_after_name_pattern, tail) or re.match(
            parenthesized_cert_after_name_pattern,
            tail,
        )
        if not cert_match:
            continue
        cert = _clean_certificate_no_value(cert_match.group("cert"))
        if cert:
            return {
                "primary_responsible_person_name": name,
                "project_manager_certificate_no": cert,
            }

    filler = (
        r"(?:详见(?:投标文件公开|中标候选人公示|附件)|满足招标文件要求|完全响应|"
        r"无业绩要求|按招标文件要求|/)"
    )
    role_only_pattern = (
        rf"(?:{filler}[\s/；;，,、]*){{1,5}}"
        rf"(?:[。.]?[\s/；;，,、]*)"
        r"(?P<name>[\u4e00-\u9fff·]{2,4})"
        r"(?=\s+(?:详见|满足|完全|/|一级|二级|注册|市政|机电|公路|水利|监理|高级|工程师|[（(]))"
    )
    for match in re.finditer(role_only_pattern, text):
        name = _clean_text(match.group("name")).strip(" ：:，,；;。")
        if _looks_like_person_name(name):
            return {
                "primary_responsible_person_name": name,
                "project_manager_certificate_no": "",
            }
    return {
        "primary_responsible_person_name": "",
        "project_manager_certificate_no": "",
    }


def _clean_certificate_no_value(value: str) -> str:
    cert = _clean_text(value).strip(" ：:，,；;。）》)")
    cert = re.sub(r"\s+", "", cert)
    cert = re.split(r"(?:详见|业绩|资格|资质|候选人|投标|质量|工期)", cert, maxsplit=1)[0]
    return cert.strip(" ：:，,；;。）》)")


def _candidate_role_company_pattern() -> str:
    company_suffix = (
        r"设计院\s*有限(?:\s*责任)?\s*公司",
        r"研究院\s*有限(?:\s*责任)?\s*公司",
        r"有限\s*责任\s*公司",
        r"股份\s*有限公司",
        r"集团\s*有限公司",
        r"工程建设\s*有限公司",
        r"建设管理\s*有限公司",
        r"工程咨询\s*有限公司",
        r"监理\s*有限公司",
        r"有限\s*公司",
        r"事务所",
        r"联合体",
    )
    company_unit = (
        rf"(?:（主）|\(主\)|（成）|\(成\))?"
        rf"[\u4e00-\u9fffA-Za-z0-9（）()·\-]{{2,100}}?"
        rf"(?:{'|'.join(company_suffix)})"
    )
    return rf"(?P<company>{company_unit}(?:[;；、，,]\s*{company_unit})*)(?!\s*[;；、，,])"


def _candidate_role_amount_person_pattern() -> str:
    return (
        r"(?:\d[\d,.]*\s*(?:元|%)?(?:[/／]\s*\d[\d,.]*\s*(?:元)?)?[\s，,、]*){1,6}"
        r"(?P<name>[\u4e00-\u9fff·]{2,8})"
        r"(?:(?:\s*/\s*|\s+)(?P<cert>[\u4e00-\u9fff]{0,4}[A-Za-z0-9][A-Za-z0-9\-]{3,39}))?"
    )


def _candidate_role_table_row_pattern() -> str:
    consortium = _candidate_role_company_pattern()
    return (
        rf"{consortium}"
        rf".{{0,220}}"
        rf"{_candidate_role_amount_person_pattern()}"
    )


def _looks_like_table_candidate_company(value: str) -> bool:
    company = _clean_text(value)
    if not company:
        return False
    invalid_tokens = (
        "姓名",
        "资格",
        "能力条件",
        "候选人",
        "投标",
        "报价",
        "项目负责人",
        "注册编号",
        "证书编号",
        "资格要求",
        "可由",
        "须无",
        "截标",
        "系统上所报",
    )
    return not any(token in company for token in invalid_tokens)


def _lane_primary_role(work_lane: str) -> str:
    if work_lane == "supervision":
        return "chief_supervision_engineer"
    if work_lane == "design":
        return "design_lead"
    if work_lane == "survey":
        return "survey_lead"
    if work_lane == "survey_design":
        return "survey_design_project_lead"
    if work_lane == "supplier_service":
        return "service_project_lead"
    return "project_manager"


def _verification_priority_profile(
    *,
    work_lane: str,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    primary_name = str(identity.get("primary_responsible_person_name") or "")
    project_manager_name = str(identity.get("project_manager_name") or "")
    chief_supervision_name = str(identity.get("chief_supervision_engineer_name") or "")
    design_lead_name = str(identity.get("design_lead_name") or "")
    survey_lead_name = str(identity.get("survey_lead_name") or "")

    if work_lane == "construction_or_epc":
        present = bool(project_manager_name or primary_name)
        return {
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "verification_priority_band": "A",
            "verification_focus": "project_manager_active_conflict_certificate_qualification_performance_chain",
            "expected_responsible_role_field": "project_manager_name_or_primary_responsible_person_name",
            "expected_responsible_role_present": present,
            "responsible_role_gap_code": "" if present else "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
            "responsible_role_gap_review_required": not present,
        }
    if work_lane == "supervision":
        present = bool(chief_supervision_name or primary_name)
        return {
            "opportunity_priority_class": "B_HIGH_SUPERVISION",
            "verification_priority_band": "B",
            "verification_focus": "chief_supervision_engineer_registration_supervision_qualification_performance_chain",
            "expected_responsible_role_field": "chief_supervision_engineer_name_or_primary_responsible_person_name",
            "expected_responsible_role_present": present,
            "responsible_role_gap_code": "" if present else "B_CHIEF_SUPERVISION_ENGINEER_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
            "responsible_role_gap_review_required": not present,
        }
    if work_lane in {"design", "survey", "survey_design"}:
        present = bool(design_lead_name or survey_lead_name or primary_name)
        return {
            "opportunity_priority_class": "C_MEDIUM_DESIGN_SURVEY",
            "verification_priority_band": "C",
            "verification_focus": "design_survey_responsible_person_registration_qualification_performance_chain",
            "expected_responsible_role_field": "design_lead_name_or_survey_lead_name_or_primary_responsible_person_name",
            "expected_responsible_role_present": present,
            "responsible_role_gap_code": "" if present else "C_DESIGN_SURVEY_RESPONSIBLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
            "responsible_role_gap_review_required": not present,
        }
    if work_lane == "supplier_service":
        return {
            "opportunity_priority_class": "D_LOW_SUPPLIER_SERVICE",
            "verification_priority_band": "D",
            "verification_focus": "supplier_qualification_performance_price_credit_chain",
            "expected_responsible_role_field": "not_required_for_supplier_service",
            "expected_responsible_role_present": True,
            "responsible_role_gap_code": "",
            "responsible_role_gap_review_required": False,
        }
    return {
        "opportunity_priority_class": "REVIEW_UNCLASSIFIED_ENGINEERING",
        "verification_priority_band": "REVIEW",
        "verification_focus": "classify_engineering_lane_before_role_gate",
        "expected_responsible_role_field": "review_required_before_role_gate",
        "expected_responsible_role_present": False,
        "responsible_role_gap_code": "ENGINEERING_LANE_UNCLASSIFIED_REQUIRES_REVIEW",
        "responsible_role_gap_review_required": True,
    }


def _responsible_role_gap_diagnostics(
    *,
    text: str,
    title: str,
    work_lane: str,
    priority_profile: Mapping[str, Any],
    candidate_company: str,
) -> dict[str, Any]:
    if not priority_profile.get("responsible_role_gap_review_required"):
        return {
            "responsible_role_gap_root_cause": "",
            "responsible_role_gap_source_evidence": "",
            "responsible_role_gap_token_hits": [],
            "stage4_identity_completion_required": False,
            "stage4_identity_completion_route": "",
            "stage4_identity_completion_targets": [],
            "stage4_identity_completion_blocker": "",
        }

    cleaned_text = _clean_text(text)
    token_hits = _responsible_role_token_hits(cleaned_text)
    has_text = bool(cleaned_text.strip())
    if token_hits and _responsible_role_tokens_are_requirement_only(cleaned_text):
        root_cause = "RESPONSIBLE_ROLE_ONLY_IN_TENDER_REQUIREMENT_NOT_ASSIGNMENT"
        source_evidence = "role_tokens_appear_only_in_tender_qualification_requirement"
        route = "WAIT_FOR_CANDIDATE_NOTICE_OR_STAGE4_PROJECT_RECORD_LOOKUP"
        blocker = "role_mentioned_as_requirement_not_assigned_person"
    elif token_hits:
        root_cause = "ROLE_TOKEN_PRESENT_PARSER_MISSED_OR_COMPLEX_TABLE"
        source_evidence = "captured_text_contains_responsible_role_tokens"
        route = "STAGE3_DEEP_TABLE_PARSE_THEN_STAGE4_COMPANY_FIRST"
        blocker = "role_tokens_present_but_not_structured"
    elif has_text:
        root_cause = "CAPTURED_TEXT_HAS_NO_RESPONSIBLE_ROLE_FIELD"
        source_evidence = "detail_and_attachment_text_replayable_but_no_responsible_role_tokens"
        route = "STAGE4_COMPANY_PROJECT_FIRST_PUBLIC_RECORD_LOOKUP"
        blocker = "responsible_role_name_missing_in_stage3_source_text"
    else:
        root_cause = "NO_REPLAYABLE_TEXT_FOR_RESPONSIBLE_ROLE"
        source_evidence = "detail_and_attachment_text_missing_or_unreadable"
        route = "RECAPTURE_OR_OCR_THEN_STAGE4_COMPANY_PROJECT_FIRST"
        blocker = "source_text_not_replayable"

    targets = _stage4_identity_completion_targets(
        title=title,
        work_lane=work_lane,
        candidate_company=candidate_company,
        expected_field=str(priority_profile.get("expected_responsible_role_field") or ""),
        route=route,
    )
    return {
        "responsible_role_gap_root_cause": root_cause,
        "responsible_role_gap_source_evidence": source_evidence,
        "responsible_role_gap_token_hits": token_hits,
        "stage4_identity_completion_required": True,
        "stage4_identity_completion_route": route,
        "stage4_identity_completion_targets": targets,
        "stage4_identity_completion_blocker": blocker,
    }


def _responsible_role_token_hits(text: str) -> list[str]:
    tokens = (
        "项目经理",
        "项目负责人",
        "拟派项目负责人",
        "施工负责人",
        "总监理工程师",
        "总监",
        "监理负责人",
        "设计负责人",
        "勘察负责人",
        "项目设计负责人",
        "项目勘察负责人",
        "建造师",
        "注册建造师",
        "注册监理工程师",
        "注册建筑师",
        "注册结构工程师",
        "注册土木工程师",
        "注册电气工程师",
        "注册公用设备工程师",
        "证书编号",
        "注册编号",
        "资格能力条件",
        "拟派人员",
    )
    return [token for token in tokens if token in text]


def _responsible_role_tokens_are_requirement_only(text: str) -> bool:
    requirement_tokens = (
        "资格要求",
        "投标人资格",
        "须无在建",
        "无在建工程",
        "可由联合体",
        "不得变更",
        "截标时",
        "需具备",
    )
    assignment_tokens = (
        "第一中标候选人",
        "第一成交候选人",
        "定标候选人名称",
        "中标候选人名称",
        "候选人名称",
        "评标结果",
        "项目负责人姓名",
        "项目总负责人姓名",
        "总监理工程师姓名",
    )
    return any(token in text for token in requirement_tokens) and not any(
        token in text for token in assignment_tokens
    )


def _stage4_identity_completion_targets(
    *,
    title: str,
    work_lane: str,
    candidate_company: str,
    expected_field: str,
    route: str,
) -> list[dict[str, str]]:
    if work_lane == "supplier_service":
        return []
    role_target = {
        "supervision": "chief_supervision_engineer",
        "design": "design_lead",
        "survey": "survey_lead",
        "survey_design": "survey_or_design_project_lead",
    }.get(work_lane, "project_manager")
    base = {
        "project_name": title,
        "candidate_company": candidate_company,
        "expected_responsible_role_field": expected_field,
        "target_responsible_role": role_target,
        "completion_route": route,
    }
    targets = [
        {
            **base,
            "source_family": "guangdong_gdcic_openplatform",
            "query_order": "project_name_then_candidate_company",
            "target_evidence": "project_public_record_construction_permit_contract_completion_personnel_or_performance",
        },
        {
            **base,
            "source_family": "jzsc_company_first",
            "query_order": "candidate_company_first_then_personnel_or_project_records",
            "target_evidence": "registered_personnel_project_records_and_public_identifier",
        },
    ]
    if work_lane in {"supervision", "design", "survey", "survey_design"}:
        targets.append(
            {
                **base,
                "source_family": "local_industry_or_professional_registration",
                "query_order": "candidate_company_then_role_specific_registration",
                "target_evidence": "role_specific_registration_or_public_project_assignment",
            }
        )
    return targets


def _extract_candidate_summary_table(text: str) -> dict[str, str]:
    company_pattern = _company_like_pattern()
    manager_header = (
        r"(?:项目经理姓名|项目负责人|拟派项目负责人姓名|总监理工程师姓名|"
        r"项目经理|拟派项目负责人|总监理工程师|总监|"
        r"设计负责人|项目设计负责人|勘察负责人|项目勘察负责人|"
        r"(?:拟派)?(?:项目|标段|施工|监理|设计|勘察)负责人)"
    )
    vertical_patterns = (
        rf"中标候选人单位\s+投标报价(?:[（(]元[）)]|（元）|\(元\))?\s+{manager_header}\s+第一中标候选人\s+(?P<company>{company_pattern})\s+[0-9,，.]+\s+(?P<manager>[\u4e00-\u9fff·]{{2,8}})",
        rf"第一中标候选人\s+(?P<company>{company_pattern})\s+[0-9,，.]+\s+(?P<manager>[\u4e00-\u9fff·]{{2,8}})\s+第二中标候选人",
    )
    for pattern in vertical_patterns:
        match = re.search(pattern, text)
        if match:
            return {
                "candidate_company": _clean_company_value(_clean_text(match.group("company"))),
                "project_manager_name": _clean_text(match.group("manager")).strip(" ：:，,；;。"),
                "parse_state": "DETAIL_TEXT_CANDIDATE_SUMMARY_TABLE",
            }
    transposed = re.search(
        rf"中标候选人\s+第一中标候选人\s+第二中标候选人\s+第三中标候选人\s+单位名称\s+(?P<companies>.+?)\s+{manager_header}\s+(?P<managers>[\u4e00-\u9fff·\s]{{5,40}})",
        text,
    )
    if transposed:
        company = _first_company_like_text(transposed.group("companies"))
        manager_match = re.search(r"([\u4e00-\u9fff·]{2,8})", transposed.group("managers"))
        return {
            "candidate_company": company,
            "project_manager_name": _clean_text(manager_match.group(1)).strip(" ：:，,；;。") if manager_match else "",
            "parse_state": "DETAIL_TEXT_TRANSPOSED_CANDIDATE_TABLE",
        }
    return {}


def _looks_like_person_name(value: str) -> bool:
    name = _clean_text(value).strip(" ：:，,；;。")
    if "·" in name:
        if not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", name):
            return False
    elif not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", name):
        return False
    non_name_tokens = (
        "项目",
        "负责人",
        "经理",
        "中标",
        "候选",
        "公示",
        "公告",
        "结束",
        "时间",
        "日历",
        "日历天",
        "日内",
        "年度",
        "年版",
        "合格",
        "书面",
        "答复",
        "答疑",
        "澄清",
        "详见",
        "可由",
        "联合体",
        "须无",
        "需具备",
        "法律",
        "法规",
        "规定",
        "系统",
        "所报",
        "个月",
        "不得",
        "变更",
        "下浮",
        "报价",
        "投标",
        "开标",
        "评标",
        "情况",
        "采购",
        "序号",
        "招标",
        "按招",
        "联系",
        "地址",
        "广场",
        "广州",
        "建造师",
        "工程师",
        "文件",
        "要求",
        "公司",
        "集团",
        "设计",
        "勘测",
        "勘察",
        "规划",
        "建工",
        "招商",
        "交通",
        "建设",
        "工程",
        "建筑",
        "装修",
        "咨询",
        "管理",
        "有限",
        "注册",
        "证书",
        "资格",
        "资质",
        "业绩",
        "专业",
        "标段",
        "施工",
        "监理",
        "千伏",
        "电厂",
        "号",
        "号楼",
    )
    return not any(token in name for token in non_name_tokens)


def _extract_project_manager_certificate_identity(text: str) -> dict[str, str]:
    result = {
        "project_manager_certificate_type": "",
        "project_manager_certificate_type_parse_state": "DETAIL_TEXT_NOT_FOUND",
        "project_manager_cert_specialty": "",
        "project_manager_cert_specialty_parse_state": "DETAIL_TEXT_NOT_FOUND",
        "project_manager_professional_title": "",
        "project_manager_professional_title_parse_state": "DETAIL_TEXT_NOT_FOUND",
    }

    certificate_type_patterns = (
        (r"一级注册建造师|一级建造师", "一级建造师"),
        (r"二级注册建造师|二级建造师", "二级建造师"),
        (r"注册建造师", "注册建造师"),
        (r"注册监理工程师|监理工程师注册证书|(?<!总)监理工程师(?=\s*[/／])", "注册监理工程师"),
        (r"一级注册建筑师|一级建筑师", "一级注册建筑师"),
        (r"二级注册建筑师|二级建筑师", "二级注册建筑师"),
        (r"注册建筑师", "注册建筑师"),
        (r"注册土木工程师\s*[（(]\s*岩土\s*[）)]|注册岩土工程师", "注册土木工程师（岩土）"),
        (r"注册电气工程师(?:[（(][^）)]+[）)])?", None),
        (r"注册(?:土木|结构|公用设备|造价|安全)工程师(?:[（(][^）)]+[）)])?", None),
    )
    certificate_context = ""
    for pattern, canonical in certificate_type_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        result["project_manager_certificate_type"] = canonical or _clean_text(match.group(0))
        result["project_manager_certificate_type_parse_state"] = "DETAIL_TEXT_CERTIFICATE_CONTEXT"
        start = max(match.start() - 20, 0)
        end = min(match.end() + 50, len(text))
        certificate_context = text[start:end]
        break

    if not certificate_context:
        context_match = re.search(r"(?:注册专业|证书专业|专业|证书|建造师)[^。；;\n\r]{0,60}", text)
        certificate_context = context_match.group(0) if context_match else ""

    specialty_aliases = (
        ("机电工程", "机电"),
        ("机电", "机电"),
        ("市政公用工程", "市政"),
        ("市政", "市政"),
        ("建筑工程", "建筑"),
        ("房屋建筑", "建筑"),
        ("建筑", "建筑"),
        ("公路工程", "公路"),
        ("公路", "公路"),
        ("道路工程", "道路"),
        ("道路", "道路"),
        ("路桥", "路桥"),
        ("水利水电工程", "水利"),
        ("水利", "水利"),
        ("岩土工程", "岩土"),
        ("岩土", "岩土"),
        ("土木工程", "土木"),
        ("土木", "土木"),
        ("结构工程", "结构"),
        ("结构", "结构"),
        ("给水排水", "给排水"),
        ("给排水", "给排水"),
        ("暖通空调", "暖通"),
        ("暖通", "暖通"),
        ("动力", "动力"),
        ("供配电", "电气"),
        ("电气", "电气"),
    )
    for raw, canonical in specialty_aliases:
        if raw not in certificate_context:
            continue
        result["project_manager_cert_specialty"] = canonical
        result["project_manager_cert_specialty_parse_state"] = "DETAIL_TEXT_CERTIFICATE_CONTEXT"
        break

    title_patterns = (
        r"(?:职称|技术职称|职称证书)\s*[:：]?\s*(正高级工程师|高级工程师|工程师|助理工程师)",
        r"(正高级工程师|高级工程师|工程师|助理工程师)\s*(?:职称|职称证书)",
    )
    for pattern in title_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        result["project_manager_professional_title"] = _clean_text(match.group(1))
        result["project_manager_professional_title_parse_state"] = "DETAIL_TEXT_TITLE_CONTEXT"
        break
    return result


def _clean_company_value(value: str) -> str:
    text = value.strip()
    text = re.sub(r"(设计院|研究院)\s+(有限(?:\s*责任)?\s*公司)", r"\1\2", text)
    text = re.sub(r"有限\s+责任\s+公司", "有限责任公司", text)
    text = re.sub(r"(有限|股份|集团)\s+(公司)", r"\1\2", text)
    text = re.split(
        r"\s+(?:中标|成交|预算|采购|合同|公告|附件|金额|项目名称|采购人|供应商地址|地址|投标报价|报价)",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(r"^(?:投标报价|报价|第一(?:中标|成交)?候选人)\s*", "", text)
    text = re.split(r"(?:中标|成交)[（(]", text, maxsplit=1)[0]
    return text.strip(" ：:，,；;。")


def _extract_project_manager(text: str, *, work_lane: str = "") -> dict[str, str]:
    summary_table = _extract_candidate_summary_table(text)
    candidate_section = _section_between(
        text,
        start_tokens=("第一中标候选人", "第一成交候选人", "第一候选人"),
        end_tokens=("第二中标候选人", "第二成交候选人", "第二候选人", "中标候选人响应招标文件要求的资格能力条件"),
    )
    search_text = candidate_section or text
    manager_name = ""
    manager_state = "DETAIL_TEXT_NOT_FOUND"
    primary_name = ""
    primary_state = "DETAIL_TEXT_NOT_FOUND"
    primary_role = ""
    chief_supervision_engineer_name = ""
    chief_supervision_engineer_state = "DETAIL_TEXT_NOT_FOUND"
    design_lead_name = ""
    design_lead_state = "DETAIL_TEXT_NOT_FOUND"
    survey_lead_name = ""
    survey_lead_state = "DETAIL_TEXT_NOT_FOUND"
    if summary_table.get("project_manager_name"):
        primary_name = str(summary_table["project_manager_name"])
        primary_state = str(summary_table["parse_state"])
        primary_role = _lane_primary_role(work_lane)
    else:
        table_role = _extract_candidate_table_responsible_person(search_text)
        if (
            not table_role.get("primary_responsible_person_name")
            and candidate_section
            and search_text != text
        ):
            table_role = _extract_candidate_table_responsible_person(text)
        table_role_company = str(table_role.get("candidate_company") or "")
        table_role_name = str(table_role.get("primary_responsible_person_name") or "")
        table_role_cert = str(table_role.get("project_manager_certificate_no") or "")
        table_role_state = str(table_role.get("parse_state") or "DETAIL_TEXT_NOT_FOUND")
        supervision_patterns = (
            r"(?:总监理工程师姓名|总监理工程师|总监|监理负责人)(?:姓名)?[:：\s]+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
            r"(?:拟派)?(?:项目|标段|监理)负责人(?:姓名)?[:：\s]+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
        )
        chief_supervision_engineer_name, chief_supervision_engineer_state = _extract_role_name_by_patterns(
            search_text,
            supervision_patterns,
        )
        design_patterns = (
            r"(?:设计负责人|项目设计负责人|设计项目负责人|建筑专业负责人|结构专业负责人)(?:姓名)?[:：\s]+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
        )
        design_lead_name, design_lead_state = _extract_role_name_by_patterns(search_text, design_patterns)
        survey_patterns = (
            r"(?:勘察负责人|项目勘察负责人|勘察项目负责人|岩土负责人)(?:姓名)?[:：\s]+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
        )
        survey_lead_name, survey_lead_state = _extract_role_name_by_patterns(search_text, survey_patterns)
        construction_patterns = (
            r"(?:拟派项目负责人姓名|项目负责人姓名|项目经理姓名)\s+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
            r"(?:拟派项目负责人|项目负责人|项目经理)[:：\s]+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
            r"(?:拟派)?(?:项目|标段|施工)负责人(?:姓名)?[:：\s]+(?:资格能力条件\s+)?(?P<name>[\u4e00-\u9fff·]{2,8})",
        )
        construction_manager_name, construction_manager_state = _extract_role_name_by_patterns(
            search_text,
            construction_patterns,
        )
        if work_lane == "supervision" and chief_supervision_engineer_name:
            primary_name = chief_supervision_engineer_name
            primary_state = chief_supervision_engineer_state
            primary_role = "chief_supervision_engineer"
        elif work_lane == "design" and design_lead_name:
            primary_name = design_lead_name
            primary_state = design_lead_state
            primary_role = "design_lead"
        elif work_lane == "survey" and survey_lead_name:
            primary_name = survey_lead_name
            primary_state = survey_lead_state
            primary_role = "survey_lead"
        elif work_lane == "survey_design" and (design_lead_name or survey_lead_name):
            primary_name = design_lead_name or survey_lead_name
            primary_state = design_lead_state if design_lead_name else survey_lead_state
            primary_role = "design_lead" if design_lead_name else "survey_lead"
        elif construction_manager_name and work_lane in {"design", "survey", "survey_design"}:
            primary_name = construction_manager_name
            primary_state = construction_manager_state
            primary_role = _lane_primary_role(work_lane)
        elif construction_manager_name:
            primary_name = construction_manager_name
            primary_state = construction_manager_state
            primary_role = "project_manager"
        elif table_role_name:
            primary_name = table_role_name
            primary_state = table_role_state
            primary_role = _lane_primary_role(work_lane)
    if primary_name and not primary_role:
        primary_role = _lane_primary_role(work_lane)
    if primary_name:
        if work_lane == "supervision":
            chief_supervision_engineer_name = chief_supervision_engineer_name or primary_name
            chief_supervision_engineer_state = (
                chief_supervision_engineer_state
                if chief_supervision_engineer_state != "DETAIL_TEXT_NOT_FOUND"
                else primary_state
            )
            manager_name = primary_name
            manager_state = primary_state
        elif work_lane == "design":
            design_lead_name = design_lead_name or primary_name
            design_lead_state = design_lead_state if design_lead_state != "DETAIL_TEXT_NOT_FOUND" else primary_state
        elif work_lane == "survey":
            survey_lead_name = survey_lead_name or primary_name
            survey_lead_state = survey_lead_state if survey_lead_state != "DETAIL_TEXT_NOT_FOUND" else primary_state
        elif work_lane == "survey_design":
            pass
        elif work_lane != "supplier_service":
            manager_name = primary_name
            manager_state = primary_state
    certificate_no = ""
    certificate_state = "DETAIL_TEXT_NOT_FOUND"
    cert_patterns = (
        r"(?:注册编号|注册编\s*号|注册证书编号|证书编号|注册号)\s*[:：]?\s*([\u4e00-\u9fff]{0,4}[A-Za-z0-9][A-Za-z0-9\-]{3,39})",
        r"(?:证号)\s*[:：]\s*([\u4e00-\u9fff]{0,4}[A-Za-z0-9][A-Za-z0-9\-]{3,39})",
    )
    certificate_search_text = search_text if primary_name or manager_name else _project_manager_certificate_context(search_text)
    for pattern in cert_patterns:
        if not certificate_search_text:
            break
        match = re.search(pattern, certificate_search_text)
        if match:
            certificate_no = _clean_certificate_no_value(match.group(1))
            certificate_state = "DETAIL_TEXT_CANDIDATE_TABLE"
            break
    if not certificate_no and "table_role_cert" in locals() and table_role_cert:
        certificate_no = table_role_cert
        certificate_state = table_role_state
    identity = _extract_project_manager_certificate_identity(certificate_search_text or search_text)
    if not identity.get("project_manager_certificate_type") and certificate_search_text and certificate_search_text != search_text:
        identity = _extract_project_manager_certificate_identity(search_text)
    return {
        "primary_responsible_role": primary_role,
        "primary_responsible_person_name": primary_name,
        "primary_responsible_person_name_parse_state": primary_state,
        "chief_supervision_engineer_name": chief_supervision_engineer_name,
        "chief_supervision_engineer_name_parse_state": chief_supervision_engineer_state,
        "design_lead_name": design_lead_name,
        "design_lead_name_parse_state": design_lead_state,
        "survey_lead_name": survey_lead_name,
        "survey_lead_name_parse_state": survey_lead_state,
        "candidate_company_from_responsible_table": str(
            table_role_company if "table_role_company" in locals() else ""
        ),
        "project_manager_name": manager_name,
        "project_manager_name_parse_state": manager_state,
        "project_manager_certificate_no": certificate_no,
        "project_manager_certificate_no_parse_state": certificate_state,
        **identity,
    }


def _project_manager_certificate_context(text: str) -> str:
    patterns = (
        r"(?:项目负责人|项目经理|拟派项目负责人|总监理工程师|设计负责人|勘察负责人|建造师|注册建筑师|注册结构工程师|注册土木工程师|注册电气工程师|注册公用设备工程师|注册证书|资格证书)[^。；;\n\r]{0,140}",
        r"[^。；;\n\r]{0,80}(?:注册编号|注册证书编号|证书编号|证号|注册号)[^。；;\n\r]{0,80}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        context = match.group(0)
        if any(
            token in context
            for token in (
                "项目负责人",
                "项目经理",
                "拟派",
                "总监",
                "设计负责人",
                "勘察负责人",
                "建造师",
                "监理工程师",
                "注册建筑师",
                "注册结构工程师",
                "注册土木工程师",
                "注册证书",
            )
        ):
            return context
    return ""


def _extract_deadline(text: str) -> tuple[str, str]:
    date_pattern = (
        r"(\d{4}\s*(?:-|/|年)\s*\d{1,2}\s*(?:-|/|月)\s*\d{1,2}(?:\s*日)?"
        r"(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?)"
    )
    patterns = (
        rf"(?:异议|质疑|投诉|答疑|澄清)[^。；;\n\r]{{0,20}}?(?:截止|结束)(?:时间)?[:：\s]*{date_pattern}",
        rf"公告(?:质疑|答疑|异议|投诉)[^。；;\n\r]{{0,10}}?(?:截止|结束)(?:时间)?[:：\s]*{date_pattern}",
        rf"公示[^。；;\n\r]{{0,20}}?(?:截止|结束|期至)(?:时间)?[:：\s]*{date_pattern}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        context = _clean_text(match.group(0))
        if "发布时间" in context or "发布日期" in context:
            continue
        raw = _clean_text(match.group(1))
        return _normalize_date_to_iso_end_of_day(raw) or raw, "DETAIL_TEXT"
    return "", "DETAIL_TEXT_NOT_FOUND"


def _normalize_date_to_iso_end_of_day(value: str) -> str:
    match = re.search(
        r"(\d{4})\s*(?:-|/|年)\s*(\d{1,2})\s*(?:-|/|月)\s*(\d{1,2})(?:\s*日)?"
        r"(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
        value,
    )
    if not match:
        return ""
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    hour = int(match.group(4)) if match.group(4) else 23
    minute = int(match.group(5)) if match.group(5) else 59
    second = int(match.group(6)) if match.group(6) else 59
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}+08:00"


def _candidate_key_fields(candidate: Mapping[str, Any]) -> list[str]:
    fields: set[str] = set()
    existing = candidate.get("key_fields_present")
    if isinstance(existing, list):
        fields.update(str(item) for item in existing if item)
    elif isinstance(existing, str):
        fields.update(item.strip() for item in existing.split(",") if item.strip())
    for key in (
        "project_name",
        "notice_stage",
        "candidate_company",
        "engineering_work_lane",
        "opportunity_priority_class",
        "verification_priority_band",
        "expected_responsible_role_field",
        "responsible_role_gap_code",
        "responsible_role_gap_root_cause",
        "stage4_identity_completion_route",
        "primary_responsible_person_name",
        "project_manager_name",
        "chief_supervision_engineer_name",
        "design_lead_name",
        "survey_lead_name",
        "project_manager_certificate_no",
        "project_manager_certificate_type",
        "project_manager_cert_specialty",
    ):
        if candidate.get(key):
            fields.add(key)
    return sorted(fields)


def _capture_failure_summary(captures: list[Mapping[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for capture in captures:
        if capture.get("detail_snapshot_id_optional"):
            continue
        reasons = list(capture.get("detail_capture_failure_reasons", []) or [])
        reasons.extend(str(item) for item in list(capture.get("detail_degraded_reasons", []) or []) if str(item))
        if not reasons:
            reasons = [str(capture.get("detail_capture_status") or "detail_snapshot_missing")]
        for reason in reasons:
            key = str(reason or "unknown_detail_capture_failure")
            summary[key] = summary.get(key, 0) + 1
    return summary


def _document_completeness_summary(capture: Mapping[str, Any]) -> dict[str, Any]:
    fields = dict(capture.get("detail_fields", {}) or {})
    attachment_captures = list(capture.get("attachment_captures", []) or [])
    attachment_snapshot_refs = list(fields.get("attachment_snapshot_refs") or [])
    attachment_text_parse_states = [
        str(item)
        for item in list(fields.get("attachment_text_parse_states") or [])
        if str(item or "").strip()
    ]
    link_count = _as_int(capture.get("attachment_link_count"), 0)
    attempted_count = _as_int(capture.get("attachment_capture_attempted_count"), 0)
    snapshot_count = len([ref for ref in attachment_snapshot_refs if isinstance(ref, Mapping)])
    detail_snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
    detail_parse_state = str(capture.get("stage3_parse_state") or "NOT_RUN")
    detail_parse_errors = [
        str(item)
        for item in list(capture.get("stage3_parse_error_taxonomy", []) or [])
        if str(item or "").strip()
    ]
    source_profile_id = str(capture.get("source_profile_id") or "")
    document_kind = str(capture.get("document_kind") or "")
    guangzhou_state = str(
        fields.get("guangzhou_ywtb_download_discovery_state")
        or capture.get("guangzhou_ywtb_download_discovery_state")
        or ""
    )

    attachment_types = [
        str(ref.get("attachment_type") or "UNKNOWN_ATTACHMENT")
        for ref in attachment_snapshot_refs
        if isinstance(ref, Mapping)
    ]
    if not attachment_types:
        attachment_types = [
            _attachment_format_type(item)
            for item in attachment_captures
            if isinstance(item, Mapping)
        ]
    attachment_parse_states = [
        str(ref.get("parse_state") or "UNKNOWN")
        for ref in attachment_snapshot_refs
        if isinstance(ref, Mapping)
    ]
    if not attachment_parse_states:
        attachment_parse_states = list(attachment_text_parse_states)
    attachment_parse_states_by_snapshot = {
        str(ref.get("snapshot_id") or ""): str(ref.get("parse_state") or "UNKNOWN")
        for ref in attachment_snapshot_refs
        if isinstance(ref, Mapping) and str(ref.get("snapshot_id") or "")
    }
    for state in attachment_text_parse_states:
        snapshot_id, _, state_tail = state.partition(":")
        if snapshot_id and snapshot_id not in attachment_parse_states_by_snapshot:
            attachment_parse_states_by_snapshot[snapshot_id] = state_tail or state
    attachment_role_types = [
        str(ref.get("attachment_role_type") or _infer_attachment_role_type(ref))
        for ref in attachment_snapshot_refs
        if isinstance(ref, Mapping)
    ]
    if not attachment_role_types:
        attachment_role_types = [
            str(item.get("attachment_role_type") or _infer_attachment_role_type(item))
            for item in attachment_captures
            if isinstance(item, Mapping)
        ]
    attachment_parse_errors: list[str] = []
    for ref in attachment_snapshot_refs:
        if not isinstance(ref, Mapping):
            continue
        attachment_parse_errors.extend(
            str(item)
            for item in list(ref.get("parse_error_taxonomy") or [])
            if str(item or "").strip()
        )

    failure_reasons: list[str] = []
    failure_reasons.extend(
        str(item)
        for item in list(capture.get("detail_capture_failure_reasons", []) or [])
        if str(item or "").strip()
    )
    failure_reasons.extend(
        str(item)
        for item in list(capture.get("detail_degraded_reasons", []) or [])
        if str(item or "").strip()
    )
    failure_reasons.extend(
        str(item)
        for item in list(capture.get("detail_attachment_discovery_taxonomy") or fields.get("attachment_discovery_taxonomy") or [])
        if str(item or "").strip()
    )
    for attachment in attachment_captures:
        if not isinstance(attachment, Mapping):
            continue
        if attachment.get("attachment_snapshot_id_optional"):
            continue
        failure_reasons.extend(
            str(item)
            for item in list(attachment.get("attachment_degraded_reasons", []) or [])
            if str(item or "").strip()
        )
        failure_reasons.extend(
            str(item)
            for item in list(attachment.get("attachment_failure_taxonomy", []) or [])
            if str(item or "").strip()
        )
        for key in ("attachment_blocker_class", "attachment_blocker_reason", "attachment_capture_status"):
            value = str(attachment.get(key) or "")
            if value and not _attachment_status_is_success_or_neutral(value):
                failure_reasons.append(value)
    readback_failure_states = [
        state
        for state in attachment_text_parse_states
        if any(
            marker in state
            for marker in (
                "ATTACHMENT_SNAPSHOT_READBACK_MISSING",
                "READBACK_BYTES_MISSING",
                "MISSING_MANIFEST",
                "MISSING_OBJECT",
                "READBACK_FAILED",
            )
        )
    ]
    failure_reasons.extend(readback_failure_states)
    if readback_failure_states:
        failure_reasons.append("attachment_snapshot_readback_missing")
        if any("MISSING_MANIFEST" in state for state in readback_failure_states):
            failure_reasons.append("attachment_manifest_missing")
        if any("MISSING_OBJECT" in state for state in readback_failure_states):
            failure_reasons.append("attachment_object_missing")

    review_reasons: list[str] = []
    if not detail_snapshot_id:
        review_reasons.append("detail_snapshot_missing")
    if detail_snapshot_id and not detail_parse_state.startswith("PARSED"):
        review_reasons.append(f"detail_parse_state={detail_parse_state}")
    if link_count and snapshot_count < link_count:
        review_reasons.append("attachment_snapshot_count_below_link_count")
    if (
        link_count == 0
        and source_profile_id == "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
        and document_kind == "tender_file"
    ):
        guangzhou_failure = _guangzhou_ywtb_failure_from_state(guangzhou_state)
        if guangzhou_failure:
            failure_reasons.append(guangzhou_failure)
            review_reasons.append(guangzhou_failure)
            review_reasons.append(f"guangzhou_ywtb_download_discovery_state:{guangzhou_state}")
        else:
            failure_reasons.append("guangzhou_ywtb_attachment_download_link_not_found")
            review_reasons.append("guangzhou_ywtb_attachment_download_link_not_found")
    elif source_profile_id == "GUANGZHOU-YWTB-CONSTRUCTION-LIST" and document_kind == "tender_file":
        if guangzhou_state in {"EPPOINT_CHALLENGE_DETECTED", "EPPOINT_CHALLENGE_FAILED"}:
            guangzhou_failure = _guangzhou_ywtb_failure_from_state(guangzhou_state)
            if guangzhou_failure:
                failure_reasons.append(guangzhou_failure)
                review_reasons.append(guangzhou_failure)
            review_reasons.append(f"guangzhou_ywtb_download_discovery_state:{guangzhou_state}")
    if (
        source_profile_id == "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
        and document_kind == "tender_file"
        and guangzhou_state == "EPPOINT_CHALLENGE_RESOLVED"
    ):
        stale_guangzhou_failures = {
            "guangzhou_script_endpoint_unresolved",
            "guangzhou_epoint_challenge_detected",
            "guangzhou_challenge_required",
            "guangzhou_script_endpoint_captured_without_download_url",
        }
        failure_reasons = [reason for reason in failure_reasons if reason not in stale_guangzhou_failures]
        review_reasons = [reason for reason in review_reasons if reason not in stale_guangzhou_failures]
    if source_profile_id == "SICHUAN-GGZY-TRANSACTION-INFO":
        for reason in list(capture.get("detail_attachment_discovery_taxonomy") or fields.get("attachment_discovery_taxonomy") or []):
            text_reason = str(reason or "").strip()
            if text_reason:
                review_reasons.append(text_reason)
    if readback_failure_states:
        review_reasons.append("attachment_snapshot_readback_missing")
    if attachment_parse_errors:
        review_reasons.append("attachment_parse_error_taxonomy_present")
    if fields.get("attachment_ocr_required_count"):
        review_reasons.append("attachment_ocr_required")
    if any(item in {"UNKNOWN_ATTACHMENT", ""} for item in attachment_types):
        review_reasons.append("unknown_attachment_format")
    if any(item in {"UNKNOWN_ATTACHMENT_ROLE", ""} for item in attachment_role_types):
        review_reasons.append("unknown_attachment_role")
    if any(
        state
        and not state.startswith("PARSED")
        and "TEXT_EXTRACTED" not in state
        and state not in {"PDF_TEXT_OCR_EXTRACTED", "NOT_RUN", "UNKNOWN"}
        for state in attachment_parse_states
    ):
        review_reasons.append("attachment_parse_state_review")
    if "CLARIFICATION_OR_ADDENDUM" in attachment_role_types:
        review_reasons.append("clarification_or_addendum_requires_winning_version_review")
    if any("OCR_ENGINE_UNAVAILABLE" in str(item) for item in [*detail_parse_errors, *attachment_parse_errors, *failure_reasons]):
        review_reasons.append("ocr_engine_unavailable")
    if failure_reasons:
        review_reasons.append("capture_failure_or_blocker_present")

    if not detail_snapshot_id:
        state = "DETAIL_SNAPSHOT_MISSING_REVIEW"
    elif link_count == 0:
        state = "DETAIL_ONLY_NO_ATTACHMENTS"
    elif snapshot_count == 0:
        state = "ATTACHMENTS_NOT_CAPTURED_REVIEW"
    elif review_reasons:
        state = "PARTIAL_REVIEW_REQUIRED"
    else:
        state = "COMPLETE_WITH_ATTACHMENTS"
    notice_version_chain_state = _notice_version_chain_state(
        detail_snapshot_id=detail_snapshot_id,
        link_count=link_count,
        snapshot_count=snapshot_count,
        attachment_role_types=attachment_role_types,
    )
    download_archive_manifest = _download_archive_manifest_summary(
        capture=capture,
        attachment_snapshot_refs=[
            ref for ref in attachment_snapshot_refs if isinstance(ref, Mapping)
        ],
        attachment_captures=[
            item for item in attachment_captures if isinstance(item, Mapping)
        ],
        attachment_parse_states_by_snapshot=attachment_parse_states_by_snapshot,
    )
    download_quality_reasons = [
        str(reason)
        for reason in list(download_archive_manifest.get("quality_reasons") or [])
        if str(reason)
    ]
    review_reasons = list(dict.fromkeys([*review_reasons, *download_quality_reasons]))
    if state == "COMPLETE_WITH_ATTACHMENTS" and review_reasons:
        state = "PARTIAL_REVIEW_REQUIRED"

    attachment_ocr_required_count = _as_int(fields.get("attachment_ocr_required_count"), 0)
    attachment_ocr_extracted_count = _as_int(fields.get("attachment_ocr_extracted_count"), 0)
    if attachment_ocr_extracted_count:
        ocr_state = "OCR_EXTRACTED_REVIEW"
    elif attachment_ocr_required_count:
        ocr_state = "OCR_REQUIRED"
    elif "ocr_engine_unavailable" in review_reasons:
        ocr_state = "OCR_ENGINE_UNAVAILABLE"
    else:
        ocr_state = "NOT_REQUIRED_OR_NOT_DETECTED"

    return {
        "document_completeness_state": state,
        "notice_version_chain_state": notice_version_chain_state,
        "document_quality_state": "REVIEW_REQUIRED" if review_reasons else "READY",
        "document_quality_reasons": list(dict.fromkeys(review_reasons)),
        "ocr_state": ocr_state,
        "detail_snapshot_present": bool(detail_snapshot_id),
        "detail_parse_state": detail_parse_state,
        "detail_parse_error_taxonomy": detail_parse_errors,
        "attachment_link_count": link_count,
        "attachment_capture_attempted_count": attempted_count,
        "attachment_snapshot_count": snapshot_count,
        "attachment_types": sorted(set(attachment_types)),
        "attachment_role_types": sorted(set(attachment_role_types)),
        "attachment_parse_states": attachment_parse_states,
        "attachment_parse_error_taxonomy": sorted(set(attachment_parse_errors)),
        "attachment_ocr_required_count": attachment_ocr_required_count,
        "attachment_ocr_extracted_count": attachment_ocr_extracted_count,
        "download_archive_manifest": download_archive_manifest,
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "source": "stage2_detail_and_attachment_capture_summary",
        "customer_visible": False,
    }


def _attachment_status_is_success_or_neutral(value: str) -> bool:
    text = str(value or "").upper()
    return (
        not text
        or text in {"UNKNOWN", "SUCCESS", "FETCHED", "CAPTURED", "PARSED", "TEXT_EXTRACTED"}
        or text.startswith("PARSED")
        or "EXTRACTED" in text
    )


def _with_document_completeness(capture: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(capture)
    summary = _document_completeness_summary(enriched)
    enriched["document_completeness_summary"] = summary
    enriched["document_completeness_state"] = summary["document_completeness_state"]
    enriched["notice_version_chain_state"] = summary["notice_version_chain_state"]
    enriched["download_archive_manifest"] = summary["download_archive_manifest"]
    return enriched


class RealCandidateStage2CaptureRepository:
    def __init__(self, *, repository: OperatorActionRepository | None = None) -> None:
        self.repository = repository or OperatorActionRepository()

    def persist_capture(
        self,
        *,
        candidate: Mapping[str, Any],
        capture: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        candidate_key = str(candidate.get("candidate_key") or _candidate_key(candidate))
        snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
        status = str(capture.get("detail_capture_status") or "UNKNOWN")
        event_id = f"REAL-CANDIDATE-STAGE2-{candidate_key}-{hashlib.sha1(now.encode('utf-8')).hexdigest()[:8]}".replace(":", "").replace("+", "")
        action = PersistedOperatorAction(
            action_event_id=event_id,
            work_item_id=REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID,
            stage_scope=2,
            action_id="operator_real_candidate_stage2_detail_capture",
            button_flow_id="owner_console_real_candidate_stage2_capture",
            action_state=status,
            resulting_assignment_lifecycle_state=None,
            requested_by_role="single_operator",
            requested_by="卡卡罗特",
            assigned_owner_role="single_operator",
            assigned_owner="卡卡罗特",
            reviewer_role="single_operator",
            reviewer="卡卡罗特",
            reason="real_candidate_detail_snapshot_and_stage3_parse",
            object_refs={
                "candidate_key": candidate_key,
                "project_id": str(candidate.get("project_id") or ""),
                "project_name": str(candidate.get("project_name") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "source_profile_id": str(candidate.get("source_profile_id") or ""),
                "detail_snapshot_id": snapshot_id,
                "detail_capture_status": status,
                "stage3_parse_state": str(capture.get("stage3_parse_state") or ""),
                "attachment_link_count": str(capture.get("attachment_link_count") or 0),
                "attachment_snapshot_count": str(capture.get("attachment_snapshot_count") or 0),
                "document_completeness_state": str(capture.get("document_completeness_state") or ""),
                "notice_version_chain_state": str(capture.get("notice_version_chain_state") or ""),
                "capture_json": _json_text(capture),
            },
            trace_refs={
                "operator_console_route": "/operator-console/autonomous-opportunity-search",
                "stage2_capture_catalog_path": "/operator-console/real-candidate-stage2-captures",
                "snapshot_readback_path": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
            },
            audit_refs={
                "internal_only": "true",
                "allowlisted_same_site_detail_capture": "true",
                "real_provider_call_enabled": "false",
            },
            requested_at=now,
            completed_at=now,
        )
        self.repository.append(action)
        return self._capture_action_payload(action)

    def list_captures(self, *, limit: int = 100) -> dict[str, Any]:
        actions = self.repository.list(work_item_id=REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID)
        rows = [self._capture_action_payload(action) for action in actions]
        rows.sort(key=lambda row: str(row.get("captured_at") or ""), reverse=True)
        latest_by_candidate: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("candidate_key") or "")
            if key and key not in latest_by_candidate:
                latest_by_candidate[key] = row
        latest = list(latest_by_candidate.values())[:limit]
        return {
            "surface_id": "operator_real_candidate_stage2_capture_catalog",
            "repository_backed_readback": True,
            "data_source": "OperatorActionRepository",
            "capture_mode": REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
            "capture_count": len(latest),
            "raw_capture_event_count": len(rows),
            "duplicate_collapsed_count": max(len(rows) - len(latest), 0),
            "captures": latest,
            "manual_url_picker_primary_flow": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            "customer_download_enabled": False,
        }

    def _capture_action_payload(self, action: PersistedOperatorAction) -> dict[str, Any]:
        refs = dict(action.object_refs)
        capture = dict(_json_value(refs.get("capture_json"), {}))
        capture.update(
            {
                "capture_event_id": action.action_event_id,
                "candidate_key": refs.get("candidate_key") or capture.get("candidate_key"),
                "project_id": refs.get("project_id") or capture.get("project_id"),
                "project_name": refs.get("project_name") or capture.get("project_name"),
                "source_url": refs.get("source_url") or capture.get("source_url"),
                "source_profile_id": refs.get("source_profile_id") or capture.get("source_profile_id"),
                "detail_snapshot_id_optional": refs.get("detail_snapshot_id") or capture.get("detail_snapshot_id_optional"),
                "detail_capture_status": refs.get("detail_capture_status") or action.action_state,
                "stage3_parse_state": refs.get("stage3_parse_state") or capture.get("stage3_parse_state"),
                "attachment_link_count": _as_int(refs.get("attachment_link_count"), 0),
                "attachment_snapshot_count": _as_int(refs.get("attachment_snapshot_count"), 0),
                "document_completeness_state": refs.get("document_completeness_state")
                or capture.get("document_completeness_state"),
                "notice_version_chain_state": refs.get("notice_version_chain_state")
                or capture.get("notice_version_chain_state"),
                "captured_at": action.requested_at,
                "repository_backed": True,
            }
        )
        return _with_document_completeness(capture)


class RealCandidateStage2CaptureService:
    def __init__(
        self,
        *,
        stage2_service: Stage2Service | None = None,
        stage3_service: Stage3Service | None = None,
        object_repository: ObjectStorageRepository | None = None,
        repository: RealCandidateStage2CaptureRepository | None = None,
    ) -> None:
        self.object_repository = object_repository or ObjectStorageRepository()
        self.stage2_service = stage2_service or Stage2Service()
        self.stage3_service = stage3_service or Stage3Service()
        self.repository = repository or RealCandidateStage2CaptureRepository()

    def capture_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        now: str | None = None,
        detail_capture_limit: int | None = DEFAULT_DETAIL_CAPTURE_LIMIT,
        attachment_capture_limit: int | None = DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
        reuse_existing_captures: bool = True,
        reparse_existing_snapshots: bool = True,
        detail_capture_time_budget_seconds: float | None = DEFAULT_DETAIL_CAPTURE_TIME_BUDGET_SECONDS,
    ) -> dict[str, Any]:
        captured_at = now or utc_now_iso()
        limit = len(candidates) if detail_capture_limit is None else max(0, detail_capture_limit)
        attachment_limit = attachment_capture_limit if attachment_capture_limit is None else max(0, attachment_capture_limit)
        enriched: list[dict[str, Any]] = []
        captures: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        existing_by_key = self._existing_successful_captures(candidates) if reuse_existing_captures else {}
        reused_count = 0
        new_attempt_count = 0
        started_at_monotonic = time.monotonic()
        time_budget_exhausted = False
        for index, candidate in enumerate(candidates):
            row = dict(candidate)
            row.setdefault("candidate_key", _candidate_key(row))
            candidate_key = str(row.get("candidate_key") or "")
            existing_capture = existing_by_key.get(candidate_key)
            if existing_capture:
                if reparse_existing_snapshots:
                    existing_capture = self._refresh_capture_fields_from_snapshot(row, existing_capture)
                captures.append(existing_capture)
                by_key[candidate_key] = existing_capture
                row = self._enrich_candidate(row, existing_capture)
                reused_count += 1
            elif new_attempt_count < limit:
                if (
                    detail_capture_time_budget_seconds is not None
                    and time.monotonic() - started_at_monotonic >= detail_capture_time_budget_seconds
                ):
                    time_budget_exhausted = True
                    enriched.append(row)
                    continue
                capture = self.capture_candidate(
                    row,
                    now=captured_at,
                    attachment_capture_limit=attachment_limit,
                )
                captures.append(capture)
                by_key[candidate_key] = capture
                row = self._enrich_candidate(row, capture)
                new_attempt_count += 1
            enriched.append(row)
        return {
            "surface_id": "operator_real_candidate_stage2_capture",
            "capture_mode": REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
            "capture_limit": limit,
            "capture_limit_source": "ALL_INPUT_CANDIDATES"
            if detail_capture_limit is None
            else "EXPLICIT_LIMIT",
            "capture_execution_strategy": "ALL_CANDIDATES_RESUMABLE_WITH_TIME_BUDGET",
            "detail_capture_time_budget_seconds": detail_capture_time_budget_seconds,
            "detail_capture_time_budget_exhausted": time_budget_exhausted,
            "attachment_capture_limit": attachment_limit,
            "attachment_capture_limit_source": "ALL_SAME_SITE_ATTACHMENTS"
            if attachment_capture_limit is None
            else "EXPLICIT_LIMIT",
            "existing_capture_reused_count": reused_count,
            "existing_capture_reparse_enabled": reparse_existing_snapshots,
            "new_detail_capture_attempted_count": new_attempt_count,
            "input_candidate_count": len(candidates),
            "detail_capture_attempted_count": len(captures),
            "pending_detail_capture_count": max(len(candidates) - len(captures), 0),
            "pending_detail_capture_reason": "detail_capture_time_budget_exhausted"
            if time_budget_exhausted
            else "explicit_capture_limit"
            if max(len(candidates) - len(captures), 0)
            else "",
            "detail_capture_failed_count": sum(
                1 for item in captures if not item.get("detail_snapshot_id_optional")
            ),
            "detail_snapshot_count": sum(1 for item in captures if item.get("detail_snapshot_id_optional")),
            "stage3_parse_success_count": sum(1 for item in captures if str(item.get("stage3_parse_state") or "").startswith("PARSED")),
            "stage3_parse_failed_count": sum(
                1
                for item in captures
                if item.get("detail_snapshot_id_optional")
                and not str(item.get("stage3_parse_state") or "").startswith("PARSED")
            ),
            "detail_capture_failure_summary": _capture_failure_summary(captures),
            "attachment_link_count": sum(_as_int(item.get("attachment_link_count"), 0) for item in captures),
            "attachment_capture_attempted_count": sum(_as_int(item.get("attachment_capture_attempted_count"), 0) for item in captures),
            "attachment_snapshot_count": sum(
                len(
                    [
                        ref
                        for ref in list(dict(item.get("detail_fields") or {}).get("attachment_snapshot_refs") or [])
                        if isinstance(ref, Mapping) and str(ref.get("snapshot_id") or "").strip()
                    ]
                )
                for item in captures
            ),
            "captures": captures,
            "capture_by_candidate_key": by_key,
            "enriched_candidates": enriched,
            "repository_backed_readback": True,
            "stage2_detail_capture_enabled": True,
            "stage3_parser_readback_enabled": True,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
        }

    def _existing_successful_captures(self, candidates: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        if not candidates:
            return {}
        catalog = self.repository.list_captures(limit=max(len(candidates) * 3, 100))
        requested_keys = {
            str(candidate.get("candidate_key") or _candidate_key(candidate))
            for candidate in candidates
            if str(candidate.get("candidate_key") or _candidate_key(candidate)).strip()
        }
        existing: dict[str, dict[str, Any]] = {}
        for capture in list(catalog.get("captures", []) or []):
            key = str(capture.get("candidate_key") or "")
            snapshot_id = str(capture.get("detail_snapshot_id_optional") or "").strip()
            if key in requested_keys and key not in existing and snapshot_id:
                try:
                    replay = self.object_repository.replay_snapshot(snapshot_id)
                except Exception:
                    continue
                if not bool(replay.get("replayable")):
                    continue
                existing[key] = dict(capture)
        return existing

    def _refresh_capture_fields_from_snapshot(
        self,
        candidate: Mapping[str, Any],
        capture: Mapping[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = str(capture.get("detail_snapshot_id_optional") or "").strip()
        if not snapshot_id:
            return dict(capture)
        try:
            replay = self.object_repository.replay_snapshot(snapshot_id)
            if not bool(replay.get("replayable")):
                refreshed = dict(capture)
                state = str(replay.get("readback_state") or "READBACK_NOT_REPLAYABLE")
                refreshed["detail_capture_status"] = "STALE_DETAIL_SNAPSHOT_REVIEW"
                refreshed["detail_capture_failure_reasons"] = _dedupe_strings(
                    list(refreshed.get("detail_capture_failure_reasons") or [])
                    + [f"detail_snapshot_readback_missing:{state}"]
                )
                refreshed["stage3_parse_state"] = str(refreshed.get("stage3_parse_state") or "NOT_RUN")
                return _with_document_completeness(refreshed)
            readback_text = _decode_snapshot_text(replay)
            parser_carrier = dict(
                self.stage3_service.parse_raw_snapshot(snapshot_id, repository=self.object_repository)
            )
        except Exception:
            return dict(capture)
        refreshed = dict(capture)
        (
            attachment_text,
            attachment_text_states,
            attachment_snapshot_refs,
            qualification_text_candidate_blocks,
            attachment_text_probes,
            attachment_file_attributions,
        ) = self._attachment_text_bundle(
            list(capture.get("attachment_captures", []) or []),
            project_id=str(candidate.get("project_id") or capture.get("project_id") or ""),
        )
        combined_readback_text = "\n".join(
            part for part in (readback_text, attachment_text) if str(part or "").strip()
        )
        detail_carrier = {
            "title": capture.get("detail_title") or capture.get("project_name") or candidate.get("project_name"),
        }
        previous_fields = dict(capture.get("detail_fields") or {})
        refreshed["detail_fields"] = self._detail_fields(
            candidate=candidate,
            detail_carrier=detail_carrier,
            parser_carrier=parser_carrier,
            readback_text=combined_readback_text or readback_text,
        )
        for key in (
            "guangzhou_ywtb_download_discovery_state",
            "guangzhou_ywtb_download_diagnostics",
            "attachment_discovery_taxonomy",
            "attachment_discovery_diagnostics",
        ):
            if key in previous_fields:
                refreshed["detail_fields"][key] = previous_fields[key]
        refreshed["detail_fields"]["file_parse_attributions"] = [
            _file_parse_attribution(
                project_id=str(candidate.get("project_id") or capture.get("project_id") or ""),
                snapshot_id=snapshot_id,
                source_url=str(capture.get("source_url") or candidate.get("source_url") or ""),
                file_role="detail",
                parse_state=str(parser_carrier.get("parse_state") or capture.get("stage3_parse_state") or "NOT_RUN"),
                text=readback_text,
            ),
            *attachment_file_attributions,
        ]
        refreshed["detail_fields"]["attachment_text_probes"] = attachment_text_probes
        if attachment_text_states:
            refreshed["detail_fields"]["attachment_text_parse_states"] = attachment_text_states
            refreshed["detail_fields"]["attachment_text_merge_state"] = (
                "ATTACHMENT_TEXT_MERGED" if attachment_text else "ATTACHMENT_TEXT_NOT_EXTRACTED"
            )
            refreshed["detail_fields"]["attachment_snapshot_refs"] = attachment_snapshot_refs
            refreshed["detail_fields"]["qualification_text_candidate_blocks"] = qualification_text_candidate_blocks
            refreshed["detail_fields"]["attachment_ocr_required_count"] = sum(
                1 for state in attachment_text_states if "OCR_REQUIRED" in state
            )
            refreshed["detail_fields"]["attachment_ocr_extracted_count"] = sum(
                1 for state in attachment_text_states if "OCR" in state and "EXTRACTED" in state
            )
        refreshed["stage3_parse_state"] = str(parser_carrier.get("parse_state") or capture.get("stage3_parse_state") or "NOT_RUN")
        refreshed["stage3_parse_error_taxonomy"] = list(
            parser_carrier.get("parse_error_taxonomy", []) or capture.get("stage3_parse_error_taxonomy", []) or []
        )
        refreshed["parsed_field_count"] = len(parser_carrier.get("parsed_fields", []) or [])
        refreshed["attachment_snapshot_count"] = len(attachment_snapshot_refs)
        return _with_document_completeness(refreshed)

    def capture_candidate(
        self,
        candidate: Mapping[str, Any],
        *,
        now: str | None = None,
        attachment_capture_limit: int | None = DEFAULT_ATTACHMENT_CAPTURE_LIMIT,
    ) -> dict[str, Any]:
        captured_at = now or utc_now_iso()
        candidate_key = str(candidate.get("candidate_key") or _candidate_key(candidate))
        source_url = str(candidate.get("source_url") or "").strip()
        profile_id = str(candidate.get("source_profile_id") or "").strip()
        base_capture = {
            "candidate_key": candidate_key,
            "project_id": str(candidate.get("project_id") or ""),
            "project_name": str(candidate.get("project_name") or ""),
            "source_url": source_url,
            "source_profile_id": profile_id,
            "document_kind": str(candidate.get("evaluation_document_kind") or candidate.get("document_kind") or ""),
            "capture_mode": REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
            "captured_at": captured_at,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
        }
        if not source_url or not profile_id:
            capture = {
                **base_capture,
                "detail_capture_status": "SKIPPED",
                "detail_capture_failure_reasons": ["source_url_or_profile_id_missing"],
                "detail_snapshot_id_optional": "",
                "stage3_parse_state": "NOT_RUN",
                "attachment_link_count": 0,
                "attachment_capture_attempted_count": 0,
                "attachment_snapshot_count": 0,
                "attachment_captures": [],
            }
            capture = _with_document_completeness(capture)
            capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
            return capture

        try:
            detail_carrier = dict(
                self.stage2_service.fetch_real_public_candidate_detail_url(
                    source_url,
                    profile_id=profile_id,
                    repository=self.object_repository,
                    lineage_refs={
                        "candidate_key": candidate_key,
                        "project_id": str(candidate.get("project_id") or ""),
                        "notice_id": str(candidate.get("notice_id") or ""),
                        "source_candidate_mode": str(candidate.get("source_candidate_mode") or ""),
                    },
                )
            )
        except Exception as exc:
            capture = {
                **base_capture,
                "detail_capture_status": "FAILED_CLOSED",
                "detail_capture_failure_reasons": [str(exc)],
                "detail_snapshot_id_optional": "",
                "stage3_parse_state": "NOT_RUN",
                "attachment_link_count": 0,
                "attachment_capture_attempted_count": 0,
                "attachment_snapshot_count": 0,
                "attachment_captures": [],
            }
            capture = _with_document_completeness(capture)
            capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
            return capture

        snapshot_id = str(detail_carrier.get("snapshot_id_optional") or "")
        parser_carrier: dict[str, Any] = {}
        readback_text = ""
        if snapshot_id:
            replay = self.object_repository.replay_snapshot(snapshot_id)
            readback_text = _decode_snapshot_text(replay)
            parser_carrier = dict(
                self.stage3_service.parse_raw_snapshot(snapshot_id, repository=self.object_repository)
            )
        attachment_link_items = list(detail_carrier.get("same_site_attachment_link_items", []) or [])
        attachment_captures = self._capture_same_site_attachments(
            attachment_link_items,
            candidate=candidate,
            candidate_key=candidate_key,
            parent_profile_id=profile_id,
            detail_page_url=source_url,
            detail_snapshot_id=snapshot_id,
            limit=attachment_capture_limit,
        )
        (
            attachment_text,
            attachment_text_states,
            attachment_snapshot_refs,
            qualification_text_candidate_blocks,
            attachment_text_probes,
            attachment_file_attributions,
        ) = self._attachment_text_bundle(
            attachment_captures,
            project_id=str(candidate.get("project_id") or ""),
        )
        combined_readback_text = "\n".join(
            part for part in (readback_text, attachment_text) if str(part or "").strip()
        )
        detail_fields = self._detail_fields(
            candidate=candidate,
            detail_carrier=detail_carrier,
            parser_carrier=parser_carrier,
            readback_text=combined_readback_text or readback_text,
        )
        detail_fields["file_parse_attributions"] = [
            _file_parse_attribution(
                project_id=str(candidate.get("project_id") or ""),
                snapshot_id=snapshot_id,
                source_url=source_url,
                file_role="detail",
                parse_state=str(parser_carrier.get("parse_state") or "NOT_RUN"),
                text=readback_text,
            ),
            *attachment_file_attributions,
        ]
        detail_fields["attachment_text_probes"] = attachment_text_probes
        attachment_discovery_taxonomy = [
            str(item)
            for item in list(detail_carrier.get("attachment_discovery_taxonomy") or [])
            if str(item or "").strip()
        ]
        if attachment_discovery_taxonomy:
            detail_fields["attachment_discovery_taxonomy"] = attachment_discovery_taxonomy
            detail_fields["attachment_discovery_diagnostics"] = dict(
                detail_carrier.get("attachment_discovery_diagnostics") or {}
            )
        guangzhou_download_diagnostics = _guangzhou_ywtb_download_diagnostics(detail_carrier)
        if guangzhou_download_diagnostics:
            detail_fields["guangzhou_ywtb_download_discovery_state"] = str(
                guangzhou_download_diagnostics.get("guangzhou_ywtb_download_discovery_state") or ""
            )
            detail_fields["guangzhou_ywtb_download_diagnostics"] = guangzhou_download_diagnostics
        if str(candidate.get("source_profile_id") or "") == "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
            challenge_state, attachment_challenge_states = _guangzhou_ywtb_attachment_challenge_state(
                [item for item in attachment_captures if isinstance(item, Mapping)]
            )
            if challenge_state:
                detail_fields["guangzhou_ywtb_download_discovery_state"] = challenge_state
                diagnostics = dict(detail_fields.get("guangzhou_ywtb_download_diagnostics") or {})
                diagnostics["attachment_challenge_states"] = attachment_challenge_states
                diagnostics["attachment_challenge_summary_state"] = challenge_state
                detail_fields["guangzhou_ywtb_download_diagnostics"] = diagnostics
        if attachment_text_states:
            detail_fields["attachment_text_parse_states"] = attachment_text_states
            detail_fields["attachment_text_merge_state"] = (
                "ATTACHMENT_TEXT_MERGED" if attachment_text else "ATTACHMENT_TEXT_NOT_EXTRACTED"
            )
            detail_fields["attachment_snapshot_refs"] = attachment_snapshot_refs
            detail_fields["qualification_text_candidate_blocks"] = qualification_text_candidate_blocks
            detail_fields["attachment_ocr_required_count"] = sum(
                1 for state in attachment_text_states if "OCR_REQUIRED" in state
            )
            detail_fields["attachment_ocr_extracted_count"] = sum(
                1 for state in attachment_text_states if "OCR" in state and "EXTRACTED" in state
            )
        capture = {
            **base_capture,
            "detail_capture_status": str(detail_carrier.get("status") or "UNKNOWN"),
            "detail_snapshot_id_optional": snapshot_id,
            "detail_fetch_id": str(detail_carrier.get("detail_fetch_id") or ""),
            "detail_title": str(detail_carrier.get("title") or ""),
            "detail_content_type": str(detail_carrier.get("content_type") or ""),
            "detail_byte_size": _as_int(detail_carrier.get("byte_size"), 0),
            "detail_degraded_reasons": list(detail_carrier.get("degraded_reasons", []) or []),
            "detail_attachment_discovery_taxonomy": attachment_discovery_taxonomy,
            "detail_attachment_discovery_diagnostics": dict(
                detail_carrier.get("attachment_discovery_diagnostics") or {}
            ),
            "guangzhou_ywtb_download_discovery_state": detail_fields.get(
                "guangzhou_ywtb_download_discovery_state", ""
            ),
            "guangzhou_ywtb_download_diagnostics": detail_fields.get(
                "guangzhou_ywtb_download_diagnostics", {}
            ),
            "detail_url_retry_audit": dict(detail_carrier.get("detail_url_retry_audit") or {}),
            "detail_automated_challenge_resolution_attempted": bool(
                detail_carrier.get("automated_challenge_resolution_attempted")
            ),
            "detail_automated_challenge_resolution_state": str(
                detail_carrier.get("automated_challenge_resolution_state") or ""
            ),
            "detail_challenge_resume_audit": dict(detail_carrier.get("challenge_resume_audit") or {}),
            "stage3_parse_state": str(parser_carrier.get("parse_state") or "NOT_RUN"),
            "stage3_parse_error_taxonomy": list(parser_carrier.get("parse_error_taxonomy", []) or []),
            "parsed_field_count": len(parser_carrier.get("parsed_fields", []) or []),
            "detail_fields": detail_fields,
            "attachment_link_count": len(attachment_link_items),
            "same_site_attachment_link_items": attachment_link_items,
            "attachment_capture_attempted_count": len(attachment_captures),
            "attachment_snapshot_count": len(attachment_snapshot_refs),
            "attachment_captures": attachment_captures,
            "snapshot_readback_path_optional": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
        }
        capture = _with_document_completeness(capture)
        capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
        return capture

    def _attachment_text_bundle(
        self,
        attachment_captures: list[Mapping[str, Any]],
        *,
        project_id: str,
    ) -> tuple[str, list[str], list[dict[str, Any]], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        texts: list[str] = []
        states: list[str] = []
        snapshot_refs: list[dict[str, Any]] = []
        qualification_blocks: list[str] = []
        text_probes: list[dict[str, Any]] = []
        file_attributions: list[dict[str, Any]] = []
        for attachment in attachment_captures:
            snapshot_id = str(attachment.get("attachment_snapshot_id_optional") or "").strip()
            if not snapshot_id:
                status = str(attachment.get("attachment_capture_status") or "ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED")
                blocker = str(attachment.get("attachment_blocker_class") or attachment.get("attachment_blocker_reason") or "")
                states.append(":".join(part for part in ("NO_SNAPSHOT", status, blocker) if part))
                continue
            try:
                readback = self.object_repository.replay_snapshot(snapshot_id)
            except Exception as exc:  # pragma: no cover - repository corruption varies
                states.append(f"{snapshot_id}:READBACK_FAILED:{type(exc).__name__}")
                continue
            if not bool(readback.get("replayable")):
                state = str(readback.get("readback_state") or "READBACK_NOT_REPLAYABLE")
                states.append(f"{snapshot_id}:ATTACHMENT_SNAPSHOT_READBACK_MISSING:{state}")
                continue
            data = readback.get("bytes")
            if not isinstance(data, (bytes, bytearray)):
                state = str(readback.get("readback_state") or "READBACK_BYTES_MISSING")
                states.append(f"{snapshot_id}:ATTACHMENT_SNAPSHOT_READBACK_MISSING:{state}")
                continue
            content_type = str(
                attachment.get("content_type")
                or readback.get("content_type")
                or dict(readback.get("manifest", {}) or {}).get("content_type")
                or ""
            ).lower()
            blob = bytes(data)
            if "pdf" in content_type or blob.startswith(b"%PDF"):
                text, state = _extract_pdf_text(blob)
                taxonomy: list[str] = []
                parse_state = state
                if not text or "OCR_REQUIRED" in state:
                    try:
                        parser_carrier = dict(
                            self.stage3_service.parse_raw_snapshot(
                                snapshot_id,
                                repository=self.object_repository,
                            )
                        )
                    except Exception as exc:  # pragma: no cover - parser failures are source dependent
                        state = f"{state}:MARKITDOWN_FALLBACK_FAILED:{type(exc).__name__}"
                    else:
                        parsed_text = _attachment_parsed_field_text(parser_carrier)
                        audit = dict(parser_carrier.get("parser_audit") or {})
                        markitdown_state = str(audit.get("markitdown_state") or "").strip()
                        if markitdown_state:
                            state = f"{state}:{markitdown_state}"
                        taxonomy = [
                            str(item)
                            for item in list(parser_carrier.get("parse_error_taxonomy") or [])
                            if str(item or "").strip()
                        ]
                        parse_state = str(parser_carrier.get("parse_state") or state)
                        if parsed_text:
                            text = "\n".join(part for part in (text, parsed_text) if part)
                states.append(f"{snapshot_id}:{state}")
                snapshot_refs.append(
                    _attachment_snapshot_ref(
                        attachment=attachment,
                        snapshot_id=snapshot_id,
                        parse_state=parse_state,
                        attachment_type="PDF",
                        parse_error_taxonomy=taxonomy,
                    )
                )
                if text:
                    texts.append(text)
                    attribution = _file_parse_attribution(
                        project_id=project_id,
                        snapshot_id=snapshot_id,
                        source_url=str(attachment.get("attachment_url") or ""),
                        file_role="attachment",
                        parse_state=parse_state,
                        text=text,
                    )
                    text_probes.append(attribution)
                    file_attributions.append(attribution)
                    qualification_blocks.extend(_qualification_text_candidate_blocks(text))
                continue
            parser_carrier: dict[str, Any] = {}
            try:
                parser_carrier = dict(
                    self.stage3_service.parse_raw_snapshot(snapshot_id, repository=self.object_repository)
                )
            except Exception as exc:  # pragma: no cover - parser failures are source dependent
                states.append(f"{snapshot_id}:ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED:{type(exc).__name__}")
                snapshot_refs.append(
                    _attachment_snapshot_ref(
                        attachment=attachment,
                        snapshot_id=snapshot_id,
                        parse_state="ATTACHMENT_CAPTURE_BLOCKED_REVIEW_REQUIRED",
                        attachment_type="UNKNOWN_ATTACHMENT",
                    )
                )
                continue
            parsed_text = _attachment_parsed_field_text(parser_carrier)
            parse_state = str(parser_carrier.get("parse_state") or "REVIEW_REQUIRED")
            attachment_type = str(parser_carrier.get("attachment_type") or "")
            taxonomy = [
                str(item)
                for item in list(parser_carrier.get("parse_error_taxonomy") or [])
                if str(item or "").strip()
            ]
            audit = dict(parser_carrier.get("parser_audit") or {})
            markitdown_state = str(audit.get("markitdown_state") or "").strip()
            state_parts = [snapshot_id, attachment_type or "ATTACHMENT", parse_state]
            if markitdown_state:
                state_parts.append(markitdown_state)
            state_parts.extend(taxonomy[:4])
            states.append(":".join(state_parts))
            snapshot_refs.append(
                _attachment_snapshot_ref(
                    attachment=attachment,
                    snapshot_id=snapshot_id,
                    parse_state=parse_state,
                    attachment_type=attachment_type,
                    parse_error_taxonomy=taxonomy,
                )
            )
            if parsed_text:
                texts.append(parsed_text)
                attribution = _file_parse_attribution(
                    project_id=project_id,
                    snapshot_id=snapshot_id,
                    source_url=str(attachment.get("attachment_url") or ""),
                    file_role="attachment",
                    parse_state=parse_state,
                    text=parsed_text,
                )
                text_probes.append(attribution)
                file_attributions.append(attribution)
                qualification_blocks.extend(_qualification_text_candidate_blocks(parsed_text))
                continue
            decoded_text = _decode_snapshot_text(readback)
            decoded_state = "ATTACHMENT_TEXT_EXTRACTED" if decoded_text.strip() else "ATTACHMENT_TEXT_EMPTY"
            states.append(f"{snapshot_id}:{decoded_state}")
            if decoded_text.strip():
                texts.append(decoded_text)
                attribution = _file_parse_attribution(
                    project_id=project_id,
                    snapshot_id=snapshot_id,
                    source_url=str(attachment.get("attachment_url") or ""),
                    file_role="attachment",
                    parse_state=decoded_state,
                    text=decoded_text,
                )
                text_probes.append(attribution)
                file_attributions.append(attribution)
                qualification_blocks.extend(_qualification_text_candidate_blocks(decoded_text))
        return (
            "\n".join(texts),
            states,
            snapshot_refs,
            _dedupe_texts(qualification_blocks)[:20],
            text_probes[:20],
            file_attributions[:30],
        )

    def _capture_same_site_attachments(
        self,
        attachment_link_items: list[Any],
        *,
        candidate: Mapping[str, Any],
        candidate_key: str,
        parent_profile_id: str,
        detail_page_url: str,
        detail_snapshot_id: str,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        captures: list[dict[str, Any]] = []
        selected_items = attachment_link_items if limit is None else attachment_link_items[: max(0, limit)]
        for item in selected_items:
            link = dict(item or {}) if isinstance(item, Mapping) else {"url": str(item or "")}
            attachment_url = str(link.get("url") or "").strip()
            if not attachment_url:
                continue
            if "{{" in attachment_url or "}}" in attachment_url or "%7b%7b" in attachment_url.lower():
                failed_attachment = {
                    "attachment_url": attachment_url,
                    "attachment_link_text": str(link.get("text") or ""),
                }
                captures.append(
                    {
                        **failed_attachment,
                        "attachment_capture_status": "SKIPPED_TEMPLATE_PLACEHOLDER",
                        "attachment_snapshot_id_optional": "",
                        "attachment_role_type": _infer_attachment_role_type(failed_attachment),
                        "attachment_type": _attachment_format_type(failed_attachment),
                        "attachment_degraded_reasons": ["sichuan_template_placeholder_attachment_ignored"],
                        "attachment_failure_taxonomy": ["sichuan_template_placeholder_attachment_ignored"],
                        "review_required": True,
                    }
                )
                continue
            try:
                carrier = dict(
                    self.stage2_service.fetch_real_public_same_site_attachment_url(
                        attachment_url,
                        parent_profile_id=parent_profile_id,
                        repository=self.object_repository,
                        detail_page_url=detail_page_url,
                        lineage_refs={
                            "candidate_key": candidate_key,
                            "project_id": str(candidate.get("project_id") or ""),
                            "notice_id": str(candidate.get("notice_id") or ""),
                            "detail_snapshot_id": detail_snapshot_id,
                        },
                    )
                )
            except Exception as exc:
                failed_attachment = {
                    "attachment_url": attachment_url,
                    "attachment_link_text": str(link.get("text") or ""),
                }
                captures.append(
                    {
                        **failed_attachment,
                        "attachment_capture_status": "FAILED_CLOSED",
                        "attachment_snapshot_id_optional": "",
                        "attachment_role_type": _infer_attachment_role_type(failed_attachment),
                        "attachment_type": _attachment_format_type(failed_attachment),
                        "attachment_degraded_reasons": [str(exc)],
                        "review_required": True,
                    }
                )
                continue
            attachment_meta = {
                "attachment_url": attachment_url,
                "attachment_link_text": str(link.get("text") or ""),
                "attachment_filename": str(carrier.get("attachment_filename") or ""),
                "content_type": str(carrier.get("content_type") or ""),
            }
            captures.append(
                {
                    **attachment_meta,
                    "attachment_capture_status": str(carrier.get("status") or "UNKNOWN"),
                    "attachment_snapshot_id_optional": str(carrier.get("snapshot_id_optional") or ""),
                    "attachment_role_type": _infer_attachment_role_type(attachment_meta),
                    "attachment_type": _attachment_format_type(attachment_meta),
                    "byte_size": _as_int(carrier.get("byte_size"), 0),
                    "attachment_degraded_reasons": list(carrier.get("degraded_reasons", []) or []),
                    "attachment_blocker_class": str(carrier.get("attachment_blocker_class") or ""),
                    "attachment_blocker_reason": str(carrier.get("attachment_blocker_reason") or ""),
                    "attachment_failure_taxonomy": list(carrier.get("attachment_failure_taxonomy") or []),
                    "attachment_resolution_route": str(carrier.get("attachment_resolution_route") or ""),
                    "attachment_browser_replay_steps": list(carrier.get("attachment_browser_replay_steps") or []),
                    "automated_challenge_resolution_attempted": bool(
                        carrier.get("automated_challenge_resolution_attempted")
                        or carrier.get("automated_challenge_resume_used")
                    ),
                    "automated_challenge_resolution_state": str(
                        carrier.get("automated_challenge_resolution_state") or ""
                    ),
                    "challenge_resume_audit": dict(carrier.get("challenge_resume_audit") or {}),
                    "first_attempt_carrier": dict(carrier.get("first_attempt_carrier") or {}),
                    "review_required": bool(carrier.get("review_required")),
                }
            )
        return captures

    def _detail_fields(
        self,
        *,
        candidate: Mapping[str, Any],
        detail_carrier: Mapping[str, Any],
        parser_carrier: Mapping[str, Any],
        readback_text: str,
    ) -> dict[str, Any]:
        fields = _parser_fields_by_name(parser_carrier)
        text, detail_text_source = _preferred_detail_text(candidate, readback_text)
        parsed_title = _field_value(fields, "project_name", "announcement_title")
        detail_title = str(detail_carrier.get("title") or "").strip()
        generic_detail_titles = {"广州交易集团有限公司"}
        source_profile_id = str(candidate.get("source_profile_id") or "")
        title = (
            detail_title
            if (
                detail_title
                and (
                    parsed_title in generic_detail_titles
                    or source_profile_id == "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
                )
            )
            else parsed_title or detail_title or str(candidate.get("project_name") or "")
        )
        amount, amount_state = _extract_amount(text)
        candidate_company, candidate_company_state = _extract_candidate_company(text)
        work_lane = _infer_engineering_work_lane(
            f"{title} {text[:2000]}",
            str(candidate.get("project_type") or ""),
            title=title,
        )
        project_manager_identity = _extract_project_manager(
            text,
            work_lane=str(work_lane.get("engineering_work_lane") or ""),
        )
        fallback_certificate_identity = _extract_project_manager_certificate_identity(text)
        for key in (
            "project_manager_certificate_type",
            "project_manager_certificate_type_parse_state",
            "project_manager_cert_specialty",
            "project_manager_cert_specialty_parse_state",
            "project_manager_professional_title",
            "project_manager_professional_title_parse_state",
        ):
            if key.endswith("_parse_state"):
                base_key = key[: -len("_parse_state")]
                if not project_manager_identity.get(base_key) and fallback_certificate_identity.get(base_key):
                    project_manager_identity[key] = fallback_certificate_identity.get(key, project_manager_identity[key])
            elif not project_manager_identity.get(key) and fallback_certificate_identity.get(key):
                project_manager_identity[key] = fallback_certificate_identity[key]
        priority_profile = _verification_priority_profile(
            work_lane=str(work_lane.get("engineering_work_lane") or ""),
            identity=project_manager_identity,
        )
        responsible_table_company = str(
            project_manager_identity.get("candidate_company_from_responsible_table") or ""
        )
        if responsible_table_company:
            candidate_company = responsible_table_company
            candidate_company_state = project_manager_identity["primary_responsible_person_name_parse_state"]
        role_gap_diagnostics = _responsible_role_gap_diagnostics(
            text=text,
            title=title,
            work_lane=str(work_lane.get("engineering_work_lane") or ""),
            priority_profile=priority_profile,
            candidate_company=candidate_company,
        )
        deadline, deadline_state = _extract_deadline(text)
        notice_stage = _infer_notice_stage(f"{title} {text[:2000]}", str(candidate.get("notice_stage") or ""))
        detail_text_probe = _clip_text(text)
        return {
            "project_name": title,
            "notice_stage": notice_stage,
            "detail_text_source": detail_text_source,
            "detail_text_probe": detail_text_probe,
            "detail_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "detail_section_flags": _section_flags_for_text(text),
            **work_lane,
            **priority_profile,
            **role_gap_diagnostics,
            "amount": amount,
            "amount_parse_state": amount_state,
            "candidate_company": candidate_company,
            "candidate_company_parse_state": candidate_company_state,
            "primary_responsible_role": project_manager_identity["primary_responsible_role"],
            "primary_responsible_person_name": project_manager_identity["primary_responsible_person_name"],
            "primary_responsible_person_name_parse_state": project_manager_identity[
                "primary_responsible_person_name_parse_state"
            ],
            "chief_supervision_engineer_name": project_manager_identity["chief_supervision_engineer_name"],
            "chief_supervision_engineer_name_parse_state": project_manager_identity[
                "chief_supervision_engineer_name_parse_state"
            ],
            "design_lead_name": project_manager_identity["design_lead_name"],
            "design_lead_name_parse_state": project_manager_identity["design_lead_name_parse_state"],
            "survey_lead_name": project_manager_identity["survey_lead_name"],
            "survey_lead_name_parse_state": project_manager_identity["survey_lead_name_parse_state"],
            "project_manager_name": project_manager_identity["project_manager_name"],
            "project_manager_name_parse_state": project_manager_identity["project_manager_name_parse_state"],
            "project_manager_certificate_no": project_manager_identity["project_manager_certificate_no"],
            "project_manager_certificate_no_parse_state": project_manager_identity[
                "project_manager_certificate_no_parse_state"
            ],
            "project_manager_certificate_type": project_manager_identity["project_manager_certificate_type"],
            "project_manager_certificate_type_parse_state": project_manager_identity[
                "project_manager_certificate_type_parse_state"
            ],
            "project_manager_cert_specialty": project_manager_identity["project_manager_cert_specialty"],
            "project_manager_cert_specialty_parse_state": project_manager_identity[
                "project_manager_cert_specialty_parse_state"
            ],
            "project_manager_professional_title": project_manager_identity["project_manager_professional_title"],
            "project_manager_professional_title_parse_state": project_manager_identity[
                "project_manager_professional_title_parse_state"
            ],
            "objection_deadline_at_optional": deadline,
            "objection_deadline_parse_state": deadline_state,
            "parser_project_name": _field_value(fields, "project_name"),
            "parser_announcement_title": _field_value(fields, "announcement_title"),
            "parser_announcement_date": _field_value(fields, "announcement_date"),
        }

    def _enrich_candidate(self, candidate: Mapping[str, Any], capture: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(candidate)
        fields = dict(capture.get("detail_fields", {}) or {})
        detail_snapshot_id = str(capture.get("detail_snapshot_id_optional") or "")
        row["stage2_detail_capture_state"] = str(capture.get("detail_capture_status") or "")
        row["stage2_detail_snapshot_id_optional"] = detail_snapshot_id
        row["stage2_detail_capture_event_id_optional"] = str(
            dict(capture.get("capture_record", {}) or {}).get("capture_event_id") or ""
        )
        row["stage3_detail_parse_state"] = str(capture.get("stage3_parse_state") or "")
        document_summary = dict(
            capture.get("document_completeness_summary")
            or _document_completeness_summary(capture)
        )
        row["document_completeness_state"] = str(
            capture.get("document_completeness_state")
            or document_summary.get("document_completeness_state")
            or ""
        )
        row["document_completeness_summary"] = document_summary
        row["notice_version_chain_state"] = str(
            capture.get("notice_version_chain_state")
            or document_summary.get("notice_version_chain_state")
            or ""
        )
        row["download_archive_manifest"] = dict(
            capture.get("download_archive_manifest")
            or document_summary.get("download_archive_manifest")
            or {}
        )
        row["stage2_attachment_link_count"] = _as_int(capture.get("attachment_link_count"), 0)
        row["same_site_attachment_link_items"] = list(capture.get("same_site_attachment_link_items", []) or [])
        attachment_snapshot_refs = [
            ref
            for ref in list(fields.get("attachment_snapshot_refs") or [])
            if isinstance(ref, Mapping) and str(ref.get("snapshot_id") or "").strip()
        ]
        attachment_snapshot_ids = [str(ref.get("snapshot_id") or "") for ref in attachment_snapshot_refs]
        row["stage2_attachment_snapshot_count"] = len(attachment_snapshot_ids)
        row["stage2_attachment_snapshot_ids"] = attachment_snapshot_ids
        row["stage2_attachment_captures"] = list(capture.get("attachment_captures", []) or [])
        row["stage2_attachment_types"] = list(document_summary.get("attachment_types") or [])
        row["stage2_attachment_role_types"] = list(document_summary.get("attachment_role_types") or [])
        row["stage2_attachment_parse_error_taxonomy"] = list(
            document_summary.get("attachment_parse_error_taxonomy") or []
        )
        row["stage2_attachment_failure_reasons"] = list(document_summary.get("failure_reasons") or [])
        row["attachment_text_merge_state"] = str(fields.get("attachment_text_merge_state") or "")
        row["attachment_text_parse_states"] = list(fields.get("attachment_text_parse_states") or [])
        row["detail_text_probe"] = str(fields.get("detail_text_probe") or "")
        row["guangzhou_ywtb_download_discovery_state"] = str(
            fields.get("guangzhou_ywtb_download_discovery_state") or ""
        )
        row["guangzhou_ywtb_download_diagnostics"] = dict(
            fields.get("guangzhou_ywtb_download_diagnostics") or {}
        )
        row["attachment_text_probes"] = list(fields.get("attachment_text_probes") or [])
        row["file_parse_attributions"] = list(fields.get("file_parse_attributions") or [])
        row["attachment_snapshot_refs"] = attachment_snapshot_refs
        row["qualification_text_candidate_blocks"] = list(fields.get("qualification_text_candidate_blocks") or [])
        row["attachment_ocr_required_count"] = _as_int(fields.get("attachment_ocr_required_count"), 0)
        row["attachment_ocr_extracted_count"] = _as_int(fields.get("attachment_ocr_extracted_count"), 0)
        if fields.get("project_name"):
            row["project_name"] = str(fields["project_name"])
        if fields.get("notice_stage"):
            row["notice_stage"] = str(fields["notice_stage"])
        if fields.get("amount") is not None:
            row["amount"] = fields["amount"]
            row["estimated_amount"] = fields["amount"]
            row["amount_parse_state"] = fields.get("amount_parse_state") or "DETAIL_TEXT"
        elif row.get("amount") in (None, ""):
            row["amount_parse_state"] = fields.get("amount_parse_state") or row.get("amount_parse_state") or "DETAIL_TEXT_NOT_FOUND"
        if fields.get("candidate_company"):
            row["candidate_company"] = str(fields["candidate_company"])
            row["candidate_company_parse_state"] = fields.get("candidate_company_parse_state") or "DETAIL_TEXT"
        else:
            row["candidate_company_parse_state"] = fields.get("candidate_company_parse_state") or "DETAIL_TEXT_NOT_FOUND"
        for key in (
            "engineering_work_lane",
            "engineering_work_lane_parse_state",
            "engineering_role_route",
            "opportunity_priority_class",
            "verification_priority_band",
            "verification_focus",
            "expected_responsible_role_field",
            "responsible_role_gap_code",
            "responsible_role_gap_root_cause",
            "responsible_role_gap_source_evidence",
            "stage4_identity_completion_route",
            "stage4_identity_completion_blocker",
            "primary_responsible_role",
            "primary_responsible_person_name",
            "primary_responsible_person_name_parse_state",
            "chief_supervision_engineer_name",
            "chief_supervision_engineer_name_parse_state",
            "design_lead_name",
            "design_lead_name_parse_state",
            "survey_lead_name",
            "survey_lead_name_parse_state",
        ):
            if fields.get(key):
                row[key] = str(fields[key])
        row["responsible_role_gap_token_hits"] = list(fields.get("responsible_role_gap_token_hits") or [])
        row["stage4_identity_completion_targets"] = list(fields.get("stage4_identity_completion_targets") or [])
        row["expected_responsible_role_present"] = bool(fields.get("expected_responsible_role_present"))
        row["responsible_role_gap_review_required"] = bool(fields.get("responsible_role_gap_review_required"))
        row["stage4_identity_completion_required"] = bool(fields.get("stage4_identity_completion_required"))
        if fields.get("project_manager_name"):
            row["project_manager_name"] = str(fields["project_manager_name"])
            row["project_manager_name_parse_state"] = fields.get("project_manager_name_parse_state") or "DETAIL_TEXT"
        else:
            row["project_manager_name_parse_state"] = fields.get("project_manager_name_parse_state") or "DETAIL_TEXT_NOT_FOUND"
        if fields.get("project_manager_certificate_no"):
            row["project_manager_certificate_no"] = str(fields["project_manager_certificate_no"])
            row["project_manager_certificate_no_parse_state"] = (
                fields.get("project_manager_certificate_no_parse_state") or "DETAIL_TEXT"
            )
        else:
            row["project_manager_certificate_no_parse_state"] = (
                fields.get("project_manager_certificate_no_parse_state") or "DETAIL_TEXT_NOT_FOUND"
            )
        if fields.get("project_manager_certificate_type"):
            row["project_manager_certificate_type"] = str(fields["project_manager_certificate_type"])
            row["project_manager_certificate_type_parse_state"] = (
                fields.get("project_manager_certificate_type_parse_state") or "DETAIL_TEXT"
            )
        else:
            row["project_manager_certificate_type_parse_state"] = (
                fields.get("project_manager_certificate_type_parse_state") or "DETAIL_TEXT_NOT_FOUND"
            )
        if fields.get("project_manager_cert_specialty"):
            row["project_manager_cert_specialty"] = str(fields["project_manager_cert_specialty"])
            row["project_manager_cert_specialty_parse_state"] = (
                fields.get("project_manager_cert_specialty_parse_state") or "DETAIL_TEXT"
            )
        else:
            row["project_manager_cert_specialty_parse_state"] = (
                fields.get("project_manager_cert_specialty_parse_state") or "DETAIL_TEXT_NOT_FOUND"
            )
        if fields.get("project_manager_professional_title"):
            row["project_manager_professional_title"] = str(fields["project_manager_professional_title"])
            row["project_manager_professional_title_parse_state"] = (
                fields.get("project_manager_professional_title_parse_state") or "DETAIL_TEXT"
            )
        else:
            row["project_manager_professional_title_parse_state"] = (
                fields.get("project_manager_professional_title_parse_state") or "DETAIL_TEXT_NOT_FOUND"
            )
        if fields.get("objection_deadline_at_optional"):
            row["objection_deadline_at_optional"] = str(fields["objection_deadline_at_optional"])
        if detail_snapshot_id:
            row["source_document_ref"] = detail_snapshot_id
            row["source_slice_ref"] = detail_snapshot_id
            row["real_snapshot_ids"] = [
                item
                for item in (
                    str(row.get("snapshot_id_optional") or ""),
                    detail_snapshot_id,
                    *attachment_snapshot_ids,
                )
                if item
            ]
        if row.get("candidate_company") and _as_int(row.get("candidate_count"), 0) < 1:
            row["candidate_count"] = 1
            row["competitor_count"] = max(_as_int(row.get("competitor_count"), 0), 1)
        row["key_fields_present"] = _candidate_key_fields(row)
        row["sellability_evidence_state"] = (
            "REAL_DETAIL_AND_ATTACHMENT_SNAPSHOTS_PARSED_NEEDS_STAGE4_TO_STAGE9"
            if detail_snapshot_id and attachment_snapshot_ids
            else "REAL_DETAIL_SNAPSHOT_PARSED_NEEDS_STAGE4_TO_STAGE9"
            if detail_snapshot_id
            else "REAL_LIST_PAGE_CANDIDATE_NEEDS_DETAIL_CAPTURE"
        )
        row["truth_boundary"] = (
            "真实详情页和同站附件快照已保存；客户可售前仍需 Stage4-9 消费快照并完成证据回链。"
            if detail_snapshot_id and attachment_snapshot_ids
            else
            "真实详情页快照已保存并完成 Stage3 读回；客户可售前仍需 Stage4-9 消费该快照并完成证据回链。"
            if detail_snapshot_id
            else "真实列表页候选已入库；详情页快照未完成，不能形成客户可售证据。"
        )
        return row


def list_real_candidate_stage2_captures(*, limit: int = 100) -> dict[str, Any]:
    return RealCandidateStage2CaptureRepository().list_captures(limit=limit)


__all__ = [
    "DEFAULT_DETAIL_CAPTURE_LIMIT",
    "DEFAULT_ATTACHMENT_CAPTURE_LIMIT",
    "DEFAULT_DETAIL_CAPTURE_TIME_BUDGET_SECONDS",
    "REAL_CANDIDATE_STAGE2_CAPTURE_MODE",
    "REAL_CANDIDATE_STAGE2_CAPTURE_WORK_ITEM_ID",
    "RealCandidateStage2CaptureRepository",
    "RealCandidateStage2CaptureService",
    "list_real_candidate_stage2_captures",
]
