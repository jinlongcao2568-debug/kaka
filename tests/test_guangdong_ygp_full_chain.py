from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import storage.guangdong_ygp_full_chain as full_chain  # noqa: E402
from storage.guangdong_ygp_full_chain import (  # noqa: E402
    _attachment_failure_taxonomy,
    build_guangdong_ygp_full_chain,
)


class GuangdongYgpFullChainTests(unittest.TestCase):
    def test_dry_run_without_city_results_keeps_empty_manifest_without_path_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = build_guangdong_ygp_full_chain(
                output_root=Path(tmp_dir) / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                execute=False,
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["execution_mode"], "DRY_RUN")
            self.assertEqual(result["summary"]["project_count"], 0)
            self.assertEqual(result["summary"]["flow_item_count"], 0)
            self.assertEqual(result["summary"]["city_no_supported_07_candidate_count"], 0)

    def test_execute_builds_attachment_downloads_human_dirs_responsible_probe_and_reports(self) -> None:
        calls: list[str] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangdong_ygp_full_chain(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                flow_nos=["03", "04", "07", "08"],
                max_attachments_per_flow_item=5,
                execute=True,
                http_getter=_fake_ygp_full_chain_getter(download_calls=calls, with_certificate=True),
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_count"], 1)
            self.assertEqual(summary["city_search_ready_count"], 1)
            self.assertEqual(summary["city_no_supported_07_candidate_count"], 0)
            self.assertEqual(summary["flow_item_count"], 4)
            self.assertEqual(summary["listed_attachment_count"], 4)
            self.assertEqual(summary["download_attempted_count"], 3)
            self.assertEqual(summary["attachment_snapshot_count"], 3)
            self.assertEqual(summary["batch_closeout_state"], "YGP_FULL_CHAIN_READY")
            self.assertEqual(summary["flow_08_register_only_count"], 1)
            self.assertEqual(summary["responsible_person_summary"]["project_count"], 1)
            self.assertEqual(
                summary["responsible_person_summary"]["stage4_input_count"],
                1,
            )
            self.assertFalse(any("row-notice08" in url for url in calls))
            self.assertTrue(any("row-notice03" in url for url in calls))

            out = root / "out"
            self.assertTrue((out / "ygp-full-chain-manifest.json").exists())
            self.assertTrue((out / "attachment-list.json").exists())
            self.assertTrue((out / "project-file-audit.json").exists())
            self.assertTrue((out / "human-readable-file-map.json").exists())
            self.assertTrue((out / "manual-url-check-table.json").exists())
            self.assertTrue((out / "challenge-stability-report.json").exists())
            self.assertTrue((out / "ygp-evidence-report-v1.json").exists())
            self.assertTrue((out / "guangdong-ygp-batch-stability-closeout-v1.json").exists())
            self.assertTrue(list((out / "projects" / "CN-GD" / "440400").glob("PROJ-CN-GD-YGP-*")))
            self.assertEqual(len(list(out.rglob("download-probe.json"))), 4)

            attachment_list = json.loads((out / "attachment-list.json").read_text(encoding="utf-8"))
            self.assertEqual(attachment_list["summary"]["attachment_count"], 4)
            owner_keys = {
                (
                    item["project_id"],
                    item["city_code"],
                    item["flow_no"],
                    item["detail_url"],
                )
                for item in attachment_list["attachment_items"]
            }
            self.assertEqual(len(owner_keys), 4)

            evidence = json.loads((out / "ygp-evidence-report-v1.json").read_text(encoding="utf-8"))
            self.assertIn("verification_evidence", evidence)
            self.assertIn("process_stability", evidence)
            self.assertIn("optimization_recommendations", evidence)
            self.assertFalse(evidence["customer_visible_allowed"])

            manifest_text = json.dumps(result, ensure_ascii=False)
            for term in ("无风险", "无冲突", "在建冲突成立", "违法成立", "确认本人", "造假成立", "是不是本人"):
                self.assertNotIn(term, manifest_text)

    def test_company_first_and_name_enumeration_miss_keeps_flow08_as_targeted_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangdong_ygp_full_chain(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                flow_nos=["07", "08"],
                execute=True,
                company_first_result_state="NO_MATCH",
                name_enumeration_result_state="NO_MATCH",
                http_getter=_fake_ygp_full_chain_getter(download_calls=[], with_certificate=False),
                created_at="2026-05-15T00:00:00+08:00",
            )

            supplement = json.loads(
                (root / "out" / "company-first-supplement" / "company-first-certificate-supplement.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                supplement["manifest"]["items"][0]["supplement_probe_state"],
                "FLOW_08_TARGETED_PARSE_REQUIRED",
            )
            self.assertTrue(supplement["manifest"]["items"][0]["flow_08_targeted_parse_required"])
            flow08_items = [item for item in result["manifest"]["items"] if item["flow_no"] == "08"]
            self.assertEqual(flow08_items[0]["download_policy_state"], "FLOW_08_REGISTER_ONLY")
            self.assertIn(
                "FLOW_08_REGISTER_ONLY_NOT_DOWNLOADED_BY_DEFAULT",
                flow08_items[0]["failure_taxonomy"],
            )
            self.assertEqual(result["summary"]["batch_closeout_state"], "YGP_FULL_CHAIN_READY")

    def test_download_required_attachments_all_failed_keeps_batch_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch("storage.guangdong_ygp_full_chain._resolve_with_browser", return_value=_failed_challenge_result()):
                result = build_guangdong_ygp_full_chain(
                    output_root=root / "out",
                    city_codes=["440400"],
                    per_city_candidate_limit=1,
                    max_pages_per_city=1,
                    flow_nos=["03", "04", "07"],
                    max_attachments_per_flow_item=5,
                    execute=True,
                    http_getter=_fake_ygp_full_chain_getter(
                        download_calls=[],
                        with_certificate=True,
                        attachment_response_state="html_login",
                    ),
                    created_at="2026-05-15T00:00:00+08:00",
                )

            self.assertEqual(result["summary"]["project_count"], 1)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 0)
            self.assertEqual(result["summary"]["batch_closeout_state"], "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED")
            closeout = json.loads(
                (root / "out" / "guangdong-ygp-batch-stability-closeout-v1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(closeout["summary"]["download_required_attachment_snapshot_count"], 0)
            self.assertIn("ygp_attachment_login_or_permission_required", closeout["summary"]["download_blocker_taxonomy_counts"])

    def test_download_required_partial_failure_keeps_batch_partial_even_with_successes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch("storage.guangdong_ygp_full_chain._resolve_with_browser", return_value=_failed_challenge_result()):
                result = build_guangdong_ygp_full_chain(
                    output_root=root / "out",
                    city_codes=["440400"],
                    per_city_candidate_limit=1,
                    max_pages_per_city=1,
                    flow_nos=["03", "04", "07"],
                    max_attachments_per_flow_item=5,
                    execute=True,
                    http_getter=_fake_ygp_full_chain_getter(
                        download_calls=[],
                        with_certificate=True,
                        attachment_response_state="second_html_login",
                    ),
                    created_at="2026-05-15T00:00:00+08:00",
                )

            self.assertEqual(result["summary"]["download_attempted_count"], 3)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 2)
            self.assertEqual(result["summary"]["batch_closeout_state"], "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED")
            closeout = json.loads(
                (root / "out" / "guangdong-ygp-batch-stability-closeout-v1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(closeout["summary"]["download_required_failed_attempt_count"], 1)

    def test_empty_response_records_probe_and_retries_after_detail_prewarm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            context_calls: list[Mapping[str, Any]] = []
            result = build_guangdong_ygp_full_chain(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                flow_nos=["07"],
                execute=True,
                http_getter=_fake_ygp_full_chain_getter(
                    download_calls=[],
                    context_calls=context_calls,
                    with_certificate=True,
                    attachment_response_state="empty_then_file",
                ),
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["attachment_snapshot_count"], 1)
            probe = json.loads(next((root / "out").rglob("download-probe.json")).read_text(encoding="utf-8"))
            attempt = probe["download_attempts"][0]
            self.assertEqual(attempt["status"], "FETCHED")
            self.assertEqual(attempt["file_size_bytes"], 12345)
            self.assertEqual(attempt["download_diagnostics"]["response_attempts"][0]["content_length"], 0)
            self.assertEqual(attempt["download_diagnostics"]["response_attempts"][1]["phase"], "after_detail_prewarm_retry")
            self.assertTrue(any(call["route"] == "ygp_detail_prewarm" for call in context_calls))

    def test_oversize_size_probe_is_policy_deferred_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            download_calls: list[str] = []
            result = build_guangdong_ygp_full_chain(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                flow_nos=["07"],
                execute=True,
                http_getter=_fake_ygp_full_chain_getter(
                    download_calls=download_calls,
                    with_certificate=True,
                    attachment_response_state="oversize_size",
                ),
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["download_attempted_count"], 0)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 0)
            probe = json.loads(next((root / "out").rglob("download-probe.json")).read_text(encoding="utf-8"))
            attempt = probe["download_attempts"][0]
            self.assertEqual(attempt["status"], "POLICY_DEFERRED")
            self.assertIn("OVERSIZE_DEFERRED_BY_POLICY", attempt["failure_taxonomy"])
            self.assertEqual(attempt["file_size_bytes"], 50 * 1024 * 1024)
            self.assertEqual(download_calls, [])

    def test_interface_error_triggers_detail_prewarm_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            context_calls: list[Mapping[str, Any]] = []
            result = build_guangdong_ygp_full_chain(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                flow_nos=["07"],
                execute=True,
                http_getter=_fake_ygp_full_chain_getter(
                    download_calls=[],
                    context_calls=context_calls,
                    with_certificate=True,
                    attachment_response_state="interface_then_file",
                ),
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["attachment_snapshot_count"], 1)
            probe = json.loads(next((root / "out").rglob("download-probe.json")).read_text(encoding="utf-8"))
            attempt = probe["download_attempts"][0]
            self.assertEqual(attempt["download_diagnostics"]["response_attempts"][0]["content_type"], "application/json")
            self.assertIn("errcode", attempt["download_diagnostics"]["response_attempts"][0]["response_probe"])
            self.assertTrue(any(call["route"] == "ygp_detail_prewarm" for call in context_calls))

    def test_not_file_like_json_attempts_challenge_resolver_or_records_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch("storage.guangdong_ygp_full_chain._resolve_with_browser", return_value=_failed_challenge_result()) as resolver:
                result = build_guangdong_ygp_full_chain(
                    output_root=root / "out",
                    city_codes=["440400"],
                    per_city_candidate_limit=1,
                    max_pages_per_city=1,
                    flow_nos=["07"],
                    execute=True,
                    http_getter=_fake_ygp_full_chain_getter(
                        download_calls=[],
                        with_certificate=True,
                        attachment_response_state="not_file_like_json",
                    ),
                    created_at="2026-05-15T00:00:00+08:00",
                )

            self.assertTrue(resolver.called)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 0)
            self.assertEqual(result["summary"]["batch_closeout_state"], "YGP_FULL_CHAIN_PARTIAL_REVIEW_REQUIRED")
            probe = json.loads(next((root / "out").rglob("download-probe.json")).read_text(encoding="utf-8"))
            attempt = probe["download_attempts"][0]
            self.assertIn("ygp_attachment_not_file_like_response", attempt["failure_taxonomy"])
            self.assertTrue(attempt["challenge_diagnostic"]["attempted"])

    def test_flow08_register_only_without_download_still_can_closeout_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_guangdong_ygp_full_chain(
                output_root=root / "out",
                city_codes=["440400"],
                per_city_candidate_limit=1,
                max_pages_per_city=1,
                flow_nos=["08"],
                execute=True,
                http_getter=_fake_ygp_full_chain_getter(download_calls=[], with_certificate=True),
                created_at="2026-05-15T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["flow_item_count"], 1)
            self.assertEqual(result["summary"]["flow_08_register_only_count"], 1)
            self.assertEqual(result["summary"]["attachment_snapshot_count"], 0)
            self.assertEqual(result["summary"]["batch_closeout_state"], "YGP_FULL_CHAIN_READY")

    def test_attachment_failure_taxonomy_classifies_challenge_login_expired_empty_response(self) -> None:
        self.assertIn(
            "ygp_attachment_captcha_or_challenge_required",
            _attachment_failure_taxonomy(status_code=200, content_type="text/html", data="需要验证码".encode(), error=""),
        )
        self.assertIn(
            "ygp_attachment_login_or_permission_required",
            _attachment_failure_taxonomy(status_code=200, content_type="text/html", data="请登录后下载".encode(), error=""),
        )
        self.assertIn(
            "ygp_attachment_interface_expired_or_stale",
            _attachment_failure_taxonomy(status_code=200, content_type="application/json", data="接口已过期".encode(), error=""),
        )
        self.assertIn(
            "ygp_attachment_empty_response_review",
            _attachment_failure_taxonomy(status_code=200, content_type="application/octet-stream", data=b"", error=""),
        )
        self.assertIn(
            "OVERSIZE_DEFERRED_BY_POLICY",
            _attachment_failure_taxonomy(
                status_code=200,
                content_type="application/zip",
                data=b"",
                error="attachment_content_length_exceeds_limit:244172800>31457280",
            ),
        )
        self.assertIn(
            "ygp_attachment_incomplete_read_retry_required",
            _attachment_failure_taxonomy(status_code=0, content_type="", data=b"", error="IncompleteRead:partial"),
        )

    def test_http_retry_delay_respects_ygp_chinese_retry_after_message(self) -> None:
        self.assertEqual(
            full_chain._http_retry_delay_seconds(
                {"status_code": 429, "body": "{\"errmsg\":\"访问频率过高，请34秒后重试\"}"},
                attempt_no=1,
            ),
            34.0,
        )

    def test_human_attachment_path_is_shortened_and_keeps_source_file_name_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            long_title = "珠海市海水淡化一期工程第二标段施工" * 5
            source_dir = full_chain._flow_notice_directory(
                output_root=root / ("guangdong-ygp-full-chain-v1-live-smoke-" + "x" * 40),
                city_code="440400",
                project_id="PROJ-CN-GD-YGP-440400-E4404000001005932001",
                flow_no="04",
                flow_title="澄清答疑_更正公告" * 4,
                published_date="2026-04-14",
                title=long_title,
            )
            original_file_name = "E4404000001005932001001招标文件" * 6 + ".zip"
            self.assertTrue(any(part.startswith("PROJ-CN-GD-") for part in source_dir.parts))
            local_path = Path(
                full_chain._write_human_attachment(
                    source_dir=source_dir,
                    file_name=original_file_name,
                    index=1,
                    data=b"PK\x03\x04fake",
                    ref_sha256="abc123",
                    snapshot_id="YGP-ATTACH-0123456789abcdef",
                    source_url="https://example.test/file.zip",
                )
            )

            self.assertTrue(local_path.exists())
            self.assertLessEqual(len(local_path.name), 80)
            meta = json.loads(local_path.with_suffix(local_path.suffix + ".meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source_file_name"], original_file_name)
            self.assertEqual(meta["human_file_name"], local_path.name)

    def test_human_attachment_write_failure_degrades_without_crashing_batch(self) -> None:
        original_writer = full_chain._write_human_attachment

        def raising_writer(**_: Any) -> str:
            raise OSError("simulated long path")

        full_chain._write_human_attachment = raising_writer
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                result = full_chain.build_guangdong_ygp_full_chain(
                    output_root=root / "out",
                    city_codes=["440400"],
                    per_city_candidate_limit=1,
                    max_pages_per_city=1,
                    flow_nos=["03"],
                    max_attachments_per_flow_item=1,
                    execute=True,
                    http_getter=_fake_ygp_full_chain_getter(download_calls=[], with_certificate=True),
                    created_at="2026-05-15T00:00:00+08:00",
                )
                self.assertTrue(result["safe_to_execute"])
                self.assertEqual(result["summary"]["download_attempted_count"], 1)
                self.assertEqual(result["summary"]["attachment_snapshot_count"], 0)
                attempt_files = list((root / "out").rglob("download-probe.json"))
                self.assertEqual(len(attempt_files), 1)
                probe = json.loads(attempt_files[0].read_text(encoding="utf-8"))
                attempt = probe["download_attempts"][0]
                self.assertEqual(attempt["status"], "DEGRADED")
                self.assertIn("ygp_attachment_snapshot_captured_human_write_failed", attempt["failure_taxonomy"])
        finally:
            full_chain._write_human_attachment = original_writer


def _fake_ygp_full_chain_getter(
    *,
    download_calls: list[str],
    with_certificate: bool,
    attachment_response_state: str = "file",
    context_calls: list[Mapping[str, Any]] | None = None,
):
    def getter(url: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
        route = str(context.get("route") or "")
        if context_calls is not None:
            context_calls.append({"url": url, "route": route, "headers": dict(context.get("headers") or {})})
        if route == "ygp_city_search":
            return {
                "status_code": 200,
                "content_type": "application/json;charset=UTF-8",
                "body": json.dumps({"data": {"pageData": [_candidate_item()]}}, ensure_ascii=False),
                "url": url,
            }
        if "nodeList" in url:
            return {
                "status_code": 200,
                "content_type": "application/json;charset=UTF-8",
                "body": json.dumps({"data": _node_list_payload()}, ensure_ascii=False),
                "url": url,
            }
        if "detail" in url:
            params = _query(url)
            notice_id = params.get("noticeId", "")
            return {
                "status_code": 200,
                "content_type": "application/json;charset=UTF-8",
                "body": json.dumps({"data": _detail_payload(notice_id, with_certificate=with_certificate)}, ensure_ascii=False),
                "url": url,
            }
        if route == "ygp_attachment_file_size":
            size = 50 * 1024 * 1024 if attachment_response_state == "oversize_size" else 12345
            return {
                "status_code": 200,
                "content_type": "application/json",
                "body": json.dumps({"errcode": 0, "errmsg": "ok", "data": str(size)}, ensure_ascii=False),
                "url": url,
            }
        if route == "ygp_attachment_head_size":
            return {
                "status_code": 200,
                "content_type": "application/octet-stream",
                "headers": {"Content-Length": "12345"},
                "body": "",
                "url": url,
            }
        if route == "ygp_attachment_download":
            download_calls.append(url)
            if attachment_response_state == "html_login" or (
                attachment_response_state == "second_html_login" and "row-notice04" in url
            ):
                return {
                    "status_code": 200,
                    "content_type": "text/html;charset=UTF-8",
                    "body": "<html>请登录后下载</html>",
                    "url": url,
                }
            if attachment_response_state == "empty_then_file":
                return {
                    "status_code": 200,
                    "content_type": "application/pdf",
                    "content": b"",
                    "url": url,
                }
            if attachment_response_state == "interface_then_file":
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": json.dumps({"errcode": 500, "errmsg": "temporary"}, ensure_ascii=False),
                    "url": url,
                }
            if attachment_response_state == "not_file_like_json":
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": json.dumps({"ok": True, "data": None}, ensure_ascii=False),
                    "url": url,
                }
            return {
                "status_code": 200,
                "content_type": "application/pdf",
                "content": b"%PDF fake ygp attachment",
                "url": url,
            }
        if route == "ygp_attachment_download_retry":
            download_calls.append(url)
            if attachment_response_state == "html_login" or (
                attachment_response_state == "second_html_login" and "row-notice04" in url
            ):
                return {
                    "status_code": 200,
                    "content_type": "text/html;charset=UTF-8",
                    "body": "<html>请登录后下载</html>",
                    "url": url,
                }
            if attachment_response_state in {"empty_then_file", "interface_then_file"}:
                return {
                    "status_code": 200,
                    "content_type": "application/pdf",
                    "content": b"%PDF fake ygp attachment",
                    "url": url,
                }
            if attachment_response_state == "not_file_like_json":
                return {
                    "status_code": 200,
                    "content_type": "application/json",
                    "body": json.dumps({"ok": True, "data": None}, ensure_ascii=False),
                    "url": url,
                }
            return {
                "status_code": 200,
                "content_type": "application/pdf",
                "content": b"%PDF fake ygp attachment",
                "url": url,
            }
        return {"status_code": 404, "content_type": "text/plain", "body": "not found", "url": url}

    return getter


def _failed_challenge_result() -> dict[str, Any]:
    return {
        "content": b"",
        "content_type": "",
        "failure_taxonomy": ["ygp_attachment_challenge_resolver_failed:unit_test"],
        "challenge_diagnostic": {
            "attempted": True,
            "state": "FAILED_CLOSED_CHALLENGE_NOT_RESOLVED",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }


def _candidate_item() -> dict[str, Any]:
    return {
        "noticeId": "notice07",
        "projectCode": "E4404000001005932001",
        "noticeTitle": "珠海测试工程中标候选人公示",
        "noticeSecondType": "A",
        "noticeSecondTypeDesc": "工程建设",
        "noticeThirdTypeDesc": "中标候选人公示",
        "datasetName": "中标候选人公示",
        "tradingProcess": "3C51",
        "regionCode": "440400",
        "siteCode": "440400",
        "publishDate": "20260515171800",
        "edition": "v3",
        "projectType": "A02",
        "projectTypeName": "市政",
        "pubServicePlat": "珠海市公共资源交易中心一体化平台",
    }


def _node_list_payload() -> list[dict[str, Any]]:
    return [
        _node("n03", "招标公告及资格预审", "3C14@招标公告、资格预审公告", "notice03"),
        _node("n04", "招标文件澄清与修改", "3C16@招标文件、招标文件澄清与修改", "notice04"),
        _node("n07", "中标候选人公示", "3C51@中标候选人公示", "notice07"),
        _node("n08", "投标文件公开", "3C71@投标文件公开", "notice08"),
    ]


def _node(node_id: str, name: str, ds_key: str, notice_id: str) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "nodeName": name,
        "selectedBizCode": ds_key.split("@", 1)[0],
        "dataCount": 1,
        "dsList": [{ds_key: [notice_id]}],
    }


def _detail_payload(notice_id: str, *, with_certificate: bool) -> dict[str, Any]:
    certificate = "证书编号：粤1442020202100001\n" if with_certificate else ""
    candidate_text = (
        "第一中标候选人：珠海测试建设有限公司\n"
        "项目负责人：张三\n"
        f"{certificate}"
        "投标报价：1234.56万元"
    )
    return {
        "title": f"珠海测试工程{notice_id}",
        "publishDate": "2026-05-15",
        "tradingNoticeColumnModelList": [
            {
                "name": "主要信息",
                "multiKeyValueTableList": [
                    [
                        {"key": "项目名称", "value": "珠海测试工程"},
                        {"key": "中标候选人", "value": "珠海测试建设有限公司"},
                        {"key": "项目负责人", "value": "张三"},
                        {"key": "证书编号", "value": "粤1442020202100001" if with_certificate else ""},
                    ]
                ],
                "richtext": f"<p>{candidate_text}</p>",
                "noticeFileBOList": [
                    {
                        "fileName": f"{notice_id}.pdf" if notice_id != "notice08" else "投标文件公开.zip",
                        "rowGuid": f"row-{notice_id}",
                        "flowId": f"flow-{notice_id}",
                    }
                ],
            }
        ],
    }


def _query(url: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse

    return {key: values[-1] for key, values in parse_qs(urlparse(url).query).items() if values}


if __name__ == "__main__":
    unittest.main()
