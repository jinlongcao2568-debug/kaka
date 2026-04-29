from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from shared.utils import utc_now_iso
from storage.repositories.object_storage_repo import ObjectStorageRepository


REAL_PUBLIC_ENTRY_FETCHER_ID = "stage2.real_public_entry_url_fetcher.v1"
REAL_PUBLIC_ENTRY_FETCH_MODE = "REAL_PUBLIC_ENTRY_ALLOWLIST"
REAL_PUBLIC_ATTACHMENT_FETCH_MODE = "REAL_PUBLIC_ATTACHMENT_ALLOWLIST"
REAL_PUBLIC_ENTRY_SNAPSHOT_KIND = "real_public_entry_html_snapshot"
REAL_PUBLIC_ATTACHMENT_SNAPSHOT_KIND = "real_public_attachment_original_file"
REAL_PUBLIC_ENTRY_USER_AGENT = (
    "AX9S-RealPublicEntryFetcher/0.1 (+public-readonly-validation)"
)


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
        profile_id="GUANGDONG-PROVINCIAL-PORTAL",
        url="https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/440000/index",
        site_name="广东省公共资源交易平台",
        source_family="provincial_bidding_platform",
        expected_title_contains="广东省公共资源交易平台",
        visible_entry_markers=("交易服务", "公告", "搜索"),
        sample_detail_url="https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/445300/index",
        browser_verified_at="2026-04-28T15:35:00+08:00",
        browser_verified_evidence="省级总入口 runtime 直连返回 200，但原始 HTML 更接近前端壳页，需要按弱正文/fail-closed 分类。",
        lightweight_public_entry_markers=("广东省公共资源交易平台", "工程建设", "政府采购"),
    ),
    RealPublicEntryProfile(
        profile_id="GUANGDONG-YUNFU-PORTAL",
        url="https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/445300/index",
        site_name="广东省公共资源交易平台（云浮）",
        source_family="provincial_bidding_platform",
        expected_title_contains="广东省公共资源交易平台",
        visible_entry_markers=("交易服务", "公告", "搜索"),
        sample_detail_url="https://ygp.gdzwfw.gov.cn/ggzy-portal/index.html#/440000/index",
        browser_verified_at="2026-04-28T15:35:00+08:00",
        browser_verified_evidence="云浮入口 runtime 直连返回 200，但原始 HTML 更接近前端壳页，需要按弱正文/fail-closed 分类。",
        lightweight_public_entry_markers=("广东省公共资源交易平台", "工程建设", "政府采购"),
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
    "GUANGDONG-PROVINCIAL-PORTAL",
    "GUANGDONG-YUNFU-PORTAL",
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
    "GUANGDONG-PROVINCIAL-PORTAL",
    "GUANGDONG-YUNFU-PORTAL",
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

_BLOCKED_BODY_PATTERNS = (
    "错误页面",
    "页面不存在",
    "404 Not Found",
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
        if urlsplit(profile.url).scheme != "https":
            raise self._boundary_error(url, "non_https_public_entry_url")
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
                "uncontrolled_crawler_enabled": False,
                "deep_crawl_enabled": False,
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
        blocked_body_patterns = [
            marker for marker in _BLOCKED_BODY_PATTERNS if marker.lower() in text.lower()
        ]
        strong_blocked_body_patterns = [
            marker
            for marker in blocked_body_patterns
            if marker.lower() not in {"验证码", "captcha"}
        ]
        weak_blocked_body_patterns = [
            marker for marker in blocked_body_patterns if marker not in strong_blocked_body_patterns
        ]
        same_site_links = _discover_same_site_links(
            text,
            base_url=response.final_url or profile.url,
            host=profile.host,
        )
        degraded_reasons: list[str] = []
        if response.status_code != 200:
            degraded_reasons.append(f"http_status:{response.status_code}")
        if "html" not in (response.content_type or "").lower():
            degraded_reasons.append("non_html_content_type")
        if len(content) < 500:
            degraded_reasons.append("entry_body_too_small")
        if not markers_found and not lightweight_markers_complete:
            degraded_reasons.append("visible_entry_markers_missing")
        if strong_blocked_body_patterns or (
            weak_blocked_body_patterns and not markers_found and not lightweight_markers_complete
        ):
            degraded_reasons.append("blocked_body_pattern:" + ",".join(blocked_body_patterns))
        if profile.expected_title_contains and profile.expected_title_contains not in title:
            degraded_reasons.append("title_mismatch")

        status = "DEGRADED" if degraded_reasons else "FETCHED"
        validation_level = (
            "VISIBLE_ENTRY_MARKERS"
            if markers_found
            else (
                "LIGHTWEIGHT_PUBLIC_ENTRY"
                if lightweight_markers_complete
                else "FAIL_CLOSED_INSUFFICIENT_VISIBLE_ENTRY"
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
            "uncontrolled_crawler_enabled": False,
            "deep_crawl_enabled": False,
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
            "sample_detail_url": profile.sample_detail_url,
            "browser_verified": True,
            "browser_verified_at": profile.browser_verified_at,
            "browser_verified_evidence": profile.browser_verified_evidence,
            "blocked_body_patterns_observed": blocked_body_patterns,
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
            "sample_detail_url": profile.sample_detail_url,
            "snapshot_id_optional": snapshot_id if manifest_payload else None,
            "manifest_optional": manifest_payload,
            "degraded_reasons": degraded_reasons,
            "review_required": bool(degraded_reasons),
            "fail_closed": bool(degraded_reasons),
            "no_broad_fallback": True,
            "fetch_audit": fetch_audit,
            "failure_taxonomy": failure_taxonomy,
            "transport": fetch_audit["transport"],
            "controlled_opening_boundaries": _controlled_opening_boundaries(),
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
                "uncontrolled_crawler_enabled": False,
                "deep_crawl_enabled": False,
                "real_provider_call_executed": False,
            },
            "controlled_opening_boundaries": _controlled_opening_boundaries(),
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
            "uncontrolled_crawler_enabled": False,
            "deep_crawl_enabled": False,
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
            "controlled_opening_boundaries": _controlled_opening_boundaries(),
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
                "uncontrolled_crawler_enabled": False,
                "deep_crawl_enabled": False,
                "real_provider_call_executed": False,
            },
            "controlled_opening_boundaries": _controlled_opening_boundaries(),
        }


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
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"href=[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE):
        href = unescape(match.group(1)).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        parsed = urlsplit(full)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host:
            continue
        if not (
            parsed.path.endswith((".html", ".htm", ".shtml"))
            or "/information/" in parsed.path
            or "/cggg/" in parsed.path
            or "/deal/" in parsed.path
        ):
            continue
        clean = full.split("#", 1)[0]
        if clean not in seen:
            seen.add(clean)
            links.append(clean)
        if len(links) >= 20:
            break
    return links


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
    if any(reason.startswith("http_status:412") for reason in degraded_reasons):
        failure_class = "UPSTREAM_PRECONDITION_FAILED"
    elif any(reason.startswith("http_status:521") for reason in degraded_reasons):
        failure_class = "UPSTREAM_WEB_SERVER_DOWN_OR_BLOCKED"
    elif any(reason.startswith("http_status:") for reason in degraded_reasons):
        failure_class = "UPSTREAM_HTTP_STATUS_NOT_OK"
    elif "visible_entry_markers_missing" in degraded_reasons and validation_level == "FAIL_CLOSED_INSUFFICIENT_VISIBLE_ENTRY":
        failure_class = "PUBLIC_ENTRY_MARKERS_MISSING_OR_SPA_SHELL"
    elif any(reason.startswith("blocked_body_pattern") for reason in degraded_reasons):
        failure_class = "BLOCKED_BODY_PATTERN"
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
        "manual_review_required": True,
        "fail_closed": True,
        "no_broad_fallback": True,
    }


def _controlled_opening_boundaries() -> dict[str, bool]:
    return {
        "private_or_gray_source_used": False,
        "uncontrolled_live_crawler_used": False,
        "deep_crawl_used": False,
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
