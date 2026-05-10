from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Mapping
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from shared.utils import build_id, utc_now_iso
from stage1_tasking.region_adapters import (
    list_region_source_adapters,
    resolve_region_source_adapter,
    resolve_source_quality_policy,
)
from stage2_ingestion.real_public_url_fetcher import (
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    RealPublicEntryFetcher,
)
from storage.db import PersistedOperatorAction, build_persisted_at
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.operator_action_repo import OperatorActionRepository


REAL_PUBLIC_SOURCE_CANDIDATE_MODE = "REAL_PUBLIC_SOURCE_CANDIDATES"
REAL_CANDIDATE_DISCOVERY_RUN_WORK_ITEM_ID = "operator-real-candidate-discovery-runs"
REAL_CANDIDATE_DISCOVERY_CANDIDATE_WORK_ITEM_ID = "operator-real-candidate-discovery-candidates"

DEFAULT_DISCOVERY_PROFILE_LIMIT_PER_REGION = 3
GUANGDONG_STAGE1_6_VALIDATION_CANDIDATE_LIMIT = 30
GUANGDONG_DISCOVERY_PAGE_SIZE = 50
MAX_GUANGDONG_DISCOVERY_PAGES = 1
GUANGZHOU_YWTB_PROFILE_ID = "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
GUANGZHOU_YWTB_DISCOVERY_PAGE_SIZE = 50
GUANGZHOU_YWTB_FLOW_INTERFACE_PAGE_LIMIT = 8
GUANGZHOU_YWTB_FLOW_INTERFACE_SAMPLE_LIMIT = 2
GUANGZHOU_YWTB_FLOW_INTERFACE_MONTH_WINDOWS = 12
GUANGZHOU_YWTB_CONSTRUCTION_CATEGORY_NUM = "002001001"
GUANGZHOU_YWTB_TENDER_NOTICE_TYPE = "01"
GUANGZHOU_YWTB_QUALIFICATION_RESULT_TYPE = "02"
GUANGZHOU_YWTB_CANDIDATE_NOTICE_TYPE = "03"
GUANGZHOU_YWTB_BID_FILE_PUBLIC_TYPE = "04"
GUANGZHOU_YWTB_AWARD_INFO_TYPE = "05"
GUANGZHOU_YWTB_AWARD_RESULT_TYPE = "06"
GUANGZHOU_YWTB_BID_PLAN_TYPE = "08"
GUANGZHOU_YWTB_CONTRACT_PUBLIC_TYPE = "15"
GUANGZHOU_YWTB_TENDER_FILE_PUBLICITY_TYPE = "17"
GUANGZHOU_YWTB_CLARIFICATION_TYPE = "18"
GUANGZHOU_YWTB_OPENING_INFO_TYPE = "19"
GUANGZHOU_YWTB_PROJECT_EXCEPTION_TYPE = "20"
GUANGZHOU_YWTB_PROCESS_METADATA = {
    GUANGZHOU_YWTB_BID_PLAN_TYPE: {
        "process_label": "bid_plan",
        "dataset_name": "招标计划",
        "notice_third_type_desc": "招标计划",
        "guangzhou_flow_no": "01",
        "guangzhou_flow_title": "招标计划",
    },
    GUANGZHOU_YWTB_TENDER_FILE_PUBLICITY_TYPE: {
        "process_label": "tender_file_publicity",
        "dataset_name": "招标文件公示",
        "notice_third_type_desc": "招标文件公示",
        "guangzhou_flow_no": "02",
        "guangzhou_flow_title": "招标文件公示",
    },
    GUANGZHOU_YWTB_TENDER_NOTICE_TYPE: {
        "process_label": "tender_notice",
        "dataset_name": "招标公告/关联公告",
        "notice_third_type_desc": "招标公告/关联公告",
        "guangzhou_flow_no": "03",
        "guangzhou_flow_title": "招标公告/关联公告",
    },
    GUANGZHOU_YWTB_CLARIFICATION_TYPE: {
        "process_label": "clarification_notice",
        "dataset_name": "澄清答疑",
        "notice_third_type_desc": "澄清答疑",
        "guangzhou_flow_no": "04",
        "guangzhou_flow_title": "澄清答疑",
    },
    GUANGZHOU_YWTB_OPENING_INFO_TYPE: {
        "process_label": "opening_info",
        "dataset_name": "开标信息",
        "notice_third_type_desc": "开标信息",
        "guangzhou_flow_no": "05",
        "guangzhou_flow_title": "开标信息",
    },
    GUANGZHOU_YWTB_QUALIFICATION_RESULT_TYPE: {
        "process_label": "qualification_review_result",
        "dataset_name": "资审结果公示",
        "notice_third_type_desc": "资审结果公示",
        "guangzhou_flow_no": "06",
        "guangzhou_flow_title": "资审结果公示",
    },
    GUANGZHOU_YWTB_CANDIDATE_NOTICE_TYPE: {
        "process_label": "candidate_publicity",
        "dataset_name": "中标候选人公示",
        "notice_third_type_desc": "中标候选人公示",
        "guangzhou_flow_no": "07",
        "guangzhou_flow_title": "中标候选人公示",
    },
    GUANGZHOU_YWTB_BID_FILE_PUBLIC_TYPE: {
        "process_label": "bid_file_publicity",
        "dataset_name": "投标(资格预审申请)文件公开",
        "notice_third_type_desc": "投标(资格预审申请)文件公开",
        "guangzhou_flow_no": "08",
        "guangzhou_flow_title": "投标(资格预审申请)文件公开",
    },
    GUANGZHOU_YWTB_AWARD_RESULT_TYPE: {
        "process_label": "award_result",
        "dataset_name": "中标结果公示/公告",
        "notice_third_type_desc": "中标结果公示/公告",
        "guangzhou_flow_no": "09",
        "guangzhou_flow_title": "中标结果公示/公告",
    },
    GUANGZHOU_YWTB_AWARD_INFO_TYPE: {
        "process_label": "award_info",
        "dataset_name": "中标信息",
        "notice_third_type_desc": "中标信息",
        "guangzhou_flow_no": "10",
        "guangzhou_flow_title": "中标信息",
    },
    GUANGZHOU_YWTB_CONTRACT_PUBLIC_TYPE: {
        "process_label": "contract_public_info",
        "dataset_name": "合同信息公开",
        "notice_third_type_desc": "合同信息公开",
        "guangzhou_flow_no": "11",
        "guangzhou_flow_title": "合同信息公开",
    },
    GUANGZHOU_YWTB_PROJECT_EXCEPTION_TYPE: {
        "process_label": "project_exception",
        "dataset_name": "项目异常",
        "notice_third_type_desc": "项目异常",
        "guangzhou_flow_no": "12",
        "guangzhou_flow_title": "项目异常",
    },
}
GUANGZHOU_YWTB_DOCUMENT_KIND_TO_PROCESS = {
    "bid_plan": (GUANGZHOU_YWTB_BID_PLAN_TYPE,),
    "tender_file_publicity": (GUANGZHOU_YWTB_TENDER_FILE_PUBLICITY_TYPE,),
    "tender_file": (GUANGZHOU_YWTB_TENDER_NOTICE_TYPE,),
    "clarification_notice": (GUANGZHOU_YWTB_CLARIFICATION_TYPE,),
    "opening_info": (GUANGZHOU_YWTB_OPENING_INFO_TYPE,),
    "qualification_review_result": (GUANGZHOU_YWTB_QUALIFICATION_RESULT_TYPE,),
    "candidate_notice": (GUANGZHOU_YWTB_CANDIDATE_NOTICE_TYPE,),
    "bid_file_publicity": (GUANGZHOU_YWTB_BID_FILE_PUBLIC_TYPE,),
    "award_result": (GUANGZHOU_YWTB_AWARD_RESULT_TYPE,),
    "award_info": (GUANGZHOU_YWTB_AWARD_INFO_TYPE,),
    "contract_public_info": (GUANGZHOU_YWTB_CONTRACT_PUBLIC_TYPE,),
    "project_exception": (GUANGZHOU_YWTB_PROJECT_EXCEPTION_TYPE,),
}
_PROJECT_TYPE_LABELS = {
    "construction": "房建工程",
    "municipal": "市政工程",
    "highway": "公路交通",
    "water_conservancy": "水利工程",
}

_PROVINCE_ADMIN_CODE_TO_REGION = {
    "110000": "CN-BJ",
    "310000": "CN-SH",
    "320000": "CN-JS",
    "330000": "CN-ZJ",
    "370000": "CN-SD",
    "420000": "CN-HB",
    "440000": "CN-GD",
    "510000": "CN-SC",
    "530000": "CN-YN",
}

_BROWSER_RENDERED_REALTIME_PROFILE_IDS = {
    GUANGZHOU_YWTB_PROFILE_ID,
}

_PROVINCE_REALTIME_PROFILE_IDS = {
    GUANGZHOU_YWTB_PROFILE_ID,
    "JIANGSU-GGZY-HOME",
    "ZHEJIANG-GGZY-JYXXGK-LIST",
    "SHANDONG-GGZY-JYXXGK-LIST",
    "HUBEI-BIDCLOUD-JYXX-LIST",
    "SICHUAN-GGZY-TRANSACTION-INFO",
}

EXCLUDED_DISCOVERY_PROFILE_IDS: set[str] = set()

_GENERIC_NAV_TITLE_EXACTS = {
    "首页",
    "通知公告",
    "交易公开",
    "交易信息",
    "主体信息",
    "信用信息",
    "政策文件",
    "政策法规",
    "服务指南",
    "办事指南",
    "互动交流",
    "关于我们",
    "查看更多",
    "更多",
    "工程建设",
    "政府采购",
    "土地矿业",
    "产权交易",
    "药械采购",
    "项目注册",
    "房建市政",
    "水利工程",
    "交通工程",
    "招标公告",
    "中标公告",
    "中标候选人公示",
    "结果公告",
    "onlinelettersubmit",
    "生产要素",
}

_NON_PROJECT_DETAIL_PATH_TOKENS = (
    "onlinelettersubmit",
    "login",
    "userlogin",
    "register",
    "wechat",
    "wxlogin",
    "letter",
    "mailbox",
    "consult",
    "feedback",
    "complaintsubmit",
    "appeal",
    "serviceguide",
    "transactioninfoscys",
)

_NON_PROJECT_DETAIL_TITLE_TOKENS = (
    "登录",
    "注册",
    "留言",
    "在线留言",
    "办件",
    "咨询",
    "投诉提交",
    "意见反馈",
)

_NOTICE_TITLE_TOKENS = (
    "公告",
    "公示",
    "招标",
    "中标",
    "成交",
    "评标",
    "结果",
    "更正",
    "变更",
    "澄清",
    "答疑",
    "补遗",
    "合同",
    "采购",
    "资格预审",
    "招标计划",
)

_PROJECT_TITLE_TOKENS = (
    "工程",
    "项目",
    "施工",
    "监理",
    "设计",
    "改造",
    "建设",
    "道路",
    "公路",
    "桥梁",
    "管网",
    "排水",
    "污水",
    "水利",
    "河道",
    "灌区",
    "水库",
    "学校",
    "医院",
    "中心",
    "小区",
    "园区",
    "标段",
    "epc",
)

_NON_ACTIONABLE_NOTICE_TOKENS = (
    "暂停招标",
    "终止招标",
    "招标失败",
    "流标",
    "废标",
    "异常公告",
    "投诉处理",
    "投诉决定",
    "监督检查",
    "行政处罚",
    "典型案例",
)

_TEST_OR_PLACEHOLDER_NOTICE_TOKENS = (
    "测试",
    "测-试",
    "test",
    "demo",
)

_FILE_NAME_ONLY_NOTICE_EXTENSIONS = (
    ".cdz",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
)


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _present_text(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _is_guangdong_stage1_6_validation_scope(region_codes: list[str]) -> bool:
    return bool(region_codes) and all(str(code).upper() == "CN-GD" for code in region_codes)


def _as_string_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        raw = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = [value]
    items: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items or list(default)


def _dedupe_texts(values: Any) -> list[str]:
    items: list[str] = []
    for value in list(values or []):
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _slug(value: Any, default: str = "ITEM") -> str:
    token = "".join(
        char.upper() if char.isascii() and char.isalnum() else "-"
        for char in str(value or "").strip()
    ).strip("-")
    token = "-".join(part for part in token.split("-") if part)
    return token or default


def _hash_text(value: Any, length: int = 16) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:length]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _project_type_label(project_type: str) -> str:
    return _PROJECT_TYPE_LABELS.get(project_type, project_type)


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(text).split())


def _normalize_public_title(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", text)
    return text


def _title_from_url(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1] if path else url
    name = re.sub(r"\.(html?|shtml)$", "", name, flags=re.IGNORECASE)
    return name or "公开来源候选"


def _infer_notice_stage(text: str) -> str:
    normalized = str(text or "").replace(" ", "")
    if any(token in normalized for token in ("候选人", "中标候选", "成交候选", "评标报告", "评标结果公示")):
        return "candidate_notice"
    if any(token in normalized for token in ("中标结果", "成交结果", "结果公告", "中标公告", "成交公告")):
        return "award_result"
    if any(token in normalized for token in ("更正", "变更", "澄清", "答疑", "补遗")):
        return "correction_notice"
    if any(token in normalized for token in ("采购", "招标", "公告", "交易")):
        return "tender_notice"
    return "procurement_notice"


def _infer_project_type(text: str, requested_project_types: list[str]) -> tuple[str, str]:
    normalized = str(text or "").replace(" ", "")
    if any(token in normalized for token in ("市政", "管网", "排水", "污水", "道路")):
        inferred = "municipal"
    elif any(token in normalized for token in ("公路", "交通", "路基", "桥梁")):
        inferred = "highway"
    elif any(token in normalized for token in ("水利", "河道", "灌区", "水库")):
        inferred = "water_conservancy"
    elif any(token in normalized for token in ("房建", "建筑", "施工", "工程", "改造")):
        inferred = "construction"
    else:
        inferred = ""
    if inferred:
        return inferred, "TITLE_KEYWORD"
    return (requested_project_types[0] if requested_project_types else "construction"), "SEARCH_SCOPE_DEFAULT"


def _extract_amount(text: str) -> tuple[float | None, str]:
    normalized = text.replace(",", "")
    for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*(万元|万|元)", normalized):
        number = _as_float(match.group(1))
        if number is None:
            continue
        unit = match.group(2)
        amount = number * 10000 if unit in {"万", "万元"} else number
        return amount, "TITLE_TEXT"
    return None, "NOT_FOUND"


def _region_from_source_url(url: str) -> str:
    match = re.search(r"/a/([0-9]{6})/", url)
    if match:
        return _PROVINCE_ADMIN_CODE_TO_REGION.get(match.group(1), "")
    host = urlsplit(url).netloc.lower()
    if "beijing" in host or "bj" in host:
        return "CN-BJ"
    if "gdzwfw" in host or "guangdong" in host or "gzggzy.cn" in host:
        return "CN-GD"
    if "jszwfw.gov.cn" in host:
        return "CN-JS"
    if "ggzy.zj.gov.cn" in host:
        return "CN-ZJ"
    if "shandong.gov.cn" in host:
        return "CN-SD"
    if "hbbidcloud.cn" in host:
        return "CN-HB"
    if "ggzyjy.sc.gov.cn" in host:
        return "CN-SC"
    return ""


def _has_template_placeholder(*values: Any) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(token in text for token in ("{{", "}}", "%7b%7b", "%7d%7d", "${", "<%"))


def _is_navigation_or_template_link(url: str, title: str) -> bool:
    clean_title = _clean_text(title)
    if _has_template_placeholder(url, clean_title):
        return True
    if _is_non_project_detail_path(url, clean_title):
        return True
    normalized = clean_title.replace(" ", "").lower()
    if not normalized:
        return True
    if normalized in _GENERIC_NAV_TITLE_EXACTS:
        return True
    if len(normalized) <= 8 and any(token in normalized for token in ("更多", "查看更多", "入口", "栏目", "专题")):
        return True
    return False


def _is_non_project_detail_path(url: str, title: str = "") -> bool:
    parsed = urlsplit(str(url or "").strip())
    path_query = f"{parsed.path}?{parsed.query}".lower()
    if any(token in path_query for token in _NON_PROJECT_DETAIL_PATH_TOKENS):
        return True
    normalized_title = str(title or "").replace(" ", "").lower()
    return any(token.lower() in normalized_title for token in _NON_PROJECT_DETAIL_TITLE_TOKENS)


def _is_real_notice_candidate_title(title: str) -> bool:
    clean_title = _normalize_public_title(title)
    if _is_navigation_or_template_link("", clean_title):
        return False
    if _is_non_actionable_notice_text(clean_title):
        return False
    normalized = clean_title.replace(" ", "").lower()
    has_notice_signal = any(token in normalized for token in _NOTICE_TITLE_TOKENS)
    has_project_signal = any(token in normalized for token in _PROJECT_TITLE_TOKENS)
    has_amount_signal = _extract_amount(clean_title)[0] is not None
    if has_amount_signal and (has_notice_signal or has_project_signal):
        return True
    if has_project_signal and len(normalized) >= 12:
        return True
    if has_notice_signal and len(normalized) >= 18:
        return True
    return False


def _is_non_actionable_notice_text(text: str) -> bool:
    normalized = str(text or "").replace(" ", "").lower()
    return any(token.lower() in normalized for token in _NON_ACTIONABLE_NOTICE_TOKENS)


def _is_test_or_placeholder_notice_text(text: str) -> bool:
    normalized = str(text or "").replace(" ", "").lower()
    return any(token.lower() in normalized for token in _TEST_OR_PLACEHOLDER_NOTICE_TOKENS)


def _is_file_name_only_notice_title(text: str) -> bool:
    normalized = _normalize_public_title(text).replace(" ", "")
    lowered = normalized.lower()
    if not lowered.endswith(_FILE_NAME_ONLY_NOTICE_EXTENSIONS):
        return False
    return not any(token in normalized for token in _PROJECT_TITLE_TOKENS)


def _date_window_from_now(now: str, *, days: int = 30) -> tuple[str, str]:
    try:
        parsed = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    end = parsed.date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _parse_public_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("T", " ").replace("Z", "+00:00")
    digits = re.sub(r"\D", "", text)
    for candidate in (
        normalized,
        normalized.split("+", 1)[0],
        normalized.split(".", 1)[0],
    ):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    for fmt, length in (("%Y%m%d%H%M%S", 14), ("%Y%m%d", 8)):
        if len(digits) >= length:
            try:
                return datetime.strptime(digits[:length], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _is_published_within_discovery_window(value: Any, *, now: str, days: int = 30) -> bool:
    published = _parse_public_date(value)
    if published is None:
        return True
    try:
        parsed_now = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        parsed_now = datetime.now(timezone.utc)
    if parsed_now.tzinfo is None:
        parsed_now = parsed_now.replace(tzinfo=timezone.utc)
    else:
        parsed_now = parsed_now.astimezone(timezone.utc)
    start = parsed_now - timedelta(days=days)
    return start.date() <= published.date() <= parsed_now.date()


def _discover_profile_api_link_items(
    profile_id: str,
    *,
    now: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if profile_id == GUANGZHOU_YWTB_PROFILE_ID:
        return _discover_guangzhou_ywtb_api_link_items(now=now, context=context or {})
    if profile_id == "GGZY-DEAL-LIST":
        return _discover_ggzy_deal_api_link_items(now=now, context=context or {})
    if profile_id == "JIANGSU-GGZY-HOME":
        return _discover_text_search_api_link_items(
            endpoint="http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
            base_url="http://jsggzy.jszwfw.gov.cn/",
            referer="http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html",
            date_field="infodatepx",
            sort_field="infodatepx",
            no_participle="1",
            now=now,
            profile_id=profile_id,
        )
    if profile_id == "ZHEJIANG-GGZY-JYXXGK-LIST":
        return _discover_text_search_api_link_items(
            endpoint="https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
            base_url="https://ggzy.zj.gov.cn/",
            referer="https://ggzy.zj.gov.cn/jyxxgk/list.html",
            date_field="webdate",
            sort_field="webdate",
            no_participle="0",
            now=now,
            profile_id=profile_id,
            context=context or {},
        )
    if profile_id == "SICHUAN-GGZY-TRANSACTION-INFO":
        return _discover_sichuan_api_link_items(now=now, context=context or {})
    return {
        "state": "UNSUPPORTED",
        "endpoint": "",
        "items": [],
        "error_optional": "",
    }


def _call_profile_api_link_discoverer(
    discoverer: Any,
    profile_id: str,
    *,
    now: str,
    context: Mapping[str, Any],
) -> Any:
    try:
        return discoverer(profile_id, now=now, context=context)
    except TypeError as exc:
        if "context" not in str(exc):
            raise
        return discoverer(profile_id, now=now)


def _discover_ggzy_deal_api_link_items(
    *,
    now: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    endpoint = "https://deal.ggzy.gov.cn/ds/deal/dealList_find.jsp"
    start_date, end_date = _date_window_from_now(now)
    terms = _ggzy_find_terms(context)
    query_text = " ".join(terms[:4])
    province_code = _ggzy_province_code(context)
    params = {
        "TIMEBEGIN_SHOW": start_date,
        "TIMEEND_SHOW": end_date,
        "TIMEBEGIN": start_date,
        "TIMEEND": end_date,
        "SOURCE_TYPE": "1",
        "DEAL_TIME": "02",
        "DEAL_CLASSIFY": "00",
        "DEAL_STAGE": "0000",
        "DEAL_PROVINCE": province_code,
        "DEAL_CITY": "0",
        "DEAL_PLATFORM": "0",
        "BID_PLATFORM": "0",
        "DEAL_TRADE": "0",
        "isShowAll": "1",
        "PAGENUMBER": "1",
        "FINDTXT": query_text,
    }
    url = f"{endpoint}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": "AX9S-RealPublicCandidateDiscovery/0.1 (+public-readonly-validation)",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.ggzy.gov.cn/deal/dealList.html",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=18) as response:
            raw = response.read(1_500_000).decode("utf-8", "ignore")
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover - public network failures vary
        return {
            "state": "FAILED",
            "endpoint": endpoint,
            "url": url,
            "items": [],
            "error_optional": str(exc),
            "query_window": {"start_date": start_date, "end_date": end_date},
            "query_terms": terms,
            "province_code": province_code,
        }
    records = _ggzy_deal_records(data)
    return {
        "state": "FETCHED" if records else "EMPTY",
        "endpoint": endpoint,
        "url": url,
        "items": _link_items_from_ggzy_deal_records(records),
        "error_optional": "",
        "query_window": {"start_date": start_date, "end_date": end_date},
        "query_terms": terms,
        "province_code": province_code,
        "record_count": len(records),
    }


def _ggzy_find_terms(context: Mapping[str, Any]) -> list[str]:
    values = _as_string_list(context.get("selection_filters"), [])
    document_kind = str(context.get("evaluation_document_kind") or "")
    if document_kind == "flow_or_re_tender_notice":
        values = ["流标", "重新招标", "终止公告", *values]
    elif document_kind == "official_case":
        values = ["公平竞争", "限制排斥", *values]
    elif document_kind == "candidate_notice":
        values = ["中标候选人公示", *values]
    elif document_kind == "award_result":
        values = ["中标结果公告", *values]
    elif document_kind == "tender_file":
        values = ["招标公告", *values]
    return [
        value
        for value in dict.fromkeys(str(item).strip() for item in values)
        if value and value not in {"工程建设", "含招标文件或应用文本", "能回链候选公示"}
    ]


def _ggzy_province_code(context: Mapping[str, Any]) -> str:
    region_code = str(context.get("requested_region_code") or "").strip()
    if region_code == "CN-SH":
        return "310000"
    filters = " ".join(_as_string_list(context.get("selection_filters"), []))
    if "上海" in filters:
        return "310000"
    return "0"


def _ggzy_deal_records(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, Mapping):
        return []
    for key in ("data", "rows", "result", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            nested = _ggzy_deal_records(value)
            if nested:
                return nested
    return []


def _link_items_from_ggzy_deal_records(records: list[Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        title = _normalize_public_title(
            record.get("title")
            or record.get("titleShow")
            or record.get("projectName")
            or record.get("noticeTitle")
            or record.get("name")
        )
        link = str(
            record.get("url")
            or record.get("href")
            or record.get("detailUrl")
            or record.get("linkurl")
            or ""
        ).strip()
        if not title or not link:
            continue
        full_url = urljoin("https://www.ggzy.gov.cn/", link)
        if not _is_candidate_detail_url(
            full_url,
            title,
            "GGZY-DEAL-LIST",
            allow_non_actionable_title=True,
        ):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(
            {
                "url": full_url,
                "text": title,
                "summary": _clean_text(
                    record.get("content")
                    or record.get("summary")
                    or record.get("platformName")
                    or record.get("districtShow")
                )[:1500],
                "published_at": str(
                    record.get("timeShow")
                    or record.get("dealTime")
                    or record.get("publishTime")
                    or record.get("pubDate")
                    or ""
                ),
                "source_region_code": _region_from_source_url(full_url),
                "source_api": "https://deal.ggzy.gov.cn/ds/deal/dealList_find.jsp",
            }
        )
    return items


def _guangzhou_ywtb_process_priority(context: Mapping[str, Any] | None = None) -> tuple[tuple[str, str], ...]:
    explicit_flow_codes = _guangzhou_backtrace_flow_codes(context or {})
    if explicit_flow_codes:
        return tuple(
            (
                str((GUANGZHOU_YWTB_PROCESS_METADATA.get(code) or {}).get("process_label") or f"flow_{code}"),
                code,
            )
            for code in explicit_flow_codes
        )
    document_kind = str((context or {}).get("evaluation_document_kind") or "")
    if document_kind == "award_result":
        return (
            ("award_result", GUANGZHOU_YWTB_AWARD_RESULT_TYPE),
            ("award_info", GUANGZHOU_YWTB_AWARD_INFO_TYPE),
        )
    process_codes = GUANGZHOU_YWTB_DOCUMENT_KIND_TO_PROCESS.get(document_kind)
    if process_codes:
        return tuple(
            (
                str((GUANGZHOU_YWTB_PROCESS_METADATA.get(code) or {}).get("process_label") or f"flow_{code}"),
                code,
            )
            for code in process_codes
        )
    return (("candidate_publicity", GUANGZHOU_YWTB_CANDIDATE_NOTICE_TYPE),)


def _guangzhou_backtrace_flow_codes(context: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for value in _as_string_list(context.get("selection_filters"), []):
        text = str(value or "").strip()
        if text.startswith("BACKTRACE_FLOW_CODE:"):
            code = text.split(":", 1)[1].strip()
            if code:
                codes.append(code)
    return _dedupe_texts(codes)


def _guangzhou_flow_interface_coverage_requested(context: Mapping[str, Any]) -> bool:
    return any(
        str(value or "").strip() == "FLOW_INTERFACE_COVERAGE"
        for value in _as_string_list(context.get("selection_filters"), [])
    )


def _guangzhou_flow_interface_page_limit(context: Mapping[str, Any]) -> int:
    for value in _as_string_list(context.get("selection_filters"), []):
        text = str(value or "").strip()
        if text.startswith("FLOW_INTERFACE_PAGE_LIMIT:"):
            return max(1, min(_as_int(text.split(":", 1)[1].strip(), GUANGZHOU_YWTB_FLOW_INTERFACE_PAGE_LIMIT), 20))
    return GUANGZHOU_YWTB_FLOW_INTERFACE_PAGE_LIMIT


def _guangzhou_flow_interface_sample_limit(context: Mapping[str, Any]) -> int:
    for value in _as_string_list(context.get("selection_filters"), []):
        text = str(value or "").strip()
        if text.startswith("FLOW_INTERFACE_SAMPLE_LIMIT:"):
            return max(1, min(_as_int(text.split(":", 1)[1].strip(), GUANGZHOU_YWTB_FLOW_INTERFACE_SAMPLE_LIMIT), 20))
    return GUANGZHOU_YWTB_FLOW_INTERFACE_SAMPLE_LIMIT


def _guangzhou_flow_interface_month_windows(context: Mapping[str, Any]) -> int:
    for value in _as_string_list(context.get("selection_filters"), []):
        text = str(value or "").strip()
        if text.startswith("FLOW_INTERFACE_MONTH_WINDOWS:"):
            return max(
                1,
                min(
                    _as_int(text.split(":", 1)[1].strip(), GUANGZHOU_YWTB_FLOW_INTERFACE_MONTH_WINDOWS),
                    36,
                ),
            )
    return GUANGZHOU_YWTB_FLOW_INTERFACE_MONTH_WINDOWS


def _guangzhou_flow_interface_date_windows(
    *,
    context: Mapping[str, Any],
    now: str,
) -> list[dict[str, Any]]:
    try:
        parsed = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    month_windows = _guangzhou_flow_interface_month_windows(context)
    windows: list[dict[str, Any]] = []
    current_end = parsed.date()
    for window_index in range(month_windows):
        window_end = current_end - timedelta(days=window_index * 30)
        window_start = window_end - timedelta(days=30)
        windows.append(
            {
                "window_index": window_index,
                "start_date": window_start.isoformat(),
                "end_date": window_end.isoformat(),
            }
        )
    return windows


def _discover_guangzhou_ywtb_api_link_items(
    *,
    now: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
    start_date, end_date = _date_window_from_now(now)
    process_priority = _guangzhou_ywtb_process_priority(context or {})
    backtrace_context = _guangzhou_ywtb_backtrace_context(context or {})
    if backtrace_context.get("relation_guid") and backtrace_context.get("flow_codes"):
        relation_result = _discover_guangzhou_ywtb_relation_link_items(
            now=now,
            backtrace_context=backtrace_context,
            process_priority=process_priority,
        )
        # The relation API is the official same-project flow source.  For
        # backtrace targets, an empty relation response means the module is
        # absent; falling back to broad title search would reintroduce polluted
        # cross-project matches.
        if relation_result["state"] in {"FETCHED", "EMPTY"}:
            return relation_result
    base_payload = {
        "token": "",
        "pn": 0,
        "rn": GUANGZHOU_YWTB_DISCOVERY_PAGE_SIZE,
        "sdt": "",
        "edt": "",
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title",
        "cnum": "002",
        "sort": json.dumps({"ordernum": "0", "webdate": "0"}, ensure_ascii=False),
        "ssort": "title",
        "cl": 500,
        "terminal": "",
        "condition": [
            {
                "fieldName": "categorynum",
                "equal": GUANGZHOU_YWTB_CONSTRUCTION_CATEGORY_NUM,
                "isLike": True,
                "likeType": 2,
            },
        ],
        "time": None,
        "highlights": "",
        "statistics": None,
        "unionCondition": None,
        "accuracy": "",
        "noParticiple": "0",
        "searchRange": [],
        "isBusiness": "1",
    }
    query_variants = list(backtrace_context["query_variants"])
    if not query_variants:
        query_variants = [""]
    flow_interface_coverage = _guangzhou_flow_interface_coverage_requested(context or {})
    page_limit = (
        _guangzhou_flow_interface_page_limit(context or {})
        if flow_interface_coverage
        else 1
    )
    sample_limit = (
        _guangzhou_flow_interface_sample_limit(context or {})
        if flow_interface_coverage
        else GUANGZHOU_YWTB_DISCOVERY_PAGE_SIZE
    )
    date_windows = (
        _guangzhou_flow_interface_date_windows(context=context or {}, now=now)
        if flow_interface_coverage
        else [{"window_index": 0, "start_date": start_date, "end_date": end_date}]
    )
    all_items: list[dict[str, str]] = []
    process_attempts: list[dict[str, Any]] = []
    totals: dict[str, str] = {}
    first_error = ""
    for process_label, process_code in process_priority:
        process_items: list[dict[str, str]] = []
        for window in date_windows:
            window_start = str(window["start_date"])
            window_end = str(window["end_date"])
            for query_index, query_variant in enumerate(query_variants, start=1):
                for page_index in range(page_limit):
                    payload = dict(base_payload)
                    payload["pn"] = page_index
                    payload["wd"] = query_variant
                    if flow_interface_coverage:
                        payload["cnum"] = "002"
                    if flow_interface_coverage:
                        payload["sdt"] = window_start
                        payload["edt"] = window_end
                        payload["time"] = [
                            {
                                "fieldName": "webdate",
                                "startTime": f"{window_start} 00:00:00",
                                "endTime": f"{window_end} 23:59:59",
                            }
                        ]
                    base_conditions = [] if flow_interface_coverage else list(base_payload["condition"])
                    payload["condition"] = [
                        *base_conditions,
                        {
                            "fieldName": "jsgcggfl",
                            "equal": process_code,
                            "isLike": False,
                            "likeType": 0,
                        },
                    ]
                    request = Request(
                        endpoint,
                        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                        headers={
                            "User-Agent": "AX9S-RealPublicCandidateDiscovery/0.1 (+public-readonly-validation)",
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                            "Referer": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/trade_purchasetoplen6.html",
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        method="POST",
                    )
                    try:
                        with urlopen(request, timeout=18) as response:
                            raw = response.read(2_500_000).decode("utf-8", "ignore")
                        outer = json.loads(raw)
                        content = outer.get("content")
                        data = json.loads(content) if isinstance(content, str) else dict(content or {})
                    except Exception as exc:  # pragma: no cover - public network failures vary
                        if not first_error:
                            first_error = str(exc)
                        process_attempts.append(
                            {
                                "process_label": process_label,
                                "trading_process": process_code,
                                "attempted_pages": 1,
                                "page_index": page_index,
                                "window_index": window["window_index"],
                                "window_start": window_start,
                                "window_end": window_end,
                                "record_count": 0,
                                "accepted_item_count": 0,
                                "total": "",
                                "state": "FAILED",
                                "error_optional": str(exc),
                                "backtrace_query_variant": query_variant,
                                "backtrace_query_index": query_index,
                                "flow_interface_coverage_mode": flow_interface_coverage,
                                "failure_taxonomy": ["guangzhou_flow_interface_page_fetch_failed"]
                                if flow_interface_coverage
                                else [],
                            }
                        )
                        continue
                    records = list(((data.get("result") or {}).get("records") or []))
                    total = str((data.get("result") or {}).get("totalcount") or "")
                    totals.setdefault(process_code, total)
                    items = _link_items_from_guangzhou_ywtb_records(
                        records,
                        allowed_processes={process_code},
                        fallback_process_label=process_label,
                        project_codes=set(backtrace_context["project_codes"]),
                        project_name_queries=list(backtrace_context["project_name_queries"]),
                        query_variant=query_variant,
                        query_variants=query_variants,
                        base_project_name=str(backtrace_context.get("base_project_name") or ""),
                    )
                    process_items = _merge_link_items(process_items, items)
                    process_attempts.append(
                        {
                            "process_label": process_label,
                            "trading_process": process_code,
                            "attempted_pages": 1,
                            "page_index": page_index,
                            "window_index": window["window_index"],
                            "window_start": window_start,
                            "window_end": window_end,
                            "record_count": len(records),
                            "accepted_item_count": len(items),
                            "total": total,
                            "state": "FETCHED" if records else "EMPTY",
                            "backtrace_query_variant": query_variant,
                            "backtrace_query_index": query_index,
                            "flow_interface_coverage_mode": flow_interface_coverage,
                            "failure_taxonomy": []
                            if items or not records
                            else ["backtrace_records_rejected_by_project_match"],
                        }
                    )
                    if not flow_interface_coverage and process_items:
                        break
                    if flow_interface_coverage and len(process_items) >= sample_limit:
                        break
                if not flow_interface_coverage and process_items:
                    break
                if flow_interface_coverage and len(process_items) >= sample_limit:
                    break
            if not flow_interface_coverage and process_items:
                break
            if flow_interface_coverage and len(process_items) >= sample_limit:
                break
        all_items = _merge_link_items(all_items, process_items)
        if process_items:
            break
    primary_process = process_priority[0][1] if process_priority else ""
    oldest_window = date_windows[-1] if date_windows else {"start_date": start_date, "end_date": end_date}
    newest_window = date_windows[0] if date_windows else {"start_date": start_date, "end_date": end_date}
    return {
        "state": "FETCHED" if all_items else ("FAILED" if first_error and not process_attempts else "EMPTY"),
        "endpoint": endpoint,
        "items": all_items,
        "error_optional": "" if all_items or process_attempts else first_error,
        "query_window": {"start_date": oldest_window["start_date"], "end_date": newest_window["end_date"]},
        "query_windows": date_windows,
        "api_time_filter_state": "guangzhou_ywtb_flow_interface_historical_month_windows"
        if flow_interface_coverage
        else "guangzhou_ywtb_stage_aware_recent_list",
        "trading_process_strategy": "guangzhou_ywtb_flow_interface_coverage"
        if flow_interface_coverage
        else "guangzhou_ywtb_stage_aware",
        "primary_trading_process": primary_process,
        "page_size": GUANGZHOU_YWTB_DISCOVERY_PAGE_SIZE,
        "page_limit": page_limit,
        "candidate_record_window_cap": GUANGZHOU_YWTB_DISCOVERY_PAGE_SIZE * page_limit * len(date_windows),
        "attempted_pages": len(process_attempts),
        "record_count": sum(_as_int(item.get("record_count"), 0) for item in process_attempts),
        "total": totals.get(primary_process, ""),
        "total_by_process": totals,
        "fallback_recent_all_used": bool(
            all_items and process_priority and str(all_items[0].get("trading_process") or "") != primary_process
        ),
        "process_attempts": process_attempts,
        "backtrace_project_codes": backtrace_context["project_codes"],
        "backtrace_project_name_queries": backtrace_context["project_name_queries"],
        "backtrace_search_query": backtrace_context["search_query"],
        "backtrace_base_project_name": backtrace_context["base_project_name"],
        "backtrace_query_variants": query_variants,
        "flow_interface_coverage_mode": flow_interface_coverage,
        "flow_interface_sample_limit": sample_limit if flow_interface_coverage else "",
        "flow_interface_month_windows": len(date_windows) if flow_interface_coverage else "",
    }


def _discover_guangzhou_ywtb_relation_link_items(
    *,
    now: str,
    backtrace_context: Mapping[str, Any],
    process_priority: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    endpoint = "https://ywtb.gzggzy.cn/EWB-FRONT-5.4.2-sp1/rest/secaction/getRelationInfo"
    relation_guid = str(backtrace_context.get("relation_guid") or "").strip()
    relation_site_guid = str(
        backtrace_context.get("relation_site_guid") or "7eb5f7f1-9041-43ad-8e13-8fcb82ea831a"
    ).strip()
    relation_category_num = str(
        backtrace_context.get("relation_category_num") or GUANGZHOU_YWTB_CONSTRUCTION_CATEGORY_NUM
    ).strip()
    if not relation_guid:
        return {
            "state": "EMPTY",
            "endpoint": endpoint,
            "items": [],
            "error_optional": "",
            "record_count": 0,
            "process_attempts": [],
        }
    payload = urlencode(
        {
            "siteGuid": relation_site_guid,
            "relationGuid": relation_guid,
            "categoryNum": relation_category_num,
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "User-Agent": "AX9S-RealPublicCandidateDiscovery/0.1 (+public-readonly-validation)",
            "Referer": "https://ywtb.gzggzy.cn/",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            raw = response.read(2_500_000).decode("utf-8", "ignore")
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover - public network failures vary
        return {
            "state": "FAILED",
            "endpoint": endpoint,
            "items": [],
            "error_optional": str(exc),
            "record_count": 0,
            "process_attempts": [
                {
                    "process_label": process_priority[0][0] if process_priority else "",
                    "trading_process": process_priority[0][1] if process_priority else "",
                    "record_count": 0,
                    "accepted_item_count": 0,
                    "attempted_pages": 1,
                    "state": "FAILED",
                    "error_optional": str(exc),
                    "failure_taxonomy": ["guangzhou_relation_info_fetch_failed"],
                }
            ],
            "trading_process_strategy": "guangzhou_ywtb_relation_flow_backtrace",
        }
    records = list(((data.get("custom") or {}).get("infodata") or []))
    allowed_codes = {code for _, code in process_priority} or set(backtrace_context.get("flow_codes") or [])
    items = _link_items_from_guangzhou_ywtb_relation_records(
        records,
        allowed_processes=allowed_codes,
        relation_guid=relation_guid,
        query_variants=list(backtrace_context.get("query_variants") or []),
        base_project_name=str(backtrace_context.get("base_project_name") or ""),
    )
    process_attempts: list[dict[str, Any]] = []
    for process_label, process_code in process_priority:
        matching_records = [
            record
            for record in records
            if isinstance(record, Mapping) and str(record.get("jsgcggfl") or "") == process_code
        ]
        matching_items = [
            item for item in items if str(item.get("trading_process") or "") == process_code
        ]
        process_attempts.append(
            {
                "process_label": process_label,
                "trading_process": process_code,
                "attempted_pages": 1,
                "record_count": len(matching_records),
                "accepted_item_count": len(matching_items),
                "total": str(len(matching_records)),
                "state": "FETCHED" if matching_records else "EMPTY",
                "backtrace_relation_guid": relation_guid,
                "failure_taxonomy": []
                if matching_items or not matching_records
                else ["guangzhou_relation_records_rejected"],
            }
        )
    primary_process = process_priority[0][1] if process_priority else ""
    return {
        "state": "FETCHED" if items else "EMPTY",
        "endpoint": endpoint,
        "items": items,
        "error_optional": "",
        "query_window": {"start_date": "", "end_date": ""},
        "api_time_filter_state": "guangzhou_ywtb_same_project_relation_info",
        "trading_process_strategy": "guangzhou_ywtb_relation_flow_backtrace",
        "primary_trading_process": primary_process,
        "page_size": len(records),
        "page_limit": 1,
        "candidate_record_window_cap": len(records),
        "attempted_pages": len(process_attempts),
        "record_count": len(records),
        "total": str(len(records)),
        "total_by_process": {
            code: str(
                sum(
                    1
                    for record in records
                    if isinstance(record, Mapping) and str(record.get("jsgcggfl") or "") == code
                )
            )
            for code in sorted(allowed_codes)
        },
        "fallback_recent_all_used": False,
        "process_attempts": process_attempts,
        "backtrace_project_codes": [relation_guid],
        "backtrace_project_name_queries": list(backtrace_context.get("project_name_queries") or []),
        "backtrace_search_query": str(backtrace_context.get("search_query") or ""),
        "backtrace_base_project_name": str(backtrace_context.get("base_project_name") or ""),
        "backtrace_query_variants": list(backtrace_context.get("query_variants") or []),
        "backtrace_relation_guid": relation_guid,
        "relation_info_record_count": len(records),
        "relation_info_flow_codes": sorted(allowed_codes),
        "relation_info_checked_at": now,
    }


def _link_items_from_guangzhou_ywtb_relation_records(
    records: list[Any],
    *,
    allowed_processes: set[str] | None = None,
    relation_guid: str,
    query_variants: list[str] | None = None,
    base_project_name: str = "",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = allowed_processes or set(GUANGZHOU_YWTB_PROCESS_METADATA)
    for record in records:
        if not isinstance(record, Mapping):
            continue
        process_code = str(record.get("jsgcggfl") or "").strip()
        if process_code not in allowed:
            continue
        title = _normalize_public_title(record.get("title") or record.get("title2"))
        link = str(record.get("infourl") or record.get("linkurl") or record.get("visiturl") or "").strip()
        if not title or not link:
            continue
        full_url = urljoin("https://ywtb.gzggzy.cn/", link)
        if full_url in seen:
            continue
        seen.add(full_url)
        metadata = dict(GUANGZHOU_YWTB_PROCESS_METADATA.get(process_code) or {})
        flow_no = str(metadata.get("guangzhou_flow_no") or "")
        flow_title = str(metadata.get("guangzhou_flow_title") or metadata.get("dataset_name") or "")
        publish_time = str(record.get("infodate") or record.get("webdate") or "")
        items.append(
            {
                "url": full_url,
                "text": title,
                "summary": _clean_text(record.get("content"))[:1500],
                "published_at": publish_time,
                "categorynum": str(record.get("categorynum") or GUANGZHOU_YWTB_CONSTRUCTION_CATEGORY_NUM),
                "trading_process": process_code,
                "dataset_name": str(metadata.get("dataset_name") or ""),
                "notice_third_type_desc": str(metadata.get("notice_third_type_desc") or ""),
                "query_process_label": str(metadata.get("process_label") or ""),
                "source_api": "https://ywtb.gzggzy.cn/EWB-FRONT-5.4.2-sp1/rest/secaction/getRelationInfo",
                "source_record_id": str(record.get("infoid") or record.get("relationGuid") or relation_guid),
                "project_code": relation_guid,
                "project_match_key": relation_guid,
                "base_project_name": base_project_name or _base_guangzhou_project_name(title),
                "backtrace_query_variant": relation_guid,
                "backtrace_query_variants": list(query_variants or [relation_guid]),
                "backtrace_match_reason": "relation_guid_exact_match",
                "source_region_code": "CN-GD",
                "guangzhou_flow_no": flow_no,
                "guangzhou_flow_title": flow_title,
                "guangzhou_flow_code": process_code,
                "guangzhou_flow_folder": f"{flow_no}_{flow_title}" if flow_no and flow_title else "",
                "guangzhou_relation_guid": relation_guid,
            }
        )
    return items


def _link_items_from_guangzhou_ywtb_records(
    records: list[Any],
    *,
    allowed_processes: set[str] | None = None,
    fallback_process_label: str = "",
    project_codes: set[str] | None = None,
    project_name_queries: list[str] | None = None,
    query_variant: str = "",
    query_variants: list[str] | None = None,
    base_project_name: str = "",
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    allowed = allowed_processes or {GUANGZHOU_YWTB_CANDIDATE_NOTICE_TYPE}
    project_codes = {str(code).strip() for code in (project_codes or set()) if str(code).strip()}
    project_name_queries = [
        _normalize_guangzhou_project_match_text(query)
        for query in list(project_name_queries or [])
        if _normalize_guangzhou_project_match_text(query)
    ]
    for record in records:
        if not isinstance(record, Mapping):
            continue
        process_code = str(record.get("jsgcggfl") or "")
        if process_code not in allowed:
            continue
        title = _normalize_public_title(record.get("title") or record.get("title2"))
        link = str(record.get("linkurl") or record.get("visiturl") or record.get("infourl") or "").strip()
        if not title or not link:
            continue
        record_project_code = str(record.get("xmbh") or "").strip()
        match_result = _guangzhou_ywtb_record_match_result(
            title=title,
            record_project_code=record_project_code,
            project_codes=project_codes,
            project_name_queries=project_name_queries,
        )
        if not match_result["matched"]:
            continue
        canonical_project_key = str(match_result.get("canonical_project_key") or "").strip()
        full_url = urljoin("https://ywtb.gzggzy.cn/", link)
        if full_url in seen:
            continue
        seen.add(full_url)
        metadata = dict(GUANGZHOU_YWTB_PROCESS_METADATA.get(process_code) or {})
        flow_no = str(metadata.get("guangzhou_flow_no") or "")
        flow_title = str(metadata.get("guangzhou_flow_title") or metadata.get("dataset_name") or "")
        items.append(
            {
                "url": full_url,
                "text": title,
                "summary": _clean_text(record.get("content"))[:1500],
                "published_at": str(record.get("webdate") or record.get("infodate") or ""),
                "categorynum": str(record.get("categorynum") or ""),
                "trading_process": process_code,
                "dataset_name": str(metadata.get("dataset_name") or ""),
                "notice_third_type_desc": str(metadata.get("notice_third_type_desc") or ""),
                "query_process_label": fallback_process_label or str(metadata.get("process_label") or ""),
                "source_api": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
                "source_record_id": str(record.get("id") or record.get("xmbh") or ""),
                "project_code": record_project_code,
                "project_match_key": canonical_project_key
                or record_project_code
                or _normalize_guangzhou_project_match_text(title),
                "base_project_name": base_project_name or _base_guangzhou_project_name(title),
                "backtrace_query_variant": query_variant,
                "backtrace_query_variants": list(query_variants or []),
                "backtrace_match_reason": str(match_result["reason"]),
                "source_region_code": "CN-GD",
                "guangzhou_flow_no": flow_no,
                "guangzhou_flow_title": flow_title,
                "guangzhou_flow_code": process_code,
                "guangzhou_flow_folder": f"{flow_no}_{flow_title}" if flow_no and flow_title else "",
            }
        )
    return items


def _guangzhou_ywtb_backtrace_context(context: Mapping[str, Any]) -> dict[str, Any]:
    project_codes: list[str] = []
    project_name_queries: list[str] = []
    explicit_variants: list[str] = []
    flow_codes: list[str] = []
    base_project_name = ""
    relation_guid = ""
    relation_site_guid = ""
    relation_category_num = ""
    for value in _as_string_list(context.get("selection_filters"), []):
        text = str(value or "").strip()
        if text.startswith("BACKTRACE_PROJECT_CODE:"):
            code = text.split(":", 1)[1].strip()
            if code:
                project_codes.append(code)
                relation_guid = relation_guid or code
        elif text.startswith("BACKTRACE_RELATION_GUID:"):
            code = text.split(":", 1)[1].strip()
            if code:
                relation_guid = code
                project_codes.append(code)
        elif text.startswith("BACKTRACE_FLOW_CODE:"):
            code = text.split(":", 1)[1].strip()
            if code:
                flow_codes.append(code)
        elif text.startswith("BACKTRACE_RELATION_SITE_GUID:"):
            relation_site_guid = text.split(":", 1)[1].strip()
        elif text.startswith("BACKTRACE_RELATION_CATEGORY_NUM:"):
            relation_category_num = text.split(":", 1)[1].strip()
        elif text.startswith("BACKTRACE_PROJECT_NAME:"):
            name = text.split(":", 1)[1].strip()
            if name:
                project_name_queries.append(name)
        elif text.startswith("BACKTRACE_QUERY_VARIANT:"):
            variant = text.split(":", 1)[1].strip()
            if variant:
                explicit_variants.append(variant)
        elif text.startswith("BACKTRACE_BASE_PROJECT_NAME:"):
            name = text.split(":", 1)[1].strip()
            if name:
                base_project_name = name
    explicit_code = str(context.get("guangzhou_ywtb_project_code") or "").strip()
    explicit_name = str(context.get("guangzhou_ywtb_project_name") or "").strip()
    if explicit_code:
        project_codes.append(explicit_code)
        relation_guid = relation_guid or explicit_code
    if explicit_name:
        project_name_queries.append(explicit_name)
    project_codes = list(dict.fromkeys(project_codes))
    project_name_queries = list(dict.fromkeys(project_name_queries))
    if not base_project_name and project_name_queries:
        base_project_name = _base_guangzhou_project_name(project_name_queries[0])
    query_variants = _guangzhou_backtrace_query_variants(
        project_codes=project_codes,
        project_name_queries=project_name_queries,
        explicit_variants=explicit_variants,
        base_project_name=base_project_name,
    )
    project_name_queries = _dedupe_texts([*project_name_queries, base_project_name, *query_variants])
    search_query = query_variants[0] if query_variants else ""
    return {
        "project_codes": project_codes,
        "project_name_queries": project_name_queries,
        "base_project_name": base_project_name,
        "query_variants": query_variants,
        "search_query": search_query,
        "flow_codes": _dedupe_texts(flow_codes),
        "relation_guid": relation_guid or (project_codes[0] if project_codes else ""),
        "relation_site_guid": relation_site_guid,
        "relation_category_num": relation_category_num,
    }


def _guangzhou_backtrace_query_variants(
    *,
    project_codes: list[str],
    project_name_queries: list[str],
    explicit_variants: list[str],
    base_project_name: str = "",
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(explicit_variants)
    candidates.extend(project_codes)
    if base_project_name:
        candidates.append(base_project_name)
    for name in project_name_queries:
        candidates.append(name)
        base = _base_guangzhou_project_name(name)
        candidates.append(base)
        candidates.append(_remove_guangzhou_parenthetical_text(base))
        candidates.append(_short_guangzhou_project_query(base))
    return _dedupe_texts(value for value in candidates if str(value or "").strip())[:8]


def _guangzhou_ywtb_record_matches_backtrace(
    *,
    title: str,
    record_project_code: str,
    project_codes: set[str],
    project_name_queries: list[str],
) -> bool:
    return bool(
        _guangzhou_ywtb_record_match_result(
            title=title,
            record_project_code=record_project_code,
            project_codes=project_codes,
            project_name_queries=project_name_queries,
        )["matched"]
    )


def _guangzhou_ywtb_record_match_result(
    *,
    title: str,
    record_project_code: str,
    project_codes: set[str],
    project_name_queries: list[str],
) -> dict[str, Any]:
    if not project_codes and not project_name_queries:
        return {"matched": True, "reason": "stage_listing_match", "canonical_project_key": record_project_code}
    if project_codes and record_project_code and record_project_code in project_codes:
        return {"matched": True, "reason": "project_code_exact_match", "canonical_project_key": record_project_code}
    normalized_title = _normalize_guangzhou_project_match_text(title)
    for query in project_name_queries:
        normalized_query = _normalize_guangzhou_project_match_text(query)
        if normalized_title and normalized_query and (
            normalized_query in normalized_title or normalized_title in normalized_query
        ):
            canonical = sorted(project_codes)[0] if project_codes else (normalized_query or record_project_code)
            return {"matched": True, "reason": "name_variant_match", "canonical_project_key": canonical}
    return {"matched": False, "reason": "backtrace_project_mismatch", "canonical_project_key": ""}


def _base_guangzhou_project_name(value: Any) -> str:
    text = _normalize_public_title(value)
    for marker in (
        "中标候选人公示",
        "中标结果公告",
        "中标结果",
        "中标信息",
        "招标公告",
        "重新招标公告",
        "变更公告",
        "补充公告",
        "答疑公告",
        "澄清公告",
        "投标文件公开",
        "开标记录",
    ):
        text = text.replace(marker, "")
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _remove_guangzhou_parenthetical_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[（(][^（）()]{1,40}[）)]", "", text)
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _short_guangzhou_project_query(value: Any) -> str:
    text = _remove_guangzhou_parenthetical_text(value)
    text = re.sub(r"(第[一二三四五六七八九十0-9]+次|标段[一二三四五六七八九十0-9]+|第[一二三四五六七八九十0-9]+标段)", "", text)
    text = re.sub(r"(工程监理服务|设计施工总承包|勘察设计施工总承包及运营|施工总承包|工程施工|施工|监理服务)$", "", text)
    return re.sub(r"\s+", " ", text).strip(" 　-—_：:")


def _normalize_guangzhou_project_match_text(value: Any) -> str:
    text = _base_guangzhou_project_name(value)
    text = re.sub(r"[\s　（）()【】\[\]《》<>:：,，。；;、_-]+", "", text)
    return text.strip()


def _format_guangdong_publish_date(value: Any) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    if len(text) >= 14:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}:{text[12:14]}"
    if len(text) >= 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return str(value or "")


def _unsupported_profile_api_link_items(profile_id: str, *, now: str) -> dict[str, Any]:
    return {
        "state": "UNSUPPORTED",
        "endpoint": "",
        "items": [],
        "error_optional": "",
    }


def _discover_text_search_api_link_items(
    *,
    endpoint: str,
    base_url: str,
    referer: str,
    date_field: str,
    sort_field: str,
    no_participle: str,
    now: str,
    profile_id: str = "",
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    start_date, end_date = _date_window_from_now(now, days=1)
    payload = {
        "token": "",
        "pn": 0,
        "rn": 12,
        "sdt": "",
        "edt": "",
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title",
        "cnum": "001",
        "sort": json.dumps({sort_field: "0"}, ensure_ascii=False),
        "ssort": "title",
        "cl": 10000,
        "terminal": "",
        "condition": [],
        "time": [
            {
                "fieldName": date_field,
                "startTime": f"{start_date} 00:00:00",
                "endTime": f"{end_date} 23:59:59",
            }
        ],
        "highlights": "",
        "statistics": None,
        "unionCondition": [],
        "accuracy": "",
        "noParticiple": no_participle,
        "searchRange": None,
        "isBusiness": "1",
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "User-Agent": "AX9S-RealPublicCandidateDiscovery/0.1 (+public-readonly-validation)",
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json, text/plain, */*",
            "Referer": referer,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            raw = response.read(1_500_000).decode("utf-8", "ignore")
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover - public network failures vary
        return {
            "state": "FAILED",
            "endpoint": endpoint,
            "items": [],
            "error_optional": str(exc),
            "query_window": {"start_date": start_date, "end_date": end_date},
        }
    records = list(((data.get("result") or {}).get("records") or []))
    return {
        "state": "FETCHED" if records else "EMPTY",
        "endpoint": endpoint,
        "items": _link_items_from_text_search_records(
            records,
            base_url=base_url,
            endpoint=endpoint,
            profile_id=profile_id,
            context=context or {},
        ),
        "error_optional": "",
        "query_window": {"start_date": start_date, "end_date": end_date},
        "api_time_filter_state": "local_publish_time_filter_after_default_recent_list",
        "record_count": len(records),
    }


def _link_items_from_text_search_records(
    records: list[Any],
    *,
    base_url: str,
    endpoint: str,
    profile_id: str = "",
    context: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        title = _normalize_public_title(record.get("title") or record.get("titlenew"))
        link = str(record.get("linkurl") or record.get("visiturl") or record.get("infourl") or "").strip()
        if not title or not link:
            continue
        full_url = urljoin(base_url, link)
        categorynum = str(record.get("categorynum") or "")
        if _is_test_or_placeholder_notice_text(title) or _is_file_name_only_notice_title(title):
            continue
        if _is_navigation_or_template_link(full_url, title):
            continue
        if profile_id and not _profile_link_item_matches_document_kind(
            profile_id,
            full_url,
            title,
            categorynum=categorynum,
            context=context or {},
        ):
            continue
        if profile_id and not _is_candidate_detail_url(
            full_url,
            title,
            profile_id,
            allow_non_actionable_title=True,
        ):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(
            {
                "url": full_url,
                "text": title,
                "summary": _clean_text(record.get("content"))[:1500],
                "published_at": str(
                    record.get("webdate")
                    or record.get("infodatepx")
                    or record.get("infodate")
                    or ""
                ),
                "categorynum": categorynum,
                "source_api": endpoint,
            }
        )
    return items


def _discover_sichuan_api_link_items(
    *,
    now: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = "https://ggzyjy.sc.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
    start_date, end_date = _date_window_from_now(now)
    document_kind = str((context or {}).get("evaluation_document_kind") or "")
    categorynum = "002001001" if document_kind == "tender_file" else "002001"
    condition = {
        "fieldName": "categorynum",
        "equal": categorynum,
        "notEqual": None,
        "equalList": None,
        "notEqualList": None,
        "isLike": document_kind != "tender_file",
        "likeType": 2 if document_kind != "tender_file" else 0,
    }
    payload = {
        "token": "",
        "pn": 0,
        "rn": 12,
        "sdt": "",
        "edt": "",
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "",
        "cnum": "",
        "sort": "{\"ordernum\":\"0\",\"webdate\":\"0\"}",
        "ssort": "",
        "cl": 10000,
        "terminal": "",
        "condition": [condition],
        "time": [
            {
                "fieldName": "webdate",
                "startTime": f"{start_date} 00:00:00",
                "endTime": f"{end_date} 23:59:59",
            }
        ],
        "highlights": "",
        "statistics": None,
        "unionCondition": None,
        "accuracy": "",
        "noParticiple": "1",
        "searchRange": None,
        "noWd": True,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "User-Agent": "AX9S-RealPublicCandidateDiscovery/0.1 (+public-readonly-validation)",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            raw = response.read(1_500_000).decode("utf-8", "ignore")
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover - public network failures vary
        return {
            "state": "FAILED",
            "endpoint": endpoint,
            "items": [],
            "error_optional": str(exc),
            "query_window": {"start_date": start_date, "end_date": end_date},
        }
    records = list(((data.get("result") or {}).get("records") or []))
    items = _link_items_from_text_search_records(
        records,
        base_url="https://ggzyjy.sc.gov.cn/",
        endpoint=endpoint,
        profile_id="SICHUAN-GGZY-TRANSACTION-INFO",
        context=context or {},
    )
    return {
        "state": "FETCHED" if items else "EMPTY",
        "endpoint": endpoint,
        "items": items,
        "error_optional": "",
        "query_window": {"start_date": start_date, "end_date": end_date},
        "target_categorynum": categorynum,
        "category_strategy": (
            "sichuan_tender_notice_exact"
            if document_kind == "tender_file"
            else "sichuan_all_engineering_like"
        ),
        "record_count": len(records),
    }


def _profile_link_item_matches_document_kind(
    profile_id: str,
    url: str,
    title: str,
    *,
    categorynum: str,
    context: Mapping[str, Any],
) -> bool:
    document_kind = str(context.get("evaluation_document_kind") or "")
    if document_kind != "tender_file":
        return True
    path = urlsplit(str(url or "")).path.lower()
    if profile_id == "ZHEJIANG-GGZY-JYXXGK-LIST":
        return categorynum.startswith("002001001") or "/002001/002001001/" in path
    if profile_id == "SICHUAN-GGZY-TRANSACTION-INFO":
        if categorynum.startswith("002001012") or "/002001/002001012/" in path:
            return False
        return categorynum.startswith("002001001") or "/002001/002001001/" in path
    return True


def _merge_link_items(primary: list[Mapping[str, Any]], secondary: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*primary, *secondary]:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(dict(item))
    return merged


def _is_candidate_detail_url(
    url: str,
    title: str,
    profile_id: str,
    *,
    allow_non_actionable_title: bool = False,
) -> bool:
    path = urlsplit(url).path.lower()
    text = title.lower()
    if _has_template_placeholder(url, title):
        return False
    if _is_non_project_detail_path(url, title):
        return False
    blocked_title_tokens = (
        "wechat",
        "微信",
        "首页",
        "交易公开",
        "政府采购",
        "交易查询",
        "搜索",
        "登录",
        "注册",
    )
    if any(token in text for token in blocked_title_tokens):
        return False
    if profile_id == "GGZY-DEAL-LIST":
        return "/information/deal/html/" in path and path.endswith((".html", ".htm", ".shtml"))
    if profile_id.startswith("CCGP-"):
        return "/cggg/" in path and path.endswith((".htm", ".html", ".shtml")) and re.search(r"/20[0-9]{4}/", path) is not None
    if "BEIJING" in profile_id or "BDA" in profile_id:
        return path.endswith((".html", ".htm", ".shtml")) and any(
            token in path for token in ("notice", "ggzy", "cms", "jyzx")
        )
    if profile_id in _PROVINCE_REALTIME_PROFILE_IDS:
        host = urlsplit(url).netloc.lower()
        if profile_id == GUANGZHOU_YWTB_PROFILE_ID:
            if "jsgc.gzggzy.cn" in host and "/kaibiao/infotoweb_list" in path:
                return True
            if "zbtb.gd.gov.cn" in host and "/jygg/" in urlsplit(url).fragment.lower():
                return True
            if "ywtb.gzggzy.cn" not in host:
                return False
        if profile_id == "JIANGSU-GGZY-HOME" and "jszwfw.gov.cn" not in host:
            return False
        if profile_id == "ZHEJIANG-GGZY-JYXXGK-LIST" and "ggzy.zj.gov.cn" not in host:
            return False
        if profile_id == "SHANDONG-GGZY-JYXXGK-LIST" and "shandong.gov.cn" not in host:
            return False
        if profile_id == "HUBEI-BIDCLOUD-JYXX-LIST" and "hbbidcloud.cn" not in host:
            return False
        if profile_id == "SICHUAN-GGZY-TRANSACTION-INFO" and "ggzyjy.sc.gov.cn" not in host:
            return False
        if not allow_non_actionable_title and not _is_real_notice_candidate_title(title):
            return False
        return path.endswith((".html", ".htm", ".shtml", ".jhtml", ".jspx", ".jsp")) and not path.endswith(
            ("index.html", "list.html", "about.html", "transactioninfo.html")
        )
    if "GUANGDONG" in profile_id:
        return path.endswith((".html", ".htm", ".shtml")) and any(
            token in path for token in ("notice", "jygg", "ggzy", "bulletin")
        )
    return path.endswith((".html", ".htm", ".shtml")) and not path.endswith(("index.html", "deallist.html"))


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    basis = str(candidate.get("source_url") or candidate.get("notice_id") or candidate.get("project_name") or "")
    return _hash_text(basis.lower(), 24)


def _profile_ids_for_region(region_code: str) -> list[str]:
    adapter = resolve_region_source_adapter(region_code)
    profile_ids = list(adapter.get("entry_profile_ids", []) or [])
    if str(adapter.get("region_code") or region_code) == "CN-NATIONAL":
        profile_ids.extend(list(adapter.get("fallback_entry_profile_ids", []) or []))
    seen: set[str] = set()
    resolved: list[str] = []
    for profile_id in profile_ids:
        text = str(profile_id or "").strip()
        if text and text not in seen and text in REAL_PUBLIC_ENTRY_PROFILE_BY_ID:
            seen.add(text)
            resolved.append(text)
    return resolved


def _source_not_configured_report(region_code: str, adapter: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = {
        "profile_id": "",
        "entry_url": "",
        "status": "SOURCE_NOT_CONFIGURED",
        "link_item_count": 0,
        "same_site_detail_link_count": 0,
        "accepted_candidate_count": 0,
        "rejected_counts": {},
        "rejected_samples": [],
        "sample_link_items": [],
        "operator_diagnosis": ["province_realtime_source_not_registered"],
        "next_action": "先登记并验证本省官方实时招投标/公共资源列表源；省级实战搜索不使用全国平台代替本省实时源。",
        "js_shell_suspected": False,
    }
    return {
        "region_code": str(adapter.get("region_code") or region_code),
        "profile_id": "",
        "entry_url": "",
        "status": "SOURCE_NOT_CONFIGURED",
        "failure_reason": "province_realtime_source_not_registered",
        "candidate_diagnostics": diagnostics,
        "operator_diagnosis": diagnostics["operator_diagnosis"],
        "next_action": diagnostics["next_action"],
        "rejected_counts": {},
        "candidate_count": 0,
        "accepted_candidate_count": 0,
        "duplicate_filtered_count": 0,
    }


def _operator_diagnosis_for_profile(
    diagnostics: Mapping[str, Any],
    *,
    carrier: Mapping[str, Any],
    profile_id: str,
) -> list[str]:
    diagnoses: list[str] = []
    rejected = dict(diagnostics.get("rejected_counts", {}) or {})
    link_count = _as_int(diagnostics.get("link_item_count"), 0)
    accepted = _as_int(diagnostics.get("accepted_candidate_count"), 0)
    status = str(carrier.get("status") or "")
    lightweight_found = list(carrier.get("lightweight_public_entry_markers_found", []) or [])
    if status == "SOURCE_NOT_CONFIGURED":
        diagnoses.append("province_realtime_source_not_registered")
    if accepted:
        diagnoses.append("candidate_links_accepted")
    if status == "FETCHED" and link_count == 0:
        diagnoses.append("static_detail_links_missing")
        if profile_id in _BROWSER_RENDERED_REALTIME_PROFILE_IDS:
            diagnoses.append("browser_rendered_realtime_list_required")
            if isinstance(diagnostics, dict):
                diagnostics["js_shell_suspected"] = True
        elif "GUANGDONG" in profile_id or lightweight_found:
            diagnoses.append("js_rendered_list_or_api_required")
            if isinstance(diagnostics, dict):
                diagnostics["js_shell_suspected"] = True
    if rejected.get("region_mismatch"):
        diagnoses.append("all_or_some_links_filtered_by_region")
    if rejected.get("project_type_mismatch"):
        diagnoses.append("all_or_some_links_filtered_by_project_type")
    if rejected.get("amount_below_minimum") or rejected.get("amount_above_maximum"):
        diagnoses.append("all_or_some_links_filtered_by_amount_range")
    preserved = dict(diagnostics.get("preserved_filter_counts", {}) or {})
    if preserved.get("published_outside_discovery_window"):
        diagnoses.append("some_candidates_preserved_with_old_publish_time_review")
    if preserved.get("project_type_mismatch"):
        diagnoses.append("some_candidates_preserved_with_project_type_review")
    if preserved.get("amount_below_minimum") or preserved.get("amount_above_maximum"):
        diagnoses.append("some_candidates_preserved_with_amount_range_review")
    if link_count and not accepted and rejected.get("navigation_or_template_link"):
        diagnoses.append("links_present_but_navigation_or_template_only")
    if link_count and not accepted and (
        _as_int(rejected.get("not_candidate_detail_url"), 0)
        + _as_int(rejected.get("navigation_or_template_link"), 0)
    ) == link_count:
        diagnoses.append("links_present_but_not_candidate_detail_pages")
    if link_count and not accepted and not diagnoses:
        diagnoses.append("links_present_but_no_candidate_after_filters")
    return diagnoses or ["candidate_discovery_no_issue_detected"]


def _next_action_for_profile_diagnostics(diagnostics: Mapping[str, Any]) -> str:
    diagnoses = set(str(item) for item in list(diagnostics.get("operator_diagnosis", []) or []))
    rejected = dict(diagnostics.get("rejected_counts", {}) or {})
    preserved = dict(diagnostics.get("preserved_filter_counts", {}) or {})
    if _as_int(diagnostics.get("accepted_candidate_count"), 0):
        return "继续抓取详情页和附件，进入 Stage2-9。"
    if "province_realtime_source_not_registered" in diagnoses:
        return "先登记并验证本省官方实时招投标/公共资源列表源；省级实战搜索不使用全国平台代替本省实时源。"
    if "browser_rendered_realtime_list_required" in diagnoses:
        return "广东正确源已验证有实时列表；当前后端直连列表 API 需要签名，下一步接浏览器渲染后的可见列表读取或合法公开数据接口。"
    if "js_rendered_list_or_api_required" in diagnoses:
        return "补该地区 JS 列表数据源解析或浏览器渲染后列表解析；仅入口页 HTML 不足以发现公告。"
    if rejected.get("region_mismatch"):
        return "检查地区过滤和来源 URL 行政区编码；必要时补本地列表入口。"
    if rejected.get("project_type_mismatch"):
        return "扩展列表标题项目类型识别词，或调整本次项目类型筛选。"
    if rejected.get("amount_below_minimum") or rejected.get("amount_above_maximum"):
        return "放宽金额区间或改进列表/详情金额解析，再重新运行。"
    if preserved:
        return "候选未在源头丢弃；带复核标签进入候选池，下一步抓详情页/附件后再按窗口、金额、项目类型判断。"
    if rejected.get("navigation_or_template_link"):
        return "当前抓到的是栏目导航或前端模板占位链接；下一步接真实列表数据接口或浏览器渲染后的公告行。"
    if rejected.get("not_candidate_detail_url"):
        return "补详情 URL 识别规则或列表页真实公告链接解析。"
    return "查看来源快照和列表链接样本，补对应解析规则。"


def _discovery_diagnostics_summary(profile_reports: list[dict[str, Any]]) -> dict[str, Any]:
    rejected_totals: dict[str, int] = {}
    preserved_filter_totals: dict[str, int] = {}
    diagnosis_totals: dict[str, int] = {}
    link_item_count = 0
    accepted_candidate_count = 0
    candidate_limit_truncated_count = 0
    for report in profile_reports:
        diagnostics = dict(report.get("candidate_diagnostics", {}) or {})
        link_item_count += _as_int(diagnostics.get("link_item_count"), 0)
        accepted_candidate_count += _as_int(diagnostics.get("accepted_candidate_count"), 0)
        candidate_limit_truncated_count += _as_int(report.get("candidate_limit_truncated_count"), 0)
        for key, value in dict(diagnostics.get("rejected_counts", {}) or {}).items():
            rejected_totals[str(key)] = rejected_totals.get(str(key), 0) + _as_int(value, 0)
        for key, value in dict(diagnostics.get("preserved_filter_counts", {}) or {}).items():
            preserved_filter_totals[str(key)] = preserved_filter_totals.get(str(key), 0) + _as_int(value, 0)
        for item in list(diagnostics.get("operator_diagnosis", []) or []):
            text = str(item)
            diagnosis_totals[text] = diagnosis_totals.get(text, 0) + 1
    if accepted_candidate_count:
        headline = "已解析到真实候选。"
    elif diagnosis_totals.get("province_realtime_source_not_registered"):
        headline = "所选省份未登记本省实时来源；全国平台不能代替地方实时源。"
    elif diagnosis_totals.get("browser_rendered_realtime_list_required"):
        headline = "本省正确源已验证有实时列表，但当前后端静态抓取无法读取浏览器渲染列表。"
    elif diagnosis_totals.get("js_rendered_list_or_api_required"):
        headline = "入口页可访问，但至少一个来源是 JS 列表壳，静态 HTML 没有公告详情链接。"
    elif rejected_totals:
        headline = "已发现链接，但全部被地区、项目类型、金额或详情页规则过滤。"
    else:
        headline = "未发现可解析的真实公告链接。"
    return {
        "profile_count": len(profile_reports),
        "link_item_count": link_item_count,
        "accepted_candidate_count": accepted_candidate_count,
        "candidate_limit_truncated_count": candidate_limit_truncated_count,
        "rejected_totals": rejected_totals,
        "preserved_filter_totals": preserved_filter_totals,
        "diagnosis_totals": diagnosis_totals,
        "headline": headline,
    }


class RealPublicCandidateRepository:
    def __init__(self, *, repository: OperatorActionRepository | None = None) -> None:
        self.repository = repository or OperatorActionRepository()

    def persist_discovery_result(
        self,
        *,
        payload: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        requested_at = build_persisted_at()
        run_id = str(result.get("discovery_run_id") or f"REAL-CANDIDATE-DISCOVERY-RUN-{requested_at}")
        run_id = run_id.replace(":", "").replace("+", "")
        object_refs = {
            "discovery_run_id": run_id,
            "candidate_count": str(result.get("candidate_count") or 0),
            "persisted_candidate_count": str(result.get("persisted_candidate_count") or 0),
            "duplicate_candidate_count": str(result.get("duplicate_candidate_count") or 0),
            "failure_count": str(result.get("failure_count") or 0),
            "region_codes_json": _json_text(result.get("region_codes") or payload.get("region_codes") or []),
            "project_types_json": _json_text(result.get("project_types") or payload.get("project_types") or []),
            "query": str(payload.get("query") or payload.get("project_keyword") or payload.get("keyword") or ""),
            "amount_min": _present_text(
                _first_present(result.get("amount_min"), payload.get("amount_min"), payload.get("minimum_amount"))
            ),
            "amount_max": _present_text(
                _first_present(result.get("amount_max"), payload.get("amount_max"), payload.get("maximum_amount"))
            ),
            "source_candidate_mode": REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
            "candidate_limit_source": str(result.get("candidate_limit_source") or ""),
            "candidate_limit_effective": _present_text(result.get("candidate_limit_effective")),
            "stage1_6_validation_mode": str(bool(result.get("stage1_6_validation_mode"))).lower(),
            "stage1_6_validation_caps_json": _json_text(result.get("stage1_6_validation_caps") or {}),
            "profile_reports_json": _json_text(result.get("profile_reports") or []),
            "candidate_discovery_diagnostics_json": _json_text(result.get("candidate_discovery_diagnostics") or {}),
        }
        action = PersistedOperatorAction(
            action_event_id=run_id,
            work_item_id=REAL_CANDIDATE_DISCOVERY_RUN_WORK_ITEM_ID,
            stage_scope=1,
            action_id="operator_real_candidate_discovery_run",
            button_flow_id="owner_console_real_candidate_discovery",
            action_state=str(result.get("discovery_state") or "COMPLETED"),
            resulting_assignment_lifecycle_state=None,
            requested_by_role="single_operator",
            requested_by="卡卡罗特",
            assigned_owner_role="single_operator",
            assigned_owner="卡卡罗特",
            reviewer_role="single_operator",
            reviewer="卡卡罗特",
            reason="real_public_list_page_candidate_discovery",
            object_refs=object_refs,
            trace_refs={
                "operator_console_route": "/operator-console/autonomous-opportunity-search",
                "candidate_catalog_path": "/operator-console/real-candidates",
            },
            audit_refs={
                "internal_only": "true",
                "allowlisted_public_entry_fetch": "true",
                "real_provider_call_enabled": "false",
            },
            requested_at=requested_at,
            completed_at=requested_at,
        )
        self.repository.append(action)
        return self._run_action_payload(action)

    def persist_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        discovery_run_id: str,
        now: str,
    ) -> dict[str, Any]:
        existing_by_key = {
            str(item.get("candidate_key") or ""): item
            for item in self.list_candidates(limit=500).get("candidates", [])
        }
        persisted: list[dict[str, Any]] = []
        duplicate_count = 0
        for candidate in candidates:
            row = dict(candidate)
            key = str(row.get("candidate_key") or _candidate_key(row))
            row["candidate_key"] = key
            previous = existing_by_key.get(key)
            dedupe_decision = "MERGED_WITH_EXISTING" if previous else "NEW_CANDIDATE"
            if previous:
                duplicate_count += 1
            event_id = f"REAL-CANDIDATE-{key}-{_hash_text(discovery_run_id + now, 8)}".replace(":", "").replace("+", "")
            action = PersistedOperatorAction(
                action_event_id=event_id,
                work_item_id=REAL_CANDIDATE_DISCOVERY_CANDIDATE_WORK_ITEM_ID,
                stage_scope=1,
                action_id="operator_real_candidate_discovered",
                button_flow_id="owner_console_real_candidate_discovery",
                action_state=dedupe_decision,
                resulting_assignment_lifecycle_state=None,
                requested_by_role="single_operator",
                requested_by="卡卡罗特",
                assigned_owner_role="single_operator",
                assigned_owner="卡卡罗特",
                reviewer_role="single_operator",
                reviewer="卡卡罗特",
                reason="real_public_candidate_dedupe_and_persist",
                object_refs={
                    "candidate_key": key,
                    "candidate_json": _json_text(row),
                    "discovery_run_id": discovery_run_id,
                    "source_url": str(row.get("source_url") or ""),
                    "source_profile_id": str(row.get("source_profile_id") or ""),
                    "source_site_name": str(row.get("source_site_name") or ""),
                    "project_name": str(row.get("project_name") or ""),
                    "region_code": str(row.get("region_code") or ""),
                    "project_type": str(row.get("project_type") or ""),
                    "notice_stage": str(row.get("notice_stage") or ""),
                    "snapshot_id_optional": str(row.get("snapshot_id_optional") or ""),
                    "dedupe_decision": dedupe_decision,
                },
                trace_refs={
                    "operator_console_route": "/operator-console/autonomous-opportunity-search",
                    "candidate_catalog_path": "/operator-console/real-candidates",
                },
                audit_refs={
                    "internal_only": "true",
                    "allowlisted_public_entry_fetch": "true",
                    "real_provider_call_enabled": "false",
                },
                requested_at=now,
                completed_at=now,
            )
            self.repository.append(action)
            persisted.append(self._candidate_action_payload(action))
            existing_by_key[key] = row
        return {
            "persisted_candidates": persisted,
            "persisted_candidate_count": len(persisted),
            "duplicate_candidate_count": duplicate_count,
            "repository_work_item_id": REAL_CANDIDATE_DISCOVERY_CANDIDATE_WORK_ITEM_ID,
        }

    def list_candidates(self, *, limit: int = 100) -> dict[str, Any]:
        actions = self.repository.list(work_item_id=REAL_CANDIDATE_DISCOVERY_CANDIDATE_WORK_ITEM_ID)
        rows = [self._candidate_action_payload(action) for action in actions]
        raw_event_count = len(rows)
        rows = [
            row
            for row in rows
            if str(row.get("catalog_visibility_state") or "") != "HIDDEN_NON_DETAIL_LINK"
        ]
        rows.sort(key=lambda item: str(item.get("persisted_at") or ""), reverse=True)
        latest_by_key: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("candidate_key") or "")
            if not key or key in latest_by_key:
                continue
            latest_by_key[key] = row
        candidates = list(latest_by_key.values())[:limit]
        return {
            "surface_id": "operator_real_candidate_catalog",
            "repository_backed_readback": True,
            "data_source": "OperatorActionRepository",
            "storage_scope": "local_repository_operator_action_log",
            "retention_state": "PERSISTED_UNTIL_EXPLICIT_OPERATOR_CLEAR",
            "candidate_count": len(candidates),
            "raw_candidate_event_count": raw_event_count,
            "hidden_non_detail_link_event_count": max(raw_event_count - len(rows), 0),
            "duplicate_collapsed_count": max(len(rows) - len(candidates), 0),
            "candidates": candidates,
            "manual_url_picker_primary_flow": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            "customer_download_enabled": False,
        }

    def list_runs(self, *, limit: int = 50) -> dict[str, Any]:
        actions = self.repository.list(work_item_id=REAL_CANDIDATE_DISCOVERY_RUN_WORK_ITEM_ID)
        rows = [self._run_action_payload(action) for action in actions]
        rows.sort(key=lambda item: str(item.get("completed_at") or item.get("requested_at") or ""), reverse=True)
        return {
            "surface_id": "operator_real_candidate_discovery_runs",
            "repository_backed_readback": True,
            "data_source": "OperatorActionRepository",
            "run_count": len(rows),
            "runs": rows[:limit],
            "manual_url_picker_primary_flow": False,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            "customer_download_enabled": False,
        }

    def _candidate_action_payload(self, action: PersistedOperatorAction) -> dict[str, Any]:
        refs = dict(action.object_refs)
        candidate = dict(_json_value(refs.get("candidate_json"), {}))
        candidate["catalog_visibility_state"] = (
            "VISIBLE"
            if _is_candidate_detail_url(
                str(candidate.get("source_url") or ""),
                str(candidate.get("project_name") or ""),
                str(candidate.get("source_profile_id") or ""),
            )
            else "HIDDEN_NON_DETAIL_LINK"
        )
        candidate["candidate_key"] = refs.get("candidate_key") or candidate.get("candidate_key")
        candidate["dedupe_decision"] = refs.get("dedupe_decision") or action.action_state
        candidate["discovery_run_id"] = refs.get("discovery_run_id")
        candidate["persisted_at"] = action.requested_at
        candidate["repository_backed"] = True
        return candidate

    def _run_action_payload(self, action: PersistedOperatorAction) -> dict[str, Any]:
        refs = dict(action.object_refs)
        return {
            "discovery_run_id": refs.get("discovery_run_id") or action.action_event_id,
            "discovery_state": action.action_state,
            "candidate_count": _as_int(refs.get("candidate_count"), 0),
            "persisted_candidate_count": _as_int(refs.get("persisted_candidate_count"), 0),
            "duplicate_candidate_count": _as_int(refs.get("duplicate_candidate_count"), 0),
            "failure_count": _as_int(refs.get("failure_count"), 0),
            "region_codes": _json_value(refs.get("region_codes_json"), []),
            "project_types": _json_value(refs.get("project_types_json"), []),
            "query": refs.get("query"),
            "amount_min": refs.get("amount_min"),
            "amount_max": refs.get("amount_max"),
            "source_candidate_mode": refs.get("source_candidate_mode"),
            "candidate_limit_source": refs.get("candidate_limit_source"),
            "candidate_limit_effective": refs.get("candidate_limit_effective"),
            "stage1_6_validation_mode": refs.get("stage1_6_validation_mode") == "true",
            "stage1_6_validation_caps": _json_value(refs.get("stage1_6_validation_caps_json"), {}),
            "profile_reports": _json_value(refs.get("profile_reports_json"), []),
            "candidate_discovery_diagnostics": _json_value(refs.get("candidate_discovery_diagnostics_json"), {}),
            "requested_at": action.requested_at,
            "completed_at": action.completed_at,
            "repository_backed": True,
        }


class RealPublicCandidateDiscoveryService:
    def __init__(
        self,
        *,
        fetcher: RealPublicEntryFetcher | None = None,
        repository: RealPublicCandidateRepository | None = None,
        profile_api_link_discoverer: Any | None = None,
    ) -> None:
        injected_fetcher = fetcher is not None
        self.fetcher = fetcher or RealPublicEntryFetcher(repository=ObjectStorageRepository())
        self.repository = repository or RealPublicCandidateRepository()
        self.profile_api_link_discoverer = (
            profile_api_link_discoverer
            or (_unsupported_profile_api_link_items if injected_fetcher else _discover_profile_api_link_items)
        )

    def discover(self, payload: Mapping[str, Any], *, now: str | None = None) -> dict[str, Any]:
        discovered_at = now or str(payload.get("now") or utc_now_iso())
        evaluation_corpus_mode = bool(payload.get("evaluation_corpus_mode"))
        evaluation_document_kind = str(payload.get("evaluation_document_kind") or "").strip()
        explicit_source_profile_ids = _as_string_list(payload.get("source_profile_ids"), [])
        all_region_codes = [
            str(adapter.get("region_code") or "").strip()
            for adapter in list_region_source_adapters()
            if str(adapter.get("region_code") or "").strip()
        ]
        primary_region_code = str(payload.get("region_code") or "CN-NATIONAL").strip() or "CN-NATIONAL"
        region_codes = _as_string_list(payload.get("region_codes") or primary_region_code, [primary_region_code])
        if "__all__" in region_codes:
            region_codes = all_region_codes or ["CN-NATIONAL"]
        project_type = str(payload.get("project_type") or "construction").strip() or "construction"
        project_types = _as_string_list(payload.get("project_types") or project_type, [project_type])
        if "__all__" in project_types:
            project_types = ["construction", "municipal", "highway", "water_conservancy"]
        amount_min = _as_float(_first_present(payload.get("amount_min"), payload.get("minimum_amount")), 1_000_000.0)
        amount_max = _as_float(
            _first_present(payload.get("amount_max"), payload.get("maximum_amount"), payload.get("amount")),
            30_000_000.0,
        )
        if amount_min is not None and amount_max is not None and amount_max < amount_min:
            amount_min, amount_max = amount_max, amount_min
        raw_candidate_limit = _first_present(payload.get("discovery_candidate_limit"), payload.get("candidate_limit"))
        explicit_candidate_limit = _positive_int_or_none(raw_candidate_limit)
        guangdong_stage1_6_validation_scope = _is_guangdong_stage1_6_validation_scope(region_codes)
        candidate_limit = explicit_candidate_limit
        candidate_limit_source = (
            "EXPLICIT_LIMIT"
            if explicit_candidate_limit is not None
            else "ALL_FETCHED_WINDOW_CANDIDATES"
        )
        if candidate_limit is None and guangdong_stage1_6_validation_scope:
            candidate_limit = GUANGDONG_STAGE1_6_VALIDATION_CANDIDATE_LIMIT
            candidate_limit_source = "GUANGDONG_STAGE1_6_VALIDATION_DEFAULT"
        profile_limit = max(1, _as_int(payload.get("discovery_profile_limit_per_region"), DEFAULT_DISCOVERY_PROFILE_LIMIT_PER_REGION))
        query = str(payload.get("query") or payload.get("project_keyword") or payload.get("keyword") or "").strip()
        selection_filters = _as_string_list(payload.get("selection_filters"), [])
        run_id = str(payload.get("candidate_discovery_run_id") or build_id("REAL-CANDIDATE-DISCOVERY", _hash_text(discovered_at, 12)))
        per_region_candidate_limit = (
            None
            if candidate_limit is None
            else candidate_limit
            if len(region_codes) <= 1
            else max(1, (candidate_limit + len(region_codes) - 1) // len(region_codes))
        )

        candidates: list[dict[str, Any]] = []
        profile_reports: list[dict[str, Any]] = []
        seen_candidate_keys: set[str] = set()
        fetched_profiles: set[str] = set()
        for region_code in region_codes:
            adapter = resolve_region_source_adapter(region_code)
            profile_ids = (
                explicit_source_profile_ids[:profile_limit]
                if explicit_source_profile_ids
                else _profile_ids_for_region(region_code)[:profile_limit]
            )
            region_candidate_count = 0
            if not profile_ids:
                profile_reports.append(_source_not_configured_report(region_code, adapter))
                continue
            for profile_id in profile_ids:
                if (
                    (candidate_limit is not None and len(candidates) >= candidate_limit)
                    or (
                        per_region_candidate_limit is not None
                        and region_candidate_count >= per_region_candidate_limit
                    )
                ):
                    break
                if profile_id in EXCLUDED_DISCOVERY_PROFILE_IDS:
                    profile_reports.append(
                        {
                            "region_code": str(adapter.get("region_code") or region_code),
                            "profile_id": profile_id,
                            "entry_url": "",
                            "status": "SOURCE_PROFILE_EXCLUDED_BY_POLICY",
                            "failure_reason": "profile_removed_from_default_discovery_due_incomplete_tender_document_coverage",
                            "candidate_count": 0,
                            "accepted_candidate_count": 0,
                            "candidate_limit_truncated_count": 0,
                            "duplicate_filtered_count": 0,
                        }
                    )
                    continue
                profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID.get(profile_id)
                if profile is None:
                    profile_reports.append(
                        {
                            "region_code": str(adapter.get("region_code") or region_code),
                            "profile_id": profile_id,
                            "entry_url": "",
                            "status": "SOURCE_PROFILE_NOT_CONFIGURED",
                            "failure_reason": "source_profile_id_not_found",
                            "candidate_count": 0,
                            "accepted_candidate_count": 0,
                            "candidate_limit_truncated_count": 0,
                            "duplicate_filtered_count": 0,
                        }
                    )
                    continue
                if profile.profile_id in fetched_profiles:
                    continue
                fetched_profiles.add(profile.profile_id)
                try:
                    carrier = self.fetcher.fetch_entry_url(
                        profile.url,
                        profile_id=profile.profile_id,
                        lineage_refs={
                            "candidate_discovery_run_id": run_id,
                            "region_code": str(adapter.get("region_code") or region_code),
                        },
                    )
                except Exception as exc:
                    profile_reports.append(
                        {
                            "region_code": str(adapter.get("region_code") or region_code),
                            "profile_id": profile.profile_id,
                            "entry_url": profile.url,
                            "status": "FAILED",
                            "failure_reason": str(exc),
                            "candidate_count": 0,
                        }
                    )
                    continue
                parsed_result = self._candidates_from_carrier_with_diagnostics(
                    carrier,
                    region_adapter=adapter,
                    requested_region_code=str(region_code),
                    requested_project_types=project_types,
                    amount_min=amount_min,
                    amount_max=amount_max,
                    query=query,
                    run_id=run_id,
                    now=discovered_at,
                    evaluation_corpus_mode=evaluation_corpus_mode,
                    evaluation_document_kind=evaluation_document_kind,
                    selection_filters=selection_filters,
                )
                parsed = list(parsed_result["candidates"])
                diagnostics = dict(parsed_result["diagnostics"])
                new_rows: list[dict[str, Any]] = []
                candidate_limit_truncated_count = 0
                for index, row in enumerate(parsed):
                    if (
                        (candidate_limit is not None and len(candidates) >= candidate_limit)
                        or (
                            per_region_candidate_limit is not None
                            and region_candidate_count >= per_region_candidate_limit
                        )
                    ):
                        candidate_limit_truncated_count = max(len(parsed) - index, 0)
                        break
                    key = str(row.get("candidate_key") or _candidate_key(row))
                    if key in seen_candidate_keys:
                        continue
                    seen_candidate_keys.add(key)
                    new_rows.append(row)
                    candidates.append(row)
                    region_candidate_count += 1
                    if (
                        (candidate_limit is not None and len(candidates) >= candidate_limit)
                        or (
                            per_region_candidate_limit is not None
                            and region_candidate_count >= per_region_candidate_limit
                        )
                    ):
                        candidate_limit_truncated_count = max(len(parsed) - index - 1, 0)
                        break
                profile_reports.append(
                    {
                        "region_code": str(adapter.get("region_code") or region_code),
                        "profile_id": profile.profile_id,
                        "entry_url": profile.url,
                        "status": carrier.get("status"),
                        "snapshot_id_optional": carrier.get("snapshot_id_optional"),
                        "entry_fetch_id": carrier.get("entry_fetch_id"),
                        "http_status": carrier.get("http_status"),
                        "degraded_reasons": list(carrier.get("degraded_reasons", []) or []),
                        "same_site_detail_link_count": _as_int(
                            diagnostics.get("link_item_count"),
                            len(carrier.get("same_site_detail_links", []) or []),
                        ),
                        "public_api_state": diagnostics.get("public_api_state"),
                        "public_api_url": diagnostics.get("public_api_url"),
                        "public_api_total": diagnostics.get("public_api_total"),
                        "public_api_row_count": diagnostics.get("public_api_row_count"),
                        "public_api_page_size": diagnostics.get("public_api_page_size"),
                        "public_api_page_limit": diagnostics.get("public_api_page_limit"),
                        "public_api_candidate_record_window_cap": diagnostics.get(
                            "public_api_candidate_record_window_cap"
                        ),
                        "public_api_attempted_pages": diagnostics.get("public_api_attempted_pages"),
                        "public_api_trading_process_strategy": diagnostics.get(
                            "public_api_trading_process_strategy"
                        ),
                        "public_api_primary_trading_process": diagnostics.get(
                            "public_api_primary_trading_process"
                        ),
                        "public_api_fallback_recent_all_used": diagnostics.get(
                            "public_api_fallback_recent_all_used"
                        ),
                        "public_api_process_attempts": diagnostics.get("public_api_process_attempts"),
                        "candidate_diagnostics": diagnostics,
                        "operator_diagnosis": diagnostics.get("operator_diagnosis"),
                        "next_action": diagnostics.get("next_action"),
                        "rejected_counts": diagnostics.get("rejected_counts"),
                        "candidate_count": len(new_rows),
                        "accepted_candidate_count": len(parsed),
                        "candidate_limit_truncated_count": candidate_limit_truncated_count,
                        "duplicate_filtered_count": max(
                            len(parsed) - len(new_rows) - candidate_limit_truncated_count,
                            0,
                        ),
                    }
                )
            if candidate_limit is not None and len(candidates) >= candidate_limit:
                break

        persist_result = self.repository.persist_candidates(
            candidates=candidates,
            discovery_run_id=run_id,
            now=discovered_at,
        )
        result = {
            "surface_id": "operator_real_candidate_discovery",
            "discovery_run_id": run_id,
            "discovery_state": "COMPLETED" if candidates else "NO_CANDIDATES",
            "source_candidate_mode": REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
            "evaluation_corpus_mode": evaluation_corpus_mode,
            "evaluation_document_kind": evaluation_document_kind,
            "source_profile_ids_requested": explicit_source_profile_ids,
            "real_market_discovery": bool(candidates),
            "region_codes": region_codes,
            "project_types": project_types,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "query": query,
            "candidate_limit_explicit": explicit_candidate_limit is not None,
            "candidate_limit_source": candidate_limit_source,
            "candidate_limit_effective": candidate_limit
            if candidate_limit is not None
            else "ALL_FETCHED_WINDOW_CANDIDATES",
            "stage1_6_validation_mode": guangdong_stage1_6_validation_scope,
            "stage1_6_validation_caps": {
                "candidate_limit": candidate_limit
                if candidate_limit is not None
                else "ALL_FETCHED_WINDOW_CANDIDATES",
                "candidate_limit_source": candidate_limit_source,
                "guangdong_page_limit": MAX_GUANGDONG_DISCOVERY_PAGES
                if guangdong_stage1_6_validation_scope
                else "",
                "guangdong_page_size": GUANGDONG_DISCOVERY_PAGE_SIZE
                if guangdong_stage1_6_validation_scope
                else "",
                "candidate_limit_truncated_count": sum(
                    _as_int(row.get("candidate_limit_truncated_count"), 0)
                    for row in profile_reports
                ),
            },
            "candidate_count": len(candidates),
            "candidates": candidates,
            "profile_reports": profile_reports,
            "candidate_discovery_diagnostics": _discovery_diagnostics_summary(profile_reports),
            "failure_count": sum(1 for row in profile_reports if str(row.get("status")) in {"FAILED", "DEGRADED"}),
            "repository_backed_readback": True,
            "candidate_catalog_path": "/operator-console/real-candidates",
            "discovery_run_list_path": "/operator-console/real-candidate-discovery-runs",
            "manual_url_picker_primary_flow": False,
            "allowlisted_public_entry_fetch": True,
            "real_provider_call_enabled": False,
            "external_release_enabled": False,
            **persist_result,
        }
        result["run_record"] = self.repository.persist_discovery_result(payload=payload, result=result)
        return result

    def _candidates_from_carrier(
        self,
        carrier: Mapping[str, Any],
        *,
        region_adapter: Mapping[str, Any],
        requested_region_code: str,
        requested_project_types: list[str],
        amount_min: float | None,
        amount_max: float | None,
        query: str,
        run_id: str,
        now: str,
        evaluation_corpus_mode: bool = False,
        evaluation_document_kind: str = "",
        selection_filters: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return list(
            self._candidates_from_carrier_with_diagnostics(
                carrier,
                region_adapter=region_adapter,
                requested_region_code=requested_region_code,
                requested_project_types=requested_project_types,
                amount_min=amount_min,
                amount_max=amount_max,
                query=query,
                run_id=run_id,
                now=now,
                evaluation_corpus_mode=evaluation_corpus_mode,
                evaluation_document_kind=evaluation_document_kind,
                selection_filters=selection_filters,
            )["candidates"]
        )

    def _candidates_from_carrier_with_diagnostics(
        self,
        carrier: Mapping[str, Any],
        *,
        region_adapter: Mapping[str, Any],
        requested_region_code: str,
        requested_project_types: list[str],
        amount_min: float | None,
        amount_max: float | None,
        query: str,
        run_id: str,
        now: str,
        evaluation_corpus_mode: bool = False,
        evaluation_document_kind: str = "",
        selection_filters: list[str] | None = None,
    ) -> dict[str, Any]:
        profile_id = str(carrier.get("entry_profile_id") or "")
        link_items = carrier.get("same_site_detail_link_items")
        if not isinstance(link_items, list) or not link_items:
            link_items = [
                {"url": url, "text": _title_from_url(str(url))}
                for url in list(carrier.get("same_site_detail_links", []) or [])
            ]
        api_context = {
            "requested_region_code": requested_region_code,
            "requested_project_types": requested_project_types,
            "query": query,
            "evaluation_corpus_mode": evaluation_corpus_mode,
            "evaluation_document_kind": evaluation_document_kind,
            "selection_filters": list(selection_filters or []),
        }
        api_discovery = dict(
            _call_profile_api_link_discoverer(
                self.profile_api_link_discoverer,
                profile_id,
                now=now,
                context=api_context,
            )
            or {}
        )
        api_link_items = [
            dict(item)
            for item in list(api_discovery.get("items") or [])
            if isinstance(item, Mapping)
        ]
        backtrace_requested = any(
            str(value or "").strip().startswith("BACKTRACE_")
            for value in list(selection_filters or [])
        )
        if api_link_items:
            link_items = api_link_items if profile_id == GUANGZHOU_YWTB_PROFILE_ID and backtrace_requested else _merge_link_items(api_link_items, list(link_items))
        elif profile_id == GUANGZHOU_YWTB_PROFILE_ID and backtrace_requested:
            link_items = []
        rows: list[dict[str, Any]] = []
        region_name = str(region_adapter.get("region_name") or requested_region_code)
        source_site_name = str(carrier.get("site_name") or "")
        source_family = str(carrier.get("source_family") or "")
        diagnostics: dict[str, Any] = {
            "profile_id": profile_id,
            "entry_url": str(carrier.get("entry_url") or ""),
            "status": str(carrier.get("status") or ""),
            "evaluation_corpus_mode": evaluation_corpus_mode,
            "evaluation_document_kind": evaluation_document_kind,
            "link_item_count": len(link_items),
            "same_site_detail_link_count": len(carrier.get("same_site_detail_links", []) or []),
            "profile_api_discovery_state": str(api_discovery.get("state") or "UNSUPPORTED"),
            "profile_api_endpoint": str(api_discovery.get("endpoint") or ""),
            "profile_api_link_count": len(api_link_items),
            "profile_api_error_optional": str(api_discovery.get("error_optional") or ""),
            "public_api_total": api_discovery.get("total"),
            "public_api_row_count": api_discovery.get("record_count"),
            "public_api_page_size": api_discovery.get("page_size"),
            "public_api_page_limit": api_discovery.get("page_limit"),
            "public_api_candidate_record_window_cap": api_discovery.get("candidate_record_window_cap"),
            "public_api_attempted_pages": api_discovery.get("attempted_pages"),
            "public_api_trading_process_strategy": api_discovery.get("trading_process_strategy"),
            "public_api_primary_trading_process": api_discovery.get("primary_trading_process"),
            "public_api_fallback_recent_all_used": bool(api_discovery.get("fallback_recent_all_used")),
            "public_api_process_attempts": list(api_discovery.get("process_attempts", []) or []),
            "public_api_backtrace_query_variants": list(api_discovery.get("backtrace_query_variants", []) or []),
            "public_api_backtrace_base_project_name": str(api_discovery.get("backtrace_base_project_name") or ""),
            "accepted_candidate_count": 0,
            "rejected_counts": {},
            "rejected_samples": [],
            "sample_link_items": [
                {
                    "url": str(item.get("url") or ""),
                    "text": _clean_text(item.get("text"))[:120],
                }
                for item in link_items[:5]
                if isinstance(item, Mapping)
            ],
            "operator_diagnosis": [],
            "next_action": "",
            "js_shell_suspected": False,
            "candidate_time_window": "recent_30_days_by_publish_time",
        }

        def reject(reason: str, *, item: Mapping[str, Any] | None = None, extra: Mapping[str, Any] | None = None) -> None:
            rejected_counts = dict(diagnostics.get("rejected_counts", {}) or {})
            rejected_counts[reason] = _as_int(rejected_counts.get(reason), 0) + 1
            diagnostics["rejected_counts"] = rejected_counts
            samples = list(diagnostics.get("rejected_samples", []) or [])
            if item is not None and len(samples) < 8:
                sample = {
                    "reason": reason,
                    "url": str(item.get("url") or ""),
                    "title": _clean_text(item.get("text"))[:160],
                }
                if extra:
                    sample.update(dict(extra))
                samples.append(sample)
                diagnostics["rejected_samples"] = samples

        for index, item in enumerate(link_items):
            if not isinstance(item, Mapping):
                reject("non_mapping_link_item")
                continue
            source_url = str(item.get("url") or "").strip()
            if not source_url:
                reject("missing_source_url", item=item)
                continue
            title = _normalize_public_title(item.get("text")) or _title_from_url(source_url)
            analysis_text = " ".join(
                part
                for part in (
                    title,
                    _clean_text(item.get("summary")),
                    _clean_text(item.get("content")),
                )
                if part
            )
            if profile_id in _PROVINCE_REALTIME_PROFILE_IDS and _is_navigation_or_template_link(source_url, title):
                reject("navigation_or_template_link", item=item)
                continue
            if not evaluation_corpus_mode and _is_non_actionable_notice_text(analysis_text):
                reject("non_actionable_notice_state", item=item)
                continue
            published_at = str(item.get("published_at") or "").strip()
            discovery_review_reasons: list[str] = []
            discovery_filter_tags: list[str] = []
            publication_window_state = (
                "WITHIN_RECENT_DISCOVERY_WINDOW"
                if _is_published_within_discovery_window(published_at, now=now)
                else "OUTSIDE_RECENT_DISCOVERY_WINDOW"
            )
            if publication_window_state == "OUTSIDE_RECENT_DISCOVERY_WINDOW":
                discovery_review_reasons.append("published_outside_recent_discovery_window")
                discovery_filter_tags.append("published_outside_discovery_window")
            if not _is_candidate_detail_url(
                source_url,
                title,
                profile_id,
                allow_non_actionable_title=evaluation_corpus_mode,
            ):
                reject("not_candidate_detail_url", item=item)
                continue
            source_region_code = str(item.get("source_region_code") or "").strip() or _region_from_source_url(source_url)
            region_code = source_region_code or str(region_adapter.get("region_code") or requested_region_code)
            region_parse_state = "SOURCE_URL_ADMIN_CODE" if source_region_code else "SEARCH_SCOPE_UNCONFIRMED"
            if requested_region_code != "CN-NATIONAL" and source_region_code and source_region_code != requested_region_code:
                reject(
                    "region_mismatch",
                    item=item,
                    extra={"source_region_code": source_region_code, "requested_region_code": requested_region_code},
                )
                continue
            project_type, project_type_parse_state = _infer_project_type(analysis_text, requested_project_types)
            if requested_project_types and project_type not in requested_project_types:
                discovery_review_reasons.append("project_type_outside_requested_scope")
                discovery_filter_tags.append("project_type_mismatch")
            amount, amount_parse_state = _extract_amount(analysis_text)
            if amount is not None and amount_min is not None and amount < amount_min:
                discovery_review_reasons.append("amount_below_requested_minimum")
                discovery_filter_tags.append("amount_below_minimum")
            if amount is not None and amount_max is not None and amount > amount_max:
                discovery_review_reasons.append("amount_above_requested_maximum")
                discovery_filter_tags.append("amount_above_maximum")
            if discovery_filter_tags:
                preserved_counts = dict(diagnostics.get("preserved_filter_counts", {}) or {})
                for tag in discovery_filter_tags:
                    preserved_counts[tag] = _as_int(preserved_counts.get(tag), 0) + 1
                diagnostics["preserved_filter_counts"] = preserved_counts
            notice_stage = _infer_notice_stage(analysis_text)
            has_candidate_signal = notice_stage in {"candidate_notice", "award_result", "result_notice", "bid_result"}
            key_fields_present = ["project_name", "notice_stage"]
            candidate_company = ""
            if "候选人" in title:
                candidate_company = "列表页仅标明候选人公告，候选公司待详情页解析"
                key_fields_present.append("candidate_company")
            candidate_key = _hash_text(source_url.lower(), 24)
            source_project_code = str(item.get("project_code") or "").strip()
            source_record_id = str(item.get("source_record_id") or "").strip()
            base_project_name = str(item.get("base_project_name") or "").strip()
            guangzhou_flow_no = str(item.get("guangzhou_flow_no") or "").strip()
            guangzhou_flow_title = str(item.get("guangzhou_flow_title") or "").strip()
            guangzhou_flow_code = str(item.get("guangzhou_flow_code") or item.get("trading_process") or "").strip()
            guangzhou_flow_folder = str(item.get("guangzhou_flow_folder") or "").strip()
            guangzhou_relation_guid = str(item.get("guangzhou_relation_guid") or source_project_code or "").strip()
            backtrace_query_variants = _dedupe_texts(
                [str(value or "") for value in list(item.get("backtrace_query_variants") or [])]
            )
            backtrace_match_reason = str(item.get("backtrace_match_reason") or "").strip()
            project_match_key = str(
                item.get("project_match_key")
                or source_project_code
                or _normalize_guangzhou_project_match_text(title)
            ).strip()
            matched_project_keys = _dedupe_texts(
                [
                    source_project_code,
                    project_match_key,
                    _normalize_guangzhou_project_match_text(title),
                ]
            )
            notice_id = build_id("NOTICE", _slug(profile_id, "PROFILE"), candidate_key[:10])
            if profile_id == GUANGZHOU_YWTB_PROFILE_ID and project_match_key:
                project_token = (
                    _slug(project_match_key, "")
                    or _slug(source_project_code, "")
                    or f"GZ-{_hash_text(project_match_key, 14).upper()}"
                )
                project_id = build_id("PROJ", _slug(region_code, "REGION"), project_token[:28])
            else:
                project_id = build_id("PROJ", _slug(region_code, "REGION"), candidate_key[:10])
            query_match = bool(query and query in analysis_text)
            source_quality_policy = resolve_source_quality_policy(profile_id)
            rows.append(
                {
                    "notice_id": notice_id,
                    "project_id": project_id,
                    "project_name": title,
                    "region_code": region_code,
                    "region_name": region_name,
                    "project_type": project_type,
                    "project_type_label": _project_type_label(project_type),
                    "project_type_parse_state": project_type_parse_state,
                    "procurement_category": project_type,
                    "notice_stage": notice_stage,
                    "amount": amount,
                    "estimated_amount": amount,
                    "amount_min": amount_min,
                    "amount_max": amount_max,
                    "amount_parse_state": amount_parse_state,
                    "amount_range_label": f"{amount_min:,.0f}-{amount_max:,.0f}" if amount_min is not None and amount_max is not None else "",
                    "candidate_count": 1 if has_candidate_signal else 0,
                    "competitor_count": 1 if has_candidate_signal else 0,
                    "candidate_company": candidate_company,
                    "objection_deadline_at_optional": "",
                    "key_fields_present": key_fields_present,
                    "source_url": source_url,
                    "source_family": source_family,
                    "source_registry_id": "REAL_PUBLIC_LIST_PAGE_DISCOVERY",
                    "source_profile_id": profile_id,
                    "source_quality_state": source_quality_policy["source_quality_state"],
                    "source_calibration_role": source_quality_policy["source_calibration_role"],
                    "professional_source_priority": bool(
                        source_quality_policy["professional_source_priority"]
                    ),
                    "source_site_name": source_site_name,
                    "source_candidate_mode": REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
                    "evaluation_corpus_mode": evaluation_corpus_mode,
                    "evaluation_document_kind": evaluation_document_kind,
                    "is_offline_sample_candidate": False,
                    "sellability_evidence_state": "REAL_LIST_PAGE_CANDIDATE_NEEDS_DETAIL_CAPTURE",
                    "truth_boundary": "真实列表页候选已入库；客户可售证据仍需详情页/附件抓取、字段解析和证据回链。",
                    "candidate_discovery_run_id": run_id,
                    "candidate_key": candidate_key,
                    "source_entry_url": str(carrier.get("entry_url") or ""),
                    "entry_fetch_id": str(carrier.get("entry_fetch_id") or ""),
                    "entry_fetch_status": str(carrier.get("status") or ""),
                    "snapshot_id_optional": str(carrier.get("snapshot_id_optional") or ""),
                    "published_at_optional": published_at,
                    "publication_window_state": publication_window_state
                    if published_at
                    else "PUBLISH_TIME_NOT_EXPOSED_BY_LIST",
                    "source_trading_process": str(item.get("trading_process") or ""),
                    "source_dataset_name": str(item.get("dataset_name") or ""),
                    "source_notice_third_type_desc": str(item.get("notice_third_type_desc") or ""),
                    "source_query_process_label": str(item.get("query_process_label") or ""),
                    "source_project_code": source_project_code,
                    "source_record_id": source_record_id,
                    "guangzhou_flow_no": guangzhou_flow_no,
                    "guangzhou_flow_title": guangzhou_flow_title,
                    "guangzhou_flow_code": guangzhou_flow_code,
                    "guangzhou_flow_folder": guangzhou_flow_folder,
                    "guangzhou_relation_guid": guangzhou_relation_guid,
                    "project_match_key": project_match_key,
                    "matched_project_keys": matched_project_keys,
                    "base_project_name": base_project_name,
                    "backtrace_query_variants": backtrace_query_variants,
                    "backtrace_match_reason": backtrace_match_reason,
                    "discovery_preserved_after_filter_review": bool(discovery_review_reasons),
                    "discovery_review_reasons": discovery_review_reasons,
                    "discovery_filter_tags": discovery_filter_tags,
                    "market_scan_generated_at": now,
                    "discovered_at": now,
                    "query_match_state": "TITLE_MATCH" if query_match else "LIST_PAGE_CANDIDATE",
                    "region_parse_state": region_parse_state,
                    "parse_index": index,
                }
            )
        diagnostics["accepted_candidate_count"] = len(rows)
        diagnostics["operator_diagnosis"] = _operator_diagnosis_for_profile(
            diagnostics,
            carrier=carrier,
            profile_id=profile_id,
        )
        diagnostics["next_action"] = _next_action_for_profile_diagnostics(diagnostics)
        return {"candidates": rows, "diagnostics": diagnostics}


def list_persisted_real_candidates(*, limit: int = 100) -> dict[str, Any]:
    return RealPublicCandidateRepository().list_candidates(limit=limit)


def list_real_candidate_discovery_runs(*, limit: int = 50) -> dict[str, Any]:
    return RealPublicCandidateRepository().list_runs(limit=limit)


__all__ = [
    "REAL_PUBLIC_SOURCE_CANDIDATE_MODE",
    "RealPublicCandidateDiscoveryService",
    "RealPublicCandidateRepository",
    "list_persisted_real_candidates",
    "list_real_candidate_discovery_runs",
]
