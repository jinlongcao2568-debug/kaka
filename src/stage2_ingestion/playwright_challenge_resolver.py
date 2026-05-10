from __future__ import annotations

import base64
import hashlib
import os
import json
import math
import tempfile
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, urljoin, urlsplit, unquote
from urllib.parse import urlencode, urlunsplit


class PlaywrightAttachmentChallengeResolver:
    """Controlled browser resolver for public attachment challenge pages.

    This resolver is opt-in and is intended to resume the same Stage2 capture
    plan after a site returns captcha/session/hotlink HTML instead of a file.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        storage_state_path: str | None = None,
        proxy_server: str | None = None,
        timeout_ms: int = 60000,
        user_agent: str | None = None,
        ocr_attempts: int = 3,
        jigsaw_attempts: int = 3,
    ) -> None:
        self.headless = headless
        self.storage_state_path = storage_state_path
        self.proxy_server = proxy_server
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent
        self.ocr_attempts = max(1, ocr_attempts)
        self.jigsaw_attempts = max(1, jigsaw_attempts)
        self._last_browser_diagnostics: dict[str, Any] = {}

    @classmethod
    def from_environment(cls) -> "PlaywrightAttachmentChallengeResolver":
        return cls(
            headless=(os.environ.get("KAKA_CHALLENGE_BROWSER_HEADLESS") or "1") != "0",
            storage_state_path=os.environ.get("KAKA_CHALLENGE_STORAGE_STATE") or None,
            proxy_server=os.environ.get("KAKA_CHALLENGE_PROXY_SERVER") or None,
            timeout_ms=int(os.environ.get("KAKA_CHALLENGE_TIMEOUT_MS") or "60000"),
            user_agent=os.environ.get("KAKA_CHALLENGE_USER_AGENT") or None,
            ocr_attempts=int(os.environ.get("KAKA_CHALLENGE_OCR_ATTEMPTS") or "3"),
            jigsaw_attempts=int(os.environ.get("KAKA_CHALLENGE_JIGSAW_ATTEMPTS") or "3"),
        )

    def resolve_same_site_attachment(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError(f"playwright_unavailable:{exc}") from exc

        attachment_url = str(request.get("attachment_url") or "").strip()
        detail_page_url = str(request.get("detail_page_url") or "").strip()
        if not attachment_url:
            raise ValueError("attachment_url_required")

        with tempfile.TemporaryDirectory() as tmp_dir, sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": self.headless}
            if self.proxy_server:
                launch_options["proxy"] = {"server": self.proxy_server}
            browser = playwright.chromium.launch(**launch_options)
            context_options: dict[str, Any] = {
                "accept_downloads": True,
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "viewport": {"width": 1366, "height": 900},
            }
            if self.user_agent:
                context_options["user_agent"] = self.user_agent
            if self.storage_state_path and Path(self.storage_state_path).exists():
                context_options["storage_state"] = self.storage_state_path
            context = browser.new_context(**context_options)
            page = context.new_page()
            try:
                if detail_page_url:
                    page.goto(detail_page_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                download_path = None
                if _guangdong_ygp_download_url(attachment_url):
                    download_path = self._try_guangdong_ygp_download(
                        context,
                        attachment_url=attachment_url,
                        tmp_dir=tmp_dir,
                        referer_url=detail_page_url or page.url,
                    )
                if _epoint_jigsaw_captcha_url(attachment_url):
                    download_path = self._try_epoint_jigsaw_download(page, context, attachment_url, tmp_dir)
                if download_path is None:
                    download_path = self._try_browser_download(page, attachment_url, tmp_dir)
                if download_path is None:
                    download_path = self._try_page_verify_ocr_download(page, context, attachment_url, tmp_dir)
                if download_path is None:
                    download_path = self._try_request_download(
                        context,
                        attachment_url,
                        tmp_dir,
                        referer_url=detail_page_url or page.url,
                    )
                if download_path is None:
                    diagnostics = self._page_diagnostics(page)
                    diagnostics.update(self._last_browser_diagnostics)
                    raise RuntimeError(
                        "automated_challenge_download_not_resolved:"
                        + json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)[:1200]
                    )
                content = Path(download_path).read_bytes()
                content_type = _content_type_from_file(download_path)
                capabilities = [
                    "same_session_capture_resume",
                    "cookie_reuse" if self.storage_state_path else "browser_session_cookie_capture",
                    "browser_fingerprint_profile_reuse",
                    "proxy_pool" if self.proxy_server else "",
                ]
                if self._last_browser_diagnostics.get("jigsaw_resolution_state"):
                    capabilities.extend(
                        [
                            "slider_trajectory_simulation",
                            "hidden_interface_call_if_public_and_audited",
                        ]
                    )
                if self._last_browser_diagnostics.get("guangdong_ygp_resolution_state"):
                    capabilities.extend(
                        [
                            "same_site_referer_replay",
                            "hidden_interface_call_if_public_and_audited",
                        ]
                    )
                if self._last_browser_diagnostics.get("ocr_resolution_state"):
                    capabilities.extend(["captcha_recognition", "ocr_recognition"])
                return {
                    "url": attachment_url,
                    "final_url": attachment_url,
                    "status_code": 200,
                    "content": content,
                    "content_type": content_type,
                    "headers": {"x-ax9s-fetch-transport": "playwright_challenge_resolver"},
                    "resolution_method": "playwright_browser_challenge_download",
                    "resolution_capabilities_used": _dedupe([item for item in capabilities if item]),
                    "browser_context_ref": "playwright.chromium",
                    "cookie_reuse_state": "STORAGE_STATE_REUSED" if self.storage_state_path else "SESSION_COOKIES_USED",
                    "fingerprint_profile_ref": "zh-CN/chromium/1366x900/Asia-Shanghai",
                    "proxy_profile_ref": "CONFIGURED_PROXY" if self.proxy_server else "",
                }
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"playwright_timeout:{exc}") from exc
            finally:
                context.close()
                browser.close()

    def resolve_candidate_detail(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError(f"playwright_unavailable:{exc}") from exc

        detail_url = str(request.get("detail_url") or "").strip()
        if not detail_url:
            raise ValueError("detail_url_required")

        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": self.headless}
            if self.proxy_server:
                launch_options["proxy"] = {"server": self.proxy_server}
            browser = playwright.chromium.launch(**launch_options)
            context_options: dict[str, Any] = {
                "accept_downloads": True,
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "viewport": {"width": 1366, "height": 900},
            }
            if self.user_agent:
                context_options["user_agent"] = self.user_agent
            if self.storage_state_path and Path(self.storage_state_path).exists():
                context_options["storage_state"] = self.storage_state_path
            context = browser.new_context(**context_options)
            page = context.new_page()
            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 12000))
                except Exception:
                    pass
                html = page.content()
                text = ""
                try:
                    text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    text = ""
                diagnostics = self._page_diagnostics(page)
                if _detail_page_still_blocked(html, text):
                    raise RuntimeError(
                        "automated_detail_challenge_not_resolved:"
                        + json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)[:1200]
                    )
                content = html.encode("utf-8")
                return {
                    "url": detail_url,
                    "final_url": page.url or detail_url,
                    "status_code": 200,
                    "content": content,
                    "content_type": "text/html; charset=utf-8",
                    "headers": {"x-ax9s-fetch-transport": "playwright_detail_challenge_resolver"},
                    "resolution_method": "playwright_browser_detail_challenge_resume",
                    "resolution_capabilities_used": _dedupe(
                        [
                            "same_session_capture_resume",
                            "cookie_reuse" if self.storage_state_path else "browser_session_cookie_capture",
                            "browser_fingerprint_profile_reuse",
                            "proxy_pool" if self.proxy_server else "",
                        ]
                    ),
                    "browser_context_ref": "playwright.chromium",
                    "cookie_reuse_state": "STORAGE_STATE_REUSED" if self.storage_state_path else "SESSION_COOKIES_USED",
                    "fingerprint_profile_ref": "zh-CN/chromium/1366x900/Asia-Shanghai",
                    "proxy_profile_ref": "CONFIGURED_PROXY" if self.proxy_server else "",
                    "resolution_metadata": {
                        "page_title": diagnostics.get("page_title"),
                        "page_url": diagnostics.get("page_url"),
                        "selector_counts": diagnostics.get("selector_counts"),
                    },
                }
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"playwright_timeout:{exc}") from exc
            finally:
                context.close()
                browser.close()

    def diagnose_guangzhou_ywtb_detail_downloads(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Inspect a Guangzhou YWTB detail page for public tender download endpoints.

        This is diagnostic-only: it records endpoint URLs and blocker classes,
        but does not persist raw HTML or downloaded blobs.
        """
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError(f"playwright_unavailable:{exc}") from exc

        detail_url = str(request.get("detail_url") or "").strip()
        if not detail_url:
            raise ValueError("detail_url_required")

        candidates: list[dict[str, str]] = []
        response_statuses: list[dict[str, Any]] = []
        clicked_texts: list[str] = []

        def remember_candidate(url: str, text: str = "", source: str = "") -> None:
            absolute = urljoin(detail_url, str(url or "").strip())
            if not _guangzhou_ywtb_download_url(absolute):
                return
            clean = absolute.split("#", 1)[0]
            if any(item.get("url") == clean for item in candidates):
                return
            candidates.append({"url": clean, "text": text[:160], "source": source})

        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": self.headless}
            if self.proxy_server:
                launch_options["proxy"] = {"server": self.proxy_server}
            browser = playwright.chromium.launch(**launch_options)
            context_options: dict[str, Any] = {
                "accept_downloads": True,
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "viewport": {"width": 1366, "height": 900},
            }
            if self.user_agent:
                context_options["user_agent"] = self.user_agent
            if self.storage_state_path and Path(self.storage_state_path).exists():
                context_options["storage_state"] = self.storage_state_path
            context = browser.new_context(**context_options)
            page = context.new_page()

            def on_request(req: Any) -> None:
                remember_candidate(req.url, source="network_request")

            def on_response(resp: Any) -> None:
                if _guangzhou_ywtb_download_url(resp.url):
                    response_statuses.append(
                        {
                            "url": resp.url.split("#", 1)[0],
                            "status": getattr(resp, "status", None),
                            "content_type": (getattr(resp, "headers", {}) or {}).get("content-type", ""),
                        }
                    )

            page.on("request", on_request)
            page.on("response", on_response)
            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 12000))
                except Exception:
                    pass
                html = page.content()
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    body_text = ""
                for item in _guangzhou_ywtb_dom_download_candidates(page):
                    remember_candidate(item.get("url", ""), item.get("text", ""), "dom")
                if not candidates:
                    for item in _guangzhou_ywtb_click_probe(page):
                        clicked_texts.append(str(item.get("text") or "")[:160])
                        remember_candidate(item.get("url", ""), item.get("text", ""), "click_probe")
                state = _guangzhou_ywtb_download_discovery_state(
                    body_text=body_text,
                    html=html,
                    candidate_count=len(candidates),
                )
                return {
                    "guangzhou_ywtb_download_discovery_state": state,
                    "same_site_attachment_link_items": [
                        {"url": item["url"], "text": item.get("text") or "广州交易集团下载入口"}
                        for item in candidates
                    ],
                    "failure_taxonomy": _guangzhou_ywtb_discovery_failure_taxonomy(state),
                    "network_download_response_count": len(response_statuses),
                    "network_download_response_statuses": response_statuses[:20],
                    "clicked_download_probe_texts": clicked_texts[:20],
                    "page_title": _safe_page_title(page),
                    "page_url": page.url or detail_url,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"playwright_timeout:{exc}") from exc
            finally:
                context.close()
                browser.close()

    def _try_browser_download(self, page: Any, attachment_url: str, tmp_dir: str) -> str | None:
        try:
            try:
                page.wait_for_function("() => typeof window.ztbfjyz === 'function'", timeout=8000)
            except Exception:
                pass
            with page.expect_download(timeout=min(self.timeout_ms, 10000)) as download_info:
                if not self._click_attachment_anchor(page, attachment_url):
                    page.goto(attachment_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            download = download_info.value
            filename = download.suggested_filename or _filename_from_url(attachment_url)
            save_path = str(Path(tmp_dir) / filename)
            download.save_as(save_path)
            return save_path
        except Exception as exc:
            self._last_browser_diagnostics = {
                "browser_download_error": type(exc).__name__,
                "browser_download_error_detail": str(exc)[:300],
                **self._page_diagnostics(page),
            }
            return None

    def _try_epoint_jigsaw_download(
        self,
        page: Any,
        context: Any,
        attachment_url: str,
        tmp_dir: str,
    ) -> str | None:
        captcha_url = _epoint_jigsaw_captcha_url(attachment_url)
        if not captcha_url:
            return None

        verify_referer = _epoint_page_verify_url(attachment_url)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": verify_referer,
        }
        for attempt in range(1, self.jigsaw_attempts + 1):
            try:
                get_response = context.request.post(
                    captcha_url,
                    data=urlencode({"step": "get", "captchaType": "blockpuzzle"}),
                    headers=headers,
                    timeout=self.timeout_ms,
                )
                if not get_response.ok:
                    self._last_browser_diagnostics["jigsaw_get_status"] = get_response.status
                    continue
                captcha_data = _json_response(get_response)
                solution = _solve_blockpuzzle_offset(
                    str(captcha_data.get("originalImageBase64") or ""),
                    str(captcha_data.get("jigsawImageBase64") or ""),
                )
                verify_code_id = str(captcha_data.get("captchaID") or "")
                track = _build_blockpuzzle_track(
                    source_x=int(solution["source_x"]),
                    original_width=int(solution["original_width"]),
                )
                check_payload = {
                    "step": "check",
                    "captchaType": "blockpuzzle",
                    "verifyCodeId": verify_code_id,
                    "offsetX": str(solution["offset_x"]),
                    "track": json.dumps(track, ensure_ascii=False, separators=(",", ":")),
                }
                check_response = context.request.post(
                    captcha_url,
                    data=urlencode(check_payload),
                    headers=headers,
                    timeout=self.timeout_ms,
                )
                check_data = _json_response(check_response) if check_response.ok else {}
                validate_code = str(check_data.get("validateCode") or "")
                self._last_browser_diagnostics.update(
                    {
                        "jigsaw_attempt": attempt,
                        "jigsaw_source_x": solution["source_x"],
                        "jigsaw_offset_x": solution["offset_x"],
                        "jigsaw_score": solution["score"],
                        "jigsaw_validate_success": bool(check_data.get("success")),
                        "jigsaw_validate_code_present": bool(validate_code),
                    }
                )
                if not check_data.get("success") or not validate_code:
                    continue
                download_path = self._try_verified_request_download(
                    context,
                    attachment_url=attachment_url,
                    verification_code=validate_code,
                    verification_guid=validate_code,
                    tmp_dir=tmp_dir,
                    referer_url=page.url,
                )
                if download_path:
                    self._last_browser_diagnostics["jigsaw_resolution_state"] = "VERIFIED_ACTION_DOWNLOAD"
                    return download_path
            except Exception as exc:
                self._last_browser_diagnostics["jigsaw_attempt_error"] = f"{type(exc).__name__}:{str(exc)[:240]}"
                continue
        return None

    def _try_request_download(
        self,
        context: Any,
        attachment_url: str,
        tmp_dir: str,
        *,
        referer_url: str | None = None,
    ) -> str | None:
        response = context.request.get(
            attachment_url,
            headers={"Referer": referer_url or _same_site_referer_url(attachment_url)},
            timeout=self.timeout_ms,
        )
        if not response.ok:
            return None
        content_type = (response.headers.get("content-type") or "").lower()
        body = response.body()
        if not body or ("html" in content_type and b"%PDF" not in body[:20]):
            return None
        save_path = str(Path(tmp_dir) / _filename_from_url(attachment_url))
        Path(save_path).write_bytes(body)
        return save_path

    def _try_guangdong_ygp_download(
        self,
        context: Any,
        *,
        attachment_url: str,
        tmp_dir: str,
        referer_url: str | None,
    ) -> str | None:
        if not _guangdong_ygp_download_url(attachment_url):
            return None
        base_headers = {
            "Accept": "application/octet-stream,application/pdf,application/zip,*/*",
            "Referer": referer_url or "https://ygp.gdzwfw.gov.cn/",
        }
        attempts = [
            ("referer_request", base_headers),
            (
                "signed_public_request",
                {
                    **base_headers,
                    **_guangdong_ygp_signature_headers(
                        _guangdong_ygp_download_signature_params(attachment_url)
                    ),
                },
            ),
        ]
        for attempt_name, headers in attempts:
            try:
                response = context.request.get(
                    attachment_url,
                    headers=headers,
                    timeout=self.timeout_ms,
                )
                path = _save_download_response_if_file(
                    response,
                    tmp_dir=tmp_dir,
                    fallback_filename=_filename_from_url(attachment_url),
                )
                self._last_browser_diagnostics[f"guangdong_ygp_{attempt_name}_status"] = getattr(
                    response,
                    "status",
                    "",
                )
                if path:
                    self._last_browser_diagnostics["guangdong_ygp_resolution_state"] = attempt_name
                    return path
            except Exception as exc:
                self._last_browser_diagnostics[f"guangdong_ygp_{attempt_name}_error"] = (
                    f"{type(exc).__name__}:{str(exc)[:240]}"
                )
        return None

    def _try_page_verify_ocr_download(
        self,
        page: Any,
        context: Any,
        attachment_url: str,
        tmp_dir: str,
    ) -> str | None:
        frame = self._page_verify_frame(page)
        if frame is None:
            self._click_attachment_anchor(page, attachment_url)
            frame = self._page_verify_frame(page)
        if frame is None:
            return None
        for attempt in range(1, self.ocr_attempts + 1):
            try:
                img = frame.locator("#imgVerify")
                img.wait_for(state="visible", timeout=5000)
                image_path = str(Path(tmp_dir) / f"page_verify_{attempt}.png")
                img.screenshot(path=image_path)
                code = _ocr_verification_code(image_path)
                guid = str(frame.locator("#imgguid").input_value(timeout=2000) or "").strip()
                self._last_browser_diagnostics["last_ocr_code_length"] = len(code)
                self._last_browser_diagnostics["last_verification_guid_present"] = bool(guid)
                if len(code) < 4 or not guid:
                    frame.locator("#imgclick").click(timeout=2000)
                    continue
                direct_path = self._try_verified_request_download(
                    context,
                    attachment_url=attachment_url,
                    verification_code=code,
                    verification_guid=guid,
                    tmp_dir=tmp_dir,
                    referer_url=page.url,
                )
                if direct_path:
                    self._last_browser_diagnostics["ocr_resolution_state"] = "VERIFIED_REQUEST_DOWNLOAD"
                    return direct_path
                frame.locator("#yzm").fill(code, timeout=2000)
                try:
                    with page.expect_download(timeout=8000) as download_info:
                        page.locator(".layui-layer-btn0, .layui-layer-btn a").first.click(timeout=3000)
                    download = download_info.value
                    save_path = str(Path(tmp_dir) / (download.suggested_filename or _filename_from_url(attachment_url)))
                    download.save_as(save_path)
                    self._last_browser_diagnostics["ocr_resolution_state"] = "BROWSER_LAYER_CONFIRM_DOWNLOAD"
                    return save_path
                except Exception as exc:
                    self._last_browser_diagnostics["last_ocr_submit_error"] = type(exc).__name__
                    frame.locator("#imgclick").click(timeout=2000)
            except Exception as exc:
                self._last_browser_diagnostics["ocr_attempt_error"] = f"{type(exc).__name__}:{str(exc)[:200]}"
                return None
        return None

    def _click_attachment_anchor(self, page: Any, attachment_url: str) -> bool:
        attach_guid = _query_param(attachment_url, "attachGuid")
        selectors = []
        if attach_guid:
            selectors.append(f"a[onclick*='{attach_guid}']")
        selectors.append(f"a[href='{attachment_url}']")
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() > 0:
                    locator.scroll_into_view_if_needed(timeout=3000)
                    locator.click(timeout=5000)
                    return True
            except Exception:
                continue
        try:
            return bool(
                page.evaluate(
                    """
                    ({targetUrl, attachGuid}) => {
                      const anchors = Array.from(document.querySelectorAll('a'));
                      const match = anchors.find((a) => {
                        const href = a.href || '';
                        const onclick = a.getAttribute('onclick') || '';
                        return href === targetUrl
                          || href.includes(targetUrl)
                          || onclick.includes(targetUrl)
                          || (attachGuid && (href.includes(attachGuid) || onclick.includes(attachGuid)));
                      });
                      if (!match) return false;
                      match.click();
                      return true;
                    }
                    """,
                    {"targetUrl": attachment_url, "attachGuid": attach_guid},
                )
            )
        except Exception:
            return False

    def _try_verified_request_download(
        self,
        context: Any,
        *,
        attachment_url: str,
        verification_code: str,
        verification_guid: str,
        tmp_dir: str,
        referer_url: str | None = None,
    ) -> str | None:
        action_url = _epoint_attachment_action_url(
            attachment_url,
            verification_code=verification_code,
            verification_guid=verification_guid,
        )
        if not action_url:
            return None
        response = context.request.post(
            action_url,
            headers={"Referer": referer_url or attachment_url},
            timeout=self.timeout_ms,
        )
        body = response.body()
        content_type = (response.headers.get("content-type") or "").lower()
        if not response.ok or not body:
            return None
        if b"validateVerificationCode" in body[:500] or b"pageVerify" in body[:500]:
            return None
        if "html" in content_type and not body.lstrip().startswith(b"%PDF"):
            return None
        filename = _filename_from_content_disposition(response.headers.get("content-disposition") or "")
        save_path = str(Path(tmp_dir) / (filename or _filename_from_url(attachment_url)))
        Path(save_path).write_bytes(body)
        return save_path

    def _page_verify_frame(self, page: Any) -> Any | None:
        try:
            page.wait_for_selector("iframe[src*='pageVerify']", timeout=5000)
        except Exception:
            pass
        for frame in page.frames:
            if "pageVerify.html" in (frame.url or ""):
                return frame
        return None

    def _page_diagnostics(self, page: Any) -> dict[str, Any]:
        try:
            body_text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            body_text = ""
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            current_url = page.url
        except Exception:
            current_url = ""
        selectors = {
            "captcha_images": "img[src*='captcha'], img[src*='verify'], img[src*='Verify'], img[src*='valid']",
            "captcha_inputs": "input[name*='verif'], input[id*='verif'], input[name*='code'], input[id*='code']",
            "jigsaw_widgets": ".mini-jigsawverify, .mini-jigsawverify-jigsaw, .mini-jigsawverify-scroller-thumb",
            "dialogs": ".mini-window, .layui-layer, .modal, [role='dialog']",
            "download_forms": "form[action*='Download'], form[action*='download'], form[action*='getContent']",
        }
        counts: dict[str, int] = {}
        for name, selector in selectors.items():
            try:
                counts[name] = page.locator(selector).count()
            except Exception:
                counts[name] = 0
        return {
            "page_title": title,
            "page_url": current_url,
            "body_excerpt": body_text[:500],
            "selector_counts": counts,
        }


def _filename_from_url(url: str) -> str:
    name = urlsplit(url).path.rsplit("/", 1)[-1] or "attachment.bin"
    return name if "." in name else f"{name}.bin"


def _same_site_referer_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def _guangdong_ygp_download_url(url: str) -> bool:
    parsed = urlsplit(str(url or ""))
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "ygp.gdzwfw.gov.cn"
        and "/ggzy-portal/base/sys-file/download/" in parsed.path.lower()
    )


def _guangdong_ygp_download_signature_params(url: str) -> dict[str, str]:
    parsed = urlsplit(str(url or ""))
    parts = [part for part in parsed.path.split("/") if part]
    params: dict[str, str] = {}
    try:
        download_index = parts.index("download")
        params["version"] = parts[download_index + 1]
        params["rowGuid"] = parts[download_index + 2]
    except (ValueError, IndexError):
        pass
    query_values = parse_qs(parsed.query, keep_blank_values=True)
    for key, values in query_values.items():
        if values:
            params[key] = str(values[0] or "")
    if parsed.query and "=" not in parsed.query:
        params["flowId"] = parsed.query
    return params


def _guangdong_ygp_signature_headers(params: Mapping[str, Any]) -> dict[str, str]:
    nonce = os.urandom(12).hex()[:16]
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


def _guangzhou_ywtb_download_url(url: str) -> bool:
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path or "").lower()
    return host == "ywtb.gzggzy.cn" and (
        "downloadztbattach" in path or "ztbattachdownloadaction.action" in path
    )


def _guangzhou_ywtb_dom_download_candidates(page: Any) -> list[dict[str, str]]:
    script = """
    () => Array.from(document.querySelectorAll('a,button,[onclick],[href]')).map((el) => {
      const href = el.getAttribute('href') || '';
      const dataUrl = el.getAttribute('data-url') || el.getAttribute('data-href') || '';
      const onclick = el.getAttribute('onclick') || '';
      const text = (el.innerText || el.textContent || el.getAttribute('title') || '').trim();
      const values = [href, dataUrl, onclick].filter(Boolean);
      return values.map((value) => {
        const match = value.match(/['"]([^'"]*downloadztbattach[^'"]*)['"]/i);
        const rawUrl = match ? match[1] : value;
        let url = rawUrl;
        try { url = new URL(rawUrl, location.href).href; } catch (e) {}
        return {url, text};
      });
    }).flat()
    """
    try:
        raw_items = page.evaluate(script)
    except Exception:
        return []
    items: list[dict[str, str]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, Mapping):
            continue
        url = str(raw.get("url") or "").strip()
        if not _guangzhou_ywtb_download_url(url):
            continue
        items.append({"url": url, "text": str(raw.get("text") or "")})
    return items


def _guangzhou_ywtb_click_probe(page: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    try:
        locator = page.locator("a,button,[onclick]")
        count = min(int(locator.count()), 80)
    except Exception:
        return items
    for index in range(count):
        try:
            element = locator.nth(index)
            text = (element.inner_text(timeout=500) or "").strip()
            attrs = " ".join(
                str(element.get_attribute(name, timeout=500) or "")
                for name in ("href", "onclick", "title", "data-url", "data-href")
            )
            if not _guangzhou_ywtb_probe_text_or_attrs(text, attrs):
                continue
            before = set(item["url"] for item in _guangzhou_ywtb_dom_download_candidates(page))
            try:
                element.click(timeout=1200, no_wait_after=True)
            except Exception:
                pass
            time.sleep(0.2)
            after = _guangzhou_ywtb_dom_download_candidates(page)
            for candidate in after:
                if candidate["url"] not in before:
                    items.append({"url": candidate["url"], "text": text or candidate.get("text", "")})
        except Exception:
            continue
    return items


def _guangzhou_ywtb_probe_text_or_attrs(text: str, attrs: str) -> bool:
    combined = f"{text} {attrs}".lower()
    return any(
        token in combined
        for token in (
            "附件",
            "下载",
            "招标文件",
            "招标资料",
            "招标公告",
            "downloadztbattach",
            "ztbfjyz",
        )
    )


def _guangzhou_ywtb_download_discovery_state(*, body_text: str, html: str, candidate_count: int) -> str:
    if candidate_count > 0:
        return "DOWNLOAD_ENDPOINT_CAPTURED"
    text = f"{body_text or ''}\n{html or ''}"
    lowered = text.lower()
    if any(token in text for token in ("数字证书", "CA锁", "CA证书", "CA 登录", "CA登录", "粤商通")):
        return "LOGIN_OR_CA_REQUIRED"
    if any(token in text for token in ("请登录", "用户登录", "登录后", "登录系统", "会员登录")):
        return "LOGIN_OR_CA_REQUIRED"
    if any(token in text for token in ("验证码", "滑块", "拖动", "captcha", "blockpuzzle")):
        return "CHALLENGE_REQUIRED"
    if any(token in lowered for token in ("ztbfjyz", "downloadztbattach", "attachguid", "appurlflag")):
        return "SCRIPT_ENDPOINT_UNRESOLVED"
    return "NO_PUBLIC_DOWNLOAD_ENDPOINT"


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


def _safe_page_title(page: Any) -> str:
    try:
        return str(page.title() or "")
    except Exception:
        return ""


def _save_download_response_if_file(response: Any, *, tmp_dir: str, fallback_filename: str) -> str | None:
    if not response.ok:
        return None
    body = response.body()
    if not body:
        return None
    content_type = (response.headers.get("content-type") or "").lower()
    if "html" in content_type and not body.lstrip().startswith((b"%PDF", b"PK\x03\x04")):
        return None
    if not (
        body.startswith(b"%PDF")
        or body.startswith(b"PK\x03\x04")
        or body.startswith(b"\xd0\xcf\x11\xe0")
        or any(
            token in content_type
            for token in ("pdf", "zip", "msword", "officedocument", "excel", "spreadsheet", "octet-stream")
        )
    ):
        return None
    filename = _filename_from_content_disposition(response.headers.get("content-disposition") or "")
    save_path = str(Path(tmp_dir) / (filename or fallback_filename))
    Path(save_path).write_bytes(body)
    return save_path


def _query_param(url: str, name: str) -> str:
    values = parse_qs(urlsplit(url).query).get(name) or []
    return values[0] if values else ""


def _epoint_attachment_action_url(
    attachment_url: str,
    *,
    verification_code: str,
    verification_guid: str,
) -> str:
    parsed = urlsplit(attachment_url)
    params = parse_qs(parsed.query)
    path = parsed.path
    if "downloadztbattach" not in path.lower():
        return ""
    base_path = path.rsplit("/", 1)[0] + "/ztbAttachDownloadAction.action"
    action_params = {
        "cmd": "getContent",
        "attachGuid": (params.get("attachGuid") or [""])[0],
        "appUrlFlag": (params.get("appUrlFlag") or [""])[0],
        "siteGuid": (params.get("siteGuid") or [""])[0],
        "verificationCode": verification_code,
        "verificationGuid": verification_guid,
        "attachpath": (params.get("attachpath") or [""])[0],
    }
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            base_path,
            urlencode(action_params),
            "",
        )
    )


def _epoint_jigsaw_captcha_url(attachment_url: str) -> str:
    parsed = urlsplit(attachment_url)
    root = _epoint_builder_root_path(parsed.path)
    if not root:
        return ""
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{root}/rest/shellcaptcha/initAndCheckCaptcha",
            "",
            "",
        )
    )


def _epoint_page_verify_url(attachment_url: str) -> str:
    parsed = urlsplit(attachment_url)
    root = _epoint_builder_root_path(parsed.path) or "/EpointWebBuilder"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{root}/frame/pages/login/pageVerify.html",
            "",
            "",
        )
    )


def _epoint_builder_root_path(path: str) -> str:
    match = re.search(r"(?i)(/EpointWebBuilder[^/]*)/", str(path or ""))
    if not match:
        return ""
    return match.group(1)


def _json_response(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        try:
            data = json.loads(response.text())
        except Exception:
            return {}
    if isinstance(data, Mapping):
        custom = data.get("custom")
        if isinstance(custom, Mapping):
            merged = dict(data)
            merged.update(dict(custom))
            return merged
        return dict(data)
    return {}


def _solve_blockpuzzle_offset(original_image_base64: str, jigsaw_image_base64: str) -> dict[str, float | int]:
    try:
        from PIL import Image, ImageFilter, ImageOps
    except Exception as exc:  # pragma: no cover - optional image dependency
        raise RuntimeError(f"jigsaw_image_runtime_unavailable:{exc}") from exc
    if not original_image_base64 or not jigsaw_image_base64:
        raise RuntimeError("jigsaw_images_missing")
    original = Image.open(BytesIO(base64.b64decode(original_image_base64))).convert("RGB")
    piece = Image.open(BytesIO(base64.b64decode(jigsaw_image_base64))).convert("RGBA")
    alpha = piece.getchannel("A").point(lambda value: 255 if value > 32 else 0)
    boundary = (
        alpha.filter(ImageFilter.FIND_EDGES)
        .point(lambda value: 255 if value > 0 else 0)
        .filter(ImageFilter.MaxFilter(5))
    )
    boundary_pixels = [
        (px, py)
        for py in range(piece.height)
        for px in range(piece.width)
        if boundary.getpixel((px, py)) > 0
    ]
    if not boundary_pixels:
        raise RuntimeError("jigsaw_boundary_missing")
    edge_image = ImageOps.grayscale(original).filter(ImageFilter.FIND_EDGES)
    best_score = -1.0
    best_x = 0
    for x in range(0, max(1, original.width - piece.width + 1)):
        score = sum(edge_image.getpixel((x + px, py)) for px, py in boundary_pixels) / len(boundary_pixels)
        if score > best_score:
            best_score = float(score)
            best_x = x
    return {
        "source_x": best_x,
        "offset_x": best_x / max(1, original.width),
        "score": round(best_score, 4),
        "original_width": original.width,
        "original_height": original.height,
        "piece_width": piece.width,
        "piece_height": piece.height,
    }


def _build_blockpuzzle_track(*, source_x: int, original_width: int) -> list[dict[str, float]]:
    ui_width = 300.0
    piece_width = 45.0
    scroller_width = 298.0
    thumb_width = 30.0
    source_to_ui_ratio = ui_width / max(1.0, float(original_width))
    piece_left_ui = float(source_x) * source_to_ui_ratio
    piece_to_drag_ratio = (ui_width - piece_width) / (scroller_width - thumb_width)
    target = max(0.0, min(scroller_width - thumb_width, piece_left_ui / piece_to_drag_ratio))
    points: list[dict[str, float]] = []
    for index in range(1, 36):
        t = index / 35.0
        eased = 1 - (1 - t) ** 3
        x = target * eased
        y = math.sin(t * math.pi * 2) * 1.2
        points.append({"x": round(x, 2), "y": round(y, 2)})
    points.extend(
        [
            {"x": round(min(scroller_width - thumb_width, target + 1.1), 2), "y": 0.3},
            {"x": round(max(0.0, target - 0.2), 2), "y": -0.1},
            {"x": round(target, 2), "y": 0.0},
        ]
    )
    return points


def _filename_from_content_disposition(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
    if match:
        return _safe_filename(unquote(match.group(1)))
    match = re.search(r'filename="?([^";]+)"?', value, flags=re.IGNORECASE)
    if not match:
        return ""
    filename = match.group(1).strip()
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            filename = filename.encode("latin-1").decode(encoding)
            break
        except UnicodeError:
            continue
    return _safe_filename(filename)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().strip(".")
    return cleaned[:180]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _detail_page_still_blocked(html: str, text: str) -> bool:
    combined = f"{html or ''}\n{text or ''}".lower()
    if len((text or "").strip()) < 80 and len((html or "").strip()) < 500:
        return True
    return any(
        token.lower() in combined
        for token in (
            "请先登录",
            "请登录",
            "用户登录",
            "验证码",
            "captcha",
            "人机验证",
            "安全验证",
        )
    )


def _ocr_verification_code(image_path: str) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageFilter, ImageOps
    except Exception as exc:  # pragma: no cover - optional OCR dependency
        raise RuntimeError(f"ocr_runtime_unavailable:{exc}") from exc
    image = Image.open(image_path).convert("L")
    image = ImageOps.autocontrast(image)
    image = image.resize((image.width * 3, image.height * 3))
    image = image.filter(ImageFilter.MedianFilter(size=3))
    raw = pytesseract.image_to_string(
        image,
        config=(
            "--psm 7 "
            "-c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ),
    )
    return re.sub(r"[^0-9A-Za-z]", "", raw or "")[:6]


def _content_type_from_file(path: str) -> str:
    data = Path(path).read_bytes()[:16]
    if data.startswith(b"%PDF"):
        return "application/pdf"
    return _content_type_from_filename(path)


def _content_type_from_filename(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".doc":
        return "application/msword"
    if suffix == ".xls":
        return "application/vnd.ms-excel"
    if suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    return "application/octet-stream"
