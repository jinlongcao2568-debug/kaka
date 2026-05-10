from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage1_tasking.real_candidate_discovery import (
    REAL_PUBLIC_SOURCE_CANDIDATE_MODE,
    RealPublicCandidateDiscoveryService,
    RealPublicCandidateRepository,
    _guangdong_ygp_process_priority,
    _guangzhou_ywtb_process_priority,
    _is_candidate_detail_url,
    _link_items_from_guangzhou_ywtb_records,
    _link_items_from_guangdong_ygp_records,
    _link_items_from_text_search_records,
    list_persisted_real_candidates,
    list_real_candidate_discovery_runs,
)
from storage import reset_default_storage
from storage.db import DatabaseSession


class FakeCandidateEntryFetcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch_entry_url(self, url: str, *, profile_id: str | None = None, lineage_refs: dict[str, str] | None = None) -> dict:
        self.calls.append(
            {
                "url": url,
                "profile_id": profile_id,
                "lineage_refs": dict(lineage_refs or {}),
            }
        )
        return {
            "entry_fetch_id": f"FETCH-{profile_id}",
            "status": "FETCHED",
            "entry_profile_id": profile_id,
            "entry_url": url,
            "site_name": "全国公共资源交易平台",
            "source_family": "local_public_resource_trading_center",
            "http_status": 200,
            "snapshot_id_optional": f"SNAP-{profile_id}",
            "degraded_reasons": [],
            "same_site_detail_links": [
                "https://www.ggzy.gov.cn/information/deal/html/a/440000/0101/20260424/gd-road.html",
                "https://www.ggzy.gov.cn/information/deal/html/a/320000/0101/20260424/js-water.html",
            ],
            "same_site_detail_link_items": [
                {
                    "url": "https://www.ggzy.gov.cn/information/deal/html/a/440000/0101/20260424/gd-road.html",
                    "text": "广东市政道路改造工程中标候选人公示 1200万元",
                },
                {
                    "url": "https://www.ggzy.gov.cn/information/deal/html/a/320000/0101/20260424/js-water.html",
                    "text": "江苏水利工程中标公告 900万元",
                },
            ],
        }


class FakeGuangdongShellFetcher:
    def fetch_entry_url(self, url: str, *, profile_id: str | None = None, lineage_refs: dict[str, str] | None = None) -> dict:
        return {
            "entry_fetch_id": f"FETCH-{profile_id}",
            "status": "FETCHED",
            "entry_profile_id": profile_id,
            "entry_url": url,
            "site_name": "广东省公共资源交易平台",
            "source_family": "local_public_resource_trading_center",
            "http_status": 200,
            "snapshot_id_optional": f"SNAP-{profile_id}",
            "degraded_reasons": [],
            "same_site_detail_links": [],
            "same_site_detail_link_items": [],
            "lightweight_public_entry_markers_found": ["广东省公共资源交易平台"],
        }


class FakeProvinceNavigationFetcher:
    def fetch_entry_url(self, url: str, *, profile_id: str | None = None, lineage_refs: dict[str, str] | None = None) -> dict:
        return {
            "entry_fetch_id": f"FETCH-{profile_id}",
            "status": "FETCHED",
            "entry_profile_id": profile_id,
            "entry_url": url,
            "site_name": "江苏省公共资源交易网",
            "source_family": "local_public_resource_trading_center",
            "http_status": 200,
            "snapshot_id_optional": f"SNAP-{profile_id}",
            "degraded_reasons": [],
            "same_site_detail_links": [
                "http://jsggzy.jszwfw.gov.cn/jyxx/003001/index.html",
                "https://ggzy.zj.gov.cn/jyxxgk/{{linkurl}}",
                "https://ggzyjy.sc.gov.cn/jyxx/{{infourl}}",
            ],
            "same_site_detail_link_items": [
                {
                    "url": "http://jsggzy.jszwfw.gov.cn/jyxx/003001/index.html",
                    "text": "通知公告",
                },
                {
                    "url": "https://ggzy.zj.gov.cn/jyxxgk/{{linkurl}}",
                    "text": "{{title}}",
                },
                {
                    "url": "https://ggzyjy.sc.gov.cn/jyxx/{{infourl}}",
                    "text": "查看更多",
                },
            ],
        }


class FakeJiangsuRealNoticeFetcher:
    def fetch_entry_url(self, url: str, *, profile_id: str | None = None, lineage_refs: dict[str, str] | None = None) -> dict:
        return {
            "entry_fetch_id": f"FETCH-{profile_id}",
            "status": "FETCHED",
            "entry_profile_id": profile_id,
            "entry_url": url,
            "site_name": "江苏省公共资源交易网",
            "source_family": "local_public_resource_trading_center",
            "http_status": 200,
            "snapshot_id_optional": f"SNAP-{profile_id}",
            "degraded_reasons": [],
            "same_site_detail_links": [
                "http://jsggzy.jszwfw.gov.cn/jyxx/003001/003001001/20260430/js-water.html",
            ],
            "same_site_detail_link_items": [
                {
                    "url": "http://jsggzy.jszwfw.gov.cn/jyxx/003001/003001001/20260430/js-water.html",
                    "text": "江苏水利工程中标候选人公示 900万元",
                },
            ],
        }


class FakeGuangzhouFlowNoticeFetcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch_entry_url(self, url: str, *, profile_id: str | None = None, lineage_refs: dict[str, str] | None = None) -> dict:
        self.calls.append(
            {
                "url": url,
                "profile_id": profile_id,
                "lineage_refs": dict(lineage_refs or {}),
            }
        )
        return {
            "entry_fetch_id": f"FETCH-{profile_id}",
            "status": "FETCHED",
            "entry_profile_id": profile_id,
            "entry_url": url,
            "site_name": "广州公共资源交易中心",
            "source_family": "local_public_resource_trading_center",
            "http_status": 200,
            "snapshot_id_optional": f"SNAP-{profile_id}",
            "degraded_reasons": [],
            "same_site_detail_links": [
                "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/gz-flow-notice.html",
            ],
            "same_site_detail_link_items": [
                {
                    "url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/gz-flow-notice.html",
                    "text": "广州某排水工程流标公告 1200万元",
                    "published_at": "2026-05-01 00:00:00",
                },
            ],
        }


class FakeSichuanShellFetcher:
    def fetch_entry_url(self, url: str, *, profile_id: str | None = None, lineage_refs: dict[str, str] | None = None) -> dict:
        return {
            "entry_fetch_id": f"FETCH-{profile_id}",
            "status": "FETCHED",
            "entry_profile_id": profile_id,
            "entry_url": url,
            "site_name": "四川省公共资源交易信息网",
            "source_family": "local_public_resource_trading_center",
            "http_status": 200,
            "snapshot_id_optional": f"SNAP-{profile_id}",
            "degraded_reasons": [],
            "same_site_detail_links": [
                "https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html",
                "https://ggzyjy.sc.gov.cn/jyxx/{{infourl}}",
            ],
            "same_site_detail_link_items": [
                {
                    "url": "https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html",
                    "text": "交易信息",
                },
                {
                    "url": "https://ggzyjy.sc.gov.cn/jyxx/{{infourl}}",
                    "text": "{{title}}",
                },
            ],
        }


def fake_sichuan_api_link_discoverer(profile_id: str, *, now: str) -> dict:
    if profile_id != "SICHUAN-GGZY-TRANSACTION-INFO":
        return {"state": "UNSUPPORTED", "items": []}
    return {
        "state": "FETCHED",
        "endpoint": "https://ggzyjy.sc.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "items": [
            {
                "url": "https://ggzyjy.sc.gov.cn/jyxx/002001/002001009/20260501/339ea533-2c75-4ac2-bedf-2562aa567b2f.html",
                "text": "东坡老家AIGC影视产业园区一期项目招标计划公告",
                "summary": "估算总投资（元）：120000000元 项目分类：房屋建筑工程",
                "published_at": "2026-05-01 09:50:40",
            }
        ],
        "record_count": 1,
    }


class FakeGgzySelectionApiDiscoverer:
    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def __call__(self, profile_id: str, *, now: str, context: dict | None = None) -> dict:
        self.contexts.append(dict(context or {}))
        if profile_id != "GGZY-DEAL-LIST":
            return {"state": "UNSUPPORTED", "items": []}
        return {
            "state": "FETCHED",
            "endpoint": "https://deal.ggzy.gov.cn/ds/deal/dealList_find.jsp",
            "items": [
                {
                    "url": "https://www.ggzy.gov.cn/information/deal/html/a/310000/0101/20260501/sh-tender.html",
                    "text": "上海市政道路改造工程招标公告 1200万元",
                    "summary": "上海 工程建设 招标公告",
                    "published_at": "2026-05-01 09:00:00",
                }
            ],
            "record_count": 1,
        }


def fake_guangdong_api_link_discoverer(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = [
        {
            "docId": "3fd848f3-3ef4-4240-9417-bded006b182d-3C14-3C14",
            "noticeId": "3fd848f3-3ef4-4240-9417-bded006b182d-3C14",
            "noticeSecondType": "A",
            "noticeSecondTypeDesc": "工程建设",
            "noticeThirdType": "1",
            "projectType": "A07",
            "projectTypeName": "水利",
            "siteName": "三水区",
            "siteCode": "440607",
            "regionCode": "440600",
            "regionName": "佛山市",
            "noticeTitle": "白坭镇水利设施提升改造工程Ⅰ标施工招标公告",
            "projectOwner": "佛山市三水区白坭镇城建水利事务中心",
            "projectCode": "A4406010001000670003",
            "publishDate": "20260501131830",
            "edition": "v3",
            "tradingProcess": "3C14",
            "datasetName": "招标公告、资格预审公告",
            "pubServicePlat": "佛山市公共资源交易信息化综合平台",
            "noticeNature": "正常公告",
        }
    ]
    return {
        "state": "FETCHED",
        "endpoint": "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items",
        "items": _link_items_from_guangdong_ygp_records(records),
        "record_count": len(records),
    }


def fake_guangzhou_candidate_publicity_api_link_discoverer(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = [
        {
            "id": "002001001a526c402-46e6-45ae-a7e0-3c7b8059c61d_002",
            "title": "2026-2027年度南沙区排水设施小修项目施工中标候选人公示",
            "title2": "2026-2027年度南沙区排水设施小修项目施工中标候选人公示",
            "linkurl": "/jyfw/002001/002001001/20260501/a526c402-46e6-45ae-a7e0-3c7b8059c61d.html",
            "categorynum": "002001001",
            "jsgcggfl": "03",
            "webdate": "2026-05-01 00:00:00",
            "xmbh": "JG2026-11113",
            "content": "中标候选人公示 投标报价 12000000元 拟派项目负责人 张三 项目负责人资质 市政公用工程一级注册建造师/粤1440000000000",
        }
    ]
    return {
        "state": "FETCHED",
        "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "items": _link_items_from_guangzhou_ywtb_records(records),
        "record_count": len(records),
        "page_size": 50,
        "page_limit": 1,
        "candidate_record_window_cap": 50,
        "attempted_pages": 1,
        "process_attempts": [
            {
                "process_label": "candidate_publicity",
                "trading_process": "03",
                "record_count": len(records),
                "attempted_pages": 1,
            }
        ],
    }


def _gz_stage_record(code: str, title: str, suffix: str) -> dict:
    return {
        "id": f"002001001-{suffix}",
        "title": title,
        "title2": title,
        "linkurl": f"/jyfw/002001/002001001/20260501/{suffix}.html",
        "categorynum": "002001001",
        "jsgcggfl": code,
        "webdate": "2026-05-01 00:00:00",
        "xmbh": f"JG2026-{suffix}",
        "content": title,
    }


def fake_guangzhou_stage_aware_api_link_discoverer(
    profile_id: str,
    *,
    now: str,
    context: dict | None = None,
) -> dict:
    if profile_id != "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records_by_process = {
        "01": [
            _gz_stage_record(
                "01",
                "南沙区排水设施小修项目施工招标公告",
                "gz-tender-notice-001",
            )
        ],
        "03": [
            _gz_stage_record(
                "03",
                "南沙区排水设施小修项目施工中标候选人公示",
                "gz-candidate-notice-001",
            )
        ],
        "05": [
            _gz_stage_record(
                "05",
                "南沙区排水设施小修项目施工中标信息",
                "gz-award-info-001",
            )
        ],
        "06": [
            _gz_stage_record(
                "06",
                "南沙区排水设施小修项目施工中标结果公告",
                "gz-award-result-001",
            )
        ],
    }
    process_attempts = []
    for process_label, process_code in _guangzhou_ywtb_process_priority(context or {}):
        records = records_by_process.get(process_code, [])
        items = _link_items_from_guangzhou_ywtb_records(
            records,
            allowed_processes={process_code},
            fallback_process_label=process_label,
        )
        process_attempts.append(
            {
                "process_label": process_label,
                "trading_process": process_code,
                "record_count": len(records),
                "accepted_item_count": len(items),
                "attempted_pages": 1,
            }
        )
        if items:
            return {
                "state": "FETCHED",
                "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
                "items": items,
                "record_count": len(records),
                "page_size": 50,
                "page_limit": 1,
                "candidate_record_window_cap": 50,
                "attempted_pages": len(process_attempts),
                "trading_process_strategy": "guangzhou_ywtb_stage_aware",
                "primary_trading_process": _guangzhou_ywtb_process_priority(context or {})[0][1],
                "process_attempts": process_attempts,
            }
    return {
        "state": "EMPTY",
        "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "items": [],
        "record_count": 0,
        "process_attempts": process_attempts,
    }


def fake_guangzhou_award_result_fallback_api_link_discoverer(
    profile_id: str,
    *,
    now: str,
    context: dict | None = None,
) -> dict:
    if profile_id != "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    process_attempts = []
    for process_label, process_code in _guangzhou_ywtb_process_priority(context or {}):
        records = []
        if process_code == "05":
            records = [_gz_stage_record("05", "南沙区排水设施小修项目施工中标信息", "gz-award-info-001")]
        items = _link_items_from_guangzhou_ywtb_records(
            records,
            allowed_processes={process_code},
            fallback_process_label=process_label,
        )
        process_attempts.append(
            {
                "process_label": process_label,
                "trading_process": process_code,
                "record_count": len(records),
                "accepted_item_count": len(items),
                "attempted_pages": 1,
            }
        )
        if items:
            return {
                "state": "FETCHED",
                "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
                "items": items,
                "record_count": len(records),
                "trading_process_strategy": "guangzhou_ywtb_stage_aware",
                "primary_trading_process": "06",
                "fallback_recent_all_used": True,
                "process_attempts": process_attempts,
            }
    return {"state": "EMPTY", "items": [], "process_attempts": process_attempts}


def fake_guangzhou_many_candidate_publicity_api_link_discoverer(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = []
    for index in range(35):
        records.append(
            {
                "id": f"002001001-gz-candidate-publicity-many-{index:03d}",
                "title": f"南沙区排水设施小修项目{index:03d}施工中标候选人公示",
                "title2": f"南沙区排水设施小修项目{index:03d}施工中标候选人公示",
                "linkurl": f"/jyfw/002001/002001001/20260501/gz-candidate-publicity-many-{index:03d}.html",
                "categorynum": "002001001",
                "jsgcggfl": "03",
                "webdate": "2026-05-01 00:00:00",
                "xmbh": f"JG2026-11{index:03d}",
                "content": "中标候选人公示 投标报价 12000000元 市政排水设施施工",
            }
        )
    return {
        "state": "FETCHED",
        "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "items": _link_items_from_guangzhou_ywtb_records(records),
        "record_count": len(records),
        "page_size": 50,
        "page_limit": 1,
        "attempted_pages": 1,
        "candidate_record_window_cap": 50,
        "process_attempts": [
            {
                "process_label": "candidate_publicity",
                "trading_process": "03",
                "record_count": len(records),
                "attempted_pages": 1,
            }
        ],
    }


def fake_guangdong_candidate_publicity_api_link_discoverer(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = [
        {
            "docId": "gd-candidate-publicity-001",
            "noticeId": "gd-candidate-publicity-001-3C51",
            "noticeSecondType": "A",
            "noticeSecondTypeDesc": "工程建设",
            "noticeThirdType": "2",
            "noticeThirdTypeDesc": "中标候选人公示",
            "projectType": "A02",
            "projectTypeName": "市政",
            "siteName": "霞山区",
            "siteCode": "440803",
            "regionCode": "440800",
            "regionName": "湛江市",
            "noticeTitle": "霞山区农村供水一体化工程监理中标候选人公示",
            "projectCode": "E4408000001000001001",
            "publishDate": "20260501004038",
            "edition": "v3",
            "tradingProcess": "3C51",
            "datasetName": "中标候选人公示",
            "pubServicePlat": "广东省公共资源交易平台",
            "noticeNature": "正常公告",
            "_ax9s_query_process_label": "candidate_publicity",
            "_ax9s_query_trading_process": "3C51",
        }
    ]
    return {
        "state": "FETCHED",
        "endpoint": "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items",
        "items": _link_items_from_guangdong_ygp_records(records),
        "record_count": len(records),
        "process_attempts": [
            {
                "process_label": "candidate_publicity",
                "trading_process": "3C51",
                "record_count": 1,
                "attempted_pages": 1,
            }
        ],
    }


def fake_guangdong_many_candidate_publicity_api_link_discoverer(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = []
    for index in range(35):
        records.append(
            {
                "docId": f"gd-candidate-publicity-many-{index:03d}",
                "noticeId": f"gd-candidate-publicity-many-{index:03d}-3C51",
                "noticeSecondType": "A",
                "noticeSecondTypeDesc": "工程建设",
                "noticeThirdType": "2",
                "noticeThirdTypeDesc": "中标候选人公示",
                "projectType": "A02",
                "projectTypeName": "市政",
                "siteName": "霞山区",
                "siteCode": "440803",
                "regionCode": "440800",
                "regionName": "湛江市",
                "noticeTitle": f"霞山区市政道路工程{index:03d}中标候选人公示",
                "projectCode": f"E4408000001000{index:04d}",
                "publishDate": "20260501004038",
                "edition": "v3",
                "tradingProcess": "3C51",
                "datasetName": "中标候选人公示",
                "pubServicePlat": "广东省公共资源交易平台",
                "noticeNature": "正常公告",
                "_ax9s_query_process_label": "candidate_publicity",
                "_ax9s_query_trading_process": "3C51",
            }
        )
    return {
        "state": "FETCHED",
        "endpoint": "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items",
        "items": _link_items_from_guangdong_ygp_records(records),
        "record_count": len(records),
        "page_size": 50,
        "page_limit": 1,
        "attempted_pages": 1,
        "candidate_record_window_cap": 50,
        "process_attempts": [
            {
                "process_label": "candidate_publicity",
                "trading_process": "3C51",
                "record_count": len(records),
                "attempted_pages": 1,
            }
        ],
    }


def fake_guangzhou_api_link_discoverer_with_expired_notice(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = [
        {
            "id": "current-gz-notice",
            "title": "白坭镇水利设施提升改造工程Ⅰ标施工中标候选人公示",
            "title2": "白坭镇水利设施提升改造工程Ⅰ标施工中标候选人公示",
            "linkurl": "/jyfw/002001/002001001/20260501/current-gz-notice.html",
            "categorynum": "002001001",
            "jsgcggfl": "03",
            "webdate": "2026-05-01 13:18:30",
            "xmbh": "JG2026-11001",
            "content": "中标候选人公示 白坭镇水利设施提升改造工程 1200万元",
        },
        {
            "id": "expired-gz-notice",
            "title": "旧水利设施提升改造工程施工中标候选人公示",
            "title2": "旧水利设施提升改造工程施工中标候选人公示",
            "linkurl": "/jyfw/002001/002001001/20260101/expired-gz-notice.html",
            "categorynum": "002001001",
            "jsgcggfl": "03",
            "webdate": "2026-01-01 13:18:30",
            "xmbh": "JG2026-10001",
            "content": "中标候选人公示 旧水利设施提升改造工程 1100万元",
        },
    ]
    return {
        "state": "FETCHED",
        "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "items": _link_items_from_guangzhou_ywtb_records(records),
        "record_count": len(records),
    }


class RealCandidateDiscoveryTests(unittest.TestCase):
    def test_guangdong_ygp_process_priority_follows_requested_document_kind(self) -> None:
        self.assertEqual(
            _guangdong_ygp_process_priority({"evaluation_document_kind": "tender_file"})[0],
            ("tender_notice", "3C14"),
        )
        self.assertEqual(
            _guangdong_ygp_process_priority({"evaluation_document_kind": "award_result"})[0],
            ("evaluation_report", "3C42"),
        )
        self.assertEqual(
            _guangdong_ygp_process_priority({"evaluation_document_kind": "candidate_notice"})[0],
            ("candidate_publicity", "3C51"),
        )

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._old_env = {
            key: os.environ.get(key)
            for key in ("KAKA_STORAGE_BACKEND", "KAKA_STORAGE_PATH", "KAKA_STORAGE_DATABASE_URL")
        }
        os.environ["KAKA_STORAGE_BACKEND"] = "json-file"
        os.environ["KAKA_STORAGE_PATH"] = str(Path(self._tmp_dir.name) / "storage.json")
        os.environ.pop("KAKA_STORAGE_DATABASE_URL", None)
        if DatabaseSession._default is not None:
            DatabaseSession._default.close()
            DatabaseSession._default = None
        reset_default_storage()

    def tearDown(self) -> None:
        if DatabaseSession._default is not None:
            DatabaseSession._default.close()
            DatabaseSession._default = None
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp_dir.cleanup()

    def test_discovers_parses_persists_and_dedupes_real_list_candidates(self) -> None:
        fetcher = FakeCandidateEntryFetcher()
        service = RealPublicCandidateDiscoveryService(
            fetcher=fetcher, repository=RealPublicCandidateRepository()
        )

        result = service.discover(
            {
                "region_codes": ["CN-NATIONAL"],
                "project_types": ["municipal"],
                "query": "道路改造",
                "amount_min": 8_000_000,
                "amount_max": 30_000_000,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["surface_id"], "operator_real_candidate_discovery")
        self.assertEqual(result["source_candidate_mode"], REAL_PUBLIC_SOURCE_CANDIDATE_MODE)
        self.assertTrue(result["candidate_limit_explicit"])
        self.assertEqual(result["candidate_limit_effective"], 5)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["persisted_candidate_count"], 2)
        self.assertEqual(len(fetcher.calls), 3)

        candidate = result["candidates"][0]
        self.assertEqual(candidate["region_code"], "CN-GD")
        self.assertEqual(candidate["project_type"], "municipal")
        self.assertEqual(candidate["notice_stage"], "candidate_notice")
        self.assertEqual(candidate["amount"], 12_000_000)
        self.assertEqual(candidate["source_candidate_mode"], REAL_PUBLIC_SOURCE_CANDIDATE_MODE)
        self.assertEqual(candidate["snapshot_id_optional"], "SNAP-GGZY-DEAL-LIST")
        self.assertIn("candidate_company", candidate["key_fields_present"])

        preserved = next(candidate for candidate in result["candidates"] if candidate["region_code"] == "CN-JS")
        self.assertTrue(preserved["discovery_preserved_after_filter_review"])
        self.assertIn("project_type_outside_requested_scope", preserved["discovery_review_reasons"])

        catalog = list_persisted_real_candidates()
        self.assertEqual(catalog["surface_id"], "operator_real_candidate_catalog")
        self.assertEqual(catalog["candidate_count"], 2)
        self.assertIn(candidate["source_url"], {item["source_url"] for item in catalog["candidates"]})

        second = service.discover(
            {
                "region_codes": ["CN-NATIONAL"],
                "project_types": ["municipal"],
                "amount_min": 8_000_000,
                "amount_max": 30_000_000,
                "now": "2026-05-01T00:01:00+00:00",
            },
            now="2026-05-01T00:01:00+00:00",
        )
        self.assertEqual(second["candidate_count"], 2)
        self.assertFalse(second["candidate_limit_explicit"])
        self.assertEqual(second["candidate_limit_effective"], "ALL_FETCHED_WINDOW_CANDIDATES")
        self.assertEqual(second["duplicate_candidate_count"], 2)

        deduped = list_persisted_real_candidates()
        self.assertEqual(deduped["candidate_count"], 2)
        self.assertGreaterEqual(deduped["raw_candidate_event_count"], 2)
        self.assertGreaterEqual(deduped["duplicate_collapsed_count"], 1)

        runs = list_real_candidate_discovery_runs()
        self.assertEqual(runs["run_count"], 2)
        self.assertEqual(runs["runs"][0]["source_candidate_mode"], REAL_PUBLIC_SOURCE_CANDIDATE_MODE)
        self.assertIn("candidate_discovery_diagnostics", result)
        self.assertGreaterEqual(result["candidate_discovery_diagnostics"]["accepted_candidate_count"], 1)
        self.assertIn("candidate_diagnostics", result["profile_reports"][0])

    def test_discovery_source_profile_ids_fail_closed_without_profile_fallback(self) -> None:
        fetcher = FakeGuangzhouFlowNoticeFetcher()
        service = RealPublicCandidateDiscoveryService(
            fetcher=fetcher,
            repository=RealPublicCandidateRepository(),
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "source_profile_ids": ["UNKNOWN-PROFILE-ID"],
                "discovery_candidate_limit": 1,
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "NO_CANDIDATES")
        self.assertEqual(result["source_profile_ids_requested"], ["UNKNOWN-PROFILE-ID"])
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(result["profile_reports"][0]["profile_id"], "UNKNOWN-PROFILE-ID")
        self.assertEqual(result["profile_reports"][0]["status"], "SOURCE_PROFILE_NOT_CONFIGURED")

    def test_ygp_source_profile_id_is_excluded_by_policy(self) -> None:
        fetcher = FakeGuangdongShellFetcher()
        service = RealPublicCandidateDiscoveryService(
            fetcher=fetcher,
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangdong_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "source_profile_ids": ["GUANGDONG-YGP-PROVINCE-TRADING-LIST"],
                "discovery_candidate_limit": 1,
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "NO_CANDIDATES")
        self.assertEqual(result["profile_reports"][0]["profile_id"], "GUANGDONG-YGP-PROVINCE-TRADING-LIST")
        self.assertEqual(result["profile_reports"][0]["status"], "SOURCE_PROFILE_EXCLUDED_BY_POLICY")
        self.assertEqual(result["candidate_count"], 0)

    def test_evaluation_corpus_mode_preserves_non_actionable_sample_titles_only(self) -> None:
        normal_fetcher = FakeGuangzhouFlowNoticeFetcher()
        normal_service = RealPublicCandidateDiscoveryService(
            fetcher=normal_fetcher,
            repository=RealPublicCandidateRepository(),
        )
        normal = normal_service.discover(
            {
                "region_codes": ["CN-GD"],
                "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
                "discovery_candidate_limit": 1,
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(normal["discovery_state"], "NO_CANDIDATES")
        self.assertIn("non_actionable_notice_state", normal["profile_reports"][0]["rejected_counts"])

        reset_default_storage()
        sample_fetcher = FakeGuangzhouFlowNoticeFetcher()
        sample_service = RealPublicCandidateDiscoveryService(
            fetcher=sample_fetcher,
            repository=RealPublicCandidateRepository(),
        )
        sample = sample_service.discover(
            {
                "region_codes": ["CN-GD"],
                "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
                "evaluation_corpus_mode": True,
                "evaluation_document_kind": "flow_or_re_tender_notice",
                "discovery_candidate_limit": 1,
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(sample["discovery_state"], "COMPLETED")
        self.assertTrue(sample["evaluation_corpus_mode"])
        self.assertEqual(sample["candidate_count"], 1)
        self.assertEqual(sample["candidates"][0]["evaluation_document_kind"], "flow_or_re_tender_notice")
        self.assertTrue(sample["candidates"][0]["evaluation_corpus_mode"])

    def test_discovery_preserves_zero_amount_minimum(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeCandidateEntryFetcher(), repository=RealPublicCandidateRepository()
        )

        result = service.discover(
            {
                "region_codes": ["CN-NATIONAL"],
                "project_types": ["municipal"],
                "query": "道路改造",
                "amount_min": 0,
                "amount_max": 30_000_000,
                "discovery_candidate_limit": 1,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["amount_min"], 0)
        self.assertEqual(result["candidates"][0]["amount_min"], 0)
        runs = list_real_candidate_discovery_runs()
        self.assertEqual(runs["runs"][0]["amount_min"], "0.0")

    def test_discovery_reports_js_shell_when_local_entry_has_no_static_detail_links(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(), repository=RealPublicCandidateRepository()
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["construction", "municipal"],
                "query": "公共建筑工程",
                "amount_min": 8_000_000,
                "amount_max": 30_000_000,
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "NO_CANDIDATES")
        report = result["profile_reports"][0]
        diagnostics = report["candidate_diagnostics"]
        self.assertTrue(diagnostics["js_shell_suspected"])
        self.assertIn("browser_rendered_realtime_list_required", diagnostics["operator_diagnosis"])
        self.assertIn("浏览器渲染", report["next_action"])
        self.assertIn("浏览器渲染列表", result["candidate_discovery_diagnostics"]["headline"])

    def test_discovery_uses_province_specific_source_without_national_substitute(self) -> None:
        fetcher = FakeCandidateEntryFetcher()
        service = RealPublicCandidateDiscoveryService(
            fetcher=fetcher, repository=RealPublicCandidateRepository()
        )

        result = service.discover(
            {
                "region_codes": ["CN-JS"],
                "project_types": ["construction"],
                "amount_min": 8_000_000,
                "amount_max": 30_000_000,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "NO_CANDIDATES")
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(fetcher.calls[0]["profile_id"], "JIANGSU-GGZY-HOME")
        report = result["profile_reports"][0]
        self.assertEqual(report["profile_id"], "JIANGSU-GGZY-HOME")
        self.assertNotEqual(report["profile_id"], "GGZY-DEAL-LIST")
        self.assertIn("links_present_but_not_candidate_detail_pages", report["operator_diagnosis"])

    def test_province_navigation_and_template_links_are_not_candidates(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeProvinceNavigationFetcher(), repository=RealPublicCandidateRepository()
        )

        result = service.discover(
            {
                "region_codes": ["CN-JS"],
                "project_types": ["construction", "municipal", "water_conservancy"],
                "amount_min": 0,
                "amount_max": 30_000_000,
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "NO_CANDIDATES")
        self.assertEqual(result["candidate_count"], 0)
        report = result["profile_reports"][0]
        self.assertIn("links_present_but_navigation_or_template_only", report["operator_diagnosis"])
        self.assertIn("links_present_but_not_candidate_detail_pages", report["operator_diagnosis"])
        self.assertEqual(
            report["candidate_diagnostics"]["rejected_counts"]["navigation_or_template_link"],
            3,
        )
        self.assertEqual(list_persisted_real_candidates()["candidate_count"], 0)

    def test_province_real_notice_link_is_accepted(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeJiangsuRealNoticeFetcher(), repository=RealPublicCandidateRepository()
        )

        result = service.discover(
            {
                "region_codes": ["CN-JS"],
                "project_types": ["water_conservancy"],
                "amount_min": 0,
                "amount_max": 10_000_000,
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "COMPLETED")
        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["region_code"], "CN-JS")
        self.assertEqual(candidate["project_type"], "water_conservancy")
        self.assertEqual(candidate["notice_stage"], "candidate_notice")
        self.assertEqual(candidate["amount"], 9_000_000)
        self.assertEqual(candidate["source_profile_id"], "JIANGSU-GGZY-HOME")
        self.assertIn("candidate_links_accepted", result["profile_reports"][0]["operator_diagnosis"])

    def test_sichuan_public_search_api_feeds_real_candidates(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeSichuanShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_sichuan_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-SC"],
                "project_types": ["construction"],
                "amount_min": 0,
                "amount_max": 200_000_000,
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "COMPLETED")
        self.assertEqual(result["candidate_count"], 1)
        report = result["profile_reports"][0]
        self.assertEqual(report["candidate_diagnostics"]["profile_api_discovery_state"], "FETCHED")
        self.assertEqual(report["candidate_diagnostics"]["profile_api_link_count"], 1)
        self.assertIn("candidate_links_accepted", report["operator_diagnosis"])
        self.assertEqual(report["next_action"], "继续抓取详情页和附件，进入 Stage2-9。")
        candidate = result["candidates"][0]
        self.assertEqual(candidate["region_code"], "CN-SC")
        self.assertEqual(candidate["project_type"], "construction")
        self.assertEqual(candidate["notice_stage"], "tender_notice")
        self.assertEqual(candidate["amount"], 120_000_000)
        self.assertEqual(candidate["amount_parse_state"], "TITLE_TEXT")
        self.assertEqual(candidate["source_profile_id"], "SICHUAN-GGZY-TRANSACTION-INFO")

    def test_sichuan_tender_file_filters_file_name_category_pollution(self) -> None:
        items = _link_items_from_text_search_records(
            [
                {
                    "title": "招标文件.CDZ",
                    "linkurl": "/jyxx/002001/002001012/20260510/file.html",
                    "categorynum": "002001012",
                },
                {
                    "title": "四川某道路改造工程施工招标公告",
                    "linkurl": "/jyxx/002001/002001001/20260510/tender.html",
                    "categorynum": "002001001",
                },
            ],
            base_url="https://ggzyjy.sc.gov.cn/",
            endpoint="https://ggzyjy.sc.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
            profile_id="SICHUAN-GGZY-TRANSACTION-INFO",
            context={"evaluation_document_kind": "tender_file"},
        )

        self.assertEqual([item["text"] for item in items], ["四川某道路改造工程施工招标公告"])

    def test_zhejiang_online_letter_submit_is_not_candidate_detail_even_in_evaluation_mode(self) -> None:
        self.assertFalse(
            _is_candidate_detail_url(
                "https://ggzy.zj.gov.cn/zhejiangnew/onlinelettersubmit.html?cate=002",
                "onlinelettersubmit",
                "ZHEJIANG-GGZY-JYXXGK-LIST",
                allow_non_actionable_title=True,
            )
        )

    def test_zhejiang_tender_file_filters_test_and_non_tender_category(self) -> None:
        items = _link_items_from_text_search_records(
            [
                {
                    "title": "（0510测-试）临海市东大河综合整治工程",
                    "linkurl": "/jyxxgk/002001/002001008/20260510/test.html",
                    "categorynum": "002001008",
                },
                {
                    "title": "杭州西站枢纽河道整治工程设计招标公告",
                    "linkurl": "/jyxxgk/002001/002001001/20260510/tender.html",
                    "categorynum": "002001001",
                },
            ],
            base_url="https://ggzy.zj.gov.cn/",
            endpoint="https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
            profile_id="ZHEJIANG-GGZY-JYXXGK-LIST",
            context={"evaluation_document_kind": "tender_file"},
        )

        self.assertEqual([item["text"] for item in items], ["杭州西站枢纽河道整治工程设计招标公告"])

    def test_ggzy_selection_filters_feed_public_api_context_for_shanghai_targets(self) -> None:
        api_discoverer = FakeGgzySelectionApiDiscoverer()
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeCandidateEntryFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=api_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-SH"],
                "project_types": ["construction"],
                "source_profile_ids": ["GGZY-DEAL-LIST"],
                "selection_filters": ["上海", "工程建设", "招标公告"],
                "evaluation_corpus_mode": True,
                "evaluation_document_kind": "tender_file",
                "amount_min": 0,
                "amount_max": 30_000_000,
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 3,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "COMPLETED")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(api_discoverer.contexts[0]["selection_filters"], ["上海", "工程建设", "招标公告"])
        self.assertEqual(api_discoverer.contexts[0]["requested_region_code"], "CN-SH")
        candidate = result["candidates"][0]
        self.assertEqual(candidate["region_code"], "CN-SH")
        self.assertEqual(candidate["source_profile_id"], "GGZY-DEAL-LIST")

    def test_guangdong_default_discovery_excludes_ygp_pollution_source(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangdong_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["water_conservancy"],
                "amount_min": 0,
                "amount_max": 200_000_000,
                "discovery_profile_limit_per_region": 2,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "NO_CANDIDATES")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(
            [report["profile_id"] for report in result["profile_reports"]],
            ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
        )
        self.assertNotIn(
            "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            [report["profile_id"] for report in result["profile_reports"]],
        )

    def test_guangdong_candidate_publicity_process_uses_guangzhou_source_not_eval_report(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangzhou_candidate_publicity_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["municipal"],
                "amount_min": 0,
                "amount_max": 200_000_000,
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["discovery_state"], "COMPLETED")
        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["notice_stage"], "candidate_notice")
        self.assertEqual(candidate["source_profile_id"], "GUANGZHOU-YWTB-CONSTRUCTION-LIST")
        self.assertEqual(candidate["source_trading_process"], "03")
        self.assertEqual(candidate["source_dataset_name"], "中标候选人公示")
        self.assertEqual(candidate["source_query_process_label"], "candidate_publicity")
        self.assertIn("ywtb.gzggzy.cn/jyfw/002001/002001001/20260501", candidate["source_url"])

    def test_guangzhou_ywtb_process_priority_follows_requested_document_kind(self) -> None:
        self.assertEqual(
            _guangzhou_ywtb_process_priority({"evaluation_document_kind": "tender_file"})[0],
            ("tender_notice", "01"),
        )
        self.assertEqual(
            _guangzhou_ywtb_process_priority({"evaluation_document_kind": "candidate_notice"})[0],
            ("candidate_publicity", "03"),
        )
        self.assertEqual(
            _guangzhou_ywtb_process_priority({"evaluation_document_kind": "award_result"}),
            (("award_result", "06"), ("award_info_fallback", "05")),
        )

    def test_guangzhou_tender_target_uses_tender_notice_not_candidate_publicity(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangzhou_stage_aware_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["municipal"],
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
                "evaluation_corpus_mode": True,
                "evaluation_document_kind": "tender_file",
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["source_trading_process"], "01")
        self.assertEqual(candidate["source_query_process_label"], "tender_notice")
        self.assertEqual(candidate["source_dataset_name"], "招标公告")
        self.assertNotIn("中标候选人", candidate["project_name"])
        report = result["profile_reports"][0]
        self.assertEqual(report["public_api_trading_process_strategy"], "guangzhou_ywtb_stage_aware")
        self.assertEqual(report["public_api_primary_trading_process"], "01")

    def test_guangzhou_candidate_and_award_targets_use_distinct_stages(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangzhou_stage_aware_api_link_discoverer,
        )

        candidate_result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["municipal"],
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
                "evaluation_corpus_mode": True,
                "evaluation_document_kind": "candidate_notice",
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )
        award_result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["municipal"],
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
                "evaluation_corpus_mode": True,
                "evaluation_document_kind": "award_result",
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(candidate_result["candidates"][0]["source_trading_process"], "03")
        self.assertEqual(candidate_result["candidates"][0]["source_query_process_label"], "candidate_publicity")
        self.assertEqual(award_result["candidates"][0]["source_trading_process"], "06")
        self.assertEqual(award_result["candidates"][0]["source_query_process_label"], "award_result")
        self.assertEqual(award_result["candidates"][0]["source_dataset_name"], "中标结果公告")

    def test_guangzhou_award_target_falls_back_to_award_info_when_result_empty(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangzhou_award_result_fallback_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["municipal"],
                "discovery_profile_limit_per_region": 1,
                "discovery_candidate_limit": 5,
                "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
                "evaluation_corpus_mode": True,
                "evaluation_document_kind": "award_result",
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["source_trading_process"], "05")
        self.assertEqual(candidate["source_query_process_label"], "award_info_fallback")
        self.assertEqual(candidate["source_dataset_name"], "中标信息")
        attempts = result["profile_reports"][0]["public_api_process_attempts"]
        self.assertEqual([item["trading_process"] for item in attempts], ["06", "05"])

    def test_guangdong_stage1_6_validation_defaults_to_30_candidates_and_one_page_window(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangzhou_many_candidate_publicity_api_link_discoverer,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["municipal"],
                "amount_min": 0,
                "amount_max": 200_000_000,
                "discovery_profile_limit_per_region": 1,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertFalse(result["candidate_limit_explicit"])
        self.assertEqual(result["candidate_limit_source"], "GUANGDONG_STAGE1_6_VALIDATION_DEFAULT")
        self.assertEqual(result["candidate_limit_effective"], 30)
        self.assertTrue(result["stage1_6_validation_mode"])
        self.assertEqual(result["candidate_count"], 30)
        self.assertEqual(result["stage1_6_validation_caps"]["candidate_limit_truncated_count"], 5)
        report = result["profile_reports"][0]
        self.assertEqual(report["accepted_candidate_count"], 35)
        self.assertEqual(report["candidate_count"], 30)
        self.assertEqual(report["candidate_limit_truncated_count"], 5)
        self.assertEqual(report["public_api_page_limit"], 1)
        self.assertEqual(report["public_api_page_size"], 50)
        self.assertEqual(report["public_api_candidate_record_window_cap"], 50)
        self.assertEqual(
            result["candidate_discovery_diagnostics"]["candidate_limit_truncated_count"],
            5,
        )

    def test_real_candidate_discovery_preserves_old_publish_time_for_review(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangzhou_api_link_discoverer_with_expired_notice,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["water_conservancy"],
                "amount_min": 0,
                "amount_max": 200_000_000,
                "discovery_profile_limit_per_region": 2,
                "discovery_candidate_limit": 5,
                "now": "2026-05-01T00:00:00+00:00",
            },
            now="2026-05-01T00:00:00+00:00",
        )

        self.assertEqual(result["candidate_count"], 2)
        old_candidate = next(candidate for candidate in result["candidates"] if "旧水利设施" in candidate["project_name"])
        self.assertEqual(old_candidate["publication_window_state"], "OUTSIDE_RECENT_DISCOVERY_WINDOW")
        self.assertTrue(old_candidate["discovery_preserved_after_filter_review"])
        self.assertIn("published_outside_recent_discovery_window", old_candidate["discovery_review_reasons"])
        preserved = result["profile_reports"][0]["candidate_diagnostics"]["preserved_filter_counts"]
        self.assertEqual(preserved["published_outside_discovery_window"], 1)
        self.assertEqual(
            result["candidate_discovery_diagnostics"]["preserved_filter_totals"]["published_outside_discovery_window"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
