from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from shared.utils import utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


REAL_PUBLIC_ENTRY_FETCHER_ID = "stage2.real_public_entry_url_fetcher.v1"
REAL_PUBLIC_ENTRY_FETCH_MODE = "REAL_PUBLIC_ENTRY_ALLOWLIST"
REAL_PUBLIC_ATTACHMENT_FETCH_MODE = "REAL_PUBLIC_ATTACHMENT_ALLOWLIST"
REAL_PUBLIC_ENTRY_SNAPSHOT_KIND = "real_public_entry_html_snapshot"
REAL_PUBLIC_DETAIL_SNAPSHOT_KIND = "real_public_detail_html_snapshot"
REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND = "real_public_attachment_original_file"
REAL_PUBLIC_ENTRY_USER_AGENT = (
    "AX9S-RealPublicEntryFetcher/0.1 (+public-readonly-validation)"
)
HTTP_PUBLIC_ENTRY_ALLOWLIST_PROFILE_IDS = {
    "JIANGSU-GGZY-HOME",
}
PROVINCE_REALTIME_DETAIL_PROFILE_IDS = {
    "JIANGSU-GGZY-HOME",
    "ZHEJIANG-GGZY-JYXXGK-LIST",
    "SHANDONG-GGZY-JYXXGK-LIST",
    "HUBEI-BIDCLOUD-JYXX-LIST",
    "SICHUAN-GGZY-TRANSACTION-INFO",
}


@dataclass(frozen=True)
class RealPublicEntryProfile:
    profile_id: str
    url: str
    site_name: str
    source_family: str
    expected_title_contains: str
    visible_entry_markers: tuple[str, ...]
    sample_detail_url: str
    browser_verified_at: str
    browser_verified_evidence: str
    lightweight_public_entry_markers: tuple[str, ...] = ()

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc.lower()


@dataclass(frozen=True)
class RealPublicAttachmentProfile:
    profile_id: str
    url: str
    site_name: str
    source_family: str
    detail_page_url_optional: str | None
    browser_verified_at: str
    browser_verified_evidence: str

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc.lower()


REAL_PUBLIC_ENTRY_PROFILES: tuple[RealPublicEntryProfile, ...] = (
    RealPublicEntryProfile(
        profile_id="GGZY-DEAL-LIST",
        url="https://www.ggzy.gov.cn/deal/dealList.html",
        site_name="全国公共资源交易平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="全国公共资源交易平台",
        visible_entry_markers=("交易查询", "搜索", "搜索记录数"),
        sample_detail_url=(
            "https://www.ggzy.gov.cn/information/deal/html/a/530000/0101/"
            "20260424/0053fb3c1c63347a4c988cc60249e8da1a91.html"
        ),
        browser_verified_at="2026-04-28T09:10:31+08:00",
        browser_verified_evidence="浏览器可见交易查询、搜索、搜索记录数和公开交易记录列表。",
    ),
    RealPublicEntryProfile(
        profile_id="CCGP-CENTRAL-NOTICES",
        url="https://www.ccgp.gov.cn/cggg/zygg/",
        site_name="中国政府采购网",
        source_family="government_procurement_public_site",
        expected_title_contains="中央公告",
        visible_entry_markers=("中央公告", "采购头条", "政采动态"),
        sample_detail_url=(
            "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202401/"
            "t20240112_21424937.htm"
        ),
        browser_verified_at="2026-04-28T09:10:39+08:00",
        browser_verified_evidence="浏览器可见中央公告、采购头条和政采动态入口。",
    ),
    RealPublicEntryProfile(
        profile_id="CCGP-CENTRAL-AWARD-LIST",
        url="https://www.ccgp.gov.cn/cggg/zygg/zbgg/",
        site_name="中国政府采购网",
        source_family="government_procurement_public_site",
        expected_title_contains="中标公告",
        visible_entry_markers=("中标公告",),
        sample_detail_url=(
            "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202401/"
            "t20240112_21424937.htm"
        ),
        browser_verified_at="2026-04-28T09:08:17+08:00",
        browser_verified_evidence="浏览器可见中标公告列表入口。",
    ),
    RealPublicEntryProfile(
        profile_id="JZSC-NATIONAL-HOME",
        url="https://jzsc.mohurd.gov.cn/home",
        site_name="全国建筑市场监管公共服务平台（四库一平台）",
        source_family="national_construction_market_platform",
        expected_title_contains="全国建筑市场监管公共服务平台",
        visible_entry_markers=("建设工程企业", "注册人员", "建设项目"),
        sample_detail_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=002105291239452167",
        browser_verified_at="2026-04-28T15:10:00+08:00",
        browser_verified_evidence="官方首页可打开；后续原始 HTML 抓取实际返回前端壳页，需要单独按 raw-shell/fail-closed 分类。",
        lightweight_public_entry_markers=("全国建筑市场监管公共服务平台", "建筑与诚信信息发布平台"),
    ),
    RealPublicEntryProfile(
        profile_id="JZSC-NATIONAL-COMPANY",
        url="https://jzsc.mohurd.gov.cn/data/company",
        site_name="全国建筑市场监管公共服务平台（四库一平台）",
        source_family="national_construction_market_platform",
        expected_title_contains="全国建筑市场监管公共服务平台",
        visible_entry_markers=("建设工程企业",),
        sample_detail_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=002105291239452167",
        browser_verified_at="2026-04-28T15:10:00+08:00",
        browser_verified_evidence="企业入口 URL 可直接返回 200，但 raw 抓取仍是 SPA 壳页，需要后续浏览器渲染或专用 API 方案。",
    ),
    RealPublicEntryProfile(
        profile_id="JZSC-NATIONAL-PERSON",
        url="https://jzsc.mohurd.gov.cn/data/person",
        site_name="全国建筑市场监管公共服务平台（四库一平台）",
        source_family="national_construction_market_platform",
        expected_title_contains="全国建筑市场监管公共服务平台",
        visible_entry_markers=("注册人员",),
        sample_detail_url="https://jzsc.mohurd.gov.cn/data/person",
        browser_verified_at="2026-04-28T15:10:00+08:00",
        browser_verified_evidence="人员入口 URL 可直接返回 200，但 raw 抓取仍是 SPA 壳页，需要 fail-closed 处理。",
    ),
    RealPublicEntryProfile(
        profile_id="JZSC-NATIONAL-PROJECT",
        url="https://jzsc.mohurd.gov.cn/data/project",
        site_name="全国建筑市场监管公共服务平台（四库一平台）",
        source_family="national_construction_market_platform",
        expected_title_contains="全国建筑市场监管公共服务平台",
        visible_entry_markers=("建设项目",),
        sample_detail_url="https://jzsc.mohurd.gov.cn/data/project",
        browser_verified_at="2026-04-28T15:10:00+08:00",
        browser_verified_evidence="项目入口 URL 可直接返回 200，但 raw 抓取仍是 SPA 壳页，需要 fail-closed 处理。",
    ),
    RealPublicEntryProfile(
        profile_id="CREDITCHINA-HOME",
        url="https://www.creditchina.gov.cn/",
        site_name="信用中国",
        source_family="credit_china",
        expected_title_contains="信用中国",
        visible_entry_markers=("信用信息", "统一社会信用代码", "站内文章"),
        sample_detail_url="https://www.creditchina.gov.cn/",
        browser_verified_at="2026-04-28T15:12:00+08:00",
        browser_verified_evidence="官方总入口真实可解析为正式站点，但当前 runtime 直连返回 412，需要显式 fail-closed 记录。",
    ),
    RealPublicEntryProfile(
        profile_id="GSXT-HOME",
        url="https://www.gsxt.gov.cn/index.html",
        site_name="国家企业信用信息公示系统",
        source_family="national_enterprise_credit_publicity_system",
        expected_title_contains="国家企业信用信息公示系统",
        visible_entry_markers=("企业信息填报", "信息公告", "统一社会信用代码"),
        sample_detail_url="https://www.gsxt.gov.cn/index.html",
        browser_verified_at="2026-04-28T15:12:00+08:00",
        browser_verified_evidence="官方总入口真实存在，但当前 runtime 直连返回 521，需要显式 fail-closed 记录。",
    ),
    RealPublicEntryProfile(
        profile_id="BEIJING-PLATFORM-HOME",
        url="https://ggzyfw.beijing.gov.cn/",
        site_name="北京市公共资源交易服务平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="北京市公共资源交易服务平台",
        visible_entry_markers=("交易服务", "公告", "工程建设"),
        sample_detail_url="https://ggzyfw.beijing.gov.cn/tyrkgcjs/index.html",
        browser_verified_at="2026-04-28T15:35:00+08:00",
        browser_verified_evidence="官方首页 runtime 直连返回 200，正文可见交易服务、公告和工程建设等入口词。",
    ),
    RealPublicEntryProfile(
        profile_id="BEIJING-GCJS-LIST",
        url="https://ggzyfw.beijing.gov.cn/tyrkgcjs/index.html",
        site_name="北京市公共资源交易服务平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="北京市公共资源交易服务平台",
        visible_entry_markers=("交易服务", "公告", "工程建设"),
        sample_detail_url="https://ggzyfw.beijing.gov.cn/",
        browser_verified_at="2026-04-28T15:35:00+08:00",
        browser_verified_evidence="工程建设入口 runtime 直连返回 200，原始 HTML 可见公告/交易服务类入口词。",
    ),
    RealPublicEntryProfile(
        profile_id="BEIJING-BDA-HOME",
        url="https://ggzyjy.bda.gov.cn/",
        site_name="全国公共资源交易平台(北京市经济技术开发区)北京市公共资源交易服务经济技术开发区分平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="全国公共资源交易平台",
        visible_entry_markers=("交易服务", "公告", "搜索"),
        sample_detail_url="https://ggzyjy.bda.gov.cn/",
        browser_verified_at="2026-04-28T15:35:00+08:00",
        browser_verified_evidence="经开区分平台 runtime 直连返回 200，正文可见交易服务、公告和搜索。",
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-YGP-PROVINCE-TRADING-LIST",
        url="https://ygp.gdzwfw.gov.cn/#/44/jygg",
        site_name="广东省公共资源交易平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="广东省公共资源交易平台",
        visible_entry_markers=("交易公开", "工程建设", "招标公告及资格预审", "中标候选人公示"),
        sample_detail_url="https://ygp.gdzwfw.gov.cn/#/44/jygg",
        browser_verified_at="2026-05-01T14:50:39+08:00",
        browser_verified_evidence="浏览器打开 https://ygp.gdzwfw.gov.cn/#/44/jygg，页面标题为广东省公共资源交易平台，广东省项目所属交易公开列表可见 2026-05-01 全省工程建设招标公告。",
        lightweight_public_entry_markers=("广东省公共资源交易平台",),
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-GDCIC-HOME",
        url="https://www.gdcic.net/",
        site_name="广东建设信息网",
        source_family="industry_authority_filing_page",
        expected_title_contains="广东建设信息网",
        visible_entry_markers=("三库一平台", "数据开放平台", "企业信息", "人员信息", "项目信息"),
        sample_detail_url="https://skypt.gdcic.net/openplatform/",
        browser_verified_at="2026-05-02T09:05:00+08:00",
        browser_verified_evidence="官方首页可见三库一平台、数据开放平台、企业信息、人员信息、项目信息、招投标及合同履约监管系统等行业数据入口。",
        lightweight_public_entry_markers=("广东建设信息网", "三库一平台", "项目信息"),
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
        url="https://skypt.gdcic.net/openplatform/",
        site_name="广东建设信息网三库一平台数据开放平台",
        source_family="industry_authority_filing_page",
        expected_title_contains="广东省建设行业数据开放平台",
        visible_entry_markers=("企业信息", "人员信息", "项目信息"),
        sample_detail_url="https://skypt.gdcic.net/openplatform/#/project",
        browser_verified_at="2026-05-02T09:05:00+08:00",
        browser_verified_evidence="由广东建设信息网行业数据入口指向；原始直连返回 JavaScript 应用壳，需要浏览器渲染 adapter 执行项目/企业/人员查询。",
        lightweight_public_entry_markers=("JavaScript enabled", "openplatform"),
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-TZXM-HOME",
        url="https://tzxm.gd.gov.cn/",
        site_name="广东省投资项目在线审批监管平台",
        source_family="investment_project_approval_platform",
        expected_title_contains="广东省投资项目在线审批监管平台",
        visible_entry_markers=("办理结果公示", "项目代码验证", "项目进展查询", "竣工报告"),
        sample_detail_url="https://tzxm.gd.gov.cn/#/projectProgress",
        browser_verified_at="2026-05-02T09:05:00+08:00",
        browser_verified_evidence="官方首页可见办理结果公示、项目代码验证、项目进展查询和进展报告/竣工报告入口。",
        lightweight_public_entry_markers=("广东省投资项目在线审批监管平台", "项目代码验证"),
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-ZFCXJST-PENALTY-PUBLICITY",
        url="https://zfcxjst.gd.gov.cn/xxgk/sgs/",
        site_name="广东省住房和城乡建设厅行政处罚公示",
        source_family="local_housing_administrative_penalty",
        expected_title_contains="广东省住房和城乡建设厅",
        visible_entry_markers=("信用信息双公示", "行政许可公示", "行政处罚公示"),
        sample_detail_url="https://skypt.gdcic.net/openplatform/",
        browser_verified_at="2026-05-02T09:05:00+08:00",
        browser_verified_evidence="广东省住房和城乡建设厅信息公开页可见信用信息双公示、行政许可公示和行政处罚公示入口。",
        lightweight_public_entry_markers=("行政处罚公示", "信用信息双公示"),
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-CREDIT-GD-HOME",
        url="https://credit.gd.gov.cn/",
        site_name="信用广东",
        source_family="local_credit_public_record",
        expected_title_contains="信用广东",
        visible_entry_markers=("信用信息", "行政处罚", "统一社会信用代码"),
        sample_detail_url="https://credit.gd.gov.cn/xygs/",
        browser_verified_at="2026-05-02T09:05:00+08:00",
        browser_verified_evidence="广东省投资项目在线审批监管平台友情链接列出信用广东；用于企业主体信用、处罚和公开信用风险补强入口。",
        lightweight_public_entry_markers=("信用广东",),
    ),
    RealPublicEntryProfile(
        profile_id="JIANGSU-GGZY-HOME",
        url="http://jsggzy.jszwfw.gov.cn/",
        site_name="江苏省公共资源交易网",
        source_family="local_public_resource_trading_center",
        expected_title_contains="江苏省公共资源交易网",
        visible_entry_markers=("交易信息", "招标公告", "中标结果公告", "政府采购"),
        sample_detail_url="http://jsggzy.jszwfw.gov.cn/",
        browser_verified_at="2026-05-01T14:50:39+08:00",
        browser_verified_evidence="浏览器打开 http://jsggzy.jszwfw.gov.cn/，首页交易信息可见 2026-04-30 建设工程招标公告和药品耗材采购公告。",
        lightweight_public_entry_markers=("江苏省公共资源交易网",),
    ),
    RealPublicEntryProfile(
        profile_id="ZHEJIANG-GGZY-JYXXGK-LIST",
        url="https://ggzy.zj.gov.cn/jyxxgk/list.html",
        site_name="浙江省公共资源交易服务平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="浙江省公共资源交易服务平台",
        visible_entry_markers=("交易信息公开", "工程建设", "招标公告", "中标结果公告"),
        sample_detail_url="https://ggzy.zj.gov.cn/jyxxgk/list.html",
        browser_verified_at="2026-05-01T14:50:39+08:00",
        browser_verified_evidence="浏览器打开 https://ggzy.zj.gov.cn/jyxxgk/list.html，交易信息公开列表可见 2026-04-30 工程建设项目登记和公告记录。",
        lightweight_public_entry_markers=("浙江省公共资源交易服务平台",),
    ),
    RealPublicEntryProfile(
        profile_id="SHANDONG-GGZY-JYXXGK-LIST",
        url="https://ggzyjy.shandong.gov.cn/queryContent-jyxxgk.jspx?channelId=78",
        site_name="山东省公共资源交易网",
        source_family="local_public_resource_trading_center",
        expected_title_contains="山东省公共资源交易网",
        visible_entry_markers=("交易公开", "工程建设", "招标公告", "信息分类"),
        sample_detail_url="https://ggzyjy.shandong.gov.cn/queryContent-jyxxgk.jspx?channelId=78",
        browser_verified_at="2026-05-01T14:50:39+08:00",
        browser_verified_evidence="浏览器打开 https://ggzyjy.shandong.gov.cn/queryContent-jyxxgk.jspx?channelId=78，交易公开列表可见 2026-05-01 山东工程建设招标公告。",
        lightweight_public_entry_markers=("山东省公共资源交易网",),
    ),
    RealPublicEntryProfile(
        profile_id="HUBEI-BIDCLOUD-JYXX-LIST",
        url="https://www.hbbidcloud.cn/hubei/jyxx/about.html",
        site_name="湖北省公共资源交易云平台",
        source_family="local_public_resource_trading_center",
        expected_title_contains="湖北省公共资源交易云平台",
        visible_entry_markers=("交易信息", "招标公告", "评标结果公示", "中标结果公告"),
        sample_detail_url="https://www.hbbidcloud.cn/hubei/jyxx/about.html",
        browser_verified_at="2026-05-01T14:50:39+08:00",
        browser_verified_evidence="浏览器打开 https://www.hbbidcloud.cn/hubei/jyxx/about.html，交易信息列表可见 2026-04-30 湖北工程建设招标公告和评标结果。",
        lightweight_public_entry_markers=("湖北省公共资源交易云平台",),
    ),
    RealPublicEntryProfile(
        profile_id="SICHUAN-GGZY-TRANSACTION-INFO",
        url="https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html",
        site_name="四川省公共资源交易信息网",
        source_family="local_public_resource_trading_center",
        expected_title_contains="四川省公共资源交易信息网",
        visible_entry_markers=("交易信息", "工程建设", "政府采购", "招标公告"),
        sample_detail_url="https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html",
        browser_verified_at="2026-05-01T14:50:39+08:00",
        browser_verified_evidence="浏览器打开 https://ggzyjy.sc.gov.cn/jyxx/transactionInfo.html，交易信息列表可见 2026-05-01 四川政府采购、国企采购和工程相关公告。",
        lightweight_public_entry_markers=("四川省公共资源交易信息网",),
    ),
)

REAL_PUBLIC_ENTRY_PROFILE_BY_URL = {
    profile.url: profile for profile in REAL_PUBLIC_ENTRY_PROFILES
}
REAL_PUBLIC_ENTRY_PROFILE_BY_ID = {
    profile.profile_id: profile for profile in REAL_PUBLIC_ENTRY_PROFILES
}
NATIONAL_VERIFICATION_ENTRY_PROFILE_IDS = (
    "JZSC-NATIONAL-HOME",
    "JZSC-NATIONAL-COMPANY",
    "JZSC-NATIONAL-PERSON",
    "JZSC-NATIONAL-PROJECT",
    "CREDITCHINA-HOME",
    "GSXT-HOME",
)
REPRESENTATIVE_LOCAL_PLATFORM_ENTRY_PROFILE_IDS = (
    "BEIJING-PLATFORM-HOME",
    "BEIJING-GCJS-LIST",
    "BEIJING-BDA-HOME",
    "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
    "JIANGSU-GGZY-HOME",
    "ZHEJIANG-GGZY-JYXXGK-LIST",
    "SHANDONG-GGZY-JYXXGK-LIST",
    "HUBEI-BIDCLOUD-JYXX-LIST",
    "SICHUAN-GGZY-TRANSACTION-INFO",
)
PUBLIC_ATTACHMENT_PROFILE_IDS = (
    "BEIJING-STANDARD-BIDDING-PDF",
    "BEIJING-TOOLING-PDF",
)
DEGRADED_ENTRY_PROFILE_IDS_AFTER_136 = (
    "JZSC-NATIONAL-HOME",
    "JZSC-NATIONAL-COMPANY",
    "JZSC-NATIONAL-PERSON",
    "JZSC-NATIONAL-PROJECT",
    "CREDITCHINA-HOME",
    "GSXT-HOME",
    "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
)
REAL_PUBLIC_ATTACHMENT_PROFILES: tuple[RealPublicAttachmentProfile, ...] = (
    RealPublicAttachmentProfile(
        profile_id="BEIJING-STANDARD-BIDDING-PDF",
        url="https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202506/9426015154001.pdf",
        site_name="北京市公共资源交易服务平台",
        source_family="local_public_resource_trading_center",
        detail_page_url_optional="https://ggzyfw.beijing.gov.cn/",
        browser_verified_at="2026-04-28T16:10:00+08:00",
        browser_verified_evidence="官方域名下真实 PDF 原始链接，runtime 直连返回 200 和 application/pdf。",
    ),
    RealPublicAttachmentProfile(
        profile_id="BEIJING-TOOLING-PDF",
        url="https://ggzyfw.beijing.gov.cn/cmsbj/u/cms/cn.gov.bjggzyfw.www/202410/25172947ch03.pdf",
        site_name="北京市公共资源交易服务平台",
        source_family="local_public_resource_trading_center",
        detail_page_url_optional="https://ggzyfw.beijing.gov.cn/",
        browser_verified_at="2026-04-28T16:10:00+08:00",
        browser_verified_evidence="官方域名下真实 PDF 原始链接，runtime 直连返回 200 和 application/pdf。",
    ),
)
REAL_PUBLIC_ATTACHMENT_PROFILE_BY_URL = {
    profile.url: profile for profile in REAL_PUBLIC_ATTACHMENT_PROFILES
}
REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID = {
    profile.profile_id: profile for profile in REAL_PUBLIC_ATTACHMENT_PROFILES
}

_ENTRY_UNAVAILABLE_BODY_PATTERNS = (
    "错误页面",
    "页面不存在",
    "404 Not Found",
)

_CONTROLLED_CHALLENGE_BODY_PATTERNS = (
    "请先登录",
    "请登录",
    "用户登录",
    "验证码",
    "captcha",
    "人机验证",
    "安全验证",
)


@dataclass(frozen=True)
class RealPublicFetchResponse:
    url: str
    status_code: int
    content: bytes
    content_type: str = "text/html"
    final_url: str | None = None
    headers: Mapping[str, str] | None = None


class RealPublicFetchTransport(Protocol):
    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        ...


class UrlLibRealPublicFetchTransport:
    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        request = Request(url, headers={"User-Agent": user_agent})
        try:
            response_context = urlopen(request, timeout=timeout_seconds)  # noqa: S310
        except HTTPError as exc:
            content = exc.read()
            headers = dict(exc.headers.items()) if exc.headers else {}
            headers["x-ax9s-fetch-transport"] = "urllib"
            return RealPublicFetchResponse(
                url=url,
                status_code=int(exc.code),
                content=content,
                content_type=headers.get("Content-Type", "text/html"),
                final_url=exc.geturl(),
                headers=headers,
            )

        with response_context as response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "text/html")
            headers = dict(response.headers.items())
            headers["x-ax9s-fetch-transport"] = "urllib"
            return RealPublicFetchResponse(
                url=url,
                status_code=int(response.status),
                content=content,
                content_type=content_type,
                final_url=response.geturl(),
                headers=headers,
            )


class CurlCommandRealPublicFetchTransport:
    def __init__(self, *, curl_binary: str | None = None) -> None:
        self.curl_binary = curl_binary or shutil.which("curl.exe") or shutil.which("curl")

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        if not self.curl_binary:
            raise RuntimeError("curl transport unavailable")

        timeout_value = max(1, int(timeout_seconds))
        with tempfile.TemporaryDirectory() as tmp_dir:
            header_path = Path(tmp_dir) / "headers.txt"
            body_path = Path(tmp_dir) / "body.bin"
            command = [
                self.curl_binary,
                "--location",
                "--silent",
                "--show-error",
                "--max-time",
                str(timeout_value),
                "--user-agent",
                user_agent,
                "--dump-header",
                str(header_path),
                "--output",
                str(body_path),
                "--write-out",
                "\n%{http_code}\n%{url_effective}\n%{content_type}",
                url,
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_value + 5,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"curl transport failed:{completed.returncode}:{detail}")

            write_out = [line for line in completed.stdout.splitlines() if line.strip()]
            if len(write_out) < 3:
                raise RuntimeError("curl transport missing write-out metadata")

            status_code = int(write_out[-3])
            final_url = write_out[-2].strip() or url
            content_type = write_out[-1].strip() or "application/octet-stream"
            content = body_path.read_bytes() if body_path.exists() else b""
            headers = _parse_curl_headers(
                header_path.read_text(encoding="iso-8859-1", errors="replace")
                if header_path.exists()
                else ""
            )
            headers["x-ax9s-fetch-transport"] = "curl_command"
            return RealPublicFetchResponse(
                url=url,
                status_code=status_code,
                content=content,
                content_type=content_type or headers.get("Content-Type", "application/octet-stream"),
                final_url=final_url,
                headers=headers,
            )


class HybridRealPublicFetchTransport:
    def __init__(
        self,
        *,
        primary: RealPublicFetchTransport | None = None,
        fallback: RealPublicFetchTransport | None = None,
    ) -> None:
        self.primary = primary or UrlLibRealPublicFetchTransport()
        self.fallback = fallback or CurlCommandRealPublicFetchTransport()

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        try:
            return self.primary.fetch(
                url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
        except Exception as exc:
            if not _should_try_fetch_fallback(exc):
                raise
            response = self.fallback.fetch(
                url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
            headers = dict(response.headers or {})
            headers["x-ax9s-fetch-transport"] = headers.get("x-ax9s-fetch-transport", "fallback")
            headers["x-ax9s-primary-transport-error"] = str(exc)
            return RealPublicFetchResponse(
                url=response.url,
                status_code=response.status_code,
                content=response.content,
                content_type=response.content_type,
                final_url=response.final_url,
                headers=headers,
            )


class RealPublicUrlBoundaryError(ValueError):
    def __init__(self, reason: str, carrier: Mapping[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.carrier = dict(carrier)


class RealPublicEntryFetcher:
    def __init__(
        self,
        *,
        transport: RealPublicFetchTransport | None = None,
        repository: ObjectStorageRepository | None = None,
        timeout_seconds: float = 20.0,
        user_agent: str = REAL_PUBLIC_ENTRY_USER_AGENT,
    ) -> None:
        self.transport = transport or HybridRealPublicFetchTransport()
        self.repository = repository
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def fetch_entry_url(
        self,
        url: str,
        *,
        profile_id: str | None = None,
        lineage_refs: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        profile = self._resolve_profile(url, profile_id=profile_id)
        now = utc_now_iso()
        try:
            response = self.transport.fetch(
                profile.url,
                timeout_seconds=self.timeout_seconds,
                user_agent=self.user_agent,
            )
        except Exception as exc:  # pragma: no cover - concrete network exceptions vary
            return self._degraded_carrier(
                profile,
                now=now,
                reason="fetch_failed",
                detail=str(exc),
                lineage_refs=lineage_refs,
                fetch_attempted=True,
            )

        return self._carrier_from_response(
            profile,
            response,
            now=now,
            lineage_refs=lineage_refs,
        )

    def fetch_candidate_detail_url(
        self,
        url: str,
        *,
        profile_id: str,
        lineage_refs: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        profile = self._resolve_candidate_detail_profile(url, profile_id=profile_id)
        detail_url = str(url).strip()
        now = utc_now_iso()
        try:
            if _is_guangdong_ygp_hash_detail_url(detail_url, profile_id=profile.profile_id):
                response = _fetch_guangdong_ygp_detail_api_response(
                    detail_url,
                    user_agent=self.user_agent,
                )
            else:
                response = self.transport.fetch(
                    detail_url,
                    timeout_seconds=self.timeout_seconds,
                    user_agent=self.user_agent,
                )
        except Exception as exc:  # pragma: no cover - concrete network exceptions vary
            return self._degraded_detail_carrier(
                profile,
                detail_url=detail_url,
                now=now,
                reason="fetch_failed",
                detail=str(exc),
                lineage_refs=lineage_refs,
                fetch_attempted=True,
            )

        return self._detail_carrier_from_response(
            profile,
            detail_url=detail_url,
            response=response,
            now=now,
            lineage_refs=lineage_refs,
        )

    def fetch_attachment_original_link(
        self,
        url: str,
        *,
        profile_id: str | None = None,
        lineage_refs: Mapping[str, str] | None = None,
        detail_page_url: str | None = None,
    ) -> dict[str, Any]:
        profile = self._resolve_attachment_profile(url, profile_id=profile_id)
        now = utc_now_iso()
        try:
            response = self.transport.fetch(
                profile.url,
                timeout_seconds=self.timeout_seconds,
                user_agent=self.user_agent,
            )
        except Exception as exc:  # pragma: no cover - concrete network exceptions vary
            return self._degraded_attachment_carrier(
                profile,
                now=now,
                reason="fetch_failed",
                detail=str(exc),
                lineage_refs=lineage_refs,
                detail_page_url=detail_page_url,
                fetch_attempted=True,
            )

        return self._attachment_carrier_from_response(
            profile,
            response,
            now=now,
            lineage_refs=lineage_refs,
            detail_page_url=detail_page_url,
        )

    def fetch_same_site_attachment_url(
        self,
        url: str,
        *,
        parent_profile_id: str,
        lineage_refs: Mapping[str, str] | None = None,
        detail_page_url: str | None = None,
    ) -> dict[str, Any]:
        profile = self._resolve_same_site_attachment_profile(
            url,
            parent_profile_id=parent_profile_id,
            detail_page_url=detail_page_url,
        )
        now = utc_now_iso()
        try:
            response = self.transport.fetch(
                profile.url,
                timeout_seconds=self.timeout_seconds,
                user_agent=self.user_agent,
            )
        except Exception as exc:  # pragma: no cover - concrete network exceptions vary
            return self._degraded_attachment_carrier(
                profile,
                now=now,
                reason="fetch_failed",
                detail=str(exc),
                lineage_refs=lineage_refs,
                detail_page_url=detail_page_url,
                fetch_attempted=True,
            )

        return self._attachment_carrier_from_response(
            profile,
            response,
            now=now,
            lineage_refs=lineage_refs,
            detail_page_url=detail_page_url,
        )

    def _resolve_profile(
        self,
        url: str,
        *,
        profile_id: str | None,
    ) -> RealPublicEntryProfile:
        profile = REAL_PUBLIC_ENTRY_PROFILE_BY_URL.get(str(url).strip())
        if profile_id:
            by_id = REAL_PUBLIC_ENTRY_PROFILE_BY_ID.get(str(profile_id).strip())
            if by_id is None:
                raise self._boundary_error(url, f"unregistered_profile_id:{profile_id}")
            if profile is not None and by_id.url != profile.url:
                raise self._boundary_error(url, "profile_url_mismatch")
            profile = by_id
        if profile is None:
            raise self._boundary_error(url, "url_not_in_real_public_entry_allowlist")
        if urlsplit(profile.url).scheme != "https" and profile.profile_id not in HTTP_PUBLIC_ENTRY_ALLOWLIST_PROFILE_IDS:
            raise self._boundary_error(url, "non_https_public_entry_url")
        return profile

    def _resolve_candidate_detail_profile(
        self,
        url: str,
        *,
        profile_id: str,
    ) -> RealPublicEntryProfile:
        profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID.get(str(profile_id).strip())
        if profile is None:
            raise self._boundary_error(url, f"unregistered_profile_id:{profile_id}")
        detail_url = str(url or "").strip()
        parsed = urlsplit(detail_url)
        http_detail_allowed = profile.profile_id in HTTP_PUBLIC_ENTRY_ALLOWLIST_PROFILE_IDS or profile.profile_id in PROVINCE_REALTIME_DETAIL_PROFILE_IDS
        if parsed.scheme != "https" and not (parsed.scheme == "http" and http_detail_allowed):
            raise self._boundary_error(url, "non_https_public_detail_url")
        if (parsed.hostname or "").lower() != profile.host.split(":", 1)[0].lower():
            raise self._boundary_error(url, "detail_url_host_not_parent_profile")
        if _is_guangdong_ygp_hash_detail_url(detail_url, profile_id=profile.profile_id):
            return profile
        path = parsed.path.lower()
        allowed_detail_suffixes = (".html", ".htm", ".shtml")
        if profile.profile_id in PROVINCE_REALTIME_DETAIL_PROFILE_IDS:
            allowed_detail_suffixes = (*allowed_detail_suffixes, ".jhtml", ".jspx", ".jsp")
        if not path.endswith(allowed_detail_suffixes):
            raise self._boundary_error(url, "detail_url_not_html")
        if path.endswith(("index.html", "deallist.html", "list.html", "about.html", "transactioninfo.html")):
            raise self._boundary_error(url, "detail_url_points_to_list_or_index")
        if profile.profile_id == "GGZY-DEAL-LIST" and "/information/deal/html/" not in path:
            raise self._boundary_error(url, "ggzy_detail_url_pattern_mismatch")
        if profile.profile_id.startswith("CCGP-") and "/cggg/" not in path:
            raise self._boundary_error(url, "ccgp_detail_url_pattern_mismatch")
        return profile

    def _boundary_error(self, url: str, reason: str) -> RealPublicUrlBoundaryError:
        return RealPublicUrlBoundaryError(
            reason,
            {
                "status": "BLOCKED",
                "blocked_reason": reason,
                "entry_url": url,
                "fetch_attempted": False,
                "fail_closed": True,
                "no_broad_fallback": True,
                "unapproved_capture_enabled": False,
                "deep_capture_enabled": False,
                "real_provider_call_executed": False,
            },
        )

    def _resolve_attachment_profile(
        self,
        url: str,
        *,
        profile_id: str | None,
    ) -> RealPublicAttachmentProfile:
        profile = REAL_PUBLIC_ATTACHMENT_PROFILE_BY_URL.get(str(url).strip())
        if profile_id:
            by_id = REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID.get(str(profile_id).strip())
            if by_id is None:
                raise self._boundary_error(url, f"unregistered_attachment_profile_id:{profile_id}")
            if profile is not None and by_id.url != profile.url:
                raise self._boundary_error(url, "attachment_profile_url_mismatch")
            profile = by_id
        if profile is None:
            raise self._boundary_error(url, "attachment_url_not_in_allowlist")
        if urlsplit(profile.url).scheme != "https":
            raise self._boundary_error(url, "non_https_public_attachment_url")
        return profile

    def _resolve_same_site_attachment_profile(
        self,
        url: str,
        *,
        parent_profile_id: str,
        detail_page_url: str | None,
    ) -> RealPublicAttachmentProfile:
        parent = REAL_PUBLIC_ENTRY_PROFILE_BY_ID.get(str(parent_profile_id).strip())
        if parent is None:
            raise self._boundary_error(url, f"unregistered_parent_profile_id:{parent_profile_id}")
        attachment_url = str(url or "").strip()
        parsed = urlsplit(attachment_url)
        http_attachment_allowed = parent.profile_id in HTTP_PUBLIC_ENTRY_ALLOWLIST_PROFILE_IDS or parent.profile_id in PROVINCE_REALTIME_DETAIL_PROFILE_IDS
        if parsed.scheme != "https" and not (parsed.scheme == "http" and http_attachment_allowed):
            raise self._boundary_error(url, "non_https_same_site_attachment_url")
        if (parsed.hostname or "").lower() != parent.host.split(":", 1)[0].lower():
            raise self._boundary_error(url, "same_site_attachment_host_not_parent_profile")
        path = parsed.path.lower()
        guangdong_file_download = (
            parent.profile_id == "GUANGDONG-YGP-PROVINCE-TRADING-LIST"
            and "/ggzy-portal/base/sys-file/download/" in path
        )
        if not guangdong_file_download and not path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")):
            raise self._boundary_error(url, "same_site_attachment_url_not_supported_file")
        if detail_page_url:
            detail_parsed = urlsplit(str(detail_page_url).strip())
            allowed_detail_scheme = (
                detail_parsed.scheme == "https"
                or (
                    detail_parsed.scheme == "http"
                    and (
                        parent.profile_id in HTTP_PUBLIC_ENTRY_ALLOWLIST_PROFILE_IDS
                        or parent.profile_id in PROVINCE_REALTIME_DETAIL_PROFILE_IDS
                    )
                )
            )
            if not allowed_detail_scheme or (detail_parsed.hostname or "").lower() != parent.host.split(":", 1)[0].lower():
                raise self._boundary_error(url, "same_site_attachment_detail_page_host_mismatch")
        fingerprint = hashlib.sha1(attachment_url.encode("utf-8")).hexdigest()[:10]
        return RealPublicAttachmentProfile(
            profile_id=f"{parent.profile_id}-SAME-SITE-ATTACH-{fingerprint}",
            url=attachment_url,
            site_name=parent.site_name,
            source_family=parent.source_family,
            detail_page_url_optional=detail_page_url,
            browser_verified_at=parent.browser_verified_at,
            browser_verified_evidence=(
                "由已登记公开入口详情页发现的同站附件链接；父入口已完成浏览器可见性验证。"
            ),
        )

    def _carrier_from_response(
        self,
        profile: RealPublicEntryProfile,
        response: RealPublicFetchResponse,
        *,
        now: str,
        lineage_refs: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        content = response.content or b""
        text = _decode_html(content)
        title = _extract_title(text)
        sha256 = hashlib.sha256(content).hexdigest()
        markers_found = [
            marker for marker in profile.visible_entry_markers if marker in text
        ]
        missing_markers = [
            marker for marker in profile.visible_entry_markers if marker not in text
        ]
        lightweight_markers_found = [
            marker for marker in profile.lightweight_public_entry_markers if marker in text
        ]
        missing_lightweight_markers = [
            marker for marker in profile.lightweight_public_entry_markers if marker not in text
        ]
        lightweight_markers_complete = bool(profile.lightweight_public_entry_markers) and not missing_lightweight_markers
        entry_unavailable_body_patterns = [
            marker
            for marker in _ENTRY_UNAVAILABLE_BODY_PATTERNS
            if marker.lower() in text.lower()
        ]
        controlled_challenge_body_patterns = [
            marker
            for marker in _CONTROLLED_CHALLENGE_BODY_PATTERNS
            if marker.lower() in text.lower()
        ]
        same_site_link_items = _discover_same_site_link_items(
            text,
            base_url=response.final_url or profile.url,
            host=profile.host,
        )
        same_site_links = [item["url"] for item in same_site_link_items]
        degraded_reasons: list[str] = []
        if response.status_code != 200:
            degraded_reasons.append(f"http_status:{response.status_code}")
        if "html" not in (response.content_type or "").lower():
            degraded_reasons.append("non_html_content_type")
        if len(content) < 500:
            degraded_reasons.append("entry_body_too_small")
        if not markers_found and not lightweight_markers_complete:
            degraded_reasons.append("visible_entry_markers_missing")
        controlled_challenge_detected = bool(
            controlled_challenge_body_patterns
            and not markers_found
            and not lightweight_markers_complete
        )
        if controlled_challenge_detected:
            degraded_reasons.append(
                "controlled_challenge_body_pattern:"
                + ",".join(controlled_challenge_body_patterns)
            )
        elif entry_unavailable_body_patterns:
            degraded_reasons.append(
                "entry_unavailable_body_pattern:"
                + ",".join(entry_unavailable_body_patterns)
            )
        if profile.expected_title_contains and profile.expected_title_contains not in title:
            degraded_reasons.append("title_mismatch")

        status = (
            "AUTOMATED_CHALLENGE_RESOLUTION_PENDING"
            if controlled_challenge_detected
            else ("DEGRADED" if degraded_reasons else "FETCHED")
        )
        validation_level = (
            "CONTROLLED_CHALLENGE_AUTOMATED_RESUME"
            if controlled_challenge_detected
            else (
                "VISIBLE_ENTRY_MARKERS"
                if markers_found
                else (
                    "LIGHTWEIGHT_PUBLIC_ENTRY"
                    if lightweight_markers_complete
                    else "FAIL_CLOSED_INSUFFICIENT_VISIBLE_ENTRY"
                )
            )
        )
        failure_taxonomy = _response_failure_taxonomy(
            degraded_reasons,
            http_status=response.status_code,
            validation_level=validation_level,
        )
        snapshot_id = f"REAL-ENTRY-{profile.profile_id}-{sha256[:12]}"
        fetch_audit = {
            "fetcher_id": REAL_PUBLIC_ENTRY_FETCHER_ID,
            "fetch_mode": REAL_PUBLIC_ENTRY_FETCH_MODE,
            "fetch_attempted": True,
            "timeout_seconds": self.timeout_seconds,
            "user_agent": self.user_agent,
            "browser_verified": True,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
            "unapproved_capture_enabled": False,
            "deep_capture_enabled": False,
            "real_provider_call_executed": False,
            "same_site_detail_link_discovery_enabled": True,
            "cross_site_discovery_enabled": False,
            "transport": (response.headers or {}).get("x-ax9s-fetch-transport", "unknown"),
            "primary_transport_error_optional": (response.headers or {}).get("x-ax9s-primary-transport-error"),
            "entry_validation_level": validation_level,
            "failure_taxonomy": failure_taxonomy,
        }
        raw_metadata = {
            "entry_profile_id": profile.profile_id,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "entry_url": profile.url,
            "final_url": response.final_url or profile.url,
            "title": title,
            "visible_entry_markers_found": markers_found,
            "missing_visible_entry_markers": missing_markers,
            "lightweight_public_entry_markers_found": lightweight_markers_found,
            "missing_lightweight_public_entry_markers": missing_lightweight_markers,
            "entry_validation_level": validation_level,
            "same_site_detail_links": same_site_links,
            "same_site_detail_link_items": same_site_link_items,
            "sample_detail_url": profile.sample_detail_url,
            "browser_verified": True,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
            "entry_unavailable_body_patterns_observed": entry_unavailable_body_patterns,
            "controlled_challenge_body_patterns_observed": controlled_challenge_body_patterns,
            "degraded_reasons": degraded_reasons,
        }
        manifest_payload: dict[str, Any] | None = None
        if self.repository is not None and status == "FETCHED":
            manifest = self.repository.save_snapshot(
                content,
                snapshot_id=snapshot_id,
                snapshot_kind=REAL_PUBLIC_ENTRY_SNAPSHOT_KIND,
                content_type=response.content_type or "text/html",
                source_url_optional=profile.url,
                source_family_optional=profile.source_family,
                lineage_refs={
                    "entry_profile_id": profile.profile_id,
                    **{
                        str(key): str(value)
                        for key, value in dict(lineage_refs or {}).items()
                        if value not in (None, "")
                    },
                },
                adapter_id=REAL_PUBLIC_ENTRY_FETCHER_ID,
                source_visibility_state="PUBLIC_VISIBLE",
                snapshot_version="133A-entry-v1",
                fetched_at=now,
                captured_at=now,
                fetch_mode=REAL_PUBLIC_ENTRY_FETCH_MODE,
                fetch_audit=fetch_audit,
                raw_snapshot_metadata=raw_metadata,
                source_health={
                    "state": "HEALTHY",
                    "degraded_reasons": degraded_reasons,
                    "manual_review_required": False,
                },
            )
            manifest_payload = manifest.as_payload()

        return {
            "entry_fetch_id": snapshot_id,
            "status": status,
            "entry_profile_id": profile.profile_id,
            "entry_url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "http_status": response.status_code,
            "content_type": response.content_type,
            "byte_size": len(content),
            "sha256": sha256,
            "title": title,
            "browser_verified": True,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
            "visible_entry_markers_found": markers_found,
            "missing_visible_entry_markers": missing_markers,
            "lightweight_public_entry_markers_found": lightweight_markers_found,
            "missing_lightweight_public_entry_markers": missing_lightweight_markers,
            "entry_validation_level": validation_level,
            "same_site_detail_links": same_site_links,
            "same_site_detail_link_items": same_site_link_items,
            "sample_detail_url": profile.sample_detail_url,
            "snapshot_id_optional": snapshot_id if manifest_payload else None,
            "manifest_optional": manifest_payload,
            "degraded_reasons": degraded_reasons,
            "review_required": bool(degraded_reasons) and not controlled_challenge_detected,
            "automated_challenge_resolution_pending": controlled_challenge_detected,
            "automated_challenge_resolution_first": controlled_challenge_detected,
            "resume_requires_human_input": False,
            "resume_policy": "preserve_url_cookie_form_context_and_capture_plan_for_automated_resume"
            if controlled_challenge_detected
            else None,
            "fail_closed": bool(degraded_reasons) and not controlled_challenge_detected,
            "no_broad_fallback": True,
            "fetch_audit": fetch_audit,
            "failure_taxonomy": failure_taxonomy,
            "transport": fetch_audit["transport"],
            "controlled_opening_requirements": _controlled_opening_requirements(),
        }

    def _detail_carrier_from_response(
        self,
        profile: RealPublicEntryProfile,
        *,
        detail_url: str,
        response: RealPublicFetchResponse,
        now: str,
        lineage_refs: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        content = response.content or b""
        text = _decode_html(content)
        title = _extract_title(text)
        sha256 = hashlib.sha256(content).hexdigest()
        final_url = response.final_url or detail_url
        parsed_final = urlsplit(final_url)
        host = parsed_final.netloc.lower() or profile.host
        same_site_link_items = _discover_same_site_link_items(text, base_url=final_url, host=host)
        attachment_link_items = _discover_same_site_attachment_link_items(text, base_url=final_url, host=host)
        entry_unavailable_body_patterns = [
            marker
            for marker in _ENTRY_UNAVAILABLE_BODY_PATTERNS
            if marker.lower() in text.lower()
        ]
        controlled_challenge_body_patterns = [
            marker
            for marker in _CONTROLLED_CHALLENGE_BODY_PATTERNS
            if marker.lower() in text.lower()
        ]
        degraded_reasons: list[str] = []
        if response.status_code != 200:
            degraded_reasons.append(f"http_status:{response.status_code}")
        if "html" not in (response.content_type or "").lower():
            degraded_reasons.append("non_html_content_type")
        if len(content) < 300:
            degraded_reasons.append("detail_body_too_small")
        if not title:
            degraded_reasons.append("detail_title_missing")
        controlled_challenge_detected = bool(controlled_challenge_body_patterns)
        if controlled_challenge_detected:
            degraded_reasons.append(
                "controlled_challenge_body_pattern:"
                + ",".join(controlled_challenge_body_patterns)
            )
        elif entry_unavailable_body_patterns:
            degraded_reasons.append(
                "entry_unavailable_body_pattern:"
                + ",".join(entry_unavailable_body_patterns)
            )

        status = (
            "AUTOMATED_CHALLENGE_RESOLUTION_PENDING"
            if controlled_challenge_detected
            else ("DEGRADED" if degraded_reasons else "FETCHED")
        )
        validation_level = (
            "CONTROLLED_CHALLENGE_AUTOMATED_RESUME"
            if controlled_challenge_detected
            else ("PUBLIC_DETAIL_HTML" if not degraded_reasons else "FAIL_CLOSED_PUBLIC_DETAIL")
        )
        failure_taxonomy = _response_failure_taxonomy(
            degraded_reasons,
            http_status=response.status_code,
            validation_level=validation_level,
        )
        snapshot_id = f"REAL-DETAIL-{profile.profile_id}-{sha256[:12]}"
        fetch_audit = {
            "fetcher_id": REAL_PUBLIC_ENTRY_FETCHER_ID,
            "fetch_mode": "REAL_PUBLIC_DETAIL_SAME_SITE",
            "fetch_attempted": True,
            "timeout_seconds": self.timeout_seconds,
            "user_agent": self.user_agent,
            "parent_entry_profile_id": profile.profile_id,
            "parent_entry_url": profile.url,
            "list_to_detail_capture_enabled": True,
            "same_site_attachment_link_discovery_enabled": True,
            "cross_site_discovery_enabled": False,
            "unapproved_capture_enabled": False,
            "deep_capture_enabled": False,
            "real_provider_call_executed": False,
            "transport": (response.headers or {}).get("x-ax9s-fetch-transport", "unknown"),
            "primary_transport_error_optional": (response.headers or {}).get("x-ax9s-primary-transport-error"),
            "entry_validation_level": validation_level,
            "failure_taxonomy": failure_taxonomy,
        }
        raw_metadata = {
            "entry_profile_id": profile.profile_id,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "entry_url": profile.url,
            "detail_url": detail_url,
            "final_url": final_url,
            "title": title,
            "same_site_detail_links": [item["url"] for item in same_site_link_items],
            "same_site_detail_link_items": same_site_link_items,
            "same_site_attachment_links": [item["url"] for item in attachment_link_items],
            "same_site_attachment_link_items": attachment_link_items,
            "entry_unavailable_body_patterns_observed": entry_unavailable_body_patterns,
            "controlled_challenge_body_patterns_observed": controlled_challenge_body_patterns,
            "degraded_reasons": degraded_reasons,
        }
        manifest_payload: dict[str, Any] | None = None
        if self.repository is not None and status == "FETCHED":
            manifest = self.repository.save_snapshot(
                content,
                snapshot_id=snapshot_id,
                snapshot_kind=REAL_PUBLIC_DETAIL_SNAPSHOT_KIND,
                content_type=response.content_type or "text/html",
                source_url_optional=detail_url,
                source_family_optional=profile.source_family,
                lineage_refs={
                    "entry_profile_id": profile.profile_id,
                    "parent_entry_url": profile.url,
                    **{
                        str(key): str(value)
                        for key, value in dict(lineage_refs or {}).items()
                        if value not in (None, "")
                    },
                },
                adapter_id=REAL_PUBLIC_ENTRY_FETCHER_ID,
                source_visibility_state="PUBLIC_VISIBLE",
                snapshot_version="real-detail-v1",
                fetched_at=now,
                captured_at=now,
                fetch_mode="REAL_PUBLIC_DETAIL_SAME_SITE",
                fetch_audit=fetch_audit,
                raw_snapshot_metadata=raw_metadata,
                source_health={
                    "state": "HEALTHY",
                    "degraded_reasons": degraded_reasons,
                    "manual_review_required": False,
                },
            )
            manifest_payload = manifest.as_payload()

        return {
            "detail_fetch_id": snapshot_id,
            "status": status,
            "entry_profile_id": profile.profile_id,
            "parent_entry_url": profile.url,
            "detail_url": detail_url,
            "final_url": final_url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "http_status": response.status_code,
            "content_type": response.content_type,
            "byte_size": len(content),
            "sha256": sha256,
            "title": title,
            "same_site_detail_links": [item["url"] for item in same_site_link_items],
            "same_site_detail_link_items": same_site_link_items,
            "same_site_attachment_links": [item["url"] for item in attachment_link_items],
            "same_site_attachment_link_items": attachment_link_items,
            "snapshot_id_optional": snapshot_id if manifest_payload else None,
            "manifest_optional": manifest_payload,
            "degraded_reasons": degraded_reasons,
            "review_required": bool(degraded_reasons) and not controlled_challenge_detected,
            "automated_challenge_resolution_pending": controlled_challenge_detected,
            "automated_challenge_resolution_first": controlled_challenge_detected,
            "resume_requires_human_input": False,
            "fail_closed": bool(degraded_reasons) and not controlled_challenge_detected,
            "no_broad_fallback": True,
            "fetch_audit": fetch_audit,
            "failure_taxonomy": failure_taxonomy,
            "transport": fetch_audit["transport"],
            "controlled_opening_requirements": _controlled_opening_requirements(),
        }

    def _degraded_detail_carrier(
        self,
        profile: RealPublicEntryProfile,
        *,
        detail_url: str,
        now: str,
        reason: str,
        detail: str,
        lineage_refs: Mapping[str, str] | None,
        fetch_attempted: bool,
    ) -> dict[str, Any]:
        return {
            "detail_fetch_id": f"REAL-DETAIL-{profile.profile_id}-DEGRADED",
            "status": "DEGRADED",
            "entry_profile_id": profile.profile_id,
            "parent_entry_url": profile.url,
            "detail_url": detail_url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "snapshot_id_optional": None,
            "degraded_reasons": [reason],
            "failure_detail_optional": detail,
            "review_required": True,
            "fail_closed": True,
            "no_broad_fallback": True,
            "lineage_refs": dict(lineage_refs or {}),
            "fetch_audit": {
                "fetcher_id": REAL_PUBLIC_ENTRY_FETCHER_ID,
                "fetch_mode": "REAL_PUBLIC_DETAIL_SAME_SITE",
                "fetch_attempted": fetch_attempted,
                "fetched_at": now,
                "failure_taxonomy": _fetch_failure_taxonomy(detail),
                "parent_entry_profile_id": profile.profile_id,
                "parent_entry_url": profile.url,
                "list_to_detail_capture_enabled": True,
                "unapproved_capture_enabled": False,
                "deep_capture_enabled": False,
                "real_provider_call_executed": False,
            },
            "controlled_opening_requirements": _controlled_opening_requirements(),
        }

    def _degraded_carrier(
        self,
        profile: RealPublicEntryProfile,
        *,
        now: str,
        reason: str,
        detail: str,
        lineage_refs: Mapping[str, str] | None,
        fetch_attempted: bool,
    ) -> dict[str, Any]:
        return {
            "entry_fetch_id": f"REAL-ENTRY-{profile.profile_id}-DEGRADED",
            "status": "DEGRADED",
            "entry_profile_id": profile.profile_id,
            "entry_url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "browser_verified": True,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
            "snapshot_id_optional": None,
            "degraded_reasons": [reason],
            "failure_detail_optional": detail,
            "review_required": True,
            "fail_closed": True,
            "no_broad_fallback": True,
            "lineage_refs": dict(lineage_refs or {}),
            "fetch_audit": {
                "fetcher_id": REAL_PUBLIC_ENTRY_FETCHER_ID,
                "fetch_mode": REAL_PUBLIC_ENTRY_FETCH_MODE,
                "fetch_attempted": fetch_attempted,
                "fetched_at": now,
                "failure_taxonomy": _fetch_failure_taxonomy(detail),
                "unapproved_capture_enabled": False,
                "deep_capture_enabled": False,
                "real_provider_call_executed": False,
            },
            "controlled_opening_requirements": _controlled_opening_requirements(),
        }

    def _attachment_carrier_from_response(
        self,
        profile: RealPublicAttachmentProfile,
        response: RealPublicFetchResponse,
        *,
        now: str,
        lineage_refs: Mapping[str, str] | None,
        detail_page_url: str | None,
    ) -> dict[str, Any]:
        content = response.content or b""
        content_type = response.content_type or "application/octet-stream"
        filename = (urlsplit(response.final_url or profile.url).path.rsplit("/", 1)[-1] or "attachment.bin")
        sha256 = hashlib.sha256(content).hexdigest()
        degraded_reasons: list[str] = []
        if response.status_code != 200:
            degraded_reasons.append(f"http_status:{response.status_code}")
        if len(content) == 0:
            degraded_reasons.append("attachment_body_empty")
        lowered_content_type = content_type.lower()
        if "html" in lowered_content_type:
            degraded_reasons.append("html_body_not_attachment")
        if not (
            any(token in lowered_content_type for token in ("pdf", "zip", "msword", "officedocument", "excel", "octet-stream"))
            or filename.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"))
        ):
            degraded_reasons.append("unsupported_attachment_content_type")

        status = "DEGRADED" if degraded_reasons else "FETCHED"
        snapshot_id = f"REAL-ATTACH-{profile.profile_id}-{sha256[:12]}"
        fetch_audit = {
            "fetcher_id": REAL_PUBLIC_ENTRY_FETCHER_ID,
            "fetch_mode": REAL_PUBLIC_ATTACHMENT_FETCH_MODE,
            "fetch_attempted": True,
            "timeout_seconds": self.timeout_seconds,
            "user_agent": self.user_agent,
            "browser_verified": True,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
            "unapproved_capture_enabled": False,
            "deep_capture_enabled": False,
            "real_provider_call_executed": False,
            "transport": (response.headers or {}).get("x-ax9s-fetch-transport", "unknown"),
            "primary_transport_error_optional": (response.headers or {}).get("x-ax9s-primary-transport-error"),
        }
        manifest_payload: dict[str, Any] | None = None
        if self.repository is not None and status == "FETCHED":
            manifest = self.repository.save_snapshot(
                content,
                snapshot_id=snapshot_id,
                snapshot_kind=REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND,
                content_type=content_type,
                source_url_optional=profile.url,
                source_family_optional=profile.source_family,
                lineage_refs={
                    "attachment_profile_id": profile.profile_id,
                    **(
                        {"detail_page_url": detail_page_url}
                        if detail_page_url
                        else (
                            {"detail_page_url": profile.detail_page_url_optional}
                            if profile.detail_page_url_optional
                            else {}
                        )
                    ),
                    **{
                        str(key): str(value)
                        for key, value in dict(lineage_refs or {}).items()
                        if value not in (None, "")
                    },
                },
                adapter_id=REAL_PUBLIC_ENTRY_FETCHER_ID,
                source_visibility_state="PUBLIC_VISIBLE",
                snapshot_version="133D-attachment-v1",
                fetched_at=now,
                captured_at=now,
                fetch_mode=REAL_PUBLIC_ATTACHMENT_FETCH_MODE,
                fetch_audit=fetch_audit,
                raw_snapshot_metadata={
                    "attachment_profile_id": profile.profile_id,
                    "attachment_url": profile.url,
                    "attachment_filename": filename,
                    "detail_page_url_optional": detail_page_url or profile.detail_page_url_optional,
                    "site_name": profile.site_name,
                    "source_family": profile.source_family,
                },
                source_health={
                    "state": "HEALTHY",
                    "degraded_reasons": degraded_reasons,
                    "manual_review_required": False,
                },
            )
            manifest_payload = manifest.as_payload()

        return {
            "attachment_fetch_id": snapshot_id,
            "status": status,
            "attachment_profile_id": profile.profile_id,
            "attachment_url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "content_type": content_type,
            "attachment_filename": filename,
            "byte_size": len(content),
            "sha256": sha256,
            "detail_page_url_optional": detail_page_url or profile.detail_page_url_optional,
            "snapshot_id_optional": snapshot_id if manifest_payload else None,
            "manifest_optional": manifest_payload,
            "degraded_reasons": degraded_reasons,
            "review_required": bool(degraded_reasons),
            "fail_closed": bool(degraded_reasons),
            "no_broad_fallback": True,
            "fetch_audit": fetch_audit,
            "transport": fetch_audit["transport"],
            "controlled_opening_requirements": _controlled_opening_requirements(),
        }

    def _degraded_attachment_carrier(
        self,
        profile: RealPublicAttachmentProfile,
        *,
        now: str,
        reason: str,
        detail: str,
        lineage_refs: Mapping[str, str] | None,
        detail_page_url: str | None,
        fetch_attempted: bool,
    ) -> dict[str, Any]:
        return {
            "attachment_fetch_id": f"REAL-ATTACH-{profile.profile_id}-DEGRADED",
            "status": "DEGRADED",
            "attachment_profile_id": profile.profile_id,
            "attachment_url": profile.url,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "detail_page_url_optional": detail_page_url or profile.detail_page_url_optional,
            "snapshot_id_optional": None,
            "degraded_reasons": [reason],
            "failure_detail_optional": detail,
            "review_required": True,
            "fail_closed": True,
            "no_broad_fallback": True,
            "lineage_refs": dict(lineage_refs or {}),
            "fetch_audit": {
                "fetcher_id": REAL_PUBLIC_ENTRY_FETCHER_ID,
                "fetch_mode": REAL_PUBLIC_ATTACHMENT_FETCH_MODE,
                "fetch_attempted": fetch_attempted,
                "fetched_at": now,
                "failure_taxonomy": _fetch_failure_taxonomy(detail),
                "unapproved_capture_enabled": False,
                "deep_capture_enabled": False,
                "real_provider_call_executed": False,
            },
            "controlled_opening_requirements": _controlled_opening_requirements(),
        }


def _is_guangdong_ygp_hash_detail_url(url: str, *, profile_id: str) -> bool:
    if profile_id != "GUANGDONG-YGP-PROVINCE-TRADING-LIST":
        return False
    parsed = urlsplit(str(url or "").strip())
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "ygp.gdzwfw.gov.cn"
        and "/new/jygg/" in parsed.fragment
    )


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fetch_guangdong_ygp_detail_api_response(
    detail_url: str,
    *,
    user_agent: str,
) -> RealPublicFetchResponse:
    route = _parse_guangdong_ygp_detail_route(detail_url)
    node_id = route.get("nodeId") or _fetch_guangdong_ygp_node_id(route, user_agent=user_agent)
    api_params = {
        "nodeId": node_id,
        "version": route["edition"],
        "tradingType": route["tradingType"],
        "noticeId": route["noticeId"],
        "bizCode": route["bizCode"],
        "projectCode": route["projectCode"],
        "siteCode": route["siteCode"],
    }
    data = _guangdong_ygp_signed_get_json(
        "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/trading-notice/new/detail",
        api_params,
        user_agent=user_agent,
    )
    if _as_int(data.get("errcode"), -1) != 0:
        raise RuntimeError(f"guangdong_detail_api_error:{data.get('errmsg') or data.get('errcode')}")
    detail_data = data.get("data")
    if not isinstance(detail_data, Mapping):
        raise RuntimeError("guangdong_detail_api_missing_data")
    html = _guangdong_ygp_detail_html(
        detail_data,
        detail_url=detail_url,
        edition=route["edition"],
        source=str(route.get("source") or ""),
        title_details=str(route.get("titleDetails") or ""),
    )
    return RealPublicFetchResponse(
        url=detail_url,
        status_code=200,
        content=html.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        final_url=detail_url,
        headers={"x-ax9s-fetch-transport": "guangdong_ygp_public_detail_api"},
    )


def _parse_guangdong_ygp_detail_route(detail_url: str) -> dict[str, str]:
    parsed = urlsplit(str(detail_url or "").strip())
    fragment_path, _, fragment_query = parsed.fragment.partition("?")
    parts = [part for part in fragment_path.split("/") if part]
    try:
        new_index = parts.index("new")
        if parts[new_index + 1] != "jygg":
            raise ValueError
        edition = parts[new_index + 2]
        trading_type = parts[new_index + 3]
    except (ValueError, IndexError):
        raise ValueError("guangdong_detail_hash_route_invalid") from None
    query_values = {
        key: values[0]
        for key, values in parse_qs(fragment_query, keep_blank_values=True).items()
        if values
    }
    route = {
        "edition": edition,
        "tradingType": trading_type,
        **query_values,
    }
    missing = [
        key
        for key in ("noticeId", "bizCode", "projectCode", "siteCode")
        if not str(route.get(key) or "").strip()
    ]
    if missing:
        raise ValueError("guangdong_detail_query_missing:" + ",".join(missing))
    return {key: str(value or "") for key, value in route.items()}


def _fetch_guangdong_ygp_node_id(route: Mapping[str, str], *, user_agent: str) -> str:
    params = {
        "siteCode": str(route.get("siteCode") or ""),
        "tradingType": str(route.get("tradingType") or ""),
        "bizCode": str(route.get("bizCode") or ""),
        "projectCode": str(route.get("projectCode") or ""),
    }
    classify = str(route.get("classify") or "")
    if classify:
        params["classify"] = classify
    data = _guangdong_ygp_signed_get_json(
        "https://ygp.gdzwfw.gov.cn/ggzy-portal/center/apis/trading-notice/new/nodeList",
        params,
        user_agent=user_agent,
    )
    rows = list(data.get("data") or [])
    notice_id = str(route.get("noticeId") or "")
    biz_code = str(route.get("bizCode") or "")
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("noticeId") or "") == notice_id and str(row.get("selectedBizCode") or "") == biz_code:
            node_id = str(row.get("nodeId") or "")
            if node_id:
                return node_id
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if _as_int(row.get("dataCount"), 0) > 0:
            node_id = str(row.get("nodeId") or "")
            if node_id:
                return node_id
    raise RuntimeError("guangdong_node_id_not_found")


def _guangdong_ygp_signed_get_json(
    endpoint: str,
    params: Mapping[str, Any],
    *,
    user_agent: str,
) -> dict[str, Any]:
    url = f"{endpoint}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://ygp.gdzwfw.gov.cn/",
            **_guangdong_ygp_signature_headers(params),
        },
    )
    with urlopen(request, timeout=18) as response:
        return json.loads(response.read(1_500_000).decode("utf-8", "ignore"))


def _guangdong_ygp_signature_headers(params: Mapping[str, Any]) -> dict[str, str]:
    nonce = secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:16]
    timestamp_ms = str(int(time.time() * 1000))
    sorted_query = "&".join(sorted(_guangdong_ygp_query_string(params).split("&")))
    signature_basis = f"{nonce}k8tUyS$m{unquote(sorted_query)}{timestamp_ms}"
    return {
        "X-Dgi-Req-App": "ggzy-portal",
        "X-Dgi-Req-Nonce": nonce,
        "X-Dgi-Req-Timestamp": timestamp_ms,
        "X-Dgi-Req-Signature": hashlib.sha256(signature_basis.encode("utf-8")).hexdigest(),
    }


def _guangdong_ygp_query_string(params: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key, value in params.items():
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif value is None:
            text = ""
        else:
            text = str(value)
        parts.append(f"{quote(str(key), safe='')}={quote(text, safe='')}")
    return "&".join(parts)


def _guangdong_ygp_detail_html(
    data: Mapping[str, Any],
    *,
    detail_url: str,
    edition: str,
    source: str,
    title_details: str,
) -> str:
    title = str(data.get("title") or "")
    publish_date = str(data.get("publishDate") or "")
    sections: list[str] = [
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        f"<title>{escape(title)}</title>",
        "</head><body>",
        f"<h1>{escape(title)}</h1>",
        f"<p>发布时间：{escape(publish_date)} 来源：{escape(source)} {escape(title_details)}</p>",
        f"<p>公开来源：<a href=\"{escape(detail_url, quote=True)}\">广东省公共资源交易平台详情页</a></p>",
    ]
    for section in list(data.get("tradingNoticeColumnModelList") or []):
        if not isinstance(section, Mapping):
            continue
        name = str(section.get("name") or "公告内容")
        sections.append(f"<section><h2>{escape(name)}</h2>")
        for row in list(section.get("multiKeyValueTableList") or []):
            if isinstance(row, list):
                for field in row:
                    if isinstance(field, Mapping) and field.get("isShow") is not False:
                        label = str(field.get("aliasName") or field.get("key") or field.get("code") or "")
                        value = str(field.get("value") or "")
                        if label or value:
                            sections.append(f"<p><strong>{escape(label)}</strong> {escape(value)}</p>")
        richtext = str(section.get("richtext") or "")
        if richtext:
            sections.append(f"<div class=\"richtext\">{richtext}</div>")
        table_model = section.get("tradingNoticeTableColumnModel")
        if isinstance(table_model, Mapping):
            for row in list(table_model.get("dataList") or []):
                if isinstance(row, Mapping):
                    cells = " ".join(f"{escape(str(key))}: {escape(str(value))}" for key, value in row.items())
                    sections.append(f"<p>{cells}</p>")
        files = [item for item in list(section.get("noticeFileBOList") or []) if isinstance(item, Mapping)]
        if files:
            sections.append("<ul>")
            for file_item in files:
                file_name = str(file_item.get("fileName") or "附件")
                row_guid = str(file_item.get("rowGuid") or "")
                flow_id = str(file_item.get("flowId") or "")
                if row_guid and flow_id:
                    href = (
                        "https://ygp.gdzwfw.gov.cn/ggzy-portal/base/sys-file/download/"
                        f"{quote(edition, safe='')}/{quote(row_guid, safe='')}?{quote(flow_id, safe='')}"
                    )
                    sections.append(f"<li><a href=\"{escape(href, quote=True)}\">{escape(file_name)}</a></li>")
                else:
                    sections.append(f"<li>{escape(file_name)}</li>")
            sections.append("</ul>")
        sections.append("</section>")
    sections.append("</body></html>")
    return "\n".join(sections)


def _decode_html(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(unescape(match.group(1)).split())


def _discover_same_site_links(text: str, *, base_url: str, host: str) -> list[str]:
    return [
        item["url"]
        for item in _discover_same_site_link_items(text, base_url=base_url, host=host)
    ]


def _discover_same_site_link_items(text: str, *, base_url: str, host: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    expected_host = host.split(":", 1)[0].lower()
    anchor_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    href_pattern = re.compile(r"href=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)
    for match in anchor_pattern.finditer(text):
        href_match = href_pattern.search(match.group("attrs") or "")
        if not href_match:
            continue
        href = unescape(href_match.group(1)).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        parsed = urlsplit(full)
        parsed_host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or parsed_host != expected_host:
            continue
        if not (
            parsed.path.endswith((".html", ".htm", ".shtml", ".jhtml"))
            or parsed.path.endswith((".jspx", ".jsp"))
            or parsed.path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"))
            or "/information/" in parsed.path
            or "/cggg/" in parsed.path
            or "/deal/" in parsed.path
            or "/jyxx" in parsed.path.lower()
            or "/jyxxgk" in parsed.path.lower()
            or "/base/sys-file/download/" in parsed.path.lower()
            or "querycontent" in parsed.path.lower()
        ):
            continue
        clean = full.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean)
            link_text = _clean_anchor_text(match.group("body") or "")
            items.append({"url": clean, "text": link_text})
    items.sort(key=_same_site_link_item_priority, reverse=True)
    return items[:50]


def _same_site_link_item_priority(item: Mapping[str, str]) -> int:
    url = str(item.get("url") or "")
    text = _clean_anchor_text(str(item.get("text") or ""))
    lowered = f"{url} {text}".lower()
    path = urlsplit(url).path.lower()
    score = 0
    if "{{" in lowered or "}}" in lowered or "%7b%7b" in lowered:
        score -= 500
    if re.search(r"/20[0-9]{6}/", path) or re.search(r"/20[0-9]{4}/", path):
        score += 180
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path):
        score += 120
    if any(token in text for token in ("公告", "公示", "招标", "中标", "成交", "评标", "结果", "澄清", "答疑")):
        score += 70
    if any(token in text for token in ("工程", "项目", "施工", "监理", "设计", "改造", "建设", "道路", "水利", "公路")):
        score += 60
    if len(text) >= 18:
        score += 20
    if text.replace(" ", "") in {
        "首页",
        "通知公告",
        "交易公开",
        "交易信息",
        "主体信息",
        "信用信息",
        "政策文件",
        "服务指南",
        "关于我们",
        "查看更多",
        "更多",
        "项目注册",
        "房建市政",
        "水利工程",
        "交通工程",
    }:
        score -= 200
    if path.endswith(("index.html", "list.html", "about.html", "transactioninfo.html")):
        score -= 100
    return score


def _discover_same_site_attachment_link_items(text: str, *, base_url: str, host: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _discover_same_site_link_items(text, base_url=base_url, host=host):
        url = item["url"]
        parsed = urlsplit(url)
        path = parsed.path.lower()
        link_text = item.get("text", "")
        if not (
            path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"))
            or any(token in link_text for token in ("附件", "下载", "招标文件", "采购文件", "结果文件"))
            or re.search(r"\.(pdf|docx?|xlsx?|zip)$", link_text.strip(), flags=re.IGNORECASE)
        ):
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"url": url, "text": link_text})
        if len(items) >= 10:
            break
    return items


def _clean_anchor_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(without_tags).split())


def _parse_curl_headers(header_text: str) -> dict[str, str]:
    blocks = [
        block
        for block in header_text.replace("\r\n", "\n").split("\n\n")
        if block.strip()
    ]
    if not blocks:
        return {}
    headers: dict[str, str] = {}
    for line in blocks[-1].splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def _should_try_fetch_fallback(exc: Exception) -> bool:
    detail = f"{type(exc).__name__}:{exc}".lower()
    return any(
        token in detail
        for token in (
            "ssl",
            "tls",
            "bad_ecpoint",
            "handshake",
            "certificate",
            "eof occurred in violation",
            "timed out",
            "timeout",
        )
    )


def _fetch_failure_taxonomy(detail: str) -> dict[str, Any]:
    lowered = detail.lower()
    if any(token in lowered for token in ("ssl", "tls", "bad_ecpoint", "handshake", "certificate")):
        failure_class = "TLS_HANDSHAKE_FAILED"
    elif "timed out" in lowered or "timeout" in lowered:
        failure_class = "TIMEOUT"
    elif "412" in lowered:
        failure_class = "UPSTREAM_PRECONDITION_FAILED"
    elif "521" in lowered:
        failure_class = "UPSTREAM_WEB_SERVER_DOWN_OR_BLOCKED"
    else:
        failure_class = "FETCH_FAILED"
    return {
        "failure_class": failure_class,
        "failure_detail": detail,
        "retryable": failure_class in {"TLS_HANDSHAKE_FAILED", "TIMEOUT", "FETCH_FAILED"},
        "fail_closed": True,
        "no_broad_fallback": True,
    }


def _response_failure_taxonomy(
    degraded_reasons: list[str],
    *,
    http_status: int,
    validation_level: str,
) -> dict[str, Any] | None:
    if not degraded_reasons:
        return None
    if any(reason.startswith("controlled_challenge_body_pattern") for reason in degraded_reasons):
        failure_class = "CONTROLLED_CHALLENGE_BODY_PATTERN"
    elif any(reason.startswith("http_status:412") for reason in degraded_reasons):
        failure_class = "UPSTREAM_PRECONDITION_FAILED"
    elif any(reason.startswith("http_status:521") for reason in degraded_reasons):
        failure_class = "UPSTREAM_WEB_SERVER_DOWN_OR_BLOCKED"
    elif any(reason.startswith("http_status:") for reason in degraded_reasons):
        failure_class = "UPSTREAM_HTTP_STATUS_NOT_OK"
    elif "visible_entry_markers_missing" in degraded_reasons and validation_level == "FAIL_CLOSED_INSUFFICIENT_VISIBLE_ENTRY":
        failure_class = "PUBLIC_ENTRY_MARKERS_MISSING_OR_SPA_SHELL"
    elif any(reason.startswith("entry_unavailable_body_pattern") for reason in degraded_reasons):
        failure_class = "ENTRY_UNAVAILABLE_BODY_PATTERN"
    elif "title_mismatch" in degraded_reasons:
        failure_class = "TITLE_MISMATCH"
    else:
        failure_class = "PUBLIC_ENTRY_DEGRADED"
    return {
        "failure_class": failure_class,
        "http_status": http_status,
        "degraded_reasons": degraded_reasons,
        "entry_validation_level": validation_level,
        "retryable": failure_class in {"UPSTREAM_HTTP_STATUS_NOT_OK", "PUBLIC_ENTRY_DEGRADED"},
        "manual_review_required": failure_class != "CONTROLLED_CHALLENGE_BODY_PATTERN",
        "automated_challenge_resolution_first": failure_class == "CONTROLLED_CHALLENGE_BODY_PATTERN",
        "resume_requires_human_input": False,
        "fail_closed": failure_class != "CONTROLLED_CHALLENGE_BODY_PATTERN",
        "no_broad_fallback": True,
    }


def _controlled_opening_requirements() -> dict[str, bool]:
    return {
        "unapproved_live_capture_used": False,
        "deep_capture_used": False,
        "real_provider_call_executed": False,
        "external_side_effect_enabled": False,
    }


__all__ = [
    "DEGRADED_ENTRY_PROFILE_IDS_AFTER_136",
    "PUBLIC_ATTACHMENT_PROFILE_IDS",
    "REAL_PUBLIC_ATTACHMENT_FETCH_MODE",
    "REAL_PUBLIC_ATTACHMENT_PROFILES",
    "REAL_PUBLIC_ATTACHMENT_PROFILE_BY_ID",
    "REAL_PUBLIC_ATTACHMENT_PROFILE_BY_URL",
    "REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND",
    "REAL_PUBLIC_DETAIL_SNAPSHOT_KIND",
    "REAL_PUBLIC_ENTRY_FETCHER_ID",
    "REAL_PUBLIC_ENTRY_FETCH_MODE",
    "REAL_PUBLIC_ENTRY_PROFILES",
    "REAL_PUBLIC_ENTRY_PROFILE_BY_ID",
    "REAL_PUBLIC_ENTRY_PROFILE_BY_URL",
    "CurlCommandRealPublicFetchTransport",
    "HybridRealPublicFetchTransport",
    "NATIONAL_VERIFICATION_ENTRY_PROFILE_IDS",
    "REPRESENTATIVE_LOCAL_PLATFORM_ENTRY_PROFILE_IDS",
    "RealPublicAttachmentProfile",
    "RealPublicEntryFetcher",
    "RealPublicEntryProfile",
    "RealPublicFetchResponse",
    "RealPublicFetchTransport",
    "RealPublicUrlBoundaryError",
    "UrlLibRealPublicFetchTransport",
]
