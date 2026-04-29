from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.settings import Settings
from stage2_ingestion.real_public_url_fetcher import (
    DEGRADED_ENTRY_PROFILE_IDS_AFTER_136,
    NATIONAL_VERIFICATION_ENTRY_PROFILE_IDS,
    PUBLIC_ATTACHMENT_PROFILE_IDS,
    REAL_PUBLIC_ATTACHMENT_FETCH_MODE,
    REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND,
    REAL_PUBLIC_ENTRY_FETCH_MODE,
    REAL_PUBLIC_ENTRY_FETCHER_ID,
    REAL_PUBLIC_ENTRY_PROFILES,
    REAL_PUBLIC_ENTRY_SNAPSHOT_KIND,
    REPRESENTATIVE_LOCAL_PLATFORM_ENTRY_PROFILE_IDS,
    HybridRealPublicFetchTransport,
    RealPublicEntryFetcher,
    RealPublicFetchResponse,
    RealPublicUrlBoundaryError,
)
from stage2_ingestion.service import Stage2Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


GGZY_ENTRY_URL = "https://www.ggzy.gov.cn/deal/dealList.html"
CCGP_ENTRY_URL = "https://www.ccgp.gov.cn/cggg/zygg/"
JZSC_HOME_URL = "https://jzsc.mohurd.gov.cn/home"
CREDITCHINA_HOME_URL = "https://www.creditchina.gov.cn/"
GSXT_HOME_URL = "https://www.gsxt.gov.cn/index.html"
BEIJING_HOME_URL = "https://ggzyfw.beijing.gov.cn/"
BEIJING_GCJS_URL = "https://ggzyfw.beijing.gov.cn/tyrkgcjs/index.html"
BEIJING_BDA_URL = "https://ggzyjy.bda.gov.cn/"
GD_PROV_URL = "https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/440000/index"
GD_YUNFU_URL = "https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/445300/index"
BEIJING_ATTACHMENT_PDF_URL = "https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202506/9426015154001.pdf"
BEIJING_TOOLING_PDF_URL = "https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202410/25172947ch03.pdf"


class FakeRealPublicFetchTransport:
    def __init__(self, responses: dict[str, RealPublicFetchResponse | Exception]) -> None:
        self.responses = responses
        self.call_log: list[dict[str, object]] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        self.call_log.append(
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "user_agent": user_agent,
            }
        )
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class AlwaysFailTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.call_log: list[str] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        self.call_log.append(url)
        raise self.error


def _repo(tmp_dir: str) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(Path(tmp_dir) / "repo.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(Path(tmp_dir) / "objects"),
    )
    return ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )


def _ggzy_entry_html() -> bytes:
    rows = "\n".join(
        f"<li><a href='/information/deal/html/a/530000/0101/20260424/"
        f"0053fb3c1c63347a4c988cc60249e8d{i:02d}.html'>公开交易记录{i}</a></li>"
        for i in range(24)
    )
    html = f"""
    <html>
      <head><title>全国公共资源交易平台 - 交易查询</title></head>
      <body>
        <section id="deal-list">
          <h1>交易查询</h1>
          <button>搜索</button>
          <span>搜索记录数 24</span>
          <a href="javascript:void(0)">无效脚本链接</a>
          <a href="https://example.com/not-public.html">跨站链接</a>
          <ul>{rows}</ul>
        </section>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _beijing_platform_html() -> bytes:
    rows = "\n".join(
        f"<li><a href='/notice/{idx}.html'>工程建设公告{idx}</a></li>"
        for idx in range(30)
    )
    html = """
    <html>
      <head><title>北京市公共资源交易服务平台</title></head>
      <body>
        <header>交易服务</header>
        <nav>
          <a href="/tyrkgcjs/index.html">工程建设</a>
          <a href="/wzdt.html">公告</a>
        </nav>
        <ul>
    """ + rows + """
        </ul>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _guangdong_shell_html() -> bytes:
    html = """
    <html>
      <head>
        <title>广东省公共资源交易平台</title>
        <meta name="keywords" content="广东省公共资源交易平台,工程建设,政府采购">
      </head>
      <body>
        <div id="app"></div>
        <script src="/portal/app.js"></script>
        <span>工程建设</span>
        <p>广东省公共资源交易平台公开入口用于公共资源交易信息公开、工程建设、政府采购、国有产权和土地矿业等公开交易事项展示。</p>
        <p>本测试文本模拟真实入口页 meta/正文中的公开入口说明，不模拟详情页或未登记采集扩展。</p>
        <p>公共资源公开信息通过公开入口展示，后续项目详情仍必须由 allowlisted URL 或人工复核承接。</p>
        <p>公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明。</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _pdf_like_bytes() -> bytes:
    return (b"%PDF-1.4\n" + (b"public attachment\n" * 80))


class Stage2RealPublicUrlFetcherTests(unittest.TestCase):
    def test_degraded_profile_set_from_136_is_explicit_for_137(self) -> None:
        self.assertEqual(
            DEGRADED_ENTRY_PROFILE_IDS_AFTER_136,
            (
                "JZSC-NATIONAL-HOME",
                "JZSC-NATIONAL-COMPANY",
                "JZSC-NATIONAL-PERSON",
                "JZSC-NATIONAL-PROJECT",
                "CREDITCHINA-HOME",
                "GSXT-HOME",
                "GUANGDONG-PROVINCIAL-PORTAL",
                "GUANGDONG-YUNFU-PORTAL",
            ),
        )

    def test_registered_real_public_profile_inventory_is_bulk_hardened(self) -> None:
        entry_profile_ids = {profile.profile_id for profile in REAL_PUBLIC_ENTRY_PROFILES}
        attachment_profile_ids = set(PUBLIC_ATTACHMENT_PROFILE_IDS)

        self.assertEqual(len(entry_profile_ids), 14)
        self.assertEqual(len(attachment_profile_ids), 2)
        self.assertIn("GGZY-DEAL-LIST", entry_profile_ids)
        self.assertIn("CCGP-CENTRAL-NOTICES", entry_profile_ids)
        self.assertIn("JZSC-NATIONAL-HOME", entry_profile_ids)
        self.assertIn("CREDITCHINA-HOME", entry_profile_ids)
        self.assertIn("GSXT-HOME", entry_profile_ids)
        self.assertIn("BEIJING-PLATFORM-HOME", entry_profile_ids)
        self.assertIn("GUANGDONG-PROVINCIAL-PORTAL", entry_profile_ids)
        self.assertEqual(
            attachment_profile_ids,
            {"BEIJING-STANDARD-BIDDING-PDF", "BEIJING-TOOLING-PDF"},
        )

    def test_hybrid_transport_falls_back_for_tls_handshake_errors(self) -> None:
        fallback_body = _beijing_platform_html()
        fallback = FakeRealPublicFetchTransport(
            {
                BEIJING_HOME_URL: RealPublicFetchResponse(
                    url=BEIJING_HOME_URL,
                    status_code=200,
                    content=fallback_body,
                    content_type="text/html; charset=utf-8",
                    final_url=BEIJING_HOME_URL,
                    headers={"x-ax9s-fetch-transport": "curl_command"},
                )
            }
        )
        primary = AlwaysFailTransport(RuntimeError("[SSL: BAD_ECPOINT] bad ecpoint"))
        transport = HybridRealPublicFetchTransport(primary=primary, fallback=fallback)

        response = transport.fetch(
            BEIJING_HOME_URL,
            timeout_seconds=3,
            user_agent="AX9S-Test/0.1",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, fallback_body)
        self.assertEqual(response.headers["x-ax9s-fetch-transport"], "curl_command")
        self.assertIn("BAD_ECPOINT", response.headers["x-ax9s-primary-transport-error"])
        self.assertEqual(primary.call_log, [BEIJING_HOME_URL])
        self.assertEqual(fallback.call_log[0]["url"], BEIJING_HOME_URL)

    def test_visible_public_page_with_weak_captcha_token_is_not_misclassified(self) -> None:
        body = _ggzy_entry_html().replace(
            b"</body>",
            b"<script>var captchaTokenName = 'captcha';</script></body>",
        )
        transport = FakeRealPublicFetchTransport(
            {
                GGZY_ENTRY_URL: RealPublicFetchResponse(
                    url=GGZY_ENTRY_URL,
                    status_code=200,
                    content=body,
                    content_type="text/html; charset=utf-8",
                    final_url=GGZY_ENTRY_URL,
                )
            }
        )
        carrier = RealPublicEntryFetcher(transport=transport, repository=None).fetch_entry_url(
            GGZY_ENTRY_URL,
            profile_id="GGZY-DEAL-LIST",
        )

        self.assertEqual(carrier["status"], "FETCHED")
        self.assertFalse(
            any(
                reason.startswith("controlled_challenge_body_pattern")
                for reason in carrier["degraded_reasons"]
            )
        )
        self.assertFalse(
            any(
                reason.startswith("entry_unavailable_body_pattern")
                for reason in carrier["degraded_reasons"]
            )
        )

    def test_fetches_browser_verified_total_entry_and_persists_snapshot(self) -> None:
        body = _ggzy_entry_html()
        transport = FakeRealPublicFetchTransport(
            {
                GGZY_ENTRY_URL: RealPublicFetchResponse(
                    url=GGZY_ENTRY_URL,
                    status_code=200,
                    content=body,
                    content_type="text/html; charset=utf-8",
                    final_url=GGZY_ENTRY_URL,
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            fetcher = RealPublicEntryFetcher(
                transport=transport,
                repository=repo,
                timeout_seconds=3,
            )
            carrier = fetcher.fetch_entry_url(
                GGZY_ENTRY_URL,
                profile_id="GGZY-DEAL-LIST",
                lineage_refs={"owner_task_id": "TASK-133A"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertEqual(carrier["entry_profile_id"], "GGZY-DEAL-LIST")
            self.assertEqual(carrier["source_family"], "local_public_resource_trading_center")
            self.assertTrue(carrier["browser_verified"])
            self.assertEqual(carrier["visible_entry_markers_found"], ["交易查询", "搜索", "搜索记录数"])
            self.assertFalse(carrier["review_required"])
            self.assertEqual(len(carrier["same_site_detail_links"]), 20)
            self.assertTrue(
                all(link.startswith("https://www.ggzy.gov.cn/") for link in carrier["same_site_detail_links"])
            )
            self.assertFalse(any("example.com" in link for link in carrier["same_site_detail_links"]))
            self.assertFalse(any("javascript:" in link for link in carrier["same_site_detail_links"]))

            snapshot_id = carrier["snapshot_id_optional"]
            self.assertIsNotNone(snapshot_id)
            self.assertEqual(repo.read_snapshot_bytes(snapshot_id), body)
            replay = repo.replay_snapshot(snapshot_id)
            self.assertTrue(replay["replayable"])
            manifest = replay["manifest"]
            self.assertEqual(manifest["snapshot_kind"], REAL_PUBLIC_ENTRY_SNAPSHOT_KIND)
            self.assertEqual(manifest["adapter_id_optional"], REAL_PUBLIC_ENTRY_FETCHER_ID)
            self.assertEqual(manifest["fetch_mode_optional"], REAL_PUBLIC_ENTRY_FETCH_MODE)
            self.assertEqual(
                manifest["lineage_refs"]["owner_task_id"],
                "TASK-133A",
            )
            self.assertFalse(carrier["controlled_opening_requirements"]["unapproved_live_capture_used"])
            self.assertFalse(carrier["controlled_opening_requirements"]["real_provider_call_executed"])

        self.assertEqual(len(transport.call_log), 1)
        self.assertEqual(transport.call_log[0]["url"], GGZY_ENTRY_URL)

    def test_unregistered_url_is_blocked_before_fetch(self) -> None:
        transport = FakeRealPublicFetchTransport({})
        fetcher = RealPublicEntryFetcher(transport=transport, repository=None)

        with self.assertRaises(RealPublicUrlBoundaryError) as raised:
            fetcher.fetch_entry_url("https://www.ggzy.gov.cn/information/detail-only.html")

        self.assertEqual(raised.exception.reason, "url_not_in_real_public_entry_allowlist")
        self.assertFalse(raised.exception.carrier["fetch_attempted"])
        self.assertTrue(raised.exception.carrier["fail_closed"])
        self.assertEqual(transport.call_log, [])

    def test_error_login_captcha_or_empty_shell_prepares_automated_resume(self) -> None:
        challenge_body = (
            "<html><head><title>错误页面</title></head>"
            "<body>请先登录，验证码，人机验证</body></html>"
        ).encode("utf-8")
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_ENTRY_URL: RealPublicFetchResponse(
                    url=CCGP_ENTRY_URL,
                    status_code=200,
                    content=challenge_body,
                    content_type="text/html",
                    final_url=CCGP_ENTRY_URL,
                )
            }
        )
        carrier = RealPublicEntryFetcher(transport=transport, repository=None).fetch_entry_url(
            CCGP_ENTRY_URL,
            profile_id="CCGP-CENTRAL-NOTICES",
        )

        self.assertEqual(carrier["status"], "SUSPENDED")
        self.assertTrue(carrier["review_required"])
        self.assertFalse(carrier["fail_closed"])
        self.assertTrue(carrier["suspended_for_automated_resume"])
        self.assertTrue(carrier["automated_challenge_resolution_first"])
        self.assertFalse(carrier["resume_requires_human_input"])
        self.assertEqual(
            carrier["resume_policy"],
            "preserve_url_cookie_form_context_and_capture_plan_for_automated_resume",
        )
        self.assertIsNone(carrier["snapshot_id_optional"])
        self.assertIn("entry_body_too_small", carrier["degraded_reasons"])
        self.assertIn("visible_entry_markers_missing", carrier["degraded_reasons"])
        self.assertTrue(
            any(
                reason.startswith("controlled_challenge_body_pattern:")
                for reason in carrier["degraded_reasons"]
            )
        )
        self.assertEqual(
            carrier["failure_taxonomy"]["failure_class"],
            "CONTROLLED_CHALLENGE_BODY_PATTERN",
        )

    def test_profiles_are_total_entry_urls_not_detail_pages(self) -> None:
        for profile in REAL_PUBLIC_ENTRY_PROFILES:
            if profile.profile_id not in (
                *NATIONAL_VERIFICATION_ENTRY_PROFILE_IDS,
                *REPRESENTATIVE_LOCAL_PLATFORM_ENTRY_PROFILE_IDS,
            ):
                self.assertNotEqual(profile.url, profile.sample_detail_url, profile.profile_id)
            self.assertTrue(profile.url.startswith("https://"), profile.profile_id)
            self.assertNotIn("/information/deal/html/", profile.url, profile.profile_id)
            if profile.profile_id in {
                "CCGP-CENTRAL-NOTICES",
                "CCGP-CENTRAL-AWARD-LIST",
            }:
                self.assertTrue(profile.url.endswith("/"), profile.profile_id)
            self.assertTrue(profile.sample_detail_url.startswith("https://"), profile.profile_id)

    def test_national_verification_profiles_are_registered(self) -> None:
        self.assertEqual(
            NATIONAL_VERIFICATION_ENTRY_PROFILE_IDS,
            (
                "JZSC-NATIONAL-HOME",
                "JZSC-NATIONAL-COMPANY",
                "JZSC-NATIONAL-PERSON",
                "JZSC-NATIONAL-PROJECT",
                "CREDITCHINA-HOME",
                "GSXT-HOME",
            ),
        )
        profiles_by_id = {profile.profile_id: profile for profile in REAL_PUBLIC_ENTRY_PROFILES}
        self.assertEqual(profiles_by_id["JZSC-NATIONAL-HOME"].url, JZSC_HOME_URL)
        self.assertEqual(profiles_by_id["CREDITCHINA-HOME"].url, CREDITCHINA_HOME_URL)
        self.assertEqual(profiles_by_id["GSXT-HOME"].url, GSXT_HOME_URL)

    def test_representative_local_platform_profiles_are_registered(self) -> None:
        self.assertEqual(
            REPRESENTATIVE_LOCAL_PLATFORM_ENTRY_PROFILE_IDS,
            (
                "BEIJING-PLATFORM-HOME",
                "BEIJING-GCJS-LIST",
                "BEIJING-BDA-HOME",
                "GUANGDONG-PROVINCIAL-PORTAL",
                "GUANGDONG-YUNFU-PORTAL",
            ),
        )
        profiles_by_id = {profile.profile_id: profile for profile in REAL_PUBLIC_ENTRY_PROFILES}
        self.assertEqual(profiles_by_id["BEIJING-PLATFORM-HOME"].url, BEIJING_HOME_URL)
        self.assertEqual(profiles_by_id["BEIJING-GCJS-LIST"].url, BEIJING_GCJS_URL)
        self.assertEqual(profiles_by_id["BEIJING-BDA-HOME"].url, BEIJING_BDA_URL)
        self.assertEqual(profiles_by_id["GUANGDONG-PROVINCIAL-PORTAL"].url, GD_PROV_URL)
        self.assertEqual(profiles_by_id["GUANGDONG-YUNFU-PORTAL"].url, GD_YUNFU_URL)

    def test_jzsc_verification_entries_degrade_when_raw_fetch_is_only_spa_shell(self) -> None:
        shell_body = (
            "<!DOCTYPE html><html><head><title>全国建筑市场监管公共服务平台（四库一平台）</title>"
            "<script src='/js/app.js'></script></head><body><div id='app'></div></body></html>"
        ).encode("utf-8")
        transport = FakeRealPublicFetchTransport(
            {
                JZSC_HOME_URL: RealPublicFetchResponse(
                    url=JZSC_HOME_URL,
                    status_code=200,
                    content=shell_body,
                    content_type="text/html; charset=utf-8",
                    final_url=JZSC_HOME_URL,
                )
            }
        )

        carrier = RealPublicEntryFetcher(transport=transport, repository=None).fetch_entry_url(
            JZSC_HOME_URL,
            profile_id="JZSC-NATIONAL-HOME",
        )
        self.assertEqual(carrier["status"], "DEGRADED")
        self.assertEqual(carrier["source_family"], "national_construction_market_platform")
        self.assertTrue(carrier["browser_verified"])
        self.assertIn("visible_entry_markers_missing", carrier["degraded_reasons"])
        self.assertEqual(carrier["entry_validation_level"], "FAIL_CLOSED_INSUFFICIENT_VISIBLE_ENTRY")
        self.assertEqual(
            carrier["failure_taxonomy"]["failure_class"],
            "PUBLIC_ENTRY_MARKERS_MISSING_OR_SPA_SHELL",
        )
        self.assertEqual(carrier["snapshot_id_optional"], None)
        self.assertEqual(carrier["same_site_detail_links"], [])

    def test_jzsc_home_lightweight_public_entry_snapshot_is_allowed_without_unregistered_capture(self) -> None:
        public_home_body = (
            "<!DOCTYPE html><html><head><title>全国建筑市场监管公共服务平台（四库一平台）</title>"
            "<meta name='description' content='全国建筑市场监管公共服务平台（原全国建筑市场建筑与诚信信息发布平台）'>"
            "</head><body><div id='app'></div><script src='/js/app.js'></script>"
            "<p>全国建筑市场监管公共服务平台公开首页说明，用于建设市场公开信息服务入口展示；"
            "本测试不模拟企业、人员或项目详情抓取。</p>"
            "<p>公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明。</p>"
            "<p>公开首页说明公开首页说明公开首页说明公开首页说明公开首页说明公开首页说明公开首页说明公开首页说明。</p>"
            "<p>公开数据边界公开数据边界公开数据边界公开数据边界公开数据边界公开数据边界公开数据边界公开数据边界。</p>"
            "</body></html>"
        ).encode("utf-8")
        transport = FakeRealPublicFetchTransport(
            {
                JZSC_HOME_URL: RealPublicFetchResponse(
                    url=JZSC_HOME_URL,
                    status_code=200,
                    content=public_home_body,
                    content_type="text/html; charset=utf-8",
                    final_url=JZSC_HOME_URL,
                )
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            carrier = RealPublicEntryFetcher(transport=transport, repository=repo).fetch_entry_url(
                JZSC_HOME_URL,
                profile_id="JZSC-NATIONAL-HOME",
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertEqual(carrier["entry_validation_level"], "LIGHTWEIGHT_PUBLIC_ENTRY")
            self.assertEqual(
                carrier["lightweight_public_entry_markers_found"],
                ["全国建筑市场监管公共服务平台", "建筑与诚信信息发布平台"],
            )
            self.assertFalse(carrier["fail_closed"])
            self.assertTrue(carrier["snapshot_id_optional"])
            self.assertEqual(repo.read_snapshot_bytes(carrier["snapshot_id_optional"]), public_home_body)

    def test_national_verification_upstream_block_statuses_fail_closed(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                CREDITCHINA_HOME_URL: RuntimeError("Response status code does not indicate success: 412 (Precondition Failed)."),
                GSXT_HOME_URL: RuntimeError("Response status code does not indicate success: 521 ()."),
            }
        )
        fetcher = RealPublicEntryFetcher(transport=transport, repository=None)

        credit = fetcher.fetch_entry_url(
            CREDITCHINA_HOME_URL,
            profile_id="CREDITCHINA-HOME",
        )
        gsxt = fetcher.fetch_entry_url(
            GSXT_HOME_URL,
            profile_id="GSXT-HOME",
        )

        self.assertEqual(credit["status"], "DEGRADED")
        self.assertEqual(gsxt["status"], "DEGRADED")
        self.assertEqual(credit["source_family"], "credit_china")
        self.assertEqual(gsxt["source_family"], "national_enterprise_credit_publicity_system")
        self.assertEqual(credit["degraded_reasons"], ["fetch_failed"])
        self.assertEqual(gsxt["degraded_reasons"], ["fetch_failed"])
        self.assertIn("412", credit["failure_detail_optional"])
        self.assertIn("521", gsxt["failure_detail_optional"])
        self.assertTrue(credit["fail_closed"])
        self.assertTrue(gsxt["fail_closed"])

    def test_representative_local_platform_entries_fetch_or_lightweight_public_entry(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                BEIJING_HOME_URL: RealPublicFetchResponse(
                    url=BEIJING_HOME_URL,
                    status_code=200,
                    content=_beijing_platform_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=BEIJING_HOME_URL,
                ),
                GD_PROV_URL: RealPublicFetchResponse(
                    url=GD_PROV_URL,
                    status_code=200,
                    content=_guangdong_shell_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=GD_PROV_URL,
                ),
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            fetcher = RealPublicEntryFetcher(transport=transport, repository=repo)
            beijing = fetcher.fetch_entry_url(
                BEIJING_HOME_URL,
                profile_id="BEIJING-PLATFORM-HOME",
            )
            guangdong = fetcher.fetch_entry_url(
                GD_PROV_URL,
                profile_id="GUANGDONG-PROVINCIAL-PORTAL",
            )

            self.assertEqual(beijing["status"], "FETCHED")
            self.assertEqual(beijing["source_family"], "local_public_resource_trading_center")
            self.assertTrue(beijing["snapshot_id_optional"])
            self.assertEqual(repo.read_snapshot_bytes(beijing["snapshot_id_optional"]), _beijing_platform_html())

            self.assertEqual(guangdong["status"], "FETCHED")
            self.assertEqual(guangdong["source_family"], "provincial_bidding_platform")
            self.assertEqual(guangdong["entry_validation_level"], "LIGHTWEIGHT_PUBLIC_ENTRY")
            self.assertEqual(
                guangdong["lightweight_public_entry_markers_found"],
                ["广东省公共资源交易平台", "工程建设", "政府采购"],
            )
            self.assertFalse(guangdong["fail_closed"])
            self.assertTrue(guangdong["snapshot_id_optional"])

    def test_public_attachment_profiles_are_registered(self) -> None:
        self.assertEqual(
            PUBLIC_ATTACHMENT_PROFILE_IDS,
            (
                "BEIJING-STANDARD-BIDDING-PDF",
                "BEIJING-TOOLING-PDF",
            ),
        )

    def test_public_attachment_original_link_fetch_persists_pdf_snapshot(self) -> None:
        pdf_bytes = _pdf_like_bytes()
        transport = FakeRealPublicFetchTransport(
            {
                BEIJING_ATTACHMENT_PDF_URL: RealPublicFetchResponse(
                    url=BEIJING_ATTACHMENT_PDF_URL,
                    status_code=200,
                    content=pdf_bytes,
                    content_type="application/pdf",
                    final_url=BEIJING_ATTACHMENT_PDF_URL,
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            fetcher = RealPublicEntryFetcher(transport=transport, repository=repo)
            carrier = fetcher.fetch_attachment_original_link(
                BEIJING_ATTACHMENT_PDF_URL,
                profile_id="BEIJING-STANDARD-BIDDING-PDF",
                detail_page_url=BEIJING_HOME_URL,
                lineage_refs={"owner_task_id": "TASK-133D"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertEqual(carrier["attachment_profile_id"], "BEIJING-STANDARD-BIDDING-PDF")
            self.assertEqual(carrier["content_type"], "application/pdf")
            self.assertEqual(carrier["detail_page_url_optional"], BEIJING_HOME_URL)
            self.assertTrue(carrier["snapshot_id_optional"])
            self.assertEqual(repo.read_snapshot_bytes(carrier["snapshot_id_optional"]), pdf_bytes)
            replay = repo.replay_snapshot(carrier["snapshot_id_optional"])
            self.assertEqual(replay["manifest"]["snapshot_kind"], REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND)
            self.assertEqual(replay["manifest"]["fetch_mode_optional"], REAL_PUBLIC_ATTACHMENT_FETCH_MODE)
            self.assertEqual(replay["manifest"]["lineage_refs"]["owner_task_id"], "TASK-133D")

    def test_public_attachment_fetch_blocks_unregistered_url_and_html_disguised_payload(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                BEIJING_TOOLING_PDF_URL: RealPublicFetchResponse(
                    url=BEIJING_TOOLING_PDF_URL,
                    status_code=200,
                    content=b"<html><title>not attachment</title><body>download blocked</body></html>",
                    content_type="text/html",
                    final_url=BEIJING_TOOLING_PDF_URL,
                )
            }
        )
        fetcher = RealPublicEntryFetcher(transport=transport, repository=None)

        with self.assertRaises(RealPublicUrlBoundaryError):
            fetcher.fetch_attachment_original_link("https://ggzyfw.beijing.gov.cn/not-allowlisted.pdf")

        carrier = fetcher.fetch_attachment_original_link(
            BEIJING_TOOLING_PDF_URL,
            profile_id="BEIJING-TOOLING-PDF",
        )
        self.assertEqual(carrier["status"], "DEGRADED")
        self.assertIn("html_body_not_attachment", carrier["degraded_reasons"])
        self.assertTrue(carrier["fail_closed"])

    def test_stage2_service_exposes_real_public_attachment_fetcher(self) -> None:
        pdf_bytes = _pdf_like_bytes()
        transport = FakeRealPublicFetchTransport(
            {
                BEIJING_ATTACHMENT_PDF_URL: RealPublicFetchResponse(
                    url=BEIJING_ATTACHMENT_PDF_URL,
                    status_code=200,
                    content=pdf_bytes,
                    content_type="application/pdf",
                    final_url=BEIJING_ATTACHMENT_PDF_URL,
                )
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            carrier = Stage2Service().fetch_real_public_attachment_url(
                BEIJING_ATTACHMENT_PDF_URL,
                profile_id="BEIJING-STANDARD-BIDDING-PDF",
                repository=repo,
                transport=transport,
                detail_page_url=BEIJING_HOME_URL,
            )
            self.assertEqual(carrier["status"], "FETCHED")
            replay = repo.replay_snapshot(carrier["snapshot_id_optional"])
            self.assertEqual(
                replay["manifest"]["raw_snapshot_metadata"]["attachment_filename"],
                "9426015154001.pdf",
            )

    def test_stage2_service_exposes_real_public_entry_fetcher(self) -> None:
        body = _ggzy_entry_html()
        transport = FakeRealPublicFetchTransport(
            {
                GGZY_ENTRY_URL: RealPublicFetchResponse(
                    url=GGZY_ENTRY_URL,
                    status_code=200,
                    content=body,
                    content_type="text/html; charset=utf-8",
                    final_url=GGZY_ENTRY_URL,
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            carrier = Stage2Service().fetch_real_public_entry_url(
                GGZY_ENTRY_URL,
                profile_id="GGZY-DEAL-LIST",
                repository=repo,
                transport=transport,
                lineage_refs={"source_blueprint_batch_id": "PTL-I100-133A"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            replay = repo.replay_snapshot(carrier["snapshot_id_optional"])
            self.assertEqual(
                replay["manifest"]["lineage_refs"]["source_blueprint_batch_id"],
                "PTL-I100-133A",
            )


if __name__ == "__main__":
    unittest.main()
