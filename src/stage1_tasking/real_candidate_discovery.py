from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from shared.utils import build_id, utc_now_iso
from stage1_tasking.region_adapters import (
    list_region_source_adapters,
    resolve_region_source_adapter,
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
GUANGDONG_CANDIDATE_PUBLICITY_TRADING_PROCESS = "3C42"
GUANGDONG_YGP_TRADING_PROCESS_PRIORITY = (
    ("candidate_publicity", GUANGDONG_CANDIDATE_PUBLICITY_TRADING_PROCESS),
    ("recent_all_fallback", ""),
)

_PROJECT_TYPE_LABELS = {
    "construction": "房建工程",
    "municipal": "市政工程",
    "highway": "公路交通",
    "water_conservancy": "水利工程",
}

_PROVINCE_ADMIN_CODE_TO_REGION = {
    "110000": "CN-BJ",
    "320000": "CN-JS",
    "330000": "CN-ZJ",
    "370000": "CN-SD",
    "420000": "CN-HB",
    "440000": "CN-GD",
    "510000": "CN-SC",
    "530000": "CN-YN",
}

_BROWSER_RENDERED_REALTIME_PROFILE_IDS = {
    "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
}

_PROVINCE_REALTIME_PROFILE_IDS = {
    "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
    "JIANGSU-GGZY-HOME",
    "ZHEJIANG-GGZY-JYXXGK-LIST",
    "SHANDONG-GGZY-JYXXGK-LIST",
    "HUBEI-BIDCLOUD-JYXX-LIST",
    "SICHUAN-GGZY-TRANSACTION-INFO",
}

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
}

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
    if "gdzwfw" in host or "guangdong" in host:
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
    normalized = clean_title.replace(" ", "").lower()
    if not normalized:
        return True
    if normalized in _GENERIC_NAV_TITLE_EXACTS:
        return True
    if len(normalized) <= 8 and any(token in normalized for token in ("更多", "查看更多", "入口", "栏目", "专题")):
        return True
    return False


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


def _discover_profile_api_link_items(profile_id: str, *, now: str) -> dict[str, Any]:
    if profile_id == "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return _discover_guangdong_ygp_api_link_items(now=now)
    if profile_id == "JIANGSU-GGZY-HOME":
        return _discover_text_search_api_link_items(
            endpoint="http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
            base_url="http://jsggzy.jszwfw.gov.cn/",
            referer="http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html",
            date_field="infodatepx",
            sort_field="infodatepx",
            no_participle="1",
            now=now,
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
        )
    if profile_id == "SICHUAN-GGZY-TRANSACTION-INFO":
        return _discover_sichuan_api_link_items(now=now)
    return {
        "state": "UNSUPPORTED",
        "endpoint": "",
        "items": [],
        "error_optional": "",
    }


def _stringify_guangdong_ygp_payload(payload: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif value is None:
            text = ""
        else:
            text = str(value)
        parts.append(f"{quote(str(key), safe='')}={quote(text, safe='')}")
    return "&".join(parts)


def _guangdong_ygp_signature_headers(payload: Mapping[str, Any]) -> dict[str, str]:
    nonce = secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:16]
    timestamp_ms = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    sorted_query = "&".join(sorted(_stringify_guangdong_ygp_payload(payload).split("&")))
    signature_basis = f"{nonce}k8tUyS$m{_url_decode_for_guangdong_signature(sorted_query)}{timestamp_ms}"
    return {
        "X-Dgi-Req-App": "ggzy-portal",
        "X-Dgi-Req-Nonce": nonce,
        "X-Dgi-Req-Timestamp": timestamp_ms,
        "X-Dgi-Req-Signature": hashlib.sha256(signature_basis.encode("utf-8")).hexdigest(),
    }


def _url_decode_for_guangdong_signature(value: str) -> str:
    # 广东门户前端签名逻辑先按 & 排序，再对 query-string 做 decodeURIComponent。
    return unquote(value)


def _discover_guangdong_ygp_api_link_items(*, now: str) -> dict[str, Any]:
    endpoint = "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items"
    start_date, end_date = _date_window_from_now(now)
    base_payload = {
        "type": "trading-type",
        "openConvert": False,
        "keyword": "",
        "siteCode": "44",
        "secondType": "A",
        "tradingProcess": "",
        "thirdType": "[]",
        "projectType": "",
        "publishStartTime": "",
        "publishEndTime": "",
        "pageSize": GUANGDONG_DISCOVERY_PAGE_SIZE,
    }
    all_records: list[Any] = []
    total_by_process: dict[str, str] = {}
    process_attempts: list[dict[str, Any]] = []
    page_errors: list[str] = []
    for process_label, trading_process in GUANGDONG_YGP_TRADING_PROCESS_PRIORITY:
        process_records: list[Any] = []
        attempted_pages = 0
        for page_no in range(1, MAX_GUANGDONG_DISCOVERY_PAGES + 1):
            payload = {**base_payload, "tradingProcess": trading_process, "pageNo": page_no}
            request = Request(
                endpoint,
                data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                headers={
                    "User-Agent": "AX9S-RealPublicCandidateDiscovery/0.1 (+public-readonly-validation)",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://ygp.gdzwfw.gov.cn/",
                    **_guangdong_ygp_signature_headers(payload),
                },
                method="POST",
            )
            attempted_pages = page_no
            try:
                with urlopen(request, timeout=18) as response:
                    raw = response.read(1_500_000).decode("utf-8", "ignore")
                data = json.loads(raw)
            except Exception as exc:  # pragma: no cover - public network failures vary
                page_errors.append(f"{process_label}:page_{page_no}:{exc}")
                break
            page_data = list(((data.get("data") or {}).get("pageData") or []))
            total_by_process[process_label] = str((data.get("data") or {}).get("total") or "")
            if not page_data:
                break
            for record in page_data:
                row = dict(record) if isinstance(record, Mapping) else record
                if isinstance(row, dict):
                    row["_ax9s_query_process_label"] = process_label
                    row["_ax9s_query_trading_process"] = trading_process
                process_records.append(row)
            if len(page_data) < GUANGDONG_DISCOVERY_PAGE_SIZE:
                break
        process_attempts.append(
            {
                "process_label": process_label,
                "trading_process": trading_process,
                "attempted_pages": attempted_pages,
                "record_count": len(process_records),
                "total": total_by_process.get(process_label, ""),
            }
        )
        if process_records:
            all_records.extend(process_records)
            if process_label == "candidate_publicity":
                break
    items = _link_items_from_guangdong_ygp_records(all_records)
    return {
        "state": "FETCHED" if items else "FAILED" if page_errors else "EMPTY",
        "endpoint": endpoint,
        "items": items,
        "error_optional": ";".join(page_errors),
        "query_window": {"start_date": start_date, "end_date": end_date},
        "api_time_filter_state": "candidate_publicity_process_first_then_recent_fallback",
        "trading_process_strategy": "candidate_publicity_first",
        "process_attempts": process_attempts,
        "primary_trading_process": GUANGDONG_CANDIDATE_PUBLICITY_TRADING_PROCESS,
        "fallback_recent_all_used": bool(
            process_attempts
            and process_attempts[-1].get("process_label") == "recent_all_fallback"
            and process_attempts[-1].get("record_count")
        ),
        "page_size": GUANGDONG_DISCOVERY_PAGE_SIZE,
        "page_limit": MAX_GUANGDONG_DISCOVERY_PAGES,
        "candidate_record_window_cap": GUANGDONG_DISCOVERY_PAGE_SIZE * MAX_GUANGDONG_DISCOVERY_PAGES,
        "attempted_pages": sum(_as_int(item.get("attempted_pages"), 0) for item in process_attempts),
        "record_count": len(all_records),
        "total": total_by_process.get("candidate_publicity") or total_by_process.get("recent_all_fallback") or "",
        "total_by_process": total_by_process,
    }


def _link_items_from_guangdong_ygp_records(records: list[Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        title = _normalize_public_title(record.get("noticeTitle"))
        notice_id = str(record.get("noticeId") or "").strip()
        edition = str(record.get("edition") or "").strip()
        notice_second_type = str(record.get("noticeSecondType") or "").strip()
        if not title or not notice_id or not edition or not notice_second_type:
            continue
        detail_url = _guangdong_ygp_detail_url(record)
        if not detail_url or detail_url in seen:
            continue
        seen.add(detail_url)
        summary_parts = [
            record.get("noticeSecondTypeDesc"),
            record.get("projectTypeName"),
            record.get("datasetName"),
            record.get("regionName"),
            record.get("siteName"),
            record.get("projectOwner"),
            record.get("pubServicePlat"),
            record.get("noticeNature"),
        ]
        items.append(
            {
                "url": detail_url,
                "text": title,
                "summary": " ".join(_clean_text(part) for part in summary_parts if _clean_text(part)),
                "published_at": _format_guangdong_publish_date(record.get("publishDate")),
                "categorynum": str(record.get("noticeThirdType") or ""),
                "trading_process": str(record.get("tradingProcess") or record.get("_ax9s_query_trading_process") or ""),
                "dataset_name": str(record.get("datasetName") or ""),
                "notice_third_type_desc": str(record.get("noticeThirdTypeDesc") or ""),
                "query_process_label": str(record.get("_ax9s_query_process_label") or ""),
                "source_api": "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items",
                "source_record_id": str(record.get("docId") or notice_id),
            }
        )
    return items


def _guangdong_ygp_detail_url(record: Mapping[str, Any]) -> str:
    base = "https://ygp.gdzwfw.gov.cn/#/44/new/jygg"
    edition = str(record.get("edition") or "").strip()
    notice_second_type = str(record.get("noticeSecondType") or "").strip()
    if not edition or not notice_second_type:
        return ""
    query = {
        "noticeId": str(record.get("noticeId") or "").strip(),
        "projectCode": str(record.get("projectCode") or "").strip(),
        "bizCode": str(record.get("tradingProcess") or record.get("bizCode") or "").strip(),
        "siteCode": str(record.get("regionCode") or record.get("siteCode") or "44").strip(),
        "publishDate": str(record.get("publishDate") or "").strip(),
        "source": str(record.get("pubServicePlat") or "").strip(),
        "titleDetails": str(record.get("noticeSecondTypeDesc") or "").strip(),
        "classify": str(record.get("projectType") or "").strip(),
    }
    query = {key: value for key, value in query.items() if value}
    return f"{base}/{quote(edition, safe='')}/{quote(notice_second_type, safe='')}?{urlencode(query)}"


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
        "items": _link_items_from_text_search_records(records, base_url=base_url, endpoint=endpoint),
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
                "categorynum": str(record.get("categorynum") or ""),
                "source_api": endpoint,
            }
        )
    return items


def _discover_sichuan_api_link_items(*, now: str) -> dict[str, Any]:
    endpoint = "https://ggzyjy.sc.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
    start_date, end_date = _date_window_from_now(now)
    condition = {
        "fieldName": "categorynum",
        "equal": "002001",
        "notEqual": None,
        "equalList": None,
        "notEqualList": None,
        "isLike": True,
        "likeType": 2,
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
    )
    return {
        "state": "FETCHED" if items else "EMPTY",
        "endpoint": endpoint,
        "items": items,
        "error_optional": "",
        "query_window": {"start_date": start_date, "end_date": end_date},
        "record_count": len(records),
    }


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


def _is_candidate_detail_url(url: str, title: str, profile_id: str) -> bool:
    path = urlsplit(url).path.lower()
    text = title.lower()
    if _has_template_placeholder(url, title):
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
    if profile_id == "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return (
            "ygp.gdzwfw.gov.cn" in urlsplit(url).netloc.lower()
            and "/jygg" in url
            and (_is_real_notice_candidate_title(title) or _is_guangdong_ygp_structured_notice_url(url))
        )
    if profile_id in _PROVINCE_REALTIME_PROFILE_IDS:
        host = urlsplit(url).netloc.lower()
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
        if not _is_real_notice_candidate_title(title):
            return False
        return path.endswith((".html", ".htm", ".shtml", ".jhtml", ".jspx", ".jsp")) and not path.endswith(
            ("index.html", "list.html", "about.html", "transactioninfo.html")
        )
    if "GUANGDONG" in profile_id:
        return path.endswith((".html", ".htm", ".shtml")) and any(
            token in path for token in ("notice", "jygg", "ggzy", "bulletin")
        )
    return path.endswith((".html", ".htm", ".shtml")) and not path.endswith(("index.html", "deallist.html"))


def _is_guangdong_ygp_structured_notice_url(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    if parsed.netloc.lower() != "ygp.gdzwfw.gov.cn":
        return False
    fragment_path, _, fragment_query = parsed.fragment.partition("?")
    if "/jygg/" not in fragment_path:
        return False
    query_values = parse_qs(fragment_query, keep_blank_values=True)
    return all(str((query_values.get(key) or [""])[0]).strip() for key in ("noticeId", "projectCode", "bizCode"))


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
            profile_ids = _profile_ids_for_region(region_code)[:profile_limit]
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
                profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID.get(profile_id)
                if profile is None:
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
    ) -> dict[str, Any]:
        profile_id = str(carrier.get("entry_profile_id") or "")
        link_items = carrier.get("same_site_detail_link_items")
        if not isinstance(link_items, list) or not link_items:
            link_items = [
                {"url": url, "text": _title_from_url(str(url))}
                for url in list(carrier.get("same_site_detail_links", []) or [])
            ]
        api_discovery = dict(self.profile_api_link_discoverer(profile_id, now=now) or {})
        api_link_items = [
            dict(item)
            for item in list(api_discovery.get("items") or [])
            if isinstance(item, Mapping)
        ]
        if api_link_items:
            link_items = _merge_link_items(api_link_items, list(link_items))
        rows: list[dict[str, Any]] = []
        region_name = str(region_adapter.get("region_name") or requested_region_code)
        source_site_name = str(carrier.get("site_name") or "")
        source_family = str(carrier.get("source_family") or "")
        diagnostics: dict[str, Any] = {
            "profile_id": profile_id,
            "entry_url": str(carrier.get("entry_url") or ""),
            "status": str(carrier.get("status") or ""),
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
            if profile_id in _PROVINCE_REALTIME_PROFILE_IDS and _is_non_actionable_notice_text(analysis_text):
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
            if not _is_candidate_detail_url(source_url, title, profile_id):
                reject("not_candidate_detail_url", item=item)
                continue
            source_region_code = _region_from_source_url(source_url)
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
            notice_id = build_id("NOTICE", _slug(profile_id, "PROFILE"), candidate_key[:10])
            project_id = build_id("PROJ", _slug(region_code, "REGION"), candidate_key[:10])
            query_match = bool(query and query in analysis_text)
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
                    "source_site_name": source_site_name,
                    "source_candidate_mode": REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
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
