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
from stage2_ingestion.real_candidate_capture import (
    REAL_CANDIDATE_STAGE2_CAPTURE_MODE,
    RealCandidateStage2CaptureRepository,
    RealCandidateStage2CaptureService,
    list_real_candidate_stage2_captures,
)
from stage2_ingestion.real_public_url_fetcher import (
    RealPublicEntryFetcher,
    RealPublicFetchResponse,
)
from storage import reset_default_storage
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


CCGP_DETAIL_URL = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_0000001.htm"
CCGP_ATTACHMENT_URL = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/notice.pdf"


class FakeRealPublicFetchTransport:
    def __init__(self, responses: dict[str, RealPublicFetchResponse]) -> None:
        self.responses = responses
        self.call_log: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float, user_agent: str) -> RealPublicFetchResponse:
        self.call_log.append(url)
        return self.responses[url]


class FakeStage2Service:
    def __init__(self, transport: FakeRealPublicFetchTransport) -> None:
        self.transport = transport

    def fetch_real_public_candidate_detail_url(
        self,
        url: str,
        *,
        profile_id: str,
        repository: ObjectStorageRepository | None = None,
        lineage_refs: dict[str, str] | None = None,
    ) -> dict:
        return RealPublicEntryFetcher(
            repository=repository,
            transport=self.transport,
        ).fetch_candidate_detail_url(url, profile_id=profile_id, lineage_refs=lineage_refs)

    def fetch_real_public_same_site_attachment_url(
        self,
        url: str,
        *,
        parent_profile_id: str,
        repository: ObjectStorageRepository | None = None,
        lineage_refs: dict[str, str] | None = None,
        detail_page_url: str | None = None,
    ) -> dict:
        return RealPublicEntryFetcher(
            repository=repository,
            transport=self.transport,
        ).fetch_same_site_attachment_url(
            url,
            parent_profile_id=parent_profile_id,
            lineage_refs=lineage_refs,
            detail_page_url=detail_page_url,
        )


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
        <p>中标供应商名称：北京测试科技有限公司 供应商地址：北京市海淀区测试路1号</p>
        <p>中标（成交）金额：1280.50 万元（人民币）</p>
        <p><a href="./files/notice.pdf">附件：中标公告原文下载</a></p>
      </body>
    </html>
    """
    return html.encode("utf-8")


class RealCandidateStage2CaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def test_captures_detail_snapshot_parses_fields_enriches_candidate_and_persists_readback(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_DETAIL_URL: RealPublicFetchResponse(
                    url=CCGP_DETAIL_URL,
                    status_code=200,
                    content=_ccgp_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=CCGP_DETAIL_URL,
                ),
                CCGP_ATTACHMENT_URL: RealPublicFetchResponse(
                    url=CCGP_ATTACHMENT_URL,
                    status_code=200,
                    content=b"%PDF-1.4\nreal public attachment\n",
                    content_type="application/pdf",
                    final_url=CCGP_ATTACHMENT_URL,
                )
            }
        )
        candidate = {
            "candidate_key": "real-candidate-001",
            "notice_id": "NOTICE-REAL-001",
            "project_id": "PROJ-REAL-001",
            "project_name": "列表页标题待详情校正",
            "region_code": "CN-GD",
            "project_type": "municipal",
            "notice_stage": "tender_notice",
            "source_url": CCGP_DETAIL_URL,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _repo(tmp_dir)
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=repo,
                repository=RealCandidateStage2CaptureRepository(),
            )

            result = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:00:00+00:00",
                detail_capture_limit=1,
            )

            self.assertEqual(result["capture_mode"], REAL_CANDIDATE_STAGE2_CAPTURE_MODE)
            self.assertEqual(result["detail_snapshot_count"], 1)
            self.assertEqual(result["stage3_parse_success_count"], 1)
            self.assertEqual(result["attachment_link_count"], 1)
            self.assertEqual(result["attachment_capture_attempted_count"], 1)
            self.assertEqual(result["attachment_snapshot_count"], 1)
            enriched = result["enriched_candidates"][0]
            self.assertEqual(enriched["stage2_detail_capture_state"], "FETCHED")
            self.assertEqual(enriched["stage3_detail_parse_state"], "PARSED")
            self.assertEqual(enriched["project_name"], "北京科技大学煤气管网检测装置采购项目")
            self.assertEqual(enriched["amount"], 12_805_000.0)
            self.assertEqual(enriched["candidate_company"], "北京测试科技有限公司")
            self.assertEqual(enriched["objection_deadline_at_optional"], "2026-04-30T23:59:59+08:00")
            self.assertEqual(enriched["candidate_count"], 1)
            self.assertIn("candidate_company", enriched["key_fields_present"])
            self.assertEqual(enriched["source_document_ref"], enriched["stage2_detail_snapshot_id_optional"])
            self.assertEqual(enriched["stage2_attachment_snapshot_count"], 1)
            self.assertEqual(len(enriched["stage2_attachment_snapshot_ids"]), 1)
            self.assertIn(enriched["stage2_attachment_snapshot_ids"][0], enriched["real_snapshot_ids"])

        catalog = list_real_candidate_stage2_captures()
        self.assertEqual(catalog["capture_count"], 1)
        self.assertEqual(catalog["captures"][0]["candidate_key"], "real-candidate-001")
        self.assertEqual(catalog["captures"][0]["detail_capture_status"], "FETCHED")
        self.assertEqual(catalog["captures"][0]["attachment_snapshot_count"], 1)
        self.assertEqual(transport.call_log, [CCGP_DETAIL_URL, CCGP_ATTACHMENT_URL])


if __name__ == "__main__":
    unittest.main()
