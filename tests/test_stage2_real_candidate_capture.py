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
from stage3_parsing.ocr_text import ExtractedText, OCR_REQUIRED, PDF_TEXT_OCR_EXTRACTED
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


def _capture_single_candidate_from_html(
    *,
    detail_url: str,
    title: str,
    html: bytes,
    source_profile_id: str = "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
) -> dict:
    transport = FakeRealPublicFetchTransport(
        {
            detail_url: RealPublicFetchResponse(
                url=detail_url,
                status_code=200,
                content=html,
                content_type="text/html; charset=utf-8",
                final_url=detail_url,
            ),
        }
    )
    candidate = {
        "candidate_key": f"candidate-{abs(hash(detail_url))}",
        "notice_id": f"NOTICE-{abs(hash(detail_url))}",
        "project_id": f"PROJ-{abs(hash(detail_url))}",
        "project_name": title,
        "region_code": "CN-GD",
        "project_type": "construction",
        "notice_stage": "candidate_notice",
        "source_url": detail_url,
        "source_profile_id": source_profile_id,
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
    return result["enriched_candidates"][0]


def _classification_detail_html(title: str, *, body: str = "") -> bytes:
    html = f"""
    <html>
      <head><title>{title}</title></head>
      <body>
        <h1>{title}</h1>
        <p>中标候选人公示</p>
        <p>第一中标候选人 广东测试工程有限公司 投标报价 1000.00 万元。</p>
        <p>{body}</p>
        <p>公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文。</p>
        <p>公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文公开详情正文。</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _guangzhou_publicity_table_html(title: str, *, first_row: str) -> bytes:
    html = f"""
    <html>
      <head><title>{title}</title></head>
      <body>
        <h1>{title}</h1>
        <p>中标候选人公示</p>
        <p>序号 中标候选人名称 候选人代码 排名 投标报价 质量承诺 工期（交货期） 候选人资格情况 候选人业绩情况 拟派项目负责人 项目负责人资质 项目负责人业绩</p>
        <p>1 {first_row}</p>
        <p>2 广州第二测试工程有限公司 914401010000000002 2 2000000.00元 按招标文件要求 按招标文件要求 详见投标文件公开 详见投标文件公开 周永兵 详见投标文件公开 详见投标文件公开</p>
        <p>公示结束时间：2026年05月07日</p>
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


def _guangzhou_candidate_publicity_table_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东警官学院嘉禾校区警体馆建设工程项目施工监理中标候选人公示</title></head>
      <body>
        <h1>广东警官学院嘉禾校区警体馆建设工程项目施工监理中标候选人公示</h1>
        <p>中标候选人公示</p>
        <p>序号 中标候选人名称 候选人代码 排名 投标报价 监理质量标准 监理服务期限 候选人资格情况 候选人业绩情况 拟派项目负责人 项目负责人资质 项目负责人业绩</p>
        <p>1 广州珠江监理咨询集团有限公司 91440101190668588M 1 1974252.50元 按招标文件的要求 按招标文件的要求 详见投标文件公开 详见投标文件公开 张合力 监理工程师/44012765 详见投标文件公开</p>
        <p>2 广州市市政工程监理有限公司 91440101716359393C 2 1963695.00元 按招标文件要求 按招标文件要求 详见投标文件公开 详见投标文件公开 钱超 监理工程师/44014267 详见投标文件公开</p>
        <p>公示结束时间：2026年05月07日</p>
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


def _survey_design_candidate_table_with_certificate_detail_html() -> bytes:
    html = """
    <html>
      <head><title>广东医院项目勘察设计评标报告</title></head>
      <body>
        <h1>广东医院项目勘察设计评标报告</h1>
        <p>无排序的三名定标候选人名单：</p>
        <p>定标候选人名称 投标下浮率及投标报价 项目负责人姓名及资格证书 编号</p>
        <p>(主)广东海外建筑设计院 有限公司;(成)建材广州工程勘测院有限公司 勘察费下浮率 0.26%，设计费下浮率 0.26%/4214214.48 元 杨昕/20114411031</p>
        <p>(主)广东粤建设计研究院有限公司;(成)顺驰勘测有限公司 勘察费下浮率 0.50%，设计费下浮率 0.35%/4209398.55 元 冯浩/20074401484</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _survey_design_role_table_after_irrelevant_header_html() -> bytes:
    html = """
    <html>
      <head><title>广东医院项目勘察设计评标报告</title></head>
      <body>
        <h1>广东医院项目勘察设计评标报告</h1>
        <p>项目负责人联系方式由招标人另行通知，本段不是候选表。</p>
        <p>无排序的三名定标候选人名单：</p>
        <p>定标候选人名称 投标下浮率及投标报价 项目负责人姓名及资格证书 编号</p>
        <p>(主)广东海外建筑设计院有限 公司;(成)建材广州工程勘测院有限公司 勘察费下浮率 0.26%， 设计费下浮率 0.26%/4214214.48 元 杨昕/20114411031</p>
        <p>(主)广东粤建设计研究院有限公司;(成)顺驰勘测有限公司 勘察费下浮率 0.50%， 设计费下浮率 0.35%/4209398.55 元 冯浩/20074401484</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _survey_design_candidate_table_without_certificate_detail_html() -> bytes:
    html = """
    <html>
      <head><title>绿色化工园区土方工程勘察设计评标报告</title></head>
      <body>
        <h1>绿色化工园区土方工程勘察设计评标报告</h1>
        <p>无排序的 3 名定标候选人名单：</p>
        <p>定标候选人名称 投标总报价（元） 下浮率（%） 项目负责人</p>
        <p>一方设计集团有限 公司 3426871.63 0.03 何勇均</p>
        <p>中都工程设计有限 公司 3427557.21 0.01 陈睿</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _service_project_total_responsible_table_detail_html() -> bytes:
    html = """
    <html>
      <head><title>高州排水管线工程监理造价咨询评标报告</title></head>
      <body>
        <h1>高州排水管线工程监理造价咨询评标报告</h1>
        <p>推荐排名 中标候选人名称 投标报价（元） 项目总负责人姓名及资格证书编号</p>
        <p>第一中标候选人 深圳市昊源建设监理有限公司 2316935.04 梅琦枫 44044619</p>
        <p>第二中标候选人 五洲工程顾问集团有限公司 2486348.80 王涛 33042716</p>
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


def _tender_qualification_role_requirement_detail_html() -> bytes:
    html = """
    <html>
      <head><title>福田中心区照明整治工程EPC总承包招标公告</title></head>
      <body>
        <h1>福田中心区照明整治工程EPC总承包招标公告</h1>
        <p>招标公告</p>
        <p>资格要求：拟派项目负责人须无在建工程，项目负责人可由联合体成员委派。</p>
        <p>项目负责人 可由联合体 3 截标时系统上所报 个月内不得变更。</p>
        <p>本公告仅为资格要求，不包含结果公示表。</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _digital_system_service_detail_html() -> bytes:
    html = """
    <html>
      <head><title>智慧景区数字化提升项目评标报告</title></head>
      <body>
        <h1>智慧景区数字化提升项目评标报告</h1>
        <p>第一中标候选人 广州翼然科技股份有限公司 投标报价 6800000.00 元</p>
        <p>项目内容包括数字化平台、软件系统和设备集成服务。</p>
      </body>
    </html>
    """
    return html.encode("utf-8")


def _shipbuilding_service_detail_html() -> bytes:
    html = """
    <html>
      <head><title>新建1艘4000载重吨级集装箱海船项目评标报告</title></head>
      <body>
        <h1>新建1艘4000载重吨级集装箱海船项目评标报告</h1>
        <p>第一中标候选人 广东南祥造船有限公司 投标报价 18000000.00 元</p>
        <p>服务内容包括船舶建造、设备供货和试航验收。</p>
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


def _build_blank_pdf_bytes() -> bytes:
    try:
        from pypdf import PdfWriter
    except Exception as exc:  # pragma: no cover - optional test dependency
        raise unittest.SkipTest(f"pypdf unavailable: {exc}") from exc
    from io import BytesIO

    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
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

    def test_pdf_attachment_ocr_text_fills_missing_project_manager_with_review_counters(self) -> None:
        detail_url = "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t20260430_pdf_ocr_manager.htm"
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
                    content=_build_blank_pdf_bytes(),
                    content_type="application/pdf",
                    final_url=attachment_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-pdf-ocr-manager-001",
            "notice_id": "NOTICE-GD-PDF-OCR-MANAGER-001",
            "project_id": "PROJ-GD-PDF-OCR-MANAGER-001",
            "project_name": "广东扫描件项目评标报告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "candidate_notice",
            "source_url": detail_url,
            "source_profile_id": "CCGP-CENTRAL-NOTICES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "key_fields_present": ["project_name", "notice_stage"],
            "candidate_count": 0,
        }

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "stage2_ingestion.real_candidate_capture.extract_pdf_text_with_ocr",
            return_value=ExtractedText(
                text="第一中标候选人: 广东省机电建设有限公司\n项目负责人: 李建国\n注册编号: 144202498765",
                state=PDF_TEXT_OCR_EXTRACTED,
                extractor="provided_pdf_ocr",
                confidence=0.62,
                review_required=True,
                warnings=[OCR_REQUIRED],
            ),
        ):
            service = RealCandidateStage2CaptureService(
                stage2_service=FakeStage2Service(transport),
                object_repository=_repo(tmp_dir),
                repository=RealCandidateStage2CaptureRepository(),
            )
            result = service.capture_candidates([candidate], now="2026-05-01T00:00:00+00:00")

        enriched = result["enriched_candidates"][0]
        self.assertEqual(enriched["candidate_company"], "广东省机电建设有限公司")
        self.assertEqual(enriched["project_manager_name"], "李建国")
        self.assertEqual(enriched["project_manager_certificate_no"], "144202498765")
        self.assertEqual(enriched["attachment_ocr_required_count"], 1)
        self.assertEqual(enriched["attachment_ocr_extracted_count"], 1)
        fields = result["captures"][0]["detail_fields"]
        self.assertEqual(fields["attachment_text_merge_state"], "ATTACHMENT_TEXT_MERGED")
        self.assertEqual(fields["attachment_ocr_required_count"], 1)
        self.assertEqual(fields["attachment_ocr_extracted_count"], 1)
        self.assertTrue(any(PDF_TEXT_OCR_EXTRACTED in state for state in fields["attachment_text_parse_states"]))

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
        self.assertEqual(enriched["opportunity_priority_class"], "B_HIGH_SUPERVISION")
        self.assertEqual(enriched["verification_priority_band"], "B")
        self.assertEqual(enriched["expected_responsible_role_field"], "chief_supervision_engineer_name_or_primary_responsible_person_name")
        self.assertTrue(enriched["expected_responsible_role_present"])
        self.assertFalse(enriched["responsible_role_gap_review_required"])
        self.assertEqual(enriched["primary_responsible_role"], "chief_supervision_engineer")
        self.assertEqual(enriched["primary_responsible_person_name"], "李明")
        self.assertEqual(enriched["chief_supervision_engineer_name"], "李明")
        self.assertEqual(enriched["project_manager_name"], "李明")
        self.assertEqual(enriched["project_manager_certificate_no"], "44030186")
        self.assertEqual(enriched["project_manager_certificate_type"], "注册监理工程师")
        self.assertEqual(enriched["project_manager_professional_title"], "高级工程师")

    def test_candidate_publicity_table_extracts_person_after_quality_columns(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/guangzhou-candidate-publicity-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_guangzhou_candidate_publicity_table_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-guangzhou-candidate-publicity-001",
            "notice_id": "NOTICE-GD-GZ-CANDIDATE-PUBLICITY-001",
            "project_id": "PROJ-GD-GZ-CANDIDATE-PUBLICITY-001",
            "project_name": "广东警官学院嘉禾校区警体馆建设工程项目施工监理中标候选人公示",
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
        self.assertEqual(enriched["candidate_company"], "广州珠江监理咨询集团有限公司")
        self.assertEqual(enriched["primary_responsible_person_name"], "张合力")
        self.assertEqual(enriched["chief_supervision_engineer_name"], "张合力")
        self.assertEqual(enriched["project_manager_name"], "张合力")
        self.assertEqual(enriched["project_manager_certificate_no"], "44012765")
        self.assertNotEqual(enriched["primary_responsible_person_name"], "按招标文件的要求")

    def test_guangzhou_publicity_table_extracts_name_only_without_fabricating_certificate(self) -> None:
        title = "2026-2027年度南沙区排水设施小修项目施工中标候选人公示"
        enriched = _capture_single_candidate_from_html(
            detail_url="https://ygp.gdzwfw.gov.cn/notice/gz-publicity-name-only-001.html",
            title=title,
            html=_guangzhou_publicity_table_html(
                title,
                first_row=(
                    "广东浩禹建设有限公司 91440101MA59GY1G1R 1 39069868.25元 "
                    "按招标文件的要求 按招标文件的要求 详见投标文件公开 "
                    "详见投标文件公开 陈丽丽 详见投标文件公开 详见投标文件公开"
                ),
            ),
        )

        self.assertEqual(enriched["engineering_work_lane"], "construction_or_epc")
        self.assertEqual(enriched["primary_responsible_person_name"], "陈丽丽")
        self.assertEqual(enriched["project_manager_name"], "陈丽丽")
        self.assertEqual(enriched.get("project_manager_certificate_no", ""), "")
        self.assertFalse(enriched["responsible_role_gap_review_required"])
        self.assertNotEqual(enriched["primary_responsible_person_name"], "按招标文件的要求")
        self.assertNotEqual(enriched.get("project_manager_certificate_no", ""), "详见投标文件公开")

    def test_guangzhou_publicity_table_extracts_construction_certificate_with_space(self) -> None:
        title = "长安镇110kV东宝站10kV领阳线电力迁改工程施工中标候选人公示"
        enriched = _capture_single_candidate_from_html(
            detail_url="https://ygp.gdzwfw.gov.cn/notice/gz-publicity-builder-cert-001.html",
            title=title,
            html=_guangzhou_publicity_table_html(
                title,
                first_row=(
                    "东莞市昌晖电气工程有限公司 91441900777836579R 1 2635697.38元 "
                    "通过各级验收合格并完成启动投产。 83日历天 "
                    "电力工程施工总承包二级 无业绩要求 莫福源 "
                    "二级注册建造师（机电工程专业）/粤 2442021202125000 详见投标文件公开"
                ),
            ),
        )

        self.assertEqual(enriched["primary_responsible_person_name"], "莫福源")
        self.assertEqual(enriched["project_manager_name"], "莫福源")
        self.assertEqual(enriched["project_manager_certificate_no"], "粤2442021202125000")
        self.assertEqual(enriched["project_manager_certificate_type"], "二级建造师")
        self.assertEqual(enriched["project_manager_cert_specialty"], "机电")

    def test_guangzhou_publicity_table_extracts_survey_design_registered_civil_certificate(self) -> None:
        title = "绿色化工和氢能产业园基础设施建设－北区土方工程一期勘察设计中标候选人公示"
        enriched = _capture_single_candidate_from_html(
            detail_url="https://ygp.gdzwfw.gov.cn/notice/gz-publicity-survey-design-cert-001.html",
            title=title,
            html=_guangzhou_publicity_table_html(
                title,
                first_row=(
                    "一方设计集团有限公司 914401010000000001 1 投标总报价3426871.63元 "
                    "本工程验收达到合格标准。 60日历天 何勇均 "
                    "注册土木工程师(道路工程)/AD244400169 详见投标文件公开"
                ),
            ),
        )

        self.assertEqual(enriched["engineering_work_lane"], "survey_design")
        self.assertEqual(enriched["opportunity_priority_class"], "C_MEDIUM_DESIGN_SURVEY")
        self.assertEqual(enriched["primary_responsible_role"], "survey_design_project_lead")
        self.assertEqual(enriched["primary_responsible_person_name"], "何勇均")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_certificate_no"], "AD244400169")
        self.assertEqual(enriched["project_manager_certificate_type"], "注册土木工程师(道路工程)")
        self.assertEqual(enriched["project_manager_cert_specialty"], "道路")

    def test_guangzhou_publicity_table_extracts_supervision_engineer_slash_certificate(self) -> None:
        title = "广州市黄埔区城中村改造项目工程监理服务中标候选人公示"
        enriched = _capture_single_candidate_from_html(
            detail_url="https://ygp.gdzwfw.gov.cn/notice/gz-publicity-supervision-cert-001.html",
            title=title,
            html=_guangzhou_publicity_table_html(
                title,
                first_row=(
                    "广东重工建设监理有限公司 91440000707652977E 1 5831229.17元 "
                    "按招标文件要求 按招标文件要求 详见投标文件公开 "
                    "详见投标文件公开 黄坤 监理工程师/44012345 详见投标文件公开"
                ),
            ),
        )

        self.assertEqual(enriched["engineering_work_lane"], "supervision")
        self.assertEqual(enriched["opportunity_priority_class"], "B_HIGH_SUPERVISION")
        self.assertEqual(enriched["primary_responsible_role"], "chief_supervision_engineer")
        self.assertEqual(enriched["chief_supervision_engineer_name"], "黄坤")
        self.assertEqual(enriched["project_manager_name"], "黄坤")
        self.assertEqual(enriched["project_manager_certificate_no"], "44012345")
        self.assertEqual(enriched["project_manager_certificate_type"], "注册监理工程师")

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
        self.assertEqual(enriched["opportunity_priority_class"], "C_MEDIUM_DESIGN_SURVEY")
        self.assertEqual(
            enriched["expected_responsible_role_field"],
            "design_lead_name_or_survey_lead_name_or_primary_responsible_person_name",
        )
        self.assertTrue(enriched["expected_responsible_role_present"])
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
        self.assertEqual(enriched["opportunity_priority_class"], "C_MEDIUM_DESIGN_SURVEY")
        self.assertEqual(enriched["verification_priority_band"], "C")
        self.assertTrue(enriched["expected_responsible_role_present"])
        self.assertEqual(enriched["primary_responsible_role"], "survey_lead")
        self.assertEqual(enriched["primary_responsible_person_name"], "赵岩")
        self.assertEqual(enriched["survey_lead_name"], "赵岩")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_certificate_type"], "注册土木工程师（岩土）")
        self.assertEqual(enriched["project_manager_cert_specialty"], "岩土")
        self.assertEqual(enriched["project_manager_professional_title"], "工程师")

    def test_survey_design_candidate_table_extracts_project_lead_and_certificate_no(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/survey-design-table-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_survey_design_candidate_table_with_certificate_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-survey-design-table-001",
            "notice_id": "NOTICE-GD-SURVEY-DESIGN-TABLE-001",
            "project_id": "PROJ-GD-SURVEY-DESIGN-TABLE-001",
            "project_name": "广东医院项目勘察设计评标报告",
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
        self.assertEqual(enriched["engineering_work_lane"], "survey_design")
        self.assertEqual(enriched["opportunity_priority_class"], "C_MEDIUM_DESIGN_SURVEY")
        self.assertTrue(enriched["expected_responsible_role_present"])
        self.assertEqual(enriched["candidate_company"], "(主)广东海外建筑设计院有限公司;(成)建材广州工程勘测院有限公司")
        self.assertEqual(enriched["primary_responsible_role"], "survey_design_project_lead")
        self.assertEqual(enriched["primary_responsible_person_name"], "杨昕")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_certificate_no"], "20114411031")
        self.assertEqual(
            enriched["primary_responsible_person_name_parse_state"],
            "DETAIL_TEXT_CANDIDATE_ROLE_CERT_TABLE",
        )

    def test_survey_design_role_table_skips_earlier_irrelevant_project_manager_header(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/survey-design-table-late-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_survey_design_role_table_after_irrelevant_header_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-survey-design-table-late-001",
            "notice_id": "NOTICE-GD-SURVEY-DESIGN-TABLE-LATE-001",
            "project_id": "PROJ-GD-SURVEY-DESIGN-TABLE-LATE-001",
            "project_name": "广东医院项目勘察设计评标报告",
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
        self.assertEqual(enriched["engineering_work_lane"], "survey_design")
        self.assertEqual(enriched["candidate_company"], "(主)广东海外建筑设计院有限公司;(成)建材广州工程勘测院有限公司")
        self.assertEqual(enriched["primary_responsible_person_name"], "杨昕")
        self.assertEqual(enriched["project_manager_certificate_no"], "20114411031")
        self.assertFalse(enriched["responsible_role_gap_review_required"])

    def test_survey_design_candidate_table_extracts_project_lead_without_certificate_no(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/survey-design-table-no-cert-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_survey_design_candidate_table_without_certificate_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-survey-design-table-no-cert-001",
            "notice_id": "NOTICE-GD-SURVEY-DESIGN-TABLE-NO-CERT-001",
            "project_id": "PROJ-GD-SURVEY-DESIGN-TABLE-NO-CERT-001",
            "project_name": "绿色化工园区土方工程勘察设计评标报告",
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
        self.assertEqual(enriched["engineering_work_lane"], "survey_design")
        self.assertEqual(enriched["opportunity_priority_class"], "C_MEDIUM_DESIGN_SURVEY")
        self.assertTrue(enriched["expected_responsible_role_present"])
        self.assertEqual(enriched["candidate_company"], "一方设计集团有限公司")
        self.assertEqual(enriched["primary_responsible_role"], "survey_design_project_lead")
        self.assertEqual(enriched["primary_responsible_person_name"], "何勇均")
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched.get("project_manager_certificate_no", ""), "")
        self.assertEqual(
            enriched["primary_responsible_person_name_parse_state"],
            "DETAIL_TEXT_CANDIDATE_ROLE_TABLE",
        )

    def test_service_project_total_responsible_table_extracts_name_and_certificate(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/service-total-responsible-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_service_project_total_responsible_table_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-service-total-responsible-001",
            "notice_id": "NOTICE-GD-SERVICE-TOTAL-RESPONSIBLE-001",
            "project_id": "PROJ-GD-SERVICE-TOTAL-RESPONSIBLE-001",
            "project_name": "高州排水管线工程监理造价咨询评标报告",
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
        self.assertEqual(enriched["opportunity_priority_class"], "B_HIGH_SUPERVISION")
        self.assertTrue(enriched["expected_responsible_role_present"])
        self.assertEqual(enriched["candidate_company"], "深圳市昊源建设监理有限公司")
        self.assertEqual(enriched["primary_responsible_role"], "chief_supervision_engineer")
        self.assertEqual(enriched["primary_responsible_person_name"], "梅琦枫")
        self.assertEqual(enriched["chief_supervision_engineer_name"], "梅琦枫")
        self.assertEqual(enriched["project_manager_certificate_no"], "44044619")
        self.assertEqual(
            enriched["primary_responsible_person_name_parse_state"],
            "DETAIL_TEXT_CANDIDATE_ROLE_CERT_TABLE",
        )

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
        self.assertEqual(enriched["opportunity_priority_class"], "D_LOW_SUPPLIER_SERVICE")
        self.assertEqual(enriched["expected_responsible_role_field"], "not_required_for_supplier_service")
        self.assertTrue(enriched["expected_responsible_role_present"])
        self.assertFalse(enriched["responsible_role_gap_review_required"])
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched.get("primary_responsible_person_name", ""), "")
        self.assertEqual(enriched["project_manager_name_parse_state"], "DETAIL_TEXT_NOT_FOUND")
        self.assertEqual(enriched["project_manager_cert_specialty_parse_state"], "DETAIL_TEXT_NOT_FOUND")

    def test_tender_qualification_text_is_not_candidate_role_table(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/epc-tender-requirement-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_tender_qualification_role_requirement_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-epc-tender-requirement-001",
            "notice_id": "NOTICE-GD-EPC-TENDER-REQUIREMENT-001",
            "project_id": "PROJ-GD-EPC-TENDER-REQUIREMENT-001",
            "project_name": "福田中心区照明整治工程EPC总承包招标公告",
            "region_code": "CN-GD",
            "project_type": "construction",
            "notice_stage": "tender_notice",
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
        self.assertEqual(enriched["engineering_work_lane"], "construction_or_epc")
        self.assertEqual(enriched["opportunity_priority_class"], "A_HIGH_CONSTRUCTION_EPC")
        self.assertFalse(enriched["expected_responsible_role_present"])
        self.assertTrue(enriched["responsible_role_gap_review_required"])
        self.assertEqual(enriched["responsible_role_gap_code"], "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY")
        self.assertEqual(enriched["responsible_role_gap_root_cause"], "RESPONSIBLE_ROLE_ONLY_IN_TENDER_REQUIREMENT_NOT_ASSIGNMENT")
        self.assertEqual(
            enriched["stage4_identity_completion_route"],
            "WAIT_FOR_CANDIDATE_NOTICE_OR_STAGE4_PROJECT_RECORD_LOOKUP",
        )
        self.assertNotEqual(enriched.get("candidate_company", ""), "可由联合体")
        self.assertEqual(enriched.get("primary_responsible_person_name", ""), "")
        self.assertEqual(enriched.get("project_manager_name", ""), "")

    def test_digital_system_project_uses_supplier_service_priority_class(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/digital-system-service-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_digital_system_service_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-digital-system-service-001",
            "notice_id": "NOTICE-GD-DIGITAL-SYSTEM-SERVICE-001",
            "project_id": "PROJ-GD-DIGITAL-SYSTEM-SERVICE-001",
            "project_name": "智慧景区数字化提升项目评标报告",
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
        self.assertEqual(enriched["engineering_work_lane"], "supplier_service")
        self.assertEqual(enriched["opportunity_priority_class"], "D_LOW_SUPPLIER_SERVICE")
        self.assertEqual(enriched["expected_responsible_role_field"], "not_required_for_supplier_service")
        self.assertFalse(enriched["responsible_role_gap_review_required"])
        self.assertEqual(enriched.get("project_manager_name", ""), "")

    def test_shipbuilding_project_uses_supplier_service_priority_class(self) -> None:
        detail_url = "https://ygp.gdzwfw.gov.cn/notice/shipbuilding-service-001.html"
        transport = FakeRealPublicFetchTransport(
            {
                detail_url: RealPublicFetchResponse(
                    url=detail_url,
                    status_code=200,
                    content=_shipbuilding_service_detail_html(),
                    content_type="text/html; charset=utf-8",
                    final_url=detail_url,
                ),
            }
        )
        candidate = {
            "candidate_key": "gd-shipbuilding-service-001",
            "notice_id": "NOTICE-GD-SHIPBUILDING-SERVICE-001",
            "project_id": "PROJ-GD-SHIPBUILDING-SERVICE-001",
            "project_name": "新建1艘4000载重吨级集装箱海船项目评标报告",
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
        self.assertEqual(enriched["engineering_work_lane"], "supplier_service")
        self.assertEqual(enriched["opportunity_priority_class"], "D_LOW_SUPPLIER_SERVICE")
        self.assertFalse(enriched["responsible_role_gap_review_required"])
        self.assertEqual(enriched.get("project_manager_name", ""), "")

    def test_abcd_priority_classification_rules_are_applied_after_detail_parse(self) -> None:
        cases = (
            (
                "施工总承包",
                "广州城市道路工程施工总承包中标候选人公示",
                "项目负责人 建造师",
                "construction_or_epc",
                "A_HIGH_CONSTRUCTION_EPC",
                True,
            ),
            (
                "监理",
                "华南快速路二期改扩建工程施工监理中标候选人公示",
                "总监理工程师 注册监理工程师",
                "supervision",
                "B_HIGH_SUPERVISION",
                True,
            ),
            (
                "勘察设计",
                "绿色化工和氢能产业园基础设施建设工程勘察设计中标候选人公示",
                "设计负责人 勘察负责人 注册土木工程师",
                "survey_design",
                "C_MEDIUM_DESIGN_SURVEY",
                True,
            ),
            (
                "甲供物资",
                "新建合浦至湛江铁路建设单位管理甲供物资防水材料采购中标候选人公示",
                "供应商资格 业绩 参数 报价 信用记录",
                "supplier_service",
                "D_LOW_SUPPLIER_SERVICE",
                False,
            ),
            (
                "保险采购",
                "佛开高速公路2026年度综合保险采购项目中标候选人公示",
                "供应商资格 业绩 报价 信用记录",
                "supplier_service",
                "D_LOW_SUPPLIER_SERVICE",
                False,
            ),
            (
                "EPC例外",
                "科技公司分布式光伏发电建设项目设计施工(EPC)总承包中标候选人公示",
                "项目负责人 注册建造师",
                "construction_or_epc",
                "A_HIGH_CONSTRUCTION_EPC",
                True,
            ),
            (
                "站点服务词不误分D",
                "广东省储备粮汕头直属库二期工程光伏发电项目中标候选人公示",
                "广州公共资源交易服务平台 采购公告 变更澄清公告 公开详情",
                "construction_or_epc",
                "A_HIGH_CONSTRUCTION_EPC",
                True,
            ),
        )
        for index, (label, title, body, lane, priority, gap_required) in enumerate(cases, 1):
            with self.subTest(label=label):
                detail_url = f"https://ygp.gdzwfw.gov.cn/notice/abcd-classification-{index}.html"
                transport = FakeRealPublicFetchTransport(
                    {
                        detail_url: RealPublicFetchResponse(
                            url=detail_url,
                            status_code=200,
                            content=_classification_detail_html(title, body=body),
                            content_type="text/html; charset=utf-8",
                            final_url=detail_url,
                        ),
                    }
                )
                candidate = {
                    "candidate_key": f"gd-abcd-classification-{index}",
                    "notice_id": f"NOTICE-GD-ABCD-CLASSIFICATION-{index}",
                    "project_id": f"PROJ-GD-ABCD-CLASSIFICATION-{index}",
                    "project_name": title,
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
                    )

                enriched = result["enriched_candidates"][0]
                self.assertEqual(enriched["engineering_work_lane"], lane)
                self.assertEqual(enriched["opportunity_priority_class"], priority)
                self.assertEqual(enriched["responsible_role_gap_review_required"], gap_required)
                if priority == "D_LOW_SUPPLIER_SERVICE":
                    self.assertEqual(
                        enriched["expected_responsible_role_field"],
                        "not_required_for_supplier_service",
                    )
                    self.assertTrue(enriched["expected_responsible_role_present"])
                    self.assertFalse(enriched["stage4_identity_completion_required"])

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
        self.assertEqual(enriched["engineering_work_lane"], "construction_or_epc")
        self.assertEqual(enriched["opportunity_priority_class"], "A_HIGH_CONSTRUCTION_EPC")
        self.assertEqual(
            enriched["expected_responsible_role_field"],
            "project_manager_name_or_primary_responsible_person_name",
        )
        self.assertFalse(enriched["expected_responsible_role_present"])
        self.assertTrue(enriched["responsible_role_gap_review_required"])
        self.assertEqual(enriched["responsible_role_gap_code"], "A_ROLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY")
        self.assertEqual(enriched["responsible_role_gap_root_cause"], "CAPTURED_TEXT_HAS_NO_RESPONSIBLE_ROLE_FIELD")
        self.assertEqual(
            enriched["responsible_role_gap_source_evidence"],
            "detail_and_attachment_text_replayable_but_no_responsible_role_tokens",
        )
        self.assertEqual(
            enriched["stage4_identity_completion_route"],
            "STAGE4_COMPANY_PROJECT_FIRST_PUBLIC_RECORD_LOOKUP",
        )
        self.assertTrue(enriched["stage4_identity_completion_required"])
        self.assertEqual(enriched["responsible_role_gap_token_hits"], [])
        self.assertGreaterEqual(len(enriched["stage4_identity_completion_targets"]), 2)
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
        self.assertEqual(enriched["engineering_work_lane"], "survey_design")
        self.assertEqual(enriched["opportunity_priority_class"], "C_MEDIUM_DESIGN_SURVEY")
        self.assertEqual(
            enriched["responsible_role_gap_code"],
            "C_DESIGN_SURVEY_RESPONSIBLE_MISSING_REQUIRES_COMPANY_FIRST_IDENTITY",
        )
        self.assertEqual(enriched.get("project_manager_name", ""), "")
        self.assertEqual(enriched["project_manager_name_parse_state"], "DETAIL_TEXT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
