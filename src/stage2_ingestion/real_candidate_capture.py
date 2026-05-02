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
        if value and not any(token in value for token in ("投标报价", "质量承诺", "工期", "资质资格", "项目负责人")):
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
    if any(token in text for token in ("造价咨询", "第三方监测", "检测服务", "监测及检测", "咨询服务")):
        return {
            "engineering_work_lane": "supplier_service",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "supplier_qualification_credit_chain",
        }
    if any(token in text for token in ("勘察设计施工总承包", "设计施工总承包", "EPC", "工程总承包", "施工总承包")):
        return {
            "engineering_work_lane": "construction_or_epc",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "project_manager_identity_chain",
        }
    if "勘察设计" in text or ("勘察" in text and "设计" in text and "施工" not in text):
        return {
            "engineering_work_lane": "survey_design",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "survey_design_responsible_person_identity_chain",
        }
    if any(token in text for token in ("施工监理", "工程监理", "监理服务", "总监理工程师", "总监")):
        return {
            "engineering_work_lane": "supervision",
            "engineering_work_lane_parse_state": parse_state,
            "engineering_role_route": "chief_supervision_engineer_identity_chain",
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
    if any(token in text for token in ("设备", "材料", "采购", "服务")):
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
        rf"(?P<name>[\u4e00-\u9fff·]{{2,8}})\s*/\s*(?P<cert>[A-Za-z0-9\-]{{5,40}})",
        rf"(?:项目总负责人姓名|项目总负责人|项目负责人姓名|项目负责人).{{0,220}}?{company_pattern}.{{0,220}}?"
        rf"(?P<name>[\u4e00-\u9fff·]{{2,8}})\s*/\s*(?P<cert>[A-Za-z0-9\-]{{5,40}})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        name = _clean_text(match.group("name")).strip(" ：:，,；;。")
        cert = _clean_text(match.group("cert")).strip(" ：:，,；;。")
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
    body_match = re.search(
        r"(?:项目总负责人姓名及资格证书\s*编号|项目总负责人姓名及资格证书编号|"
        r"项目负责人姓名及资格证书\s*编号|项目负责人姓名及资格证书编号|项目负责人姓名/资格证书编号|"
        r"项目总负责人|项目负责人)"
        r"(?P<body>.{0,420})",
        text,
    )
    if body_match:
        body = body_match.group("body")
        for match in re.finditer(
            r"(?P<company>[\u4e00-\u9fffA-Za-z0-9（）()·\-\s]{2,100}?"
            r"(?:有限\s*公司|股份\s*有限公司|集团\s*有限公司|设计院(?!\s*有限\s*公司)|研究院(?!\s*有限\s*公司)|事务所|联合体))"
            r"\s+(?:\d[\d,.]*\s*(?:元|%)?\s+){1,4}"
            r"(?P<name>[\u4e00-\u9fff·]{2,8})(?:(?:\s*/\s*|\s+)(?P<cert>[A-Za-z0-9\-]{5,40}))?",
            body,
        ):
            name = _clean_text(match.group("name")).strip(" ：:，,；;。")
            if not _looks_like_person_name(name):
                continue
            cert = _clean_text(match.group("cert") or "").strip(" ：:，,；;。")
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
    if not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", name):
        return False
    non_name_tokens = (
        "项目",
        "负责人",
        "经理",
        "建造师",
        "工程师",
        "公司",
        "集团",
        "设计",
        "建设",
        "工程",
        "咨询",
        "管理",
        "有限",
        "注册",
        "证书",
        "资格",
        "资质",
        "专业",
        "标段",
        "施工",
        "监理",
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
        (r"注册监理工程师|监理工程师注册证书", "注册监理工程师"),
        (r"一级注册建筑师|一级建筑师", "一级注册建筑师"),
        (r"二级注册建筑师|二级建筑师", "二级注册建筑师"),
        (r"注册建筑师", "注册建筑师"),
        (r"注册土木工程师[（(]岩土[）)]|注册岩土工程师", "注册土木工程师（岩土）"),
        (r"注册电气工程师(?:（[^）]+）)?", None),
        (r"注册(?:土木|结构|公用设备|造价|安全)工程师(?:（[^）]+）)?", None),
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
        r"(?:注册编号|注册编\s*号|注册证书编号|证书编号|注册号)\s*[:：]?\s*([A-Za-z0-9\-]{4,40})",
        r"(?:证号)\s*[:：]\s*([A-Za-z0-9\-]{4,40})",
    )
    certificate_search_text = search_text if primary_name or manager_name else _project_manager_certificate_context(search_text)
    for pattern in cert_patterns:
        if not certificate_search_text:
            break
        match = re.search(pattern, certificate_search_text)
        if match:
            certificate_no = _clean_text(match.group(1)).strip(" ：:，,；;。")
            certificate_state = "DETAIL_TEXT_CANDIDATE_TABLE"
            break
    if not certificate_no and "table_role_cert" in locals() and table_role_cert:
        certificate_no = table_role_cert
        certificate_state = table_role_state
    identity = _extract_project_manager_certificate_identity(certificate_search_text or search_text)
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
                "captured_at": action.requested_at,
                "repository_backed": True,
            }
        )
        return capture


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
            "attachment_snapshot_count": sum(_as_int(item.get("attachment_snapshot_count"), 0) for item in captures),
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
            if (
                key in requested_keys
                and key not in existing
                and str(capture.get("detail_snapshot_id_optional") or "").strip()
            ):
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
            readback_text = _decode_snapshot_text(replay)
            parser_carrier = dict(
                self.stage3_service.parse_raw_snapshot(snapshot_id, repository=self.object_repository)
            )
        except Exception:
            return dict(capture)
        refreshed = dict(capture)
        detail_carrier = {
            "title": capture.get("detail_title") or capture.get("project_name") or candidate.get("project_name"),
        }
        refreshed["detail_fields"] = self._detail_fields(
            candidate=candidate,
            detail_carrier=detail_carrier,
            parser_carrier=parser_carrier,
            readback_text=readback_text,
        )
        refreshed["stage3_parse_state"] = str(parser_carrier.get("parse_state") or capture.get("stage3_parse_state") or "NOT_RUN")
        refreshed["stage3_parse_error_taxonomy"] = list(
            parser_carrier.get("parse_error_taxonomy", []) or capture.get("stage3_parse_error_taxonomy", []) or []
        )
        refreshed["parsed_field_count"] = len(parser_carrier.get("parsed_fields", []) or [])
        return refreshed

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
        attachment_text, attachment_text_states = self._attachment_text_bundle(attachment_captures)
        combined_readback_text = "\n".join(
            part for part in (readback_text, attachment_text) if str(part or "").strip()
        )
        detail_fields = self._detail_fields(
            candidate=candidate,
            detail_carrier=detail_carrier,
            parser_carrier=parser_carrier,
            readback_text=combined_readback_text or readback_text,
        )
        if attachment_text_states:
            detail_fields["attachment_text_parse_states"] = attachment_text_states
            detail_fields["attachment_text_merge_state"] = (
                "ATTACHMENT_TEXT_MERGED" if attachment_text else "ATTACHMENT_TEXT_NOT_EXTRACTED"
            )
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
            "stage3_parse_state": str(parser_carrier.get("parse_state") or "NOT_RUN"),
            "stage3_parse_error_taxonomy": list(parser_carrier.get("parse_error_taxonomy", []) or []),
            "parsed_field_count": len(parser_carrier.get("parsed_fields", []) or []),
            "detail_fields": detail_fields,
            "attachment_link_count": len(attachment_link_items),
            "same_site_attachment_link_items": attachment_link_items,
            "attachment_capture_attempted_count": len(attachment_captures),
            "attachment_snapshot_count": sum(1 for item in attachment_captures if item.get("attachment_snapshot_id_optional")),
            "attachment_captures": attachment_captures,
            "snapshot_readback_path_optional": f"/operator-console/real-source-runs/{snapshot_id}" if snapshot_id else "",
        }
        capture["capture_record"] = self.repository.persist_capture(candidate=candidate, capture=capture, now=captured_at)
        return capture

    def _attachment_text_bundle(self, attachment_captures: list[Mapping[str, Any]]) -> tuple[str, list[str]]:
        texts: list[str] = []
        states: list[str] = []
        for attachment in attachment_captures:
            snapshot_id = str(attachment.get("attachment_snapshot_id_optional") or "").strip()
            if not snapshot_id:
                continue
            try:
                readback = self.object_repository.replay_snapshot(snapshot_id)
            except Exception as exc:  # pragma: no cover - repository corruption varies
                states.append(f"{snapshot_id}:READBACK_FAILED:{type(exc).__name__}")
                continue
            data = readback.get("bytes")
            if not isinstance(data, (bytes, bytearray)):
                states.append(f"{snapshot_id}:READBACK_BYTES_MISSING")
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
                states.append(f"{snapshot_id}:{state}")
                if text:
                    texts.append(text)
                continue
            text = _decode_snapshot_text(readback)
            state = "ATTACHMENT_TEXT_EXTRACTED" if text.strip() else "ATTACHMENT_TEXT_EMPTY"
            states.append(f"{snapshot_id}:{state}")
            if text.strip():
                texts.append(text)
        return "\n".join(texts), states

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
                captures.append(
                    {
                        "attachment_url": attachment_url,
                        "attachment_link_text": str(link.get("text") or ""),
                        "attachment_capture_status": "FAILED_CLOSED",
                        "attachment_snapshot_id_optional": "",
                        "attachment_degraded_reasons": [str(exc)],
                        "review_required": True,
                    }
                )
                continue
            captures.append(
                {
                    "attachment_url": attachment_url,
                    "attachment_link_text": str(link.get("text") or ""),
                    "attachment_capture_status": str(carrier.get("status") or "UNKNOWN"),
                    "attachment_snapshot_id_optional": str(carrier.get("snapshot_id_optional") or ""),
                    "attachment_filename": str(carrier.get("attachment_filename") or ""),
                    "content_type": str(carrier.get("content_type") or ""),
                    "byte_size": _as_int(carrier.get("byte_size"), 0),
                    "attachment_degraded_reasons": list(carrier.get("degraded_reasons", []) or []),
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
        text = _clean_text(readback_text)
        title = (
            _field_value(fields, "project_name", "announcement_title")
            or str(detail_carrier.get("title") or "")
            or str(candidate.get("project_name") or "")
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
        responsible_table_company = str(
            project_manager_identity.get("candidate_company_from_responsible_table") or ""
        )
        if responsible_table_company:
            candidate_company = responsible_table_company
            candidate_company_state = project_manager_identity["primary_responsible_person_name_parse_state"]
        deadline, deadline_state = _extract_deadline(text)
        notice_stage = _infer_notice_stage(f"{title} {text[:2000]}", str(candidate.get("notice_stage") or ""))
        return {
            "project_name": title,
            "notice_stage": notice_stage,
            **work_lane,
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
        row["stage2_attachment_link_count"] = _as_int(capture.get("attachment_link_count"), 0)
        row["same_site_attachment_link_items"] = list(capture.get("same_site_attachment_link_items", []) or [])
        attachment_snapshot_ids = [
            str(item.get("attachment_snapshot_id_optional") or "")
            for item in list(capture.get("attachment_captures", []) or [])
            if str(item.get("attachment_snapshot_id_optional") or "")
        ]
        row["stage2_attachment_snapshot_count"] = len(attachment_snapshot_ids)
        row["stage2_attachment_snapshot_ids"] = attachment_snapshot_ids
        row["stage2_attachment_captures"] = list(capture.get("attachment_captures", []) or [])
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
