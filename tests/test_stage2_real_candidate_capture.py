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


def _candidate_table_detail_html() -> bytes:
    html = """
    <html>
      <head><title>霞山区农村供水一体化工程监理评标报告</title></head>
      <body>
        <h1>霞山区农村供水一体化工程监理评标报告</h1>
        <p>公告内容 龙头镇通村入户便民利民提升工程项目(一期)监理 中标候选人公示</p>
        <p>评标情况 第一中标候选人 投标报价 中唯耘源建设管理有限公司 510,573.09 元</p>
        <p>监理工程师注册证书，注册编号:51010186 资质资格 业绩 拟派项目负责人姓名 资格能力条件 苟瑾</p>
        <p>第二中标候选人 投标报价 四川省城市建设工程咨询集团有限公司 508,251.135 元</p>
        <p>公示结束时间：2026年05月08日</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _unit_name_table_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东警官学院嘉禾校区警体馆建设工程项目施工监理评标报告</title></head>
      <body>
        <h1>广东警官学院嘉禾校区警体馆建设工程项目施工监理评标报告</h1>
        <section><h2>公告内容</h2>
          <table>
            <thead><tr><th>序号</th><th>单位名称</th><th>报价（元）</th></tr></thead>
            <tbody>
              <tr><td></td><td>深圳科宇工程顾问有限公司</td><td>2005925.0</td></tr>
              <tr><td>1</td><td>广州珠江监理咨询集团有限公司</td><td>1974252.5</td></tr>
            </tbody>
          </table>
        </section>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _unit_name_table_with_pdf_attachment_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东机电安装工程评标报告</title></head>
      <body>
        <h1>广东机电安装工程评标报告</h1>
        <section><h2>公告内容</h2>
          <table>
            <thead><tr><th>序号</th><th>单位名称</th><th>报价（元）</th></tr></thead>
            <tbody>
              <tr><td>1</td><td>广东省机电建设有限公司</td><td>12000000.0</td></tr>
            </tbody>
          </table>
          <p><a href="https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/gd-manager.pdf">评标报告（隐去评标委员会姓名版）.pdf</a></p>
        </section>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _candidate_summary_table_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东省茂名市施工监理评标报告</title></head>
      <body>
        <h1>广东省茂名市施工监理评标报告</h1>
        <section><h2>公告内容</h2>
          <p>推荐中标人候选人如下：</p>
          <p>中标候选人单位 投标报价（元） 项目经理姓名</p>
          <p>第一中标候选人 广东协立工程咨询监理有限公司 350330.00 阳青波</p>
          <p>第二中标候选人 广东国安建设管理有限公司 348856.50 陈家裕</p>
        </section>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _transposed_candidate_table_detail_html() -> bytes:
    html = """
    <html>
      <head><title>肇庆市鼎湖区合盛石化能源有限公司永贝大道加油站项目（施工）评标报告</title></head>
      <body>
        <h1>肇庆市鼎湖区合盛石化能源有限公司永贝大道加油站项目（施工）评标报告</h1>
        <section><h2>公告内容</h2>
          <p>评标委员会推荐的评审结果为（评审资料附后）：</p>
          <p>中标候选人 第一中标候选人 第二中标候选人 第三中标候选人</p>
          <p>单位名称 肇庆市盛建工程建设有限公司 广东金华城建设集团有限公司 肇庆市高要区恒安水利水电工程有限公司</p>
          <p>项目负责人 刘忠贵 陈宝怡 郑聪</p>
          <p>投标报价（元） 4716885.29 4491518.11 4742375.69</p>
        </section>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _contextual_manager_alias_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东机电安装工程中标候选人公示</title></head>
      <body>
        <h1>广东机电安装工程中标候选人公示</h1>
        <p>第一中标候选人 广东省机电建设有限公司 投标报价 12000000.00 元</p>
        <p>施工负责人：张建明 一级建造师 机电工程 职称：高级工程师</p>
        <p>公示结束时间：2026年05月08日</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _supervision_chief_engineer_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东学校扩建工程监理中标候选人公示</title></head>
      <body>
        <h1>广东学校扩建工程监理中标候选人公示</h1>
        <p>第一中标候选人 广东省工程监理有限公司 投标报价 980000.00 元</p>
        <p>总监理工程师：李明 注册监理工程师 注册号: 44030186 职称：高级工程师</p>
        <p>公示结束时间：2026年05月08日</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _design_lead_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东产业园更新改造设计中标候选人公示</title></head>
      <body>
        <h1>广东产业园更新改造设计中标候选人公示</h1>
        <p>第一中标候选人 广东省建筑设计研究院有限公司 投标报价 3200000.00 元</p>
        <p>设计负责人：王磊 一级注册建筑师 建筑工程 职称：高级工程师</p>
        <p>公示结束时间：2026年05月08日</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _survey_lead_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东地下管网勘察中标候选人公示</title></head>
      <body>
        <h1>广东地下管网勘察中标候选人公示</h1>
        <p>第一中标候选人 广东岩土工程勘察有限公司 投标报价 2100000.00 元</p>
        <p>勘察负责人：赵岩 注册土木工程师（岩土） 岩土工程 职称：工程师</p>
        <p>公示结束时间：2026年05月08日</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _generic_responsible_person_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东材料采购中标公告</title></head>
      <body>
        <h1>广东材料采购中标公告</h1>
        <p>中标供应商名称：广东建筑工程有限公司</p>
        <p>采购负责人：王五 联系电话 020-00000000</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _project_code_without_manager_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广州装修工程评标报告</title></head>
      <body>
        <h1>广州装修工程评标报告</h1>
        <p>第一中标候选人 广州装修工程有限公司 投标报价 10000000.00 元</p>
        <p>招标编号：JG2026-11144 项目编号：E4401000000000001</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _company_fragment_after_manager_label_detail_html() -> bytes:
    html = """
    <html>
      <head><title>绿色化工基础设施勘察设计评标报告</title></head>
      <body>
        <h1>绿色化工基础设施勘察设计评标报告</h1>
        <p>第一中标候选人 中国华西工程设计建设有限公司</p>
        <p>项目负责人 一方设计集团有限公司 质量承诺 合格</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _build_text_pdf_bytes(lines: list[str]) -> bytes:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except Exception as exc:  # pragma: no cover - optional test rendering dependency
        raise unittest.SkipTest(f"reportlab unavailable: {exc}") from exc
    from io import BytesIO

    buffer = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    page = canvas.Canvas(buffer)
    page.setFont("STSong-Light", 12)
    y = 780
    for line in lines:
        page.drawString(72, y, line)
        y -= 24
    page.save()
    return buffer.getvalue()


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
            self.assertNotIn("objection_deadline_at_optional", enriched)
            self.assertEqual(
                result["captures"][0]["detail_fields"]["objection_deadline_parse_state"],
                "DETAIL_TEXT_NOT_FOUND",
            )
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

    def test_default_capture_limit_covers_all_input_candidates_and_summarizes_failures(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_DETAIL_URL: RealPublicFetchResponse(
                    url=CCGP_DETAIL_URL,
                    status_code=200,
                    content=_ccgp_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=CCGP_DETAIL_URL,
                ),
            }
        )
        valid_candidate = {
            "candidate_key": "real-candidate-default-limit-001",
            "notice_id": "NOTICE-REAL-DEFAULT-001",
            "project_id": "PROJ-REAL-DEFAULT-001",
            "project_name": "列表页标题待详情校正",
            "region_code": "CN-GD",
            "project_type": "municipal",
            "notice_stage": "candidate_notice",
            "source_url": CCGP_DETAIL_URL,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }
        missing_url_candidate = {
            **valid_candidate,
            "candidate_key": "real-candidate-default-limit-002",
            "notice_id": "NOTICE-REAL-DEFAULT-002",
            "project_id": "PROJ-REAL-DEFAULT-002",
            "source_url": "",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )

            result = service.capture_candidates(
                [valid_candidate, missing_url_candidate],
                now="2026-05-01T00:00:00+00:00",
            )

        self.assertEqual(result["capture_limit"], 2)
        self.assertEqual(result["capture_limit_source"], "ALL_INPUT_CANDIDATES")
        self.assertEqual(result["capture_execution_strategy"], "ALL_CANDIDATES_RESUMABLE_WITH_TIME_BUDGET")
        self.assertFalse(result["detail_capture_time_budget_exhausted"])
        self.assertEqual(result["input_candidate_count"], 2)
        self.assertEqual(result["new_detail_capture_attempted_count"], 2)
        self.assertEqual(result["existing_capture_reused_count"], 0)
        self.assertEqual(result["pending_detail_capture_count"], 0)
        self.assertEqual(result["detail_capture_attempted_count"], 2)
        self.assertEqual(result["detail_snapshot_count"], 1)
        self.assertEqual(result["detail_capture_failed_count"], 1)
        self.assertEqual(result["detail_capture_failure_summary"]["source_url_or_profile_id_missing"], 1)

    def test_capture_candidates_reuses_existing_snapshots_for_resume(self) -> None:
        transport = FakeRealPublicFetchTransport(
            {
                CCGP_DETAIL_URL: RealPublicFetchResponse(
                    url=CCGP_DETAIL_URL,
                    status_code=200,
                    content=_ccgp_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=CCGP_DETAIL_URL,
                ),
            }
        )
        candidate = {
            "candidate_key": "real-candidate-resume-001",
            "notice_id": "NOTICE-REAL-RESUME-001",
            "project_id": "PROJ-REAL-RESUME-001",
            "project_name": "列表页标题待详情校正",
            "region_code": "CN-GD",
            "project_type": "municipal",
            "notice_stage": "candidate_notice",
            "source_url": CCGP_DETAIL_URL,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            first = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:00:00+00:00",
            )
            second = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:05:00+00:00",
            )

        self.assertEqual(first["new_detail_capture_attempted_count"], 1)
        self.assertEqual(second["existing_capture_reused_count"], 1)
        self.assertEqual(second["new_detail_capture_attempted_count"], 0)
        self.assertEqual(second["detail_snapshot_count"], 1)

    def test_candidate_table_detail_extracts_clean_company_and_project_manager(self) -> None:
        detail_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_candidate.htm"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_candidate_table_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-candidate-table-001",
            "notice_id": "NOTICE-GD-TABLE-001",
            "project_id": "PROJ-GD-TABLE-001",
            "project_name": "霞山区农村供水一体化工程监理评标报告",
            "region_code": "CN-GD",
            "project_type": "municipal",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )

            result = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:00:00+00:00",
                detail_capture_limit=1,
            )

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "中唯耘源建设管理有限公司")
        self.assertEqual(enriched["candidate_company_parse_state"], "DETAIL_TEXT_CANDIDATE_TABLE")
        self.assertEqual(enriched["project_manager_name"], "苟瑾")
        self.assertEqual(enriched["project_manager_certificate_no"], "51010186")
        self.assertEqual(enriched["notice_stage"], "candidate_notice")
        self.assertEqual(enriched["objection_deadline_at_optional"], "2026-05-08T23:59:59+08:00")
        self.assertIn("candidate_company", enriched["key_fields_present"])
        self.assertIn("project_manager_name", enriched["key_fields_present"])

    def test_unit_name_table_extracts_first_company_from_guangdong_richtext(self) -> None:
        detail_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_unit_table.htm"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_unit_name_table_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-unit-name-table-001",
            "notice_id": "NOTICE-GD-UNIT-001",
            "project_id": "PROJ-GD-UNIT-001",
            "project_name": "广东警官学院嘉禾校区警体馆建设工程项目施工监理评标报告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )

            result = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:00:00+00:00",
            )

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "深圳科宇工程顾问有限公司")
        self.assertEqual(enriched["candidate_company_parse_state"], "DETAIL_TEXT_UNIT_NAME_TABLE")

    def test_pdf_attachment_text_fills_missing_project_manager_from_guangdong_detail(self) -> None:
        detail_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_pdf_manager.htm"
        attachment_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/gd-manager.pdf"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_unit_name_table_with_pdf_attachment_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
                attachment_url: RealPublicFetchResponse(
                    url=attachment_url,
                    status_code=200,
                    content=_build_text_pdf_bytes(
                        [
                            "第一中标候选人: 广东省机电建设有限公司",
                            "项目负责人: 张建明",
                            "注册编号: 144202412345",
                            "一级建造师 机电工程 职称: 高级工程师",
                        ]
                    ),
                    content_type="application/pdf",
                    final_url=attachment_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-pdf-manager-001",
            "notice_id": "NOTICE-GD-PDF-MANAGER-001",
            "project_id": "PROJ-GD-PDF-MANAGER-001",
            "project_name": "广东机电安装工程评标报告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "广东省机电建设有限公司")
        self.assertEqual(enriched["project_manager_name"], "张建明")
        self.assertEqual(enriched["project_manager_certificate_no"], "144202412345")
        self.assertEqual(enriched["project_manager_certificate_type"], "一级建造师")
        self.assertEqual(enriched["project_manager_cert_specialty"], "机电")
        fields = result["captures"][0]["detail_fields"]
        self.assertEqual(fields["attachment_text_merge_state"], "ATTACHMENT_TEXT_MERGED")
        self.assertTrue(any("PDF_TEXT_EXTRACTED" in state for state in fields["attachment_text_parse_states"]))

    def test_candidate_summary_table_extracts_company_and_project_manager(self) -> None:
        detail_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_summary_table.htm"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_candidate_summary_table_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-summary-table-001",
            "notice_id": "NOTICE-GD-SUMMARY-001",
            "project_id": "PROJ-GD-SUMMARY-001",
            "project_name": "广东省茂名市施工监理评标报告",
            "region_code": "CN-GD",
            "project_type": "municipal",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "广东协立工程咨询监理有限公司")
        self.assertEqual(enriched["project_manager_name"], "阳青波")
        self.assertEqual(enriched["candidate_company_parse_state"], "DETAIL_TEXT_CANDIDATE_SUMMARY_TABLE")

    def test_transposed_candidate_table_extracts_first_company_and_project_manager(self) -> None:
        detail_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_transposed_table.htm"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_transposed_candidate_table_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-transposed-table-001",
            "notice_id": "NOTICE-GD-TRANSPOSED-001",
            "project_id": "PROJ-GD-TRANSPOSED-001",
            "project_name": "肇庆市鼎湖区合盛石化能源有限公司永贝大道加油站项目（施工）评标报告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "肇庆市盛建工程建设有限公司")
        self.assertEqual(enriched["project_manager_name"], "刘忠贵")
        self.assertEqual(enriched["candidate_company_parse_state"], "DETAIL_TEXT_TRANSPOSED_CANDIDATE_TABLE")

    def test_contextual_responsible_person_alias_and_certificate_identity_are_normalized(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/alias-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_contextual_manager_alias_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-alias-001",
            "notice_id": "NOTICE-GD-ALIAS-001",
            "project_id": "PROJ-GD-ALIAS-001",
            "project_name": "广东机电安装工程中标候选人公示",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )

            result = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:00:00+00:00",
                detail_capture_limit=1,
            )

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "广东省机电建设有限公司")
        self.assertEqual(enriched["project_manager_name"], "张建明")
        self.assertEqual(enriched.get("project_manager_certificate_no", ""), "")
        self.assertEqual(enriched["project_manager_certificate_type"], "一级建造师")
        self.assertEqual(enriched["project_manager_cert_specialty"], "机电")
        self.assertEqual(enriched["project_manager_professional_title"], "高级工程师")
        self.assertIn("project_manager_certificate_type", enriched["key_fields_present"])
        self.assertIn("project_manager_cert_specialty", enriched["key_fields_present"])

    def test_supervision_chief_engineer_is_lane_specific_and_backfilled_to_project_manager_chain(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/supervision-chief-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_supervision_chief_engineer_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-supervision-chief-001",
            "notice_id": "NOTICE-GD-SUPERVISION-CHIEF-001",
            "project_id": "PROJ-GD-SUPERVISION-CHIEF-001",
            "project_name": "广东学校扩建工程监理中标候选人公示",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["engineering_work_lane"], "supervision")
        self.assertEqual(enriched["primary_responsible_role"], "chief_supervision_engineer")
        self.assertEqual(enriched["primary_responsible_person_name"], "李明")
        self.assertEqual(enriched["chief_supervision_engineer_name"], "李明")
        self.assertEqual(enriched["project_manager_name"], "李明")
        self.assertEqual(enriched["project_manager_certificate_no"], "44030186")
        self.assertEqual(enriched["project_manager_certificate_type"], "注册监理工程师")
        self.assertEqual(enriched["project_manager_professional_title"], "高级工程师")

    def test_design_lead_is_not_forced_into_construction_project_manager(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/design-lead-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_design_lead_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-design-lead-001",
            "notice_id": "NOTICE-GD-DESIGN-LEAD-001",
            "project_id": "PROJ-GD-DESIGN-LEAD-001",
            "project_name": "广东产业园更新改造设计中标候选人公示",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["engineering_work_lane"], "design")
        self.assertEqual(enriched["primary_responsible_role"], "design_lead")
        self.assertEqual(enriched["primary_responsible_person_name"], "王磊")
        self.assertEqual(enriched["design_lead_name"], "王磊")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_certificate_type"], "一级注册建筑师")
        self.assertEqual(enriched["project_manager_cert_specialty"], "建筑")
        self.assertEqual(enriched["project_manager_professional_title"], "高级工程师")

    def test_survey_lead_and_registered_geotechnical_identity_are_normalized(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/survey-lead-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_survey_lead_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-survey-lead-001",
            "notice_id": "NOTICE-GD-SURVEY-LEAD-001",
            "project_id": "PROJ-GD-SURVEY-LEAD-001",
            "project_name": "广东地下管网勘察中标候选人公示",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["engineering_work_lane"], "survey")
        self.assertEqual(enriched["primary_responsible_role"], "survey_lead")
        self.assertEqual(enriched["primary_responsible_person_name"], "赵岩")
        self.assertEqual(enriched["survey_lead_name"], "赵岩")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_certificate_type"], "注册土木工程师（岩土）")
        self.assertEqual(enriched["project_manager_cert_specialty"], "岩土")
        self.assertEqual(enriched["project_manager_professional_title"], "工程师")

    def test_generic_responsible_person_without_project_context_is_not_project_manager(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/generic-person-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_generic_responsible_person_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-generic-person-001",
            "notice_id": "NOTICE-GD-GENERIC-PERSON-001",
            "project_id": "PROJ-GD-GENERIC-PERSON-001",
            "project_name": "广东材料采购中标公告",
            "region_code": "CN-GD",
            "project_type": "procurement",
            "notice_stage": "award_result",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )

            result = service.capture_candidates(
                [candidate],
                now="2026-05-01T00:00:00+00:00",
                detail_capture_limit=1,
            )

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["engineering_work_lane"], "supplier_service")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched.get("primary_responsible_person_name", ""), "")
        self.assertEqual(enriched["project_manager_name_parse_state"], "DETAIL_TEXT_NOT_FOUND")
        self.assertEqual(enriched["project_manager_cert_specialty_parse_state"], "DETAIL_TEXT_NOT_FOUND")

    def test_project_or_tender_number_is_not_project_manager_certificate(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/project-code-only-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_project_code_without_manager_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-project-code-only-001",
            "notice_id": "NOTICE-GD-PROJECT-CODE-ONLY-001",
            "project_id": "PROJ-GD-PROJECT-CODE-ONLY-001",
            "project_name": "广州装修工程评标报告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched.get("project_manager_certificate_no", ""), "")
        self.assertEqual(enriched["project_manager_certificate_no_parse_state"], "DETAIL_TEXT_NOT_FOUND")

    def test_company_fragment_after_manager_label_is_not_project_manager_name(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/company-fragment-manager-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_company_fragment_after_manager_label_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-company-fragment-manager-001",
            "notice_id": "NOTICE-GD-COMPANY-FRAGMENT-MANAGER-001",
            "project_id": "PROJ-GD-COMPANY-FRAGMENT-MANAGER-001",
            "project_name": "绿色化工基础设施勘察设计评标报告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_name_parse_state"], "DETAIL_TEXT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
