from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage2_ingestion.scrapling_snapshot_parser import (  # noqa: E402
    SCRAPLING_SNAPSHOT_PARSER_ADAPTER_ID,
    parse_snapshot_html_with_scrapling,
)


class _FakeSelectors(list):
    @property
    def first(self):
        return self[0] if self else None


class _FakeElement:
    def __init__(self, *, text: str = "", href: str = "") -> None:
        self.text = text
        self.attrib = {"href": href} if href else {}

    def get_all_text(self, separator: str = " ", strip: bool = True, **_: object) -> str:
        return self.text.strip() if strip else self.text


class _FakeScraplingSelector:
    def __init__(self, *, content: str, url: str = "") -> None:
        self.content = content
        self.url = url

    def css(self, selector: str):
        if selector == "title":
            return _FakeSelectors([_FakeElement(text="Fake candidate notice")])
        if selector == "a":
            return _FakeSelectors(
                [
                    _FakeElement(text="Notice pdf download", href="./files/notice.pdf"),
                    _FakeElement(text="Detail page", href="/detail/123.html"),
                ]
            )
        return _FakeSelectors([])

    def get_all_text(self, separator: str = " ", strip: bool = True, **_: object) -> str:
        text = "Fake candidate notice project manager schedule Notice pdf download Detail page"
        return text.strip() if strip else text


class ScraplingSnapshotParserTests(unittest.TestCase):
    def test_parser_extracts_attachment_links_without_live_request(self) -> None:
        html = b"""
        <html>
          <head><title>Candidate result notice</title></head>
          <body>
            <h1>Candidate result notice</h1>
            <a href="./files/notice.pdf">Notice pdf download</a>
            <a href="/detail/123.html">Detail page</a>
            <a href="https://example.com/out.html">External page</a>
          </body>
        </html>
        """

        readback = parse_snapshot_html_with_scrapling(
            html,
            base_url="https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/t1.htm",
            keywords=["Candidate result notice", "project manager"],
        )

        self.assertEqual(readback["parser_adapter_id"], SCRAPLING_SNAPSHOT_PARSER_ADAPTER_ID)
        self.assertTrue(readback["no_live_request"])
        self.assertFalse(readback["customer_visible_allowed"])
        self.assertTrue(readback["no_legal_conclusion"])
        self.assertIn(readback["parser_backend"], {"SCRAPLING_SELECTOR", "STDLIB_HTML_PARSER_FALLBACK"})
        self.assertEqual(readback["attachment_link_records"][0]["url"], "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202604/files/notice.pdf")
        self.assertEqual(readback["attachment_link_records"][0]["link_kind"], "attachment_candidate")
        self.assertEqual(readback["keyword_hits"][0]["keyword"], "Candidate result notice")
        self.assertGreaterEqual(readback["same_site_link_count"], 2)

    def test_parser_falls_back_when_selector_factory_fails(self) -> None:
        def failing_selector_factory(**_: object) -> object:
            raise RuntimeError("selector failed")

        readback = parse_snapshot_html_with_scrapling(
            "<html><head><title>Fallback title</title></head><body><a href='/a.pdf'>A pdf</a></body></html>",
            base_url="https://public.example.gov/detail.html",
            selector_factory=failing_selector_factory,
        )

        self.assertEqual(readback["parser_backend"], "STDLIB_HTML_PARSER_FALLBACK")
        self.assertEqual(readback["parser_state"], "PARSED_WITH_STDLIB_FALLBACK")
        self.assertIn("scrapling_selector_parse_failed:RuntimeError", readback["failure_taxonomy"])
        self.assertEqual(readback["title"], "Fallback title")
        self.assertEqual(readback["attachment_link_records"][0]["url"], "https://public.example.gov/a.pdf")

    def test_parser_uses_selector_factory_when_available(self) -> None:
        readback = parse_snapshot_html_with_scrapling(
            "<html></html>",
            base_url="https://public.example.gov/detail.html",
            keywords=["project manager"],
            selector_factory=_FakeScraplingSelector,
        )

        self.assertEqual(readback["parser_backend"], "SCRAPLING_SELECTOR")
        self.assertEqual(readback["parser_state"], "PARSED_WITH_SCRAPLING")
        self.assertEqual(readback["title"], "Fake candidate notice")
        self.assertEqual(readback["attachment_link_records"][0]["url"], "https://public.example.gov/files/notice.pdf")
        self.assertEqual(readback["keyword_hits"], [{"keyword": "project manager", "hit_count": 1}])

    def test_parser_keeps_guangzhou_ywtb_jsgc_attachment_alias(self) -> None:
        readback = parse_snapshot_html_with_scrapling(
            """
            <html><body>
              <a href="https://jsgc.gzggzy.cn/tpframe/rest/guangzhoutempdownattach4webaction/download?AttachGuid=abc&FileCode=TBGK001">download</a>
            </body></html>
            """,
            base_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260516/detail.html",
        )

        self.assertEqual(readback["attachment_link_records"][0]["url"], "https://jsgc.gzggzy.cn/tpframe/rest/guangzhoutempdownattach4webaction/download?AttachGuid=abc&FileCode=TBGK001")
        self.assertTrue(readback["attachment_link_records"][0]["same_site"])

    def test_parser_extracts_guangzhou_onclick_download_endpoint(self) -> None:
        readback = parse_snapshot_html_with_scrapling(
            """
            <html><body>
              <a onclick="ztbfjyz('/EpointWebBuilder/pages/webbuildermis/attach/downloadztbattach?attachGuid=abc&appUrlFlag=f2025tp','1','1')">06中标候选人公示.pdf</a>
              <a href="/jyfw/002001/002001004/002001004005/trade_purchasetoplen6.html">网上答疑</a>
            </body></html>
            """,
            base_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260510/detail.html",
        )

        self.assertEqual(readback["attachment_link_count"], 1)
        self.assertEqual(
            readback["attachment_link_records"][0]["url"],
            "https://ywtb.gzggzy.cn/EpointWebBuilder/pages/webbuildermis/attach/downloadztbattach?attachGuid=abc&appUrlFlag=f2025tp",
        )
        self.assertEqual(readback["same_site_link_count"], 2)

    def test_parser_extracts_parser_only_field_signals(self) -> None:
        readback = parse_snapshot_html_with_scrapling(
            """
            <html>
              <head><title>测试道路工程中标候选人公示</title></head>
              <body>
                <div>项目名称：测试道路工程</div>
                <div>项目编号：JG2026-12345-001</div>
                <div>发布日期：2026-05-18</div>
                <div>第一中标候选人：测试建设有限公司</div>
                <div>项目负责人：张三 / 一级注册建造师</div>
                <div>工期：2026-06-01 至 2026-12-01</div>
              </body>
            </html>
            """,
            base_url="https://example.gov/detail.html",
        )

        summary = readback["field_signal_summary"]
        self.assertEqual(summary["field_signal_state"], "FIELD_SIGNALS_FOUND")
        self.assertEqual(summary["notice_stage_signal"], "candidate_notice")
        self.assertGreaterEqual(summary["project_code_signal_count"], 1)
        self.assertEqual(summary["responsible_person_signal_count"], 1)
        self.assertEqual(summary["time_window_signal_count"], 1)
        by_name = {
            record["field_name"]: record["field_value_optional"]
            for record in readback["field_candidate_records"]
        }
        self.assertEqual(by_name["announcement_title"], "测试道路工程中标候选人公示")
        self.assertEqual(by_name["project_name"], "测试道路工程")
        self.assertEqual(by_name["project_code"], "JG2026-12345-001")
        self.assertEqual(by_name["announcement_date"], "2026-05-18")
        self.assertEqual(by_name["candidate_company"], "测试建设有限公司")
        self.assertEqual(by_name["primary_responsible_person_name"], "张三")
        self.assertEqual(by_name["duration_or_period_optional"], "2026-06-01 至 2026-12-01")
        self.assertTrue(all(record["parser_only_signal"] for record in readback["field_candidate_records"]))
        self.assertTrue(all(record["no_legal_conclusion"] for record in readback["field_candidate_records"]))

    def test_parser_prefers_h1_when_title_is_generic(self) -> None:
        readback = parse_snapshot_html_with_scrapling(
            """
            <html>
              <head><title>广州交易集团有限公司</title></head>
              <body><h1>测试道路工程中标候选人公示</h1></body>
            </html>
            """,
            base_url="https://ywtb.gzggzy.cn/detail.html",
        )

        self.assertEqual(readback["title"], "测试道路工程中标候选人公示")
        title_records = [
            record
            for record in readback["field_candidate_records"]
            if record["field_name"] == "announcement_title"
        ]
        self.assertEqual(title_records[0]["field_value_optional"], "测试道路工程中标候选人公示")

    def test_parser_extracts_table_structure_and_label_value_signals(self) -> None:
        readback = parse_snapshot_html_with_scrapling(
            """
            <html><body>
              <table>
                <tr><th>项目名称</th><td>测试道路工程</td></tr>
                <tr><th>项目编号</th><td>JG2026-12345-001</td></tr>
                <tr><th>招标人</th><td>测试市建设单位</td></tr>
              </table>
              <table>
                <tr><th>排序</th><th>中标候选人名称</th><th>项目负责人</th></tr>
                <tr><td>第一中标候选人</td><td>测试建设有限公司</td><td>张三</td></tr>
              </table>
            </body></html>
            """,
            base_url="https://example.gov/detail.html",
        )

        summary = readback["table_extraction_summary"]
        self.assertEqual(summary["table_extraction_state"], "TABLES_FOUND")
        self.assertEqual(summary["table_count"], 2)
        self.assertGreaterEqual(summary["label_value_pair_count"], 3)
        self.assertGreaterEqual(summary["candidate_row_signal_count"], 1)
        self.assertEqual(summary["table_kind_counts"]["project_metadata_table"], 1)
        self.assertEqual(summary["table_kind_counts"]["candidate_or_bidder_table"], 1)
        field_summary = readback["field_signal_summary"]
        self.assertGreaterEqual(field_summary["table_label_value_signal_count"], 3)
        by_name = {
            record["field_name"]: record["field_value_optional"]
            for record in readback["field_candidate_records"]
            if record["match_kind"] == "table_label_value"
        }
        self.assertEqual(by_name["project_name"], "测试道路工程")
        self.assertEqual(by_name["project_code"], "JG2026-12345-001")
        self.assertEqual(by_name["tenderer_or_purchaser"], "测试市建设单位")
        candidate_rows = readback["table_records"][1]["candidate_row_records"]
        self.assertEqual(candidate_rows[0]["candidate_company_optional"], "测试建设有限公司")


if __name__ == "__main__":
    unittest.main()
