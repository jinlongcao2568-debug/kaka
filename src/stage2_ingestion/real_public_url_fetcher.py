from __future__ import annotations

import hashlib
import json
import re
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
    "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
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
        profile_id="GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/trade_purchasetoplen6.html",
        site_name="广州交易集团有限公司（广州公共资源交易中心）",
        source_family="local_public_resource_trading_center",
        expected_title_contains="广州交易集团有限公司",
        visible_entry_markers=("建设工程", "项目信息", "中标候选人公示", "工程类型"),
        sample_detail_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/587b9f32-8823-4577-97ff-e76e9c92a2d3.html",
        browser_verified_at="2026-05-03T14:35:00+08:00",
        browser_verified_evidence=(
            "浏览器打开广州交易集团建设工程项目信息页，列表接口返回 jsgcggfl=03 的中标候选人公示；"
            "详情页 HTML 直接包含候选人、拟派项目负责人、项目负责人资质和相关附件。"
        ),
        lightweight_public_entry_markers=("广州交易集团有限公司", "广州公共资源交易中心"),
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
    "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
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

_SUPPORTED_ATTACHMENT_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
)
_SUPPORTED_HTML_ATTACHMENT_EXTENSIONS = (".html", ".htm")
_SUPPORTED_ATTACHMENT_CONTENT_TYPE_TOKENS = (
    "pdf",
    "zip",
    "msword",
    "officedocument",
    "excel",
    "spreadsheet",
    "rar",
    "octet-stream",
)
_DOWNLOAD_ENDPOINT_TOKENS = (
    "/download",
    "/downfile",
    "/filedownload",
    "/attach/",
    "/attachment",
    "/sys-file/download/",
    "/epointwebbuilder/pages/webbuildermis/attach/downloadztbattach",
    "downloadztbattach",
)
_ATTACHMENT_QUERY_KEYS = {
    "filename",
    "fileName",
    "file",
    "filePath",
    "fileUrl",
    "attachGuid",
    "attachmentId",
    "flowId",
    "rowGuid",
    "docId",
}
_NON_ATTACHMENT_LINK_TEXTS = {
    "首页",
    "通知公告",
    "交易服务",
    "交易公开",
    "交易信息",
    "项目信息",
    "建设工程",
    "主体信息",
    "信用信息",
    "政策文件",
    "服务指南",
    "常用服务",
    "关于我们",
    "查看更多",
    "更多",
    "项目注册",
    "房建市政",
    "水利工程",
    "交通工程",
    "打印",
    "关闭",
}

_NON_ATTACHMENT_PATH_TOKENS = (
    "/login",
    "/onlinelettersubmit",
    "/message",
    "/guestbook",
    "/help",
    "/fwtj/",
    "/bszn/",
    "/rss.html",
    "/about.html",
    "websitestatis",
    "/002001006/",
)

_HTML_ATTACHMENT_LINK_HINTS = (
    "附件",
    "下载",
    "招标文件",
    "采购文件",
    "资格要求",
    "澄清",
    "答疑",
    "补遗",
    "清单",
)
_NORMALIZED_ATTACHMENT_BLOCKER_BY_CLASS = {
    "CAPTCHA_MANUAL_REQUIRED": "attachment_captcha_required",
    "SESSION_OR_LOGIN_REQUIRED": "attachment_login_required",
    "REFERER_OR_HOTLINK_REQUIRED": "attachment_hotlink_or_referer_required",
    "ATTACHMENT_INTERFACE_ERROR": "attachment_url_expired",
    "UNKNOWN_HTML_ATTACHMENT_RESPONSE": "attachment_unknown_html_response",
}


def _attachment_html_blocker_diagnostics(
    content: bytes,
    content_type: str,
    *,
    allow_plain_html_attachment: bool = False,
) -> dict[str, Any]:
    lowered_content_type = (content_type or "").lower()
    body = ""
    if "html" in lowered_content_type or content.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        body = content.decode("utf-8", errors="ignore")
    if not body:
        return {
            "attachment_blocker_class": "",
            "attachment_blocker_reason": "",
            "attachment_failure_taxonomy": [],
            "attachment_resolution_route": "",
            "attachment_browser_replay_steps": [],
        }

    lowered_body = body.lower()
    if any(
        marker.lower() in lowered_body
        for marker in (
            "验证码",
            "captcha",
            "人机验证",
            "安全验证",
            "滑块",
            "拖动滑块",
            "请完成验证",
            "geetest",
            "极验",
            "waf",
            "web应用防火墙",
            "访问环境异常",
            "访问频率过高",
            "verificationcode",
            "verificationguid",
            "pageverify",
            "validateverificationcode",
            "验证码验证失败",
        )
    ):
        blocker_class = "CAPTCHA_MANUAL_REQUIRED"
        blocker_reason = "attachment_html_blocker:captcha_or_manual_verification"
        route = "open_detail_page_then_manual_challenge_download_and_snapshot"
    elif any(marker.lower() in lowered_body for marker in ("请先登录", "请登录", "用户登录", "登录")):
        blocker_class = "SESSION_OR_LOGIN_REQUIRED"
        blocker_reason = "attachment_html_blocker:login_or_session_required"
        route = "open_detail_page_with_valid_public_session_then_retry_attachment"
    elif any(marker.lower() in lowered_body for marker in ("referer", "防盗链", "非法访问", "访问来源", "来源错误")):
        blocker_class = "REFERER_OR_HOTLINK_REQUIRED"
        blocker_reason = "attachment_html_blocker:referer_or_hotlink_required"
        route = "open_detail_page_first_then_click_attachment_with_same_site_referer"
    elif any(
        marker.lower() in lowered_body
        for marker in (
            "错误",
            "异常",
            "不存在",
            "404",
            "参数错误",
            "下载失败",
            "签名错误",
            "签名验证失败",
            "非法请求",
            "请求参数非法",
            "token",
            "x-dgi-req",
        )
    ):
        blocker_class = "ATTACHMENT_INTERFACE_ERROR"
        blocker_reason = "attachment_html_blocker:interface_error_or_expired_link"
        route = "recapture_detail_page_and_refresh_attachment_link"
    elif allow_plain_html_attachment:
        return {
            "attachment_blocker_class": "",
            "attachment_blocker_reason": "",
            "attachment_failure_taxonomy": [],
            "attachment_resolution_route": "",
            "attachment_browser_replay_steps": [],
        }
    else:
        blocker_class = "UNKNOWN_HTML_ATTACHMENT_RESPONSE"
        blocker_reason = "attachment_html_blocker:unknown_html"
        route = "browser_replay_required_before_manual_review"

    return {
        "attachment_blocker_class": blocker_class,
        "attachment_blocker_reason": blocker_reason,
        "attachment_failure_taxonomy": [
            _NORMALIZED_ATTACHMENT_BLOCKER_BY_CLASS.get(blocker_class, "attachment_html_blocker")
        ],
        "attachment_resolution_route": route,
        "attachment_browser_replay_steps": [
            "open_detail_page_url_optional",
            "click_same_site_attachment_link",
            "save_downloaded_file_if_content_type_is_pdf_zip_or_office",
            "record_captcha_or_session_blocker_without_bypassing_third_party_controls",
        ],
    }


def _empty_attachment_blocker_diagnostics() -> dict[str, Any]:
    return {
        "attachment_blocker_class": "",
        "attachment_blocker_reason": "",
        "attachment_failure_taxonomy": [],
        "attachment_resolution_route": "",
        "attachment_browser_replay_steps": [],
    }


def _attachment_filename_from_response(
    profile: "RealPublicAttachmentProfile",
    response: "RealPublicFetchResponse",
) -> str:
    headers = {str(key).lower(): str(value) for key, value in dict(response.headers or {}).items()}
    disposition = headers.get("content-disposition", "")
    filename_match = re.search(
        r"filename\*\s*=\s*[^']*''(?P<name>[^;]+)|filename\s*=\s*\"?(?P<plain>[^\";]+)",
        disposition,
        flags=re.IGNORECASE,
    )
    if filename_match:
        filename = unquote(filename_match.group("name") or filename_match.group("plain") or "").strip()
        if filename:
            return filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    parsed = urlsplit(response.final_url or profile.url)
    path_filename = unquote(parsed.path.rsplit("/", 1)[-1] or "").strip()
    if path_filename.lower().endswith(_SUPPORTED_ATTACHMENT_EXTENSIONS):
        return path_filename
    query = parse_qs(parsed.query)
    for key in ("filename", "fileName", "file", "name"):
        values = query.get(key) or query.get(key.lower()) or []
        if values:
            filename = unquote(str(values[0] or "")).strip()
            if filename:
                return filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if path_filename:
        return path_filename
    return "attachment.bin"


def _attachment_url_has_supported_signal(url: str, *, link_text: str = "") -> bool:
    parsed = urlsplit(str(url or "").strip())
    path = unquote(parsed.path or "").lower()
    query = parse_qs(parsed.query)
    joined_query = " ".join(
        unquote(str(value or "")).lower()
        for values in query.values()
        for value in values
    )
    text = _clean_anchor_text(link_text).lower()
    if path.endswith(_SUPPORTED_ATTACHMENT_EXTENSIONS):
        return True
    if path.endswith(_SUPPORTED_HTML_ATTACHMENT_EXTENSIONS):
        return _html_attachment_link_is_strong(url, link_text=link_text)
    if re.search(r"\.(pdf|docx?|xlsx?|zip|rar)(?:$|[?#&\s])", f"{path} {joined_query} {text}", flags=re.IGNORECASE):
        return True
    if any(token in path for token in _DOWNLOAD_ENDPOINT_TOKENS):
        return True
    if any(key in query for key in _ATTACHMENT_QUERY_KEYS):
        return True
    return False


def _html_attachment_link_is_strong(url: str, *, link_text: str = "") -> bool:
    parsed = urlsplit(str(url or "").strip())
    path = unquote(parsed.path or "").lower()
    path_name = path.rsplit("/", 1)[-1] if path else ""
    text = _clean_anchor_text(link_text).lower()
    combined = f"{path_name} {text}"
    if not path_name.endswith(_SUPPORTED_HTML_ATTACHMENT_EXTENSIONS):
        return False
    if "/files/" in path or "/attachment/" in path or "/attach/" in path:
        return True
    if re.search(r"\.(pdf|docx?|xlsx?|zip|rar)$", text, flags=re.IGNORECASE):
        return True
    return any(hint.lower() in combined for hint in _HTML_ATTACHMENT_LINK_HINTS)


def _attachment_url_has_resumable_download_signal(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    path = unquote(parsed.path or "").lower()
    query = parse_qs(parsed.query)
    if any(token in path for token in _DOWNLOAD_ENDPOINT_TOKENS):
        return True
    if path.endswith(_SUPPORTED_ATTACHMENT_EXTENSIONS):
        return True
    if any(key in query for key in _ATTACHMENT_QUERY_KEYS):
        return True
    if re.search(r"\.(pdf|docx?|xlsx?|zip|rar)(?:$|[?#&\s])", unquote(parsed.query or ""), flags=re.IGNORECASE):
        return True
    return False


def _attachment_content_is_supported(
    *,
    content: bytes,
    content_type: str,
    filename: str,
    allow_plain_html_attachment: bool,
) -> bool:
    lowered_content_type = str(content_type or "").lower()
    filename_lower = str(filename or "").lower()
    stripped = content.lstrip()[:16].lower()
    if filename_lower.endswith((*_SUPPORTED_ATTACHMENT_EXTENSIONS, *_SUPPORTED_HTML_ATTACHMENT_EXTENSIONS)):
        return True
    if any(token in lowered_content_type for token in _SUPPORTED_ATTACHMENT_CONTENT_TYPE_TOKENS):
        return True
    if content.startswith(b"%PDF") or content.startswith(b"PK\x03\x04") or content.startswith(b"\xd0\xcf\x11\xe0"):
        return True
    if stripped.startswith((b"<html", b"<!doctype html")) and allow_plain_html_attachment:
        return True
    return False


def _normalized_attachment_failure_taxonomy(
    *,
    degraded_reasons: list[str],
    attachment_blocker: Mapping[str, Any],
) -> list[str]:
    taxonomy: list[str] = []
    taxonomy.extend(
        str(item)
        for item in list(attachment_blocker.get("attachment_failure_taxonomy") or [])
        if str(item or "").strip()
    )
    for reason in degraded_reasons:
        value = str(reason or "")
        if value == "attachment_body_empty":
            taxonomy.append("attachment_empty_body")
        elif value == "unsupported_attachment_content_type":
            taxonomy.append("attachment_unsupported_content_type")
        elif value == "attachment_snapshot_readback_missing":
            taxonomy.append("attachment_snapshot_readback_missing")
        elif value.startswith("http_status:"):
            taxonomy.append(value)
        elif value.startswith("attachment_html_blocker:interface_error_or_expired_link"):
            taxonomy.append("attachment_url_expired")
        elif value.startswith("attachment_html_blocker:login_or_session_required"):
            taxonomy.append("attachment_login_required")
        elif value.startswith("attachment_html_blocker:referer_or_hotlink_required"):
            taxonomy.append("attachment_hotlink_or_referer_required")
        elif value.startswith("attachment_html_blocker:captcha_or_manual_verification"):
            taxonomy.append("attachment_captcha_required")
    return list(dict.fromkeys(taxonomy))


def _attachment_challenge_family(profile: "RealPublicAttachmentProfile") -> str:
    url = str(profile.url or "")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    profile_id = str(profile.profile_id or "")
    if "downloadztbattach" in path or "GUANGZHOU-YWTB-CONSTRUCTION-LIST" in profile_id:
        return "EPOINT_PAGE_VERIFY_OR_JIGSAW"
    if "hbbidcloud.cn" in host:
        return "HUBEI_BIDCLOUD_BROWSER_SESSION"
    if "ggzyjy.sc.gov.cn" in host:
        return "SICHUAN_GGZY_BROWSER_SESSION"
    if "ggzy.gov.cn" in host:
        return "NATIONAL_GGZY_BROWSER_SESSION"
    return "GENERIC_ATTACHMENT_CHALLENGE"


def _attachment_platform_resolution_hint(profile: "RealPublicAttachmentProfile") -> dict[str, Any]:
    family = _attachment_challenge_family(profile)
    if family == "EPOINT_PAGE_VERIFY_OR_JIGSAW":
        return {
            "resolver_route": "epoint_page_verify_or_blockpuzzle",
            "preferred_steps": [
                "open_detail_page_url_optional",
                "click_same_site_attachment_link",
                "solve_epoint_blockpuzzle_or_page_verify",
                "retry_verified_download_action",
            ],
        }
    if family == "HUBEI_BIDCLOUD_BROWSER_SESSION":
        return {
            "resolver_route": "hubei_bidcloud_browser_session",
            "preferred_steps": [
                "open_detail_page_url_optional",
                "reuse_browser_session_cookies",
                "retry_attachment_with_same_site_referer",
                "record_captcha_or_slider_diagnostics_if_still_blocked",
            ],
        }
    if family == "SICHUAN_GGZY_BROWSER_SESSION":
        return {
            "resolver_route": "sichuan_ggzy_browser_session",
            "preferred_steps": [
                "open_detail_page_url_optional",
                "reuse_browser_session_cookies",
                "retry_attachment_with_same_site_referer",
                "record_interface_error_if_link_expired",
            ],
        }
    if family == "NATIONAL_GGZY_BROWSER_SESSION":
        return {
            "resolver_route": "national_ggzy_browser_session",
            "preferred_steps": [
                "open_detail_page_url_optional",
                "reuse_browser_session_cookies",
                "retry_attachment_with_same_site_referer",
            ],
        }
    return {
        "resolver_route": "generic_browser_session_retry",
        "preferred_steps": [
            "open_detail_page_url_optional",
            "click_same_site_attachment_link",
            "retry_attachment_with_same_site_referer",
        ],
    }


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


class RealPublicAttachmentChallengeResolver(Protocol):
    def resolve_candidate_detail(
        self,
        request: Mapping[str, Any],
    ) -> RealPublicFetchResponse | Mapping[str, Any]:
        ...

    def resolve_same_site_attachment(
        self,
        request: Mapping[str, Any],
    ) -> RealPublicFetchResponse | Mapping[str, Any]:
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


def _candidate_detail_url_variants(url: str, *, profile_id: str) -> list[str]:
    cleaned = str(url or "").strip()
    if not cleaned:
        return []
    variants: list[str] = []
    if profile_id == "SHANDONG-GGZY-JYXXGK-LIST" or _is_shandong_detail_url(cleaned):
        parsed = urlsplit(cleaned)
        host = parsed.hostname or parsed.netloc.split(":", 1)[0]
        if host:
            path_query = parsed.path or "/"
            if parsed.query:
                path_query = f"{path_query}?{parsed.query}"
            variants.append(f"https://{host}{path_query}")
            variants.append(f"http://{host}{path_query}")
    variants.append(cleaned)
    return list(dict.fromkeys(variants))


def _is_shandong_detail_url(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    return "shandong.gov.cn" in parsed.netloc.lower()


def _should_retry_candidate_detail_variant(carrier: Mapping[str, Any]) -> bool:
    if carrier.get("status") == "FETCHED":
        return False
    reasons = [str(item) for item in list(carrier.get("degraded_reasons") or [])]
    return any(
        reason.startswith("http_status:502")
        or reason in {"detail_body_too_small", "detail_title_missing"}
        or reason.startswith("fetch_failed")
        for reason in reasons
    )


class RealPublicEntryFetcher:
    def __init__(
        self,
        *,
        transport: RealPublicFetchTransport | None = None,
        repository: ObjectStorageRepository | None = None,
        timeout_seconds: float = 20.0,
        user_agent: str = REAL_PUBLIC_ENTRY_USER_AGENT,
        attachment_challenge_resolver: RealPublicAttachmentChallengeResolver | None = None,
        automated_challenge_resolution_enabled: bool = False,
    ) -> None:
        self.transport = transport or HybridRealPublicFetchTransport()
        self.repository = repository
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.attachment_challenge_resolver = attachment_challenge_resolver
        self.automated_challenge_resolution_enabled = automated_challenge_resolution_enabled

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
        now = utc_now_iso()
        attempts: list[dict[str, Any]] = []
        last_carrier: dict[str, Any] | None = None
        variants = _candidate_detail_url_variants(str(url).strip(), profile_id=profile.profile_id)
        for index, detail_url in enumerate(variants):
            try:
                response = self.transport.fetch(
                    detail_url,
                    timeout_seconds=self.timeout_seconds,
                    user_agent=self.user_agent,
                )
            except Exception as exc:  # pragma: no cover - concrete network exceptions vary
                carrier = self._degraded_detail_carrier(
                    profile,
                    detail_url=detail_url,
                    now=now,
                    reason="fetch_failed",
                    detail=str(exc),
                    lineage_refs=lineage_refs,
                    fetch_attempted=True,
                )
            else:
                carrier = self._detail_carrier_from_response(
                    profile,
                    detail_url=detail_url,
                    response=response,
                    now=now,
                    lineage_refs=lineage_refs,
                )
            attempts.append(
                {
                    "detail_url": detail_url,
                    "status": carrier.get("status"),
                    "http_status": carrier.get("http_status"),
                    "degraded_reasons": list(carrier.get("degraded_reasons") or []),
                }
            )
            if carrier.get("status") == "FETCHED":
                if len(attempts) > 1 or variants[0] != str(url).strip():
                    carrier["detail_url_retry_audit"] = {
                        "attempts": attempts,
                        "variant_strategy": "shandong_https_without_explicit_80_first"
                        if _is_shandong_detail_url(str(url))
                        else "candidate_detail_variants",
                    }
                return carrier
            if self._should_attempt_detail_challenge_resolution(profile, carrier):
                resolved = self._resolve_candidate_detail_after_challenge(
                    profile=profile,
                    first_carrier=carrier,
                    detail_url=detail_url,
                    lineage_refs=lineage_refs,
                )
                if len(attempts) > 1 or variants[0] != str(url).strip():
                    resolved["detail_url_retry_audit"] = {
                        "attempts": attempts,
                        "variant_strategy": "shandong_https_without_explicit_80_first"
                        if _is_shandong_detail_url(str(url))
                        else "candidate_detail_variants",
                    }
                return resolved
            last_carrier = carrier
            if index + 1 >= len(variants) or not _should_retry_candidate_detail_variant(carrier):
                break

        if last_carrier is not None:
            if len(attempts) > 1 or variants[0] != str(url).strip():
                last_carrier["detail_url_retry_audit"] = {
                    "attempts": attempts,
                    "variant_strategy": "shandong_https_without_explicit_80_first"
                    if _is_shandong_detail_url(str(url))
                    else "candidate_detail_variants",
                }
            return last_carrier

        detail_url = str(url).strip()
        return self._degraded_detail_carrier(
                profile,
                detail_url=detail_url,
                now=now,
                reason="missing_detail_url",
                detail="candidate detail url is empty",
                lineage_refs=lineage_refs,
                fetch_attempted=True,
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

        carrier = self._attachment_carrier_from_response(
            profile,
            response,
            now=now,
            lineage_refs=lineage_refs,
            detail_page_url=detail_page_url,
        )
        if self._should_attempt_attachment_challenge_resolution(profile, carrier):
            return self._resolve_same_site_attachment_after_challenge(
                profile=profile,
                first_carrier=carrier,
                parent_profile_id=parent_profile_id,
                lineage_refs=lineage_refs,
                detail_page_url=detail_page_url,
            )
        return carrier

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
        guangzhou_ywtb_file_download = (
            parent.profile_id == "GUANGZHOU-YWTB-CONSTRUCTION-LIST"
            and "/epointwebbuilder/pages/webbuildermis/attach/downloadztbattach" in path
        )
        if (
            not guangzhou_ywtb_file_download
            and not _attachment_url_has_supported_signal(attachment_url)
        ):
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

    def _should_attempt_attachment_challenge_resolution(
        self,
        profile: RealPublicAttachmentProfile,
        carrier: Mapping[str, Any],
    ) -> bool:
        if not self.automated_challenge_resolution_enabled or self.attachment_challenge_resolver is None:
            return False
        blocker_class = str(carrier.get("attachment_blocker_class") or "")
        blocker_reason = str(carrier.get("attachment_blocker_reason") or "")
        degraded_reasons = [str(item or "") for item in list(carrier.get("degraded_reasons") or [])]
        challenge_family = _attachment_challenge_family(profile)
        resumable_download = _attachment_url_has_resumable_download_signal(profile.url)
        if blocker_class == "ATTACHMENT_INTERFACE_ERROR" and not resumable_download:
            return False
        return (
            blocker_class
            in {
                "CAPTCHA_MANUAL_REQUIRED",
                "SESSION_OR_LOGIN_REQUIRED",
                "REFERER_OR_HOTLINK_REQUIRED",
                "UNKNOWN_HTML_ATTACHMENT_RESPONSE",
                "ATTACHMENT_INTERFACE_ERROR",
            }
            or "captcha" in blocker_reason.lower()
            or "manual_verification" in blocker_reason.lower()
            or (
                challenge_family != "GENERIC_ATTACHMENT_CHALLENGE"
                and any(
                    reason.startswith(("http_status:400", "http_status:401", "http_status:403", "http_status:404"))
                    or reason == "unsupported_attachment_content_type"
                    for reason in degraded_reasons
                )
            )
        )

    def _should_attempt_detail_challenge_resolution(
        self,
        profile: RealPublicEntryProfile,
        carrier: Mapping[str, Any],
    ) -> bool:
        if not self.automated_challenge_resolution_enabled or self.attachment_challenge_resolver is None:
            return False
        if not hasattr(self.attachment_challenge_resolver, "resolve_candidate_detail"):
            return False
        if str(carrier.get("status") or "") != "AUTOMATED_CHALLENGE_RESOLUTION_PENDING":
            return False
        if profile.profile_id != "JIANGSU-GGZY-HOME":
            return False
        reasons = [str(item or "") for item in list(carrier.get("degraded_reasons") or [])]
        return any(reason.startswith("controlled_challenge_body_pattern") for reason in reasons)

    def _resolve_candidate_detail_after_challenge(
        self,
        *,
        profile: RealPublicEntryProfile,
        first_carrier: Mapping[str, Any],
        detail_url: str,
        lineage_refs: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        context_id = hashlib.sha1(
            f"{profile.profile_id}|{detail_url}".encode("utf-8")
        ).hexdigest()[:16]
        request = {
            "challenge_resume_context_id": context_id,
            "detail_url": detail_url,
            "entry_profile_id": profile.profile_id,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "challenge_family": "EPOINT_DETAIL_SESSION_OR_LOGIN",
            "first_attempt_status": first_carrier.get("status"),
            "first_attempt_degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
            "same_capture_plan_resume_required": True,
            "allowed_resolution_capabilities": [
                "browser_fingerprint_profile_reuse",
                "cookie_reuse",
                "same_session_capture_resume",
                "hidden_interface_call_if_public_and_audited",
            ],
        }
        try:
            resolver = self.attachment_challenge_resolver
            result = resolver.resolve_candidate_detail(request)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - resolver implementations vary
            failed = dict(first_carrier)
            failed["automated_challenge_resolution_attempted"] = True
            failed["automated_challenge_resolution_state"] = "FAILED_CLOSED_RESOLVER_ERROR"
            failed["challenge_resume_audit"] = {
                "challenge_resume_context_id": context_id,
                "resolver_error": type(exc).__name__,
                "resolver_error_detail": str(exc),
                "resume_from_same_capture_plan": True,
                "resume_requires_human_input": False,
            }
            failed["failure_taxonomy"] = {
                "failure_class": "CONTROLLED_CHALLENGE_RESOLVER_ERROR",
                "degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
                "resolver_error": type(exc).__name__,
                "fail_closed": True,
            }
            return failed

        response, resolution_metadata = _coerce_challenge_resolution_result(result, detail_url)
        if response is None:
            failed = dict(first_carrier)
            failed["automated_challenge_resolution_attempted"] = True
            failed["automated_challenge_resolution_state"] = "FAILED_CLOSED_NO_RESPONSE"
            failed["challenge_resume_audit"] = {
                "challenge_resume_context_id": context_id,
                "resolution_metadata": resolution_metadata,
                "resume_from_same_capture_plan": True,
                "resume_requires_human_input": False,
            }
            return failed

        now = utc_now_iso()
        audit = {
            "challenge_resume_context_id": context_id,
            "resolution_method": resolution_metadata.get("resolution_method") or "automated_detail_challenge_resolver",
            "resolution_capabilities_used": list(resolution_metadata.get("resolution_capabilities_used") or []),
            "resume_from_same_capture_plan": True,
            "resume_requires_human_input": False,
            "first_attempt_status": first_carrier.get("status"),
            "first_attempt_degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
            "resolver_metadata": {
                key: value
                for key, value in resolution_metadata.items()
                if key not in {"content", "response"}
            },
        }
        carrier = self._detail_carrier_from_response(
            profile,
            detail_url=detail_url,
            response=response,
            now=now,
            lineage_refs=lineage_refs,
        )
        carrier["automated_challenge_resolution_attempted"] = True
        carrier["automated_challenge_resolution_state"] = (
            "RESOLVED_AND_SNAPSHOT_CAPTURED"
            if carrier.get("status") == "FETCHED"
            else "RESOLVED_RESPONSE_STILL_DEGRADED"
        )
        carrier["challenge_resume_audit"] = audit
        carrier["first_attempt_carrier"] = {
            "status": first_carrier.get("status"),
            "degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
        }
        return carrier

    def _resolve_same_site_attachment_after_challenge(
        self,
        *,
        profile: RealPublicAttachmentProfile,
        first_carrier: Mapping[str, Any],
        parent_profile_id: str,
        lineage_refs: Mapping[str, str] | None,
        detail_page_url: str | None,
    ) -> dict[str, Any]:
        context_id = hashlib.sha1(
            f"{profile.profile_id}|{profile.url}|{detail_page_url or ''}".encode("utf-8")
        ).hexdigest()[:16]
        request = {
            "challenge_resume_context_id": context_id,
            "attachment_url": profile.url,
            "attachment_profile_id": profile.profile_id,
            "parent_profile_id": parent_profile_id,
            "detail_page_url": detail_page_url or profile.detail_page_url_optional,
            "site_name": profile.site_name,
            "source_family": profile.source_family,
            "challenge_family": _attachment_challenge_family(profile),
            "platform_resolution_hint": _attachment_platform_resolution_hint(profile),
            "attachment_resolution_route": first_carrier.get("attachment_resolution_route"),
            "first_attempt_http_statuses": [
                reason.split(":", 1)[1]
                for reason in list(first_carrier.get("degraded_reasons") or [])
                if str(reason).startswith("http_status:")
            ],
            "first_attempt_status": first_carrier.get("status"),
            "first_attempt_degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
            "attachment_blocker_class": first_carrier.get("attachment_blocker_class"),
            "attachment_blocker_reason": first_carrier.get("attachment_blocker_reason"),
            "same_capture_plan_resume_required": True,
            "allowed_resolution_capabilities": [
                "captcha_recognition",
                "ocr_recognition",
                "slider_trajectory_simulation",
                "browser_fingerprint_profile_reuse",
                "cookie_reuse",
                "same_session_capture_resume",
                "same_site_referer_replay",
                "hidden_interface_call_if_public_and_audited",
            ],
        }
        try:
            result = self.attachment_challenge_resolver.resolve_same_site_attachment(request)
        except Exception as exc:  # pragma: no cover - resolver implementations vary
            failed = dict(first_carrier)
            failed["automated_challenge_resolution_attempted"] = True
            failed["automated_challenge_resolution_state"] = "FAILED_CLOSED_RESOLVER_ERROR"
            failed["challenge_resume_audit"] = {
                "challenge_resume_context_id": context_id,
                "resolver_error": type(exc).__name__,
                "resolver_error_detail": str(exc),
                "resume_from_same_capture_plan": True,
                "resume_requires_human_input": False,
            }
            return failed

        response, resolution_metadata = _coerce_challenge_resolution_result(result, profile.url)
        if response is None:
            failed = dict(first_carrier)
            failed["automated_challenge_resolution_attempted"] = True
            failed["automated_challenge_resolution_state"] = "FAILED_CLOSED_NO_RESPONSE"
            failed["challenge_resume_audit"] = {
                "challenge_resume_context_id": context_id,
                "resolution_metadata": resolution_metadata,
                "resume_from_same_capture_plan": True,
                "resume_requires_human_input": False,
            }
            return failed

        now = utc_now_iso()
        audit = {
            "challenge_resume_context_id": context_id,
            "resolution_method": resolution_metadata.get("resolution_method") or "automated_challenge_resolver",
            "resolution_capabilities_used": list(resolution_metadata.get("resolution_capabilities_used") or []),
            "resume_from_same_capture_plan": True,
            "resume_requires_human_input": False,
            "first_attempt_status": first_carrier.get("status"),
            "first_attempt_degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
            "first_attachment_blocker_class": first_carrier.get("attachment_blocker_class"),
            "first_attachment_blocker_reason": first_carrier.get("attachment_blocker_reason"),
            "resolver_metadata": {
                key: value
                for key, value in resolution_metadata.items()
                if key not in {"content", "response"}
            },
        }
        carrier = self._attachment_carrier_from_response(
            profile,
            response,
            now=now,
            lineage_refs=lineage_refs,
            detail_page_url=detail_page_url,
            challenge_resume_audit=audit,
        )
        carrier["automated_challenge_resolution_attempted"] = True
        carrier["automated_challenge_resolution_state"] = (
            "RESOLVED_AND_SNAPSHOT_CAPTURED"
            if carrier.get("status") == "FETCHED"
            else "RESOLVED_RESPONSE_STILL_DEGRADED"
        )
        carrier["challenge_resume_audit"] = audit
        carrier["first_attempt_carrier"] = {
            "status": first_carrier.get("status"),
            "degraded_reasons": list(first_carrier.get("degraded_reasons") or []),
            "attachment_blocker_class": first_carrier.get("attachment_blocker_class"),
            "attachment_blocker_reason": first_carrier.get("attachment_blocker_reason"),
        }
        return carrier

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
        attachment_discovery_taxonomy: list[str] = []
        attachment_discovery_diagnostics: dict[str, Any] = {}
        if profile.profile_id == "GUANGZHOU-YWTB-CONSTRUCTION-LIST":
            guangzhou_static_diagnosis = _guangzhou_ywtb_download_discovery_from_html(
                text,
                detail_url=final_url,
                attachment_link_items=attachment_link_items,
            )
            attachment_discovery_diagnostics["guangzhou_ywtb"] = guangzhou_static_diagnosis
            attachment_discovery_taxonomy.extend(
                list(guangzhou_static_diagnosis.get("failure_taxonomy") or [])
            )
            if (
                not attachment_link_items
                and self.automated_challenge_resolution_enabled
                and self.attachment_challenge_resolver is not None
                and hasattr(self.attachment_challenge_resolver, "diagnose_guangzhou_ywtb_detail_downloads")
            ):
                try:
                    rendered_diagnosis = self.attachment_challenge_resolver.diagnose_guangzhou_ywtb_detail_downloads(
                        {
                            "detail_url": final_url,
                            "parent_profile_id": profile.profile_id,
                            "site_name": profile.site_name,
                            "source_family": profile.source_family,
                        }
                    )
                    if isinstance(rendered_diagnosis, Mapping):
                        rendered_items = [
                            {"url": str(item.get("url") or ""), "text": str(item.get("text") or "")}
                            for item in list(rendered_diagnosis.get("same_site_attachment_link_items") or [])
                            if isinstance(item, Mapping) and str(item.get("url") or "").strip()
                        ]
                        attachment_link_items = _merge_link_items(rendered_items, attachment_link_items)
                        attachment_discovery_diagnostics["guangzhou_ywtb_rendered"] = dict(rendered_diagnosis)
                        rendered_state = str(
                            rendered_diagnosis.get("guangzhou_ywtb_download_discovery_state") or ""
                        )
                        if rendered_items or rendered_state in {
                            "DOWNLOAD_ENDPOINT_CAPTURED",
                            "SCRIPT_ENDPOINT_CAPTURED",
                            "CLICK_DOWNLOAD_ENDPOINT_CAPTURED",
                            "EPPOINT_CHALLENGE_DETECTED",
                            "EPPOINT_CHALLENGE_RESOLVED",
                        }:
                            attachment_discovery_taxonomy = [
                                item
                                for item in attachment_discovery_taxonomy
                                if str(item)
                                not in {
                                    "guangzhou_public_download_endpoint_missing",
                                    "guangzhou_script_endpoint_unresolved",
                                    "guangzhou_ywtb_attachment_download_link_not_found",
                                }
                            ]
                        attachment_discovery_taxonomy.extend(
                            str(item)
                            for item in list(rendered_diagnosis.get("failure_taxonomy") or [])
                            if str(item or "").strip()
                        )
                except Exception as exc:  # pragma: no cover - browser diagnostics vary by host/runtime
                    attachment_discovery_diagnostics["guangzhou_ywtb_rendered"] = {
                        "guangzhou_ywtb_download_discovery_state": "SCRIPT_ENDPOINT_UNRESOLVED",
                        "diagnostic_error": type(exc).__name__,
                        "diagnostic_error_detail": str(exc)[:500],
                    }
                    attachment_discovery_taxonomy.append("guangzhou_ywtb_rendered_diagnostic_failed")
        if profile.profile_id == "SICHUAN-GGZY-TRANSACTION-INFO":
            if _has_template_placeholder(text):
                attachment_discovery_taxonomy.append("sichuan_template_placeholder_attachment_ignored")
            sichuan_attachment_discovery = _discover_sichuan_static_json_attachment_link_items(
                text,
                base_url=final_url,
                host=host,
                transport=self.transport,
                timeout_seconds=self.timeout_seconds,
                user_agent=self.user_agent,
            )
            attachment_link_items = _merge_link_items(
                list(sichuan_attachment_discovery.get("items") or []),
                attachment_link_items,
            )
            attachment_discovery_taxonomy.extend(
                str(item)
                for item in list(sichuan_attachment_discovery.get("taxonomy") or [])
                if str(item or "").strip()
            )
            attachment_discovery_diagnostics["sichuan_static_json"] = {
                key: value
                for key, value in dict(sichuan_attachment_discovery).items()
                if key not in {"items"}
            }
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
            "attachment_discovery_taxonomy": list(dict.fromkeys(attachment_discovery_taxonomy)),
            "attachment_discovery_diagnostics": attachment_discovery_diagnostics,
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
            "attachment_discovery_taxonomy": list(dict.fromkeys(attachment_discovery_taxonomy)),
            "attachment_discovery_diagnostics": attachment_discovery_diagnostics,
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
        challenge_resume_audit: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = response.content or b""
        content_type = response.content_type or "application/octet-stream"
        filename = _attachment_filename_from_response(profile, response)
        filename_lower = filename.lower()
        sha256 = hashlib.sha256(content).hexdigest()
        degraded_reasons: list[str] = []
        if response.status_code != 200:
            degraded_reasons.append(f"http_status:{response.status_code}")
        if len(content) == 0:
            degraded_reasons.append("attachment_body_empty")
        lowered_content_type = content_type.lower()
        plain_html_attachment = filename_lower.endswith((".html", ".htm"))
        if "html" in lowered_content_type and not plain_html_attachment:
            degraded_reasons.append("html_body_not_attachment")
        attachment_blocker = _attachment_html_blocker_diagnostics(
            content,
            content_type,
            allow_plain_html_attachment=plain_html_attachment,
        )
        if attachment_blocker["attachment_blocker_reason"]:
            degraded_reasons.append(str(attachment_blocker["attachment_blocker_reason"]))
        if not _attachment_content_is_supported(
            content=content,
            content_type=content_type,
            filename=filename,
            allow_plain_html_attachment=plain_html_attachment,
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
        if challenge_resume_audit:
            fetch_audit["automated_challenge_resume_used"] = True
            fetch_audit["challenge_resume_audit"] = dict(challenge_resume_audit)
        manifest_payload: dict[str, Any] | None = None
        snapshot_readback_state = ""
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
                    **(
                        {
                            "automated_challenge_resume_used": True,
                            "challenge_resume_audit": dict(challenge_resume_audit),
                        }
                        if challenge_resume_audit
                        else {}
                    ),
                },
                source_health={
                    "state": "HEALTHY",
                    "degraded_reasons": degraded_reasons,
                    "manual_review_required": False,
                    **(
                        {"challenge_resume_audit": dict(challenge_resume_audit)}
                        if challenge_resume_audit
                        else {}
                    ),
                },
            )
            readback = self.repository.replay_snapshot(snapshot_id)
            snapshot_readback_state = str(readback.get("readback_state") or "")
            if bool(readback.get("replayable")):
                manifest_payload = manifest.as_payload()
            else:
                degraded_reasons.append("attachment_snapshot_readback_missing")
                if snapshot_readback_state:
                    degraded_reasons.append(f"attachment_snapshot_readback_state:{snapshot_readback_state}")
        status = "DEGRADED" if degraded_reasons else "FETCHED"
        attachment_failure_taxonomy = _normalized_attachment_failure_taxonomy(
            degraded_reasons=degraded_reasons,
            attachment_blocker=attachment_blocker,
        )

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
            "snapshot_readback_state": snapshot_readback_state,
            "review_required": bool(degraded_reasons),
            "fail_closed": bool(degraded_reasons),
            "no_broad_fallback": True,
            **attachment_blocker,
            "attachment_failure_taxonomy": attachment_failure_taxonomy,
            "fetch_audit": fetch_audit,
            "transport": fetch_audit["transport"],
            "controlled_opening_requirements": _controlled_opening_requirements(),
            **(
                {
                    "automated_challenge_resume_used": True,
                    "challenge_resume_audit": dict(challenge_resume_audit),
                }
                if challenge_resume_audit
                else {}
            ),
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
        attachment_blocker = {
            "attachment_blocker_class": "",
            "attachment_blocker_reason": "",
            "attachment_failure_taxonomy": [],
            "attachment_resolution_route": "",
            "attachment_browser_replay_steps": [],
        }
        failure_taxonomy = _fetch_failure_taxonomy(detail)
        if reason == "fetch_failed":
            failure_taxonomy.append("attachment_fetch_failed")
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
            "attachment_failure_taxonomy": list(dict.fromkeys(failure_taxonomy)),
            "failure_detail_optional": detail,
            "review_required": True,
            "fail_closed": True,
            "no_broad_fallback": True,
            **attachment_blocker,
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


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decode_html(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_title(text: str) -> str:
    meta_match = re.search(
        r"<meta\b[^>]*(?:name|property)=['\"](?:ArticleTitle|og:title)['\"][^>]*content=['\"]([^'\"]+)['\"][^>]*>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not meta_match:
        meta_match = re.search(
            r"<meta\b[^>]*content=['\"]([^'\"]+)['\"][^>]*(?:name|property)=['\"](?:ArticleTitle|og:title)['\"][^>]*>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    if meta_match:
        return " ".join(unescape(meta_match.group(1)).split())
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
        if _has_template_placeholder(href, match.group("body") or ""):
            continue
        full = urljoin(base_url, href)
        parsed = urlsplit(full)
        parsed_host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or parsed_host != expected_host:
            continue
        if not (
            parsed.path.endswith((".html", ".htm", ".shtml", ".jhtml"))
            or parsed.path.endswith((".jspx", ".jsp"))
            or parsed.path.endswith(_SUPPORTED_ATTACHMENT_EXTENSIONS)
            or _attachment_url_has_supported_signal(full, link_text=_clean_anchor_text(match.group("body") or ""))
            or "/information/" in parsed.path
            or "/cggg/" in parsed.path
            or "/deal/" in parsed.path
            or "/jyxx" in parsed.path.lower()
            or "/jyxxgk" in parsed.path.lower()
            or "/base/sys-file/download/" in parsed.path.lower()
            or "/epointwebbuilder/pages/webbuildermis/attach/downloadztbattach" in parsed.path.lower()
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
    expected_host = host.split(":", 1)[0].lower()
    ywtb_onclick_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    ywtb_download_pattern = re.compile(
        r"onclick\s*=\s*['\"][^'\"]*ztbfjyz\(\s*['\"](?P<href>[^'\"]+)['\"]",
        flags=re.IGNORECASE | re.DOTALL,
    )
    epoint_download_pattern = re.compile(
        r"['\"](?P<href>[^'\"]*downloadZtbAttach[^'\"]*)['\"]",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in ywtb_onclick_pattern.finditer(text):
        onclick_match = ywtb_download_pattern.search(match.group("attrs") or "") or epoint_download_pattern.search(
            match.group("attrs") or ""
        )
        if not onclick_match:
            continue
        href = unescape(onclick_match.group("href")).strip()
        if _has_template_placeholder(href, match.group("body") or ""):
            continue
        full = urljoin(base_url, href)
        parsed = urlsplit(full)
        if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").lower() != expected_host
            or "downloadztbattach" not in parsed.path.lower()
        ):
            continue
        clean = full.split("#", 1)[0]
        if clean in seen:
            continue
        seen.add(clean)
        items.append({"url": clean, "text": _clean_anchor_text(match.group("body") or "")})
        if len(items) >= 10:
            return items
    anchor_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    href_pattern = re.compile(r"href=[\"'](?P<href>[^\"']+)[\"']", flags=re.IGNORECASE)
    data_url_pattern = re.compile(
        r"(?:data-url|data-href|data-file|data-fileurl|fileurl|url)\s*=\s*[\"'](?P<href>[^\"']+)[\"']",
        flags=re.IGNORECASE,
    )
    for match in anchor_pattern.finditer(text):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        link_text = _clean_anchor_text(body)
        href_match = href_pattern.search(attrs) or data_url_pattern.search(attrs)
        if not href_match:
            continue
        href = unescape(href_match.group("href")).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if _has_template_placeholder(href, attrs, body):
            continue
        full = urljoin(base_url, href)
        parsed = urlsplit(full)
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != expected_host:
            continue
        if _is_non_attachment_navigation_link(full, link_text=link_text):
            continue
        if not _attachment_url_has_supported_signal(full, link_text=link_text):
            continue
        clean = full.split("#", 1)[0]
        if clean in seen:
            continue
        seen.add(clean)
        items.append({"url": clean, "text": link_text})
        if len(items) >= 10:
            return items
    for item in _discover_same_site_link_items(text, base_url=base_url, host=host):
        url = item["url"]
        parsed = urlsplit(url)
        path = parsed.path.lower()
        link_text = item.get("text", "")
        if _has_template_placeholder(url, link_text):
            continue
        attachment_text_hint = any(
            token in link_text
            for token in ("附件", "下载", "招标文件", "采购文件", "结果文件", "资格要求", "评标报告", "定标报告")
        )
        if not (
            path.endswith(_SUPPORTED_ATTACHMENT_EXTENSIONS)
            or _attachment_url_has_supported_signal(url, link_text=link_text)
            or attachment_text_hint
            or (path.endswith((".html", ".htm")) and attachment_text_hint)
            or re.search(r"\.(pdf|docx?|xlsx?|zip|rar)$", link_text.strip(), flags=re.IGNORECASE)
        ):
            continue
        if _is_non_attachment_navigation_link(url, link_text=link_text):
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"url": url, "text": link_text})
        if len(items) >= 10:
            break
    return items


def _merge_link_items(primary: list[Mapping[str, Any]], secondary: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in [*primary, *secondary]:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen or _has_template_placeholder(url, item.get("text")):
            continue
        seen.add(url)
        merged.append({"url": url, "text": str(item.get("text") or "")})
    return merged[:50]


def _has_template_placeholder(*values: Any) -> bool:
    text = " ".join(str(value or "") for value in values)
    lowered = text.lower()
    return (
        "{{" in text
        or "}}" in text
        or "%7b%7b" in lowered
        or "%7d%7d" in lowered
        or any(token in text for token in ("{{arrGuid}}", "{{appUrlFlag}}", "{{attFileName}}"))
    )


def _guangzhou_ywtb_download_discovery_from_html(
    text: str,
    *,
    detail_url: str,
    attachment_link_items: list[Mapping[str, Any]],
) -> dict[str, Any]:
    body = str(text or "")
    lowered = body.lower()
    if attachment_link_items:
        state = "DOWNLOAD_ENDPOINT_CAPTURED"
    elif any(token in body for token in ("数字证书", "CA锁", "CA证书", "CA 登录", "CA登录", "粤商通")):
        state = "LOGIN_OR_CA_REQUIRED"
    elif any(token in body for token in ("请登录", "用户登录", "登录后", "登录系统", "会员登录")):
        state = "LOGIN_OR_CA_REQUIRED"
    elif any(token in body for token in ("验证码", "滑块", "拖动", "captcha", "blockpuzzle")):
        state = "CHALLENGE_REQUIRED"
    elif any(token in lowered for token in ("ztbfjyz", "downloadztbattach", "attachguid", "appurlflag")):
        state = "SCRIPT_ENDPOINT_UNRESOLVED"
    else:
        state = "NO_PUBLIC_DOWNLOAD_ENDPOINT"
    return {
        "guangzhou_ywtb_download_discovery_state": state,
        "detail_url": detail_url,
        "static_download_endpoint_count": len(attachment_link_items),
        "static_download_endpoint_urls": [
            str(item.get("url") or "")
            for item in attachment_link_items[:10]
            if isinstance(item, Mapping)
        ],
        "failure_taxonomy": _guangzhou_ywtb_discovery_failure_taxonomy(state),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _guangzhou_ywtb_discovery_failure_taxonomy(state: str) -> list[str]:
    if state == "DOWNLOAD_ENDPOINT_CAPTURED":
        return []
    mapping = {
        "NO_PUBLIC_DOWNLOAD_ENDPOINT": "guangzhou_public_download_endpoint_missing",
        "LOGIN_OR_CA_REQUIRED": "guangzhou_login_or_ca_required",
        "CHALLENGE_REQUIRED": "guangzhou_challenge_required",
        "SCRIPT_ENDPOINT_UNRESOLVED": "guangzhou_script_endpoint_unresolved",
    }
    value = mapping.get(str(state or ""))
    return [value] if value else []


def _discover_sichuan_static_json_attachment_link_items(
    text: str,
    *,
    base_url: str,
    host: str,
    transport: RealPublicFetchTransport,
    timeout_seconds: float,
    user_agent: str,
) -> dict[str, Any]:
    taxonomy: list[str] = []
    relateinfoid = _extract_sichuan_relateinfoid(text)
    stage = _extract_sichuan_current_stage(text) or "503"
    if not relateinfoid:
        return {
            "state": "SKIPPED",
            "taxonomy": ["sichuan_static_json_route_missing"],
            "relateinfoid": "",
            "stage": stage,
            "json_url": "",
            "item_count": 0,
        }

    json_url = urljoin(base_url, f"/staticJson/{relateinfoid}/{stage}.json")
    try:
        response = transport.fetch(json_url, timeout_seconds=timeout_seconds, user_agent=user_agent)
    except Exception as exc:  # pragma: no cover - public site failures vary
        return {
            "state": "FETCH_FAILED",
            "taxonomy": [f"sichuan_static_json_fetch_failed:{type(exc).__name__}"],
            "relateinfoid": relateinfoid,
            "stage": stage,
            "json_url": json_url,
            "item_count": 0,
        }
    if response.status_code != 200:
        return {
            "state": "FETCH_FAILED",
            "taxonomy": [f"sichuan_static_json_http_status:{response.status_code}"],
            "relateinfoid": relateinfoid,
            "stage": stage,
            "json_url": json_url,
            "item_count": 0,
        }
    try:
        payload = json.loads(_decode_html(response.content or b"{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {
            "state": "PARSE_FAILED",
            "taxonomy": ["sichuan_static_json_parse_failed"],
            "relateinfoid": relateinfoid,
            "stage": stage,
            "json_url": json_url,
            "item_count": 0,
        }

    view_infoid = _extract_sichuan_view_infoid(text)
    rows = [row for row in list(payload.get("data") or []) if isinstance(row, Mapping)]
    matched_rows = [
        row
        for row in rows
        if view_infoid and str(row.get("infoid") or "") and str(row.get("infoid") or "") in view_infoid
    ]
    if not matched_rows:
        matched_rows = rows

    items: list[dict[str, str]] = []
    attach_file_count = 0
    for row in matched_rows:
        infoid = str(row.get("infoid") or "")
        for file_item in list(row.get("attachFiles") or []):
            if not isinstance(file_item, Mapping):
                continue
            attach_file_count += 1
            link_item = _sichuan_static_json_attach_file_link_item(
                file_item,
                base_url=base_url,
                infoid=infoid,
                host=host,
            )
            if link_item:
                items.append(link_item)
            else:
                taxonomy.append("sichuan_static_json_attach_file_missing_download_fields")
    if attach_file_count <= 0:
        taxonomy.append("sichuan_static_json_no_attach_files")
    return {
        "state": "FETCHED",
        "taxonomy": list(dict.fromkeys(taxonomy)),
        "relateinfoid": relateinfoid,
        "stage": stage,
        "json_url": json_url,
        "row_count": len(rows),
        "matched_row_count": len(matched_rows),
        "attach_file_count": attach_file_count,
        "item_count": len(items),
        "items": _merge_link_items(items, []),
    }


def _extract_sichuan_relateinfoid(text: str) -> str:
    patterns = (
        r"id=['\"]relateinfoid['\"][^>]*data-value=['\"]([^'\"]+)['\"]",
        r"data-value=['\"]([^'\"]+)['\"][^>]*id=['\"]relateinfoid['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return unescape(match.group(1)).strip()
    return ""


def _extract_sichuan_current_stage(text: str) -> str:
    match = re.search(
        r"<a\b(?=[^>]*class=['\"][^'\"]*\bcurrent\b[^'\"]*['\"])(?=[^>]*data-value=['\"]([^'\"]+)['\"])[^>]*>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return unescape(match.group(1)).strip() if match else ""


def _extract_sichuan_view_infoid(text: str) -> str:
    patterns = (
        r"id=['\"]viewGuid['\"][^>]*(?:value|data-value)=['\"]([^'\"]+)['\"]",
        r"(?:value|data-value)=['\"]([^'\"]+)['\"][^>]*id=['\"]viewGuid['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return unescape(match.group(1)).strip()
    return ""


def _sichuan_static_json_attach_file_link_item(
    file_item: Mapping[str, Any],
    *,
    base_url: str,
    infoid: str,
    host: str,
) -> dict[str, str] | None:
    filename = str(
        file_item.get("attFileName")
        or file_item.get("fileName")
        or file_item.get("filename")
        or file_item.get("name")
        or ""
    ).strip()
    filepath = str(file_item.get("filepath") or file_item.get("filePath") or "").strip()
    arr_guid = str(file_item.get("arrGuid") or file_item.get("attachGuid") or "").strip()
    app_url_flag = str(file_item.get("appUrlFlag") or "").strip()
    if _has_template_placeholder(filename, filepath, arr_guid, app_url_flag):
        return None
    if filepath:
        url = urljoin(base_url, filepath + filename)
    elif arr_guid and app_url_flag:
        url = urljoin(
            base_url,
            "/WebBuilder/WebbuilderMIS/attach/downloadZtbAttach.jspx?"
            + urlencode(
                {
                    "attachGuid": arr_guid,
                    "appUrlFlag": app_url_flag,
                    "siteGuid": "7eb5f7f1-9041-43ad-8e13-8fcb82ea831a",
                }
            ),
        )
    elif infoid and filename:
        url = urljoin(base_url, f"/uploadfile/{infoid}/{quote(filename)}")
    else:
        return None
    parsed = urlsplit(url)
    if (parsed.hostname or "").lower() != host.split(":", 1)[0].lower():
        return None
    if _is_non_attachment_navigation_link(url, link_text=filename):
        return None
    return {"url": url, "text": filename}


def _is_non_attachment_navigation_link(url: str, *, link_text: str) -> bool:
    parsed = urlsplit(str(url or ""))
    path = parsed.path.lower()
    text = _clean_anchor_text(link_text).replace(" ", "")
    normalized_text = text.lstrip("/").strip()
    if not url:
        return True
    if text in _NON_ATTACHMENT_LINK_TEXTS or normalized_text in _NON_ATTACHMENT_LINK_TEXTS:
        return True
    if any(token in path for token in _NON_ATTACHMENT_PATH_TOKENS):
        return True
    if path.endswith(("index.html", "list.html", "about.html", "transactioninfo.html")):
        return True
    return False


def _clean_anchor_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(without_tags).split())


def _coerce_challenge_resolution_result(
    result: RealPublicFetchResponse | Mapping[str, Any],
    fallback_url: str,
) -> tuple[RealPublicFetchResponse | None, dict[str, Any]]:
    if isinstance(result, RealPublicFetchResponse):
        return result, {"resolution_method": "real_public_fetch_response"}
    if not isinstance(result, Mapping):
        return None, {"resolution_error": "unsupported_resolution_result_type"}
    metadata = dict(result.get("resolution_metadata") or {})
    for key in (
        "resolution_method",
        "resolution_capabilities_used",
        "browser_context_ref",
        "cookie_reuse_state",
        "fingerprint_profile_ref",
        "proxy_profile_ref",
    ):
        if key in result and key not in metadata:
            metadata[key] = result[key]
    response_obj = result.get("response")
    if isinstance(response_obj, RealPublicFetchResponse):
        return response_obj, metadata
    content = result.get("content")
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, (bytes, bytearray)):
        return None, metadata
    return (
        RealPublicFetchResponse(
            url=str(result.get("url") or fallback_url),
            status_code=int(result.get("status_code") or 200),
            content=bytes(content),
            content_type=str(result.get("content_type") or "application/octet-stream"),
            final_url=str(result.get("final_url") or result.get("url") or fallback_url),
            headers=dict(result.get("headers") or {}),
        ),
        metadata,
    )


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
