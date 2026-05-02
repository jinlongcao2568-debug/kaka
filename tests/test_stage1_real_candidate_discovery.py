from __future__ import annotations

import sys
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
    _link_items_from_guangdong_ygp_records,
    list_persisted_real_candidates,
    list_real_candidate_discovery_runs,
)
from storage import reset_default_storage


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


def fake_guangdong_api_link_discoverer_with_expired_notice(profile_id: str, *, now: str) -> dict:
    if profile_id != "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return {"state": "UNSUPPORTED", "items": []}
    records = [
        {
            "docId": "current-gd-notice",
            "noticeId": "current-gd-notice-3C14",
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
            "projectCode": "A4406010001000670003",
            "publishDate": "20260501131830",
            "edition": "v3",
            "tradingProcess": "3C14",
            "datasetName": "招标公告、资格预审公告",
            "pubServicePlat": "佛山市公共资源交易信息化综合平台",
            "noticeNature": "正常公告",
        },
        {
            "docId": "expired-gd-notice",
            "noticeId": "expired-gd-notice-3C14",
            "noticeSecondType": "A",
            "noticeSecondTypeDesc": "工程建设",
            "noticeThirdType": "1",
            "projectType": "A07",
            "projectTypeName": "水利",
            "siteName": "三水区",
            "siteCode": "440607",
            "regionCode": "440600",
            "regionName": "佛山市",
            "noticeTitle": "旧水利设施提升改造工程施工招标公告",
            "projectCode": "A4406010001000670999",
            "publishDate": "20260101131830",
            "edition": "v3",
            "tradingProcess": "3C14",
            "datasetName": "招标公告、资格预审公告",
            "pubServicePlat": "佛山市公共资源交易信息化综合平台",
            "noticeNature": "正常公告",
        },
    ]
    return {
        "state": "FETCHED",
        "endpoint": "https://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items",
        "items": _link_items_from_guangdong_ygp_records(records),
        "record_count": len(records),
    }


class RealCandidateDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

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

    def test_guangdong_public_search_api_feeds_real_candidates(self) -> None:
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
        candidate = result["candidates"][0]
        self.assertEqual(candidate["region_code"], "CN-GD")
        self.assertEqual(candidate["project_type"], "water_conservancy")
        self.assertEqual(candidate["notice_stage"], "tender_notice")
        self.assertEqual(candidate["source_profile_id"], "GUANGDONG-YGP-PROVINCE-TRADING-LIST")
        self.assertEqual(candidate["publication_window_state"], "WITHIN_RECENT_DISCOVERY_WINDOW")
        self.assertIn("ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A", candidate["source_url"])
        self.assertIn("noticeId=3fd848f3-3ef4-4240-9417-bded006b182d-3C14", candidate["source_url"])

    def test_real_candidate_discovery_preserves_old_publish_time_for_review(self) -> None:
        service = RealPublicCandidateDiscoveryService(
            fetcher=FakeGuangdongShellFetcher(),
            repository=RealPublicCandidateRepository(),
            profile_api_link_discoverer=fake_guangdong_api_link_discoverer_with_expired_notice,
        )

        result = service.discover(
            {
                "region_codes": ["CN-GD"],
                "project_types": ["water_conservancy"],
                "amount_min": 0,
                "amount_max": 200_000_000,
                "discovery_profile_limit_per_region": 1,
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
