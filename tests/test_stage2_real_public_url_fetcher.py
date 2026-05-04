from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
    REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
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
CCGP_DETAIL_URL = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_0000001.htm"
CCGP_ATTACHMENT_URL = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/notice.pdf"
JZSC_HOME_URL = "https://jzsc.mohurd.gov.cn/home"
CREDITCHINA_HOME_URL = "https://www.creditchina.gov.cn/"
GSXT_HOME_URL = "https://www.gsxt.gov.cn/index.html"
BEIJING_HOME_URL = "https://ggzyfw.beijing.gov.cn/"
BEIJING_GCJS_URL = "https://ggzyfw.beijing.gov.cn/tyrkgcjs/index.html"
BEIJING_BDA_URL = "https://ggzyjy.bda.gov.cn/"
GZ_YWTB_URL = "https://ywtb.gzggzy.cn/jyfw/002001/002001001/trade_purchasetoplen6.html"
GZ_YWTB_DETAIL_URL = "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/587b9f32-8823-4577-97ff-e76e9c92a2d3.html"
GZ_YWTB_ATTACHMENT_URL = (
    "https://ywtb.gzggzy.cn/EpointWebBuilder/pages/webbuildermis/attach/downloadztbattach?"
    "attachGuid=568108d4-62ef-4407-83dc-a35d11c5f0f2&appUrlFlag=f2025tp"
    "&siteGuid=7eb5f7f1-9041-43ad-8e13-8fcb82ea831a"
)
GD_YGP_URL = "https://ygp.gdzwfw.gov.cn/#/44/jygg"
JS_DETAIL_URL = "http://jsggzy.jszwfw.gov.cn/jyxx/003001/003001001/20260501/e40bba6b-3eda-4245-9d15-21b921f8db54.html"
SD_DETAIL_URL = "http://ggzyjy.shandong.gov.cn:80/jsgczbgg/14229113.jhtml"
GD_YGP_DETAIL_URL = (
    "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?"
    "noticeId=3fd848f3-3ef4-4240-9417-bded006b182d-3C14"
    "&projectCode=A4406010001000670003"
    "&bizCode=3C14"
    "&siteCode=440600"
    "&publishDate=20260501131830"
    "&source=%E4%BD%9B%E5%B1%B1%E5%B8%82%E5%85%AC%E5%85%B1%E8%B5%84%E6%BA%90%E4%BA%A4%E6%98%93%E4%BF%A1%E6%81%AF%E5%8C%96%E7%BB%BC%E5%90%88%E5%B9%B3%E5%8F%B0"
    "&titleDetails=%E5%B7%A5%E7%A8%8B%E5%BB%BA%E8%AE%BE"
    "&classify=A07"
)
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


def _ccgp_detail_html() -> bytes:
    html = """
    <html>
      <head><title>北京科技大学煤气管网检测装置采购项目中标公告</title></head>
      <body>
        <h1>北京科技大学煤气管网检测装置采购项目中标公告</h1>
        <table>
          <tr><td>项目名称</td><td>北京科技大学煤气管网检测装置采购项目</td></tr>
          <tr><td>采购人</td><td>北京科技大学</td></tr>
          <tr><td>公告日期</td><td>2026年04月30日</td></tr>
        </table>
        <p>中标供应商名称：北京测试科技有限公司</p>
        <p>中标（成交）金额：1280.50 万元（人民币）</p>
        <p>公告期限：自本公告发布之日起1个工作日。</p>
        <p><a href="./files/notice.pdf">附件：中标公告原文下载</a></p>
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
        <meta name="keywords" content="广东省公共资源交易平台,公开入口">
      </head>
      <body>
        <div id="app"></div>
        <script src="/portal/app.js"></script>
        <span>工程建设</span>
        <p>广东省公共资源交易平台公开入口用于项目公开信息展示。</p>
        <p>本测试文本模拟真实入口页 meta/正文中的公开入口说明，不模拟浏览器渲染后的实时列表。</p>
        <p>公开信息通过浏览器渲染列表展示，后续项目详情仍必须由 allowlisted URL 或合法公开接口承接。</p>
        <p>公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明公开入口说明。</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _province_detail_html(title: str) -> bytes:
    html = f"""
    <html>
      <head><title>{title}</title></head>
      <body>
        <h1>{title}</h1>
        <p>招标公告，预算 1200 万元。</p>
        <p>公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文。</p>
        <p>公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文。</p>
        <p>公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文。</p>
        <a href="/files/notice.pdf">招标文件.pdf</a>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _guangzhou_ywtb_detail_html_with_onclick_attachment() -> bytes:
    html = """
    <html>
      <head>
        <title>广州交易集团有限公司</title>
        <meta name="ArticleTitle" content="南沙区龙穴岛孖沙四涌水闸泵站工程设计施工总承包中标候选人公示">
      </head>
      <body>
        <h3 class="article-title" data-ggid="JG2026-11125" data-type="03">南沙区龙穴岛孖沙四涌水闸泵站工程设计施工总承包中标候选人公示</h3>
        <div class="article-file" id="article-file">
          <h4>相关附件：</h4>
          <a class="article-file-item l" onclick="ztbfjyz('/EpointWebBuilder/pages/webbuildermis/attach/downloadztbattach?attachGuid=568108d4-62ef-4407-83dc-a35d11c5f0f2&appUrlFlag=f2025tp&siteGuid=7eb5f7f1-9041-43ad-8e13-8fcb82ea831a','1','1')">2合格中标候选人公示JG2026-11125.pdf</a>
        </div>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _fake_guangdong_detail_api(endpoint: str, params: dict, *, user_agent: str) -> dict:
    if endpoint.endswith("/nodeList"):
        return {
            "errcode": 0,
            "errmsg": "ok",
            "data": [
                {
                    "nodeName": "招标公告及资格预审",
                    "nodeId": "1971512620815388674",
                    "selectedBizCode": "3C14",
                    "dataCount": 1,
                    "noticeId": "3fd848f3-3ef4-4240-9417-bded006b182d-3C14",
                }
            ],
        }
    if endpoint.endswith("/detail"):
        return {
            "errcode": 0,
            "errmsg": "ok",
            "data": {
                "title": "白坭镇水利设施提升改造工程Ⅰ标施工招标公告",
                "publishDate": "2026-05-01 13:18:30",
                "tradingNoticeColumnModelList": [
                    {
                        "name": "公告信息",
                        "viewStyle": "keyTable",
                        "multiKeyValueTableList": [
                            [
                                {
                                    "code": "TENDER_PROJECT_NAME",
                                    "aliasName": "招标项目名称",
                                    "value": "白坭镇水利设施提升改造工程Ⅰ标施工",
                                    "isShow": True,
                                },
                                {
                                    "code": "NOTICE_NATURE",
                                    "aliasName": "公告性质",
                                    "value": "正常公告",
                                    "isShow": True,
                                },
                            ]
                        ],
                    },
                    {
                        "name": "公告内容",
                        "viewStyle": "richText",
                        "richtext": "<p>广东省工程建设项目招标公告，招标控制价 1200 万元。</p>",
                    },
                    {
                        "name": "相关附件",
                        "viewStyle": "keyTable",
                        "noticeFileBOList": [
                            {
                                "fileName": "招标公告.pdf",
                                "rowGuid": "e1633e95-9630-48e3-95fb-17e38a18cba0--3C14",
                                "flowId": "1696027",
                            }
                        ],
                    },
                ],
            },
        }
    raise AssertionError(endpoint)


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
                "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            ),
        )

    def test_registered_real_public_profile_inventory_is_bulk_hardened(self) -> None:
        entry_profile_ids = {profile.profile_id for profile in REAL_PUBLIC_ENTRY_PROFILES}
        attachment_profile_ids = set(PUBLIC_ATTACHMENT_PROFILE_IDS)

        self.assertEqual(len(entry_profile_ids), 24)
        self.assertEqual(len(attachment_profile_ids), 2)
        self.assertIn("GGZY-DEAL-LIST", entry_profile_ids)
        self.assertIn("CCGP-CENTRAL-NOTICES", entry_profile_ids)
        self.assertIn("JZSC-NATIONAL-HOME", entry_profile_ids)
        self.assertIn("CREDITCHINA-HOME", entry_profile_ids)
        self.assertIn("GSXT-HOME", entry_profile_ids)
        self.assertIn("BEIJING-PLATFORM-HOME", entry_profile_ids)
        for profile_id in (
            "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
            "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "GUANGDONG-GDCIC-HOME",
            "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
            "GUANGDONG-TZXM-HOME",
            "GUANGDONG-ZFCXJST-PENALTY-PUBLICITY",
            "GUANGDONG-CREDIT-GD-HOME",
            "JIANGSU-GGZY-HOME",
            "ZHEJIANG-GGZY-JYXXGK-LIST",
            "SHANDONG-GGZY-JYXXGK-LIST",
            "HUBEI-BIDCLOUD-JYXX-LIST",
            "SICHUAN-GGZY-TRANSACTION-INFO",
        ):
            self.assertIn(profile_id, entry_profile_ids)
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

    def test_hybrid_transport_falls_back_for_timeout_errors(self) -> None:
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
        primary = AlwaysFailTransport(TimeoutError("The read operation timed out"))
        transport = HybridRealPublicFetchTransport(primary=primary, fallback=fallback)

        response = transport.fetch(
            BEIJING_HOME_URL,
            timeout_seconds=3,
            user_agent="AX9S-Test/0.1",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, fallback_body)
        self.assertEqual(response.headers["x-ax9s-fetch-transport"], "curl_command")
        self.assertIn("timed out", response.headers["x-ax9s-primary-transport-error"])
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
            self.assertGreaterEqual(len(carrier["same_site_detail_links"]), 20)
            self.assertLessEqual(len(carrier["same_site_detail_links"]), 50)
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

    def test_same_site_candidate_detail_fetch_persists_stage2_snapshot_and_attachment_links(self) -> None:
        body = _ccgp_detail_html()
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_DETAIL_URL: RealPublicFetchResponse(
                    url=CCGP_DETAIL_URL,
                    status_code=200,
                    content=body,
                    content_type="text/html; charset=utf-8",
                    final_url=CCGP_DETAIL_URL,
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            carrier = Stage2Service().fetch_real_public_candidate_detail_url(
                CCGP_DETAIL_URL,
                profile_id="CCGP-CENTRAL-NOTICES",
                repository=repo,
                transport=transport,
                lineage_refs={"candidate_key": "candidate-001"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertEqual(carrier["entry_profile_id"], "CCGP-CENTRAL-NOTICES")
            self.assertEqual(carrier["detail_url"], CCGP_DETAIL_URL)
            self.assertEqual(carrier["same_site_attachment_link_items"][0]["url"], "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/notice.pdf")
            snapshot_id = carrier["snapshot_id_optional"]
            replay = repo.replay_snapshot(snapshot_id)
            self.assertTrue(replay["replayable"])
            manifest = replay["manifest"]
            self.assertEqual(manifest["snapshot_kind"], REAL_PUBLIC_DETAIL_SNAPSHOT_KIND)
            self.assertEqual(manifest["source_url_optional"], CCGP_DETAIL_URL)
            self.assertEqual(manifest["lineage_refs"]["candidate_key"], "candidate-001")
            self.assertEqual(
                manifest["raw_snapshot_metadata"]["same_site_attachment_links"],
                ["https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/notice.pdf"],
            )

        self.assertEqual(len(transport.call_log), 1)
        self.assertEqual(transport.call_log[0]["url"], CCGP_DETAIL_URL)

    def test_guangdong_hash_detail_uses_public_detail_api_and_discovers_download_attachments(self) -> None:
        pdf_bytes = _pdf_like_bytes()
        attachment_url = (
            "https://ygp.gdzwfw.gov.cn/ggzy-portal/base/sys-file/download/v3/"
            "e1633e95-9630-48e3-95fb-17e38a18cba0--3C14?1696027"
        )
        transport = FakeRealPublicFetchTransport(
            {
                attachment_url: RealPublicFetchResponse(
                    url=attachment_url,
                    status_code=200,
                    content=pdf_bytes,
                    content_type="application/pdf;charset=UTF-8",
                    final_url=attachment_url,
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "stage2_ingestion.real_public_url_fetcher._guangdong_ygp_signed_get_json",
            side_effect=_fake_guangdong_detail_api,
        ) as api_get:
            repo = _repo(tmp_dir)
            fetcher = RealPublicEntryFetcher(
                transport=transport,
                repository=repo,
                timeout_seconds=3,
            )
            carrier = fetcher.fetch_candidate_detail_url(
                GD_YGP_DETAIL_URL,
                profile_id="GUANGDONG-YGP-PROVINCE-TRADING-LIST",
                lineage_refs={"candidate_key": "gd-candidate-001"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertEqual(carrier["transport"], "guangdong_ygp_public_detail_api")
            self.assertEqual(carrier["title"], "白坭镇水利设施提升改造工程Ⅰ标施工招标公告")
            self.assertEqual(carrier["same_site_attachment_link_items"][0]["url"], attachment_url)
            self.assertEqual(carrier["same_site_attachment_link_items"][0]["text"], "招标公告.pdf")
            self.assertEqual(transport.call_log, [])
            self.assertEqual(api_get.call_count, 2)
            replay = repo.replay_snapshot(carrier["snapshot_id_optional"])
            self.assertEqual(replay["manifest"]["snapshot_kind"], REAL_PUBLIC_DETAIL_SNAPSHOT_KIND)
            self.assertIn("白坭镇水利设施提升改造工程", repo.read_snapshot_bytes(carrier["snapshot_id_optional"]).decode("utf-8"))

            attachment = fetcher.fetch_same_site_attachment_url(
                attachment_url,
                parent_profile_id="GUANGDONG-YGP-PROVINCE-TRADING-LIST",
                detail_page_url=GD_YGP_DETAIL_URL,
                lineage_refs={"candidate_key": "gd-candidate-001"},
            )

            self.assertEqual(attachment["status"], "FETCHED")
            self.assertEqual(repo.read_snapshot_bytes(attachment["snapshot_id_optional"]), pdf_bytes)
            self.assertEqual(transport.call_log[0]["url"], attachment_url)

    def test_guangzhou_ywtb_onclick_download_attachment_is_discovered_and_allowlisted(self) -> None:
        pdf_bytes = _pdf_like_bytes()
        transport = FakeRealPublicFetchTransport(
            {
                GZ_YWTB_DETAIL_URL: RealPublicFetchResponse(
                    url=GZ_YWTB_DETAIL_URL,
                    status_code=200,
                    content=_guangzhou_ywtb_detail_html_with_onclick_attachment(),
                    content_type="text/html; charset=utf-8",
                    final_url=GZ_YWTB_DETAIL_URL,
                ),
                GZ_YWTB_ATTACHMENT_URL: RealPublicFetchResponse(
                    url=GZ_YWTB_ATTACHMENT_URL,
                    status_code=200,
                    content=pdf_bytes,
                    content_type="application/pdf;charset=UTF-8",
                    final_url=GZ_YWTB_ATTACHMENT_URL,
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            fetcher = RealPublicEntryFetcher(
                transport=transport,
                repository=repo,
                timeout_seconds=3,
            )
            carrier = fetcher.fetch_candidate_detail_url(
                GZ_YWTB_DETAIL_URL,
                profile_id="GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                lineage_refs={"candidate_key": "gz-candidate-001"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertEqual(carrier["title"], "南沙区龙穴岛孖沙四涌水闸泵站工程设计施工总承包中标候选人公示")
            self.assertEqual(carrier["same_site_attachment_link_items"][0]["url"], GZ_YWTB_ATTACHMENT_URL)
            self.assertEqual(
                carrier["same_site_attachment_link_items"][0]["text"],
                "2合格中标候选人公示JG2026-11125.pdf",
            )

            attachment = fetcher.fetch_same_site_attachment_url(
                GZ_YWTB_ATTACHMENT_URL,
                parent_profile_id="GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                detail_page_url=GZ_YWTB_DETAIL_URL,
                lineage_refs={"candidate_key": "gz-candidate-001"},
            )

            self.assertEqual(attachment["status"], "FETCHED")
            self.assertEqual(repo.read_snapshot_bytes(attachment["snapshot_id_optional"]), pdf_bytes)
            self.assertEqual(
                [item["url"] for item in transport.call_log],
                [GZ_YWTB_DETAIL_URL, GZ_YWTB_ATTACHMENT_URL],
            )

    def test_province_detail_urls_allow_http_and_jspx_variants(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                JS_DETAIL_URL: RealPublicFetchResponse(
                    url=JS_DETAIL_URL,
                    status_code=200,
                    content=_province_detail_html("海洋渔业工厂化循环水车间建设项目施工"),
                    content_type="text/html; charset=utf-8",
                    final_url=JS_DETAIL_URL,
                ),
                SD_DETAIL_URL: RealPublicFetchResponse(
                    url=SD_DETAIL_URL,
                    status_code=200,
                    content=_province_detail_html("山东工程建设项目招标公告"),
                    content_type="text/html; charset=utf-8",
                    final_url=SD_DETAIL_URL,
                ),
            }
        )

        js_carrier = Stage2Service().fetch_real_public_candidate_detail_url(
            JS_DETAIL_URL,
            profile_id="JIANGSU-GGZY-HOME",
            transport=transport,
        )
        sd_carrier = Stage2Service().fetch_real_public_candidate_detail_url(
            SD_DETAIL_URL,
            profile_id="SHANDONG-GGZY-JYXXGK-LIST",
            transport=transport,
        )

        self.assertEqual(js_carrier["status"], "FETCHED")
        self.assertEqual(sd_carrier["status"], "FETCHED")
        self.assertEqual(transport.call_log[0]["url"], JS_DETAIL_URL)
        self.assertEqual(transport.call_log[1]["url"], SD_DETAIL_URL)

    def test_same_site_candidate_attachment_fetch_persists_dynamic_attachment_snapshot(self) -> None:
        pdf_bytes = _pdf_like_bytes()
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_ATTACHMENT_URL: RealPublicFetchResponse(
                    url=CCGP_ATTACHMENT_URL,
                    status_code=200,
                    content=pdf_bytes,
                    content_type="application/pdf",
                    final_url=CCGP_ATTACHMENT_URL,
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            carrier = Stage2Service().fetch_real_public_same_site_attachment_url(
                CCGP_ATTACHMENT_URL,
                parent_profile_id="CCGP-CENTRAL-NOTICES",
                repository=repo,
                transport=transport,
                detail_page_url=CCGP_DETAIL_URL,
                lineage_refs={"candidate_key": "candidate-001"},
            )

            self.assertEqual(carrier["status"], "FETCHED")
            self.assertTrue(carrier["attachment_profile_id"].startswith("CCGP-CENTRAL-NOTICES-SAME-SITE-ATTACH-"))
            self.assertEqual(carrier["attachment_url"], CCGP_ATTACHMENT_URL)
            self.assertEqual(carrier["detail_page_url_optional"], CCGP_DETAIL_URL)
            replay = repo.replay_snapshot(carrier["snapshot_id_optional"])
            self.assertEqual(replay["manifest"]["snapshot_kind"], REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND)
            self.assertEqual(replay["manifest"]["source_url_optional"], CCGP_ATTACHMENT_URL)
            self.assertEqual(replay["manifest"]["lineage_refs"]["candidate_key"], "candidate-001")
            self.assertEqual(repo.read_snapshot_bytes(carrier["snapshot_id_optional"]), pdf_bytes)

        self.assertEqual(transport.call_log[0]["url"], CCGP_ATTACHMENT_URL)

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

        self.assertEqual(carrier["status"], "AUTOMATED_CHALLENGE_RESOLUTION_PENDING")
        self.assertFalse(carrier["review_required"])
        self.assertFalse(carrier["fail_closed"])
        self.assertTrue(carrier["automated_challenge_resolution_pending"])
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
            if profile.profile_id == "JIANGSU-GGZY-HOME":
                self.assertTrue(profile.url.startswith("http://"), profile.profile_id)
            else:
                self.assertTrue(profile.url.startswith("https://"), profile.profile_id)
            self.assertNotIn("/information/deal/html/", profile.url, profile.profile_id)
            if profile.profile_id in {
                "CCGP-CENTRAL-NOTICES",
                "CCGP-CENTRAL-AWARD-LIST",
            }:
                self.assertTrue(profile.url.endswith("/"), profile.profile_id)
            if profile.profile_id == "JIANGSU-GGZY-HOME":
                self.assertTrue(profile.sample_detail_url.startswith("http://"), profile.profile_id)
            else:
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
                "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
                "JIANGSU-GGZY-HOME",
                "ZHEJIANG-GGZY-JYXXGK-LIST",
                "SHANDONG-GGZY-JYXXGK-LIST",
                "HUBEI-BIDCLOUD-JYXX-LIST",
                "SICHUAN-GGZY-TRANSACTION-INFO",
            ),
        )
        profiles_by_id = {profile.profile_id: profile for profile in REAL_PUBLIC_ENTRY_PROFILES}
        self.assertEqual(profiles_by_id["BEIJING-PLATFORM-HOME"].url, BEIJING_HOME_URL)
        self.assertEqual(profiles_by_id["BEIJING-GCJS-LIST"].url, BEIJING_GCJS_URL)
        self.assertEqual(profiles_by_id["BEIJING-BDA-HOME"].url, BEIJING_BDA_URL)
        self.assertEqual(profiles_by_id["GUANGZHOU-YWTB-CONSTRUCTION-LIST"].url, GZ_YWTB_URL)
        self.assertEqual(profiles_by_id["GUANGDONG-YGP-PROVINCE-TRADING-LIST"].url, GD_YGP_URL)
        self.assertEqual(profiles_by_id["JIANGSU-GGZY-HOME"].url, "http://jsggzy.jszwfw.gov.cn/")
        self.assertEqual(profiles_by_id["ZHEJIANG-GGZY-JYXXGK-LIST"].url, "https://ggzy.zj.gov.cn/jyxxgk/list.html")
        self.assertEqual(profiles_by_id["SHANDONG-GGZY-JYXXGK-LIST"].url, "https://ggzyjy.shandong.gov.cn/queryContent-jyxxgk.jspx?channelId=78")
        self.assertEqual(profiles_by_id["HUBEI-BIDCLOUD-JYXX-LIST"].url, "https://www.hbbidcloud.cn/hubei/jyxx/about.html")
        self.assertEqual(profiles_by_id["SICHUAN-GGZY-TRANSACTION-INFO"].url, "https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html")

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
                GD_YGP_URL: RealPublicFetchResponse(
                    url=GD_YGP_URL,
                    status_code=200,
                    content=_guangdong_shell_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=GD_YGP_URL,
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
                GD_YGP_URL,
                profile_id="GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            )

            self.assertEqual(beijing["status"], "FETCHED")
            self.assertEqual(beijing["source_family"], "local_public_resource_trading_center")
            self.assertTrue(beijing["snapshot_id_optional"])
            self.assertEqual(repo.read_snapshot_bytes(beijing["snapshot_id_optional"]), _beijing_platform_html())

            self.assertEqual(guangdong["status"], "FETCHED")
            self.assertEqual(guangdong["source_family"], "local_public_resource_trading_center")
            self.assertEqual(guangdong["entry_validation_level"], "VISIBLE_ENTRY_MARKERS")
            self.assertEqual(
                guangdong["lightweight_public_entry_markers_found"],
                ["广东省公共资源交易平台"],
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
        self.assertIn("attachment_html_blocker:unknown_html", carrier["degraded_reasons"])
        self.assertEqual(carrier["attachment_blocker_class"], "UNKNOWN_HTML_ATTACHMENT_RESPONSE")
        self.assertEqual(carrier["attachment_resolution_route"], "browser_replay_required_before_manual_review")
        self.assertIn("click_same_site_attachment_link", carrier["attachment_browser_replay_steps"])
        self.assertTrue(carrier["fail_closed"])

    def test_same_site_attachment_html_challenge_records_manual_replay_route(self) -> None:
        challenge_body = (
            "<html><title>安全验证</title><body>验证码 人机验证 后继续下载</body></html>"
        ).encode("utf-8")
        transport = FakeRealPublicFetchTransport(
            {
                GZ_YWTB_ATTACHMENT_URL: RealPublicFetchResponse(
                    url=GZ_YWTB_ATTACHMENT_URL,
                    status_code=200,
                    content=challenge_body,
                    content_type="text/html; charset=utf-8",
                    final_url=GZ_YWTB_ATTACHMENT_URL,
                )
            }
        )

        carrier = RealPublicEntryFetcher(transport=transport, repository=None).fetch_same_site_attachment_url(
            GZ_YWTB_ATTACHMENT_URL,
            parent_profile_id="GUANGZHOU-YWTB-CONSTRUCTION-LIST",
            detail_page_url=GZ_YWTB_DETAIL_URL,
        )

        self.assertEqual(carrier["status"], "DEGRADED")
        self.assertIn("html_body_not_attachment", carrier["degraded_reasons"])
        self.assertIn("attachment_html_blocker:captcha_or_manual_verification", carrier["degraded_reasons"])
        self.assertEqual(carrier["attachment_blocker_class"], "CAPTCHA_MANUAL_REQUIRED")
        self.assertEqual(
            carrier["attachment_resolution_route"],
            "open_detail_page_then_manual_challenge_download_and_snapshot",
        )
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
