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
    REAL_PUBLIC_ENTRY_FETCH_MODE,
    REAL_PUBLIC_ENTRY_FETCHER_ID,
    REAL_PUBLIC_ENTRY_PROFILES,
    REAL_PUBLIC_ENTRY_SNAPSHOT_KIND,
    RealPublicEntryFetcher,
    RealPublicFetchResponse,
    RealPublicUrlBoundaryError,
)
from stage2_ingestion.service import Stage2Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


GGZY_ENTRY_URL = "https://www.ggzy.gov.cn/deal/dealList.html"
CCGP_ENTRY_URL = "https://www.ccgp.gov.cn/cggg/zygg/"


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


class Stage2RealPublicUrlFetcherTests(unittest.TestCase):
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
            self.assertFalse(carrier["redlines"]["uncontrolled_live_crawler_used"])
            self.assertFalse(carrier["redlines"]["real_provider_call_executed"])

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

    def test_error_login_captcha_or_empty_shell_degrades_fail_closed(self) -> None:
        blocked_body = (
            "<html><head><title>错误页面</title></head>"
            "<body>请先登录，验证码，人机验证</body></html>"
        ).encode("utf-8")
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_ENTRY_URL: RealPublicFetchResponse(
                    url=CCGP_ENTRY_URL,
                    status_code=200,
                    content=blocked_body,
                    content_type="text/html",
                    final_url=CCGP_ENTRY_URL,
                )
            }
        )
        carrier = RealPublicEntryFetcher(transport=transport, repository=None).fetch_entry_url(
            CCGP_ENTRY_URL,
            profile_id="CCGP-CENTRAL-NOTICES",
        )

        self.assertEqual(carrier["status"], "DEGRADED")
        self.assertTrue(carrier["review_required"])
        self.assertTrue(carrier["fail_closed"])
        self.assertIsNone(carrier["snapshot_id_optional"])
        self.assertIn("entry_body_too_small", carrier["degraded_reasons"])
        self.assertIn("visible_entry_markers_missing", carrier["degraded_reasons"])
        self.assertTrue(
            any(reason.startswith("blocked_body_pattern:") for reason in carrier["degraded_reasons"])
        )

    def test_profiles_are_total_entry_urls_not_detail_pages(self) -> None:
        for profile in REAL_PUBLIC_ENTRY_PROFILES:
            self.assertNotEqual(profile.url, profile.sample_detail_url, profile.profile_id)
            self.assertTrue(profile.url.startswith("https://"), profile.profile_id)
            self.assertNotIn("/information/deal/html/", profile.url, profile.profile_id)
            if profile.profile_id != "GGZY-DEAL-LIST":
                self.assertTrue(profile.url.endswith("/"), profile.profile_id)
            self.assertRegex(profile.sample_detail_url, r"\.(html|htm)$")

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
