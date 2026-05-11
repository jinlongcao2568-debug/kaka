from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangzhou_download_probe import (  # noqa: E402
    NOT_RUN_PARSE_STATE,
    build_guangzhou_download_probe,
)


class GuangzhouDownloadProbeTests(unittest.TestCase):
    def test_download_probe_uses_analysis_plan_and_keeps_parse_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root)
            repo = FakeReplayRepository(
                {
                    "DETAIL-03": _replay("DETAIL-03", b"<html>detail 03</html>", "text/html"),
                    "ATT-03-1": _replay("ATT-03-1", b"%PDF tender", "application/pdf"),
                }
            )
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/03.html": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "DETAIL-03",
                        "same_site_attachment_link_items": [
                            {"url": "https://example.test/attach/tender.pdf", "text": "招标文件.pdf"}
                        ],
                    }
                },
                attachment_map={
                    "https://example.test/attach/tender.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-03-1",
                        "attachment_url": "https://example.test/attach/tender.pdf",
                        "content_type": "application/pdf",
                    }
                },
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["03"],
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 1)
            sample = result["manifest"]["project_sample_items"][0]
            self.assertEqual(sample["stage3_parse_state"], NOT_RUN_PARSE_STATE)
            self.assertEqual(sample["parse_summary"]["stage3_parse_success_count"], 0)
            self.assertEqual(sample["parse_summary"]["stage3_parse_state"], NOT_RUN_PARSE_STATE)
            self.assertEqual(len(service.detail_calls), 1)
            self.assertEqual(len(service.attachment_calls), 1)
            self.assertTrue((output_root / "download-probe-manifest.json").exists())
            self.assertTrue((output_root / "challenge-stability-report.json").exists())
            attachment_dirs = list((output_root / "projects" / "CN-GD").glob("**/attachments"))
            self.assertTrue(any(list(path.glob("*.pdf")) for path in attachment_dirs))

    def test_adapter_validation_and_skip_policy_are_not_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(
                input_root,
                items=[
                    _strategy_item("03", "https://example.test/03.html", adapter_validation_only=True),
                    _strategy_item("04", "https://example.test/04.html", download_policy="SKIP"),
                ],
            )
            service = FakeStage2Service()

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["03", "04"],
                execute=True,
                stage2_service=service,
                object_repository=FakeReplayRepository({}),
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("download_probe_no_strategy_items_selected", result["blocking_reasons"])
            self.assertEqual(service.detail_calls, [])
            self.assertEqual(service.attachment_calls, [])

    def test_bid_file_publicity_download_is_limited_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root, items=[_strategy_item("08", "https://example.test/08.html")])
            repo = FakeReplayRepository(
                {
                    "DETAIL-08": _replay("DETAIL-08", b"<html>detail 08</html>", "text/html"),
                    "ATT-08-1": _replay("ATT-08-1", b"%PDF public 1", "application/pdf"),
                    "ATT-08-2": _replay("ATT-08-2", b"%PDF public 2", "application/pdf"),
                    "ATT-08-3": _replay("ATT-08-3", b"%PDF public 3", "application/pdf"),
                }
            )
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/08.html": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "DETAIL-08",
                        "same_site_attachment_link_items": [
                            {"url": "https://example.test/attach/public1.pdf", "text": "投标文件1.pdf"},
                            {"url": "https://example.test/attach/public2.pdf", "text": "投标文件2.pdf"},
                            {"url": "https://example.test/attach/public3.pdf", "text": "投标文件3.pdf"},
                        ],
                    }
                },
                attachment_map={
                    "https://example.test/attach/public1.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-08-1",
                        "attachment_url": "https://example.test/attach/public1.pdf",
                    },
                    "https://example.test/attach/public2.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-08-2",
                        "attachment_url": "https://example.test/attach/public2.pdf",
                    },
                    "https://example.test/attach/public3.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-08-3",
                        "attachment_url": "https://example.test/attach/public3.pdf",
                    },
                },
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["08"],
                max_bid_file_publicity_downloads_per_project=2,
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["listed_attachment_count"], 3)
            self.assertEqual(result["summary"]["download_attempted_count"], 2)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 2)
            self.assertEqual(len(service.attachment_calls), 2)
            self.assertEqual(service.attachment_calls[-1]["url"], "https://example.test/attach/public2.pdf")

    def test_max_attachments_per_flow_item_defers_extra_tender_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root)
            repo = FakeReplayRepository(
                {
                    "DETAIL-03": _replay("DETAIL-03", b"<html>detail 03</html>", "text/html"),
                    "ATT-03-1": _replay("ATT-03-1", b"%PDF 1", "application/pdf"),
                    "ATT-03-2": _replay("ATT-03-2", b"%PDF 2", "application/pdf"),
                }
            )
            links = [
                {"url": f"https://example.test/attach/tender{index}.pdf", "text": f"招标文件{index}.pdf"}
                for index in range(1, 5)
            ]
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/03.html": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "DETAIL-03",
                        "same_site_attachment_link_items": links,
                    }
                },
                attachment_map={
                    "https://example.test/attach/tender1.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-03-1",
                        "attachment_url": "https://example.test/attach/tender1.pdf",
                    },
                    "https://example.test/attach/tender2.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-03-2",
                        "attachment_url": "https://example.test/attach/tender2.pdf",
                    },
                },
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["03"],
                max_attachments_per_flow_item=2,
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["listed_attachment_count"], 4)
            self.assertEqual(result["summary"]["download_attempted_count"], 2)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 2)
            self.assertEqual(result["summary"]["failure_taxonomy_counts"]["DEFERRED_BY_DOWNLOAD_REPAIR_LIMIT"], 2)
            self.assertEqual(len(service.attachment_calls), 2)
            sample = result["manifest"]["project_sample_items"][0]
            self.assertEqual(sample["deferred_attachment_count"], 2)

    def test_failed_snapshot_readback_is_taxonomy_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root)
            repo = FakeReplayRepository(
                {
                    "DETAIL-03": _replay("DETAIL-03", b"<html>detail 03</html>", "text/html"),
                    "ATT-MISSING": {"snapshot_id": "ATT-MISSING", "replayable": False, "readback_state": "MISSING_OBJECT"},
                }
            )
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/03.html": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "DETAIL-03",
                        "same_site_attachment_link_items": [
                            {"url": "https://example.test/attach/tender.pdf", "text": "招标文件.pdf"}
                        ],
                    }
                },
                attachment_map={
                    "https://example.test/attach/tender.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-MISSING",
                        "attachment_url": "https://example.test/attach/tender.pdf",
                    }
                },
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["03"],
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["attachment_snapshot_count"], 0)
            sample = result["manifest"]["project_sample_items"][0]
            self.assertIn("attachment_snapshot_not_captured", sample["failure_taxonomy"])
            self.assertEqual(sample["target_execution_state"], "DOWNLOAD_PROBE_PARTIAL_REVIEW")

    def test_html_navigation_links_are_not_treated_as_download_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root, items=[_strategy_item("04", "https://example.test/04.html")])
            repo = FakeReplayRepository(
                {"DETAIL-04": _replay("DETAIL-04", b"<html>clarification</html>", "text/html")}
            )
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/04.html": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "DETAIL-04",
                        "same_site_attachment_link_items": [
                            {"url": "https://example.test/jyfw/002001004/trade_purchasetoplen6.html", "text": "/ 答疑纪要"}
                        ],
                    }
                }
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["04"],
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["listed_attachment_count"], 0)
            self.assertEqual(service.attachment_calls, [])
            sample = result["manifest"]["project_sample_items"][0]
            self.assertIn("attachment_links_rejected_as_non_download_navigation", sample["failure_taxonomy"])

    def test_detail_transport_attempts_are_carried_into_probe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root)
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/03.html": {
                        "status": "DEGRADED",
                        "degraded_reasons": ["fetch_failed"],
                        "detail_transport_attempts": [
                            {
                                "route": "guangzhou_https_browser",
                                "state": "FAILED",
                                "failure_taxonomy": ["detail_ssl_protocol_error", "detail_browser_route_failed"],
                            }
                        ],
                    }
                }
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["03"],
                execute=True,
                stage2_service=service,
                object_repository=FakeReplayRepository({}),
                created_at="2026-05-10T00:00:00+08:00",
            )

            sample = result["manifest"]["project_sample_items"][0]
            item = result["manifest"]["items"][0]
            self.assertEqual(sample["detail_transport_attempts"][0]["route"], "guangzhou_https_browser")
            self.assertEqual(item["detail_transport_attempts"][0]["route"], "guangzhou_https_browser")
            self.assertIn("detail_ssl_protocol_error", sample["failure_taxonomy"])

    def test_use_all_analysis_projects_selects_all_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_multi_project_inputs(input_root)
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/11111/07.html": {"status": "FETCHED", "snapshot_id_optional": "DETAIL-11111"},
                    "https://example.test/22222/07.html": {"status": "FETCHED", "snapshot_id_optional": "DETAIL-22222"},
                }
            )
            repo = FakeReplayRepository(
                {
                    "DETAIL-11111": _replay("DETAIL-11111", b"<html>11111</html>", "text/html"),
                    "DETAIL-22222": _replay("DETAIL-22222", b"<html>22222</html>", "text/html"),
                }
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=[],
                flow_nos=["07"],
                use_all_analysis_projects=True,
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["download_probe_project_count"], 2)
            self.assertEqual(result["summary"]["flowurl_project_count"], 2)
            self.assertEqual({sample["project_id"] for sample in result["manifest"]["project_sample_items"]}, {"PROJ-CN-GD-JG2026-11111", "PROJ-CN-GD-JG2026-22222"})

    def test_expired_attachment_link_refreshes_detail_and_retries_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "input"
            output_root = root / "output"
            _write_inputs(input_root, items=[_strategy_item("08", "https://example.test/08_tb.html")])
            service = FakeStage2Service(
                detail_map={
                    "https://example.test/08_tb.html": [
                        {
                            "status": "FETCHED",
                            "snapshot_id_optional": "DETAIL-08-A",
                            "same_site_attachment_link_items": [
                                {"url": "https://example.test/attach/expired.pdf", "text": "投标文件公开.pdf"}
                            ],
                        },
                        {
                            "status": "FETCHED",
                            "snapshot_id_optional": "DETAIL-08-B",
                            "same_site_attachment_link_items": [
                                {"url": "https://example.test/attach/fresh.pdf", "text": "投标文件公开.pdf"}
                            ],
                        },
                    ]
                },
                attachment_map={
                    "https://example.test/attach/expired.pdf": {
                        "status": "DEGRADED",
                        "attachment_failure_taxonomy": ["attachment_url_expired", "ATTACHMENT_INTERFACE_ERROR"],
                    },
                    "https://example.test/attach/fresh.pdf": {
                        "status": "FETCHED",
                        "snapshot_id_optional": "ATT-08-FRESH",
                        "attachment_url": "https://example.test/attach/fresh.pdf",
                        "content_type": "application/pdf",
                    },
                },
            )
            repo = FakeReplayRepository(
                {
                    "DETAIL-08-A": _replay("DETAIL-08-A", b"<html>old</html>", "text/html"),
                    "DETAIL-08-B": _replay("DETAIL-08-B", b"<html>new</html>", "text/html"),
                    "ATT-08-FRESH": _replay("ATT-08-FRESH", b"%PDF fresh", "application/pdf"),
                }
            )

            result = build_guangzhou_download_probe(
                input_root=input_root,
                output_root=output_root,
                project_ids=["JG2026-10815"],
                flow_nos=["08"],
                max_bid_file_publicity_downloads_per_project=2,
                execute=True,
                stage2_service=service,
                object_repository=repo,
                created_at="2026-05-10T00:00:00+08:00",
            )

            self.assertEqual(len(service.detail_calls), 2)
            self.assertEqual([call["url"] for call in service.attachment_calls], ["https://example.test/attach/expired.pdf", "https://example.test/attach/fresh.pdf"])
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 1)
            sample = result["manifest"]["project_sample_items"][0]
            self.assertEqual(sample["attachment_snapshot_refs"][0]["snapshot_id"], "ATT-08-FRESH")


class FakeStage2Service:
    def __init__(self, detail_map: dict[str, dict] | None = None, attachment_map: dict[str, dict] | None = None) -> None:
        self.detail_map = detail_map or {}
        self.attachment_map = attachment_map or {}
        self.detail_calls: list[dict[str, object]] = []
        self.attachment_calls: list[dict[str, object]] = []

    def fetch_real_public_candidate_detail_url(self, url: str, **kwargs: object) -> dict:
        self.detail_calls.append({"url": url, **kwargs})
        value = self.detail_map.get(url, {"status": "DEGRADED", "degraded_reasons": ["detail_missing"]})
        if isinstance(value, list):
            index = sum(1 for call in self.detail_calls if call["url"] == url) - 1
            return dict(value[min(index, len(value) - 1)])
        return dict(value)

    def fetch_real_public_same_site_attachment_url(self, url: str, **kwargs: object) -> dict:
        self.attachment_calls.append({"url": url, **kwargs})
        return dict(self.attachment_map.get(url, {"status": "DEGRADED", "attachment_failure_taxonomy": ["missing"]}))


class FakeReplayRepository:
    def __init__(self, snapshots: dict[str, dict]) -> None:
        self.snapshots = snapshots

    def replay_snapshot(self, snapshot_id: str) -> dict:
        return dict(
            self.snapshots.get(
                snapshot_id,
                {"snapshot_id": snapshot_id, "replayable": False, "readback_state": "MISSING_MANIFEST"},
            )
        )


def _write_inputs(input_root: Path, items: list[dict[str, object]] | None = None) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    strategy_items = items or [_strategy_item("03", "https://example.test/03.html")]
    (input_root / "analysis-plan.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "items": strategy_items,
                    "summary": {},
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (input_root / "run-manifest.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "project_sample_items": [
                        {
                            "project_id": "PROJ-CN-GD-JG2026-10815",
                            "project_name": "广州测试项目招标公告",
                            "document_kind": "tender_file",
                            "guangzhou_flow_no": "03",
                            "guangzhou_flow_title": "招标公告/关联公告",
                            "source_url": "https://example.test/03.html",
                            "published_at_optional": "2026-05-10 00:00:00",
                            "source_project_code": "JG2026-10815",
                            "project_match_key": "JG2026-10815",
                        }
                    ]
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (input_root / "project-file-audit.json").write_text(
        json.dumps({"manifest": {"items": [], "summary": {}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_multi_project_inputs(input_root: Path) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    items = [
        _strategy_item("07", "https://example.test/11111/07.html", project_id="PROJ-CN-GD-JG2026-11111"),
        _strategy_item("07", "https://example.test/22222/07.html", project_id="PROJ-CN-GD-JG2026-22222"),
    ]
    samples = [
        {
            "project_id": item["project_id"],
            "project_name": f"{item['project_id']}候选公示",
            "document_kind": "candidate_notice",
            "guangzhou_flow_no": "07",
            "guangzhou_flow_title": "中标候选人公示",
            "source_url": item["source_url"],
            "published_at_optional": "2026-05-10 00:00:00",
        }
        for item in items
    ]
    (input_root / "analysis-plan.json").write_text(
        json.dumps({"manifest": {"items": items, "summary": {"project_count": 2}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (input_root / "run-manifest.json").write_text(
        json.dumps({"manifest": {"project_sample_items": samples, "summary": {"unique_project_count": 2}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (input_root / "project-file-audit.json").write_text(
        json.dumps({"manifest": {"items": [], "summary": {}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _strategy_item(
    flow_no: str,
    url: str,
    *,
    adapter_validation_only: bool = False,
    download_policy: str = "DOWNLOAD_REQUIRED",
    project_id: str = "PROJ-CN-GD-JG2026-10815",
) -> dict[str, object]:
    return {
        "strategy_item_id": f"STRATEGY-{flow_no}",
        "project_id": project_id,
        "project_name": "广州测试项目中标候选人公示",
        "product_mode": "POST_CANDIDATE_EVIDENCE_PACK",
        "strategy_state": "POST_CANDIDATE_READY",
        "flow_no": flow_no,
        "flow_title": f"{flow_no}流程",
        "document_kind": "bid_file_publicity" if flow_no == "08" else "tender_file",
        "source_url": url,
        "published_date": "2026-05-10",
        "download_policy": download_policy,
        "download_required": download_policy != "SKIP",
        "parse_depth": "SECTION_PARSE",
        "adapter_validation_only": adapter_validation_only,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _replay(snapshot_id: str, data: bytes, content_type: str) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "replayable": True,
        "readback_state": "READBACK_READY",
        "content_type": content_type,
        "byte_size": len(data),
        "sha256": "sha",
        "bytes": data,
        "manifest": {"source_url_optional": "https://example.test/file"},
    }


if __name__ == "__main__":
    unittest.main()
