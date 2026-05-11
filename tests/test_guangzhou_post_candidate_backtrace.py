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

from storage.guangzhou_post_candidate_backtrace import (  # noqa: E402
    ATTACHMENT_LISTED,
    CLICK_DOWNLOAD_ENDPOINT_FOUND,
    EPOINT_CHALLENGE_REQUIRED,
    FLOW_URL_DISCOVERED,
    FLOW_SAMPLE_NOT_FOUND,
    INTERFACE_UNRESOLVED,
    LOGIN_OR_CA_REQUIRED,
    NO_PUBLIC_ATTACHMENT,
    OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND,
    PARTIAL_RUN_INTERRUPTED,
    PIPELINE_STAGE_ATTACHMENT_LIST,
    PIPELINE_STAGE_FLOW_URL_ONLY,
    SCRIPT_DOWNLOAD_ENDPOINT_FOUND,
    STATIC_ATTACHMENT_LINK_FOUND,
    _annotate_project_samples,
    _backtrace_targets_for_entries,
    _build_flow_interface_coverage_manifest,
    _build_flow_url_manifest,
    _build_manual_interface_check_table,
    _build_pipeline_state_manifest,
    _entry_targets_with_candidate_limit,
    _flow_url_project_sample_items,
    _guangzhou_flow_interface_targets,
    _maybe_resume_flow_url_manifest,
    _scan_guangzhou_interface_html,
)


class TestGuangzhouPostCandidateBacktrace(unittest.TestCase):
    def test_entry_targets_override_small_fixture_target_count_for_batch_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_targets = Path(tmp_dir) / "targets.json"
            base_targets.write_text(
                json.dumps(
                    {
                        "target_version": 1,
                        "target_policy": {"customer_visible_allowed": False},
                        "targets": [
                            {
                                "target_id": "REAL-GD-CANDIDATE-001",
                                "target_count": 4,
                                "selection_filters": ["工程建设", "中标候选人公示"],
                            },
                            {
                                "target_id": "REAL-GD-AWARD-001",
                                "target_count": 3,
                                "selection_filters": ["工程建设", "中标结果公告"],
                            },
                            {
                                "target_id": "REAL-ZJ-CANDIDATE-001",
                                "target_count": 4,
                                "selection_filters": ["浙江"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            path = _entry_targets_with_candidate_limit(
                base_targets_path=base_targets,
                output_root=Path(tmp_dir),
                per_target_candidate_limit=30,
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual({item["target_id"] for item in payload["targets"]}, {"REAL-GD-CANDIDATE-001"})
            self.assertTrue(all(item["target_count"] == 30 for item in payload["targets"]))
            self.assertTrue(
                all("POST_CANDIDATE_BATCH_LIMIT:30" in item["selection_filters"] for item in payload["targets"])
            )

    def test_backtrace_targets_start_from_post_candidate_entry_and_include_project_filters(self) -> None:
        targets = _backtrace_targets_for_entries(
            [
                {
                    "project_id": "PROJ-CN-GD-JG2026-POST",
                    "project_name": "南沙区排水设施小修项目施工中标候选人公示",
                    "source_project_code": "JG2026-POST",
                    "project_match_key": "JG2026-POST",
                }
            ]
        )

        self.assertEqual(len(targets["targets"]), 12)
        self.assertEqual(
            {target["document_kind"] for target in targets["targets"]},
            {
                "bid_plan",
                "tender_file_publicity",
                "tender_file",
                "clarification_notice",
                "opening_info",
                "qualification_review_result",
                "candidate_notice",
                "bid_file_publicity",
                "award_result",
                "award_info",
                "contract_public_info",
                "project_exception",
            },
        )
        for target in targets["targets"]:
            filters = target["selection_filters"]
            self.assertIn("BACKTRACE_PROJECT_CODE:JG2026-POST", filters)
            self.assertIn("BACKTRACE_RELATION_GUID:JG2026-POST", filters)
            self.assertTrue(any(item.startswith("BACKTRACE_FLOW_CODE:") for item in filters))
            self.assertTrue(any(item.startswith("BACKTRACE_PROJECT_NAME:") for item in filters))
            self.assertIn("BACKTRACE_BASE_PROJECT_NAME:南沙区排水设施小修项目施工", filters)
            self.assertIn("BACKTRACE_QUERY_VARIANT:南沙区排水设施小修项目", filters)
            self.assertIn("南沙区排水设施小修项目", target["backtrace_query_variants"])
            self.assertEqual(target["required_fetch_profile_id_optional"], "GUANGZHOU-YWTB-CONSTRUCTION-LIST")

    def test_backtrace_targets_skip_entry_stage_already_captured(self) -> None:
        targets = _backtrace_targets_for_entries(
            [
                {
                    "project_id": "PROJ-CN-GD-JG2026-POST",
                    "project_name": "南沙区排水设施小修项目施工中标候选人公示",
                    "source_project_code": "JG2026-POST",
                    "project_match_key": "JG2026-POST",
                    "present_document_kinds": ["candidate_notice", "award_result"],
                }
            ]
        )

        kinds = [target["document_kind"] for target in targets["targets"]]
        self.assertNotIn("candidate_notice", kinds)
        self.assertNotIn("award_result", kinds)
        self.assertIn("tender_file", kinds)

    def test_annotates_missing_and_complete_backtrace_states(self) -> None:
        complete = _annotate_project_samples(
            [
                _sample("bid_plan", project_id="PROJ-1", flow_no="01", flow_code="08"),
                _sample("tender_file_publicity", project_id="PROJ-1", flow_no="02", flow_code="17"),
                _sample("tender_file", project_id="PROJ-1", flow_no="03", flow_code="01"),
                _sample("clarification_notice", project_id="PROJ-1", flow_no="04", flow_code="18"),
                _sample("opening_info", project_id="PROJ-1", flow_no="05", flow_code="19"),
                _sample("qualification_review_result", project_id="PROJ-1", flow_no="06", flow_code="02"),
                _sample("candidate_notice", project_id="PROJ-1", flow_no="07", flow_code="03"),
                _sample("bid_file_publicity", project_id="PROJ-1", flow_no="08", flow_code="04"),
                _sample("award_result", project_id="PROJ-1", flow_no="09", flow_code="06"),
                _sample("award_info", project_id="PROJ-1", flow_no="10", flow_code="05"),
                _sample("contract_public_info", project_id="PROJ-1", flow_no="11", flow_code="07"),
                _sample("project_exception", project_id="PROJ-1", flow_no="12", flow_code="20"),
            ]
        )
        partial = _annotate_project_samples(
            [
                _sample("candidate_notice", project_id="PROJ-2"),
            ]
        )

        self.assertTrue(all(item["backtrace_completeness_state"] == "BACKTRACE_CORE_COMPLETE" for item in complete))
        self.assertTrue(all(item["guangzhou_flow_completeness_state"] == "GUANGZHOU_FLOW_COMPLETE" for item in complete))
        self.assertTrue(all(item["post_candidate_entry_state"] == "POST_CANDIDATE_ENTRY_PRESENT" for item in complete))
        self.assertEqual(partial[0]["backtrace_completeness_state"], "BACKTRACE_PARTIAL")
        self.assertIn("tender_file", partial[0]["missing_stage_kinds"])
        self.assertIn("award_result", partial[0]["missing_stage_kinds"])
        self.assertEqual(partial[0]["guangzhou_flow_completeness_state"], "GUANGZHOU_FLOW_PARTIAL")
        self.assertEqual(partial[0]["default_entry_flow_no"], "07")
        self.assertFalse(partial[0]["late_stage_flows_required_for_recent_candidate"])
        self.assertEqual(partial[0]["recent_candidate_late_stage_missing_non_blocking"], ["11", "12"])

    def test_award_only_project_is_not_current_post_candidate_entry(self) -> None:
        annotated = _annotate_project_samples(
            [
                _sample("award_result", project_id="PROJ-AWARD-ONLY", flow_no="09", flow_code="06"),
            ]
        )

        self.assertEqual(annotated[0]["post_candidate_entry_state"], "POST_CANDIDATE_ENTRY_MISSING")
        self.assertEqual(annotated[0]["post_candidate_entry_document_kinds"], ["candidate_notice"])

    def test_no_match_backtrace_target_attempt_is_attached_to_project(self) -> None:
        annotated = _annotate_project_samples(
            [_sample("candidate_notice", project_id="PROJ-1")],
            target_items=[
                {
                    "target_id": "GZ-BACKTRACE-JG2026-POST-TENDER",
                    "document_kind": "tender_file",
                    "selection_filters": ["BACKTRACE_PROJECT_CODE:JG2026-POST"],
                    "base_project_name": "南沙区排水设施小修项目施工",
                    "backtrace_query_variants": ["JG2026-POST", "南沙区排水设施小修项目施工"],
                    "target_execution_state": "DISCOVERY_NO_MATCH_REVIEW",
                    "failure_taxonomy": ["discovery_no_match"],
                }
            ],
        )

        attempts = annotated[0]["backtrace_stage_attempts"]
        self.assertTrue(any(attempt["document_kind"] == "tender_file" for attempt in attempts))
        tender_attempt = next(attempt for attempt in attempts if attempt["document_kind"] == "tender_file")
        self.assertEqual(tender_attempt["target_execution_state"], "DISCOVERY_NO_MATCH_REVIEW")
        self.assertIn("discovery_no_match", tender_attempt["failure_taxonomy"])
        self.assertEqual(tender_attempt["base_project_name"], "南沙区排水设施小修项目施工")
        self.assertIn("南沙区排水设施小修项目施工", tender_attempt["backtrace_query_variants"])

    def test_flow_url_only_project_samples_do_not_include_snapshots_or_parse(self) -> None:
        rows = _flow_url_project_sample_items(
            plan_item={
                "target_id": "REAL-GD-CANDIDATE-001",
                "document_kind": "candidate_notice",
                "jurisdiction": "CN-GD",
                "required_fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
            },
            selected_candidates=[
                {
                    "candidate_key": "CAND-1",
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "某工程中标候选人公示",
                    "source_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260510/candidate.html",
                    "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                    "source_project_code": "JG2026-10815",
                    "project_match_key": "JG2026-10815",
                    "guangzhou_flow_no": "07",
                    "guangzhou_flow_title": "中标候选人公示",
                    "guangzhou_flow_code": "03",
                    "published_at_optional": "2026-05-10",
                }
            ],
            target_execution_state=FLOW_URL_DISCOVERED,
            failure_taxonomy=[],
        )

        self.assertEqual(rows[0]["pipeline_stage"], PIPELINE_STAGE_FLOW_URL_ONLY)
        self.assertEqual(rows[0]["detail_snapshot_refs"], [])
        self.assertEqual(rows[0]["attachment_snapshot_refs"], [])
        self.assertEqual(rows[0]["detail_capture_status"], "NOT_RUN_FLOW_URL_ONLY")
        self.assertEqual(rows[0]["stage3_parse_state"], "NOT_RUN_FLOW_URL_ONLY")

    def test_flow_url_manifest_outputs_12_flow_matrix_without_downloads(self) -> None:
        sample = _sample("candidate_notice", project_id="PROJ-CN-GD-JG2026-10815", flow_no="07", flow_code="03")
        sample["source_url"] = "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260510/candidate.html"
        sample["published_at_optional"] = "2026-05-10"

        result = _build_flow_url_manifest(
            project_samples=[sample],
            archive_manifest={"items": []},
            created_at="2026-05-10T00:00:00+08:00",
            output_root=Path("tmp/test"),
            per_target_candidate_limit=5,
        )

        project = result["manifest"]["projects"][0]
        self.assertEqual(len(project["flow_matrix"]), 12)
        by_flow = {row["flow_no"]: row for row in project["flow_matrix"]}
        self.assertTrue(by_flow["07"]["present"])
        self.assertIn(sample["source_url"], by_flow["07"]["detail_urls"])
        self.assertFalse(by_flow["07"]["download_enabled"])
        self.assertFalse(by_flow["07"]["parse_enabled"])

    def test_pipeline_state_marks_flow_urls_and_resume_marks_stale_running(self) -> None:
        sample = _sample("candidate_notice", project_id="PROJ-CN-GD-JG2026-10815", flow_no="07", flow_code="03")
        sample["source_url"] = "https://example.test/candidate.html"
        state = _build_pipeline_state_manifest(
            project_samples=[sample],
            items=[],
            created_at="2026-05-10T00:00:00+08:00",
            pipeline_stage=PIPELINE_STAGE_FLOW_URL_ONLY,
        )
        self.assertEqual(state["summary"]["state_counts"][FLOW_URL_DISCOVERED], 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "pipeline-state.json").write_text(
                json.dumps(
                    {"manifest": {"items": [{"state": "RUNNING"}], "summary": {}}},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (root / "run-manifest.json").write_text(
                json.dumps(
                    {
                        "manifest": {"pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY},
                        "summary": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (root / "flow-url-manifest.json").write_text(
                json.dumps(
                    {
                        "manifest": {
                            "pipeline_stage": PIPELINE_STAGE_FLOW_URL_ONLY,
                            "summary": {"project_count": 1},
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            resumed = _maybe_resume_flow_url_manifest(
                root=root,
                per_target_candidate_limit=1,
                created_at="2026-05-10T00:00:00+08:00",
                resume=True,
            )

            self.assertIsNotNone(resumed)
            state_payload = json.loads((root / "pipeline-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_payload["manifest"]["items"][0]["state"], PARTIAL_RUN_INTERRUPTED)

    def test_flow_interface_targets_cover_12_guangzhou_modules_without_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _guangzhou_flow_interface_targets(
                output_root=Path(tmp_dir),
                per_flow_candidate_limit=2,
            )

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["target_set_id"], "guangzhou-flow-interface-coverage-v1")
        self.assertEqual(len(payload["targets"]), 12)
        self.assertTrue(all(item["target_count"] == 2 for item in payload["targets"]))
        self.assertTrue(all("FLOW_INTERFACE_COVERAGE" in item["selection_filters"] for item in payload["targets"]))
        self.assertTrue(all("FLOW_INTERFACE_PAGE_LIMIT:8" in item["selection_filters"] for item in payload["targets"]))
        self.assertTrue(all("FLOW_INTERFACE_MONTH_WINDOWS:12" in item["selection_filters"] for item in payload["targets"]))
        self.assertTrue(all("FLOW_INTERFACE_SAMPLE_LIMIT:2" in item["selection_filters"] for item in payload["targets"]))
        self.assertFalse(payload["target_policy"]["download_enabled"])
        self.assertTrue(payload["target_policy"]["fetch_public_urls_enabled"])

    def test_static_guangzhou_interface_scanner_classifies_download_entry_types(self) -> None:
        static_scan = _scan_guangzhou_interface_html(
            '<a href="/files/招标文件.pdf">附件下载</a>',
            source_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/demo.html",
        )
        rest_scan = _scan_guangzhou_interface_html(
            '<script>var u="https://jsgc.gzggzy.cn/tpframe/rest/guangzhoutempdownattach4webaction/download?AttachGuid=A1&FileCode=TBGK001";</script>',
            source_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/demo.html",
        )
        script_scan = _scan_guangzhou_interface_html(
            "ztbfjyz('/EpointWebBuilder/downloadztbattach?attachGuid=A1')",
            source_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/demo.html",
        )
        challenge_scan = _scan_guangzhou_interface_html(
            "<script>initAndCheckCaptcha();</script><div>pageVerify blockPuzzle</div>",
            source_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/demo.html",
        )
        login_scan = _scan_guangzhou_interface_html(
            "<div>请登录后使用 CA锁 数字证书 下载</div>",
            source_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/demo.html",
        )
        empty_scan = _scan_guangzhou_interface_html(
            "<div>本公告无附件</div>",
            source_url="https://ywtb.gzggzy.cn/jyfw/002001/002001001/demo.html",
        )

        self.assertEqual(static_scan["interface_status"], STATIC_ATTACHMENT_LINK_FOUND)
        self.assertEqual(rest_scan["interface_status"], STATIC_ATTACHMENT_LINK_FOUND)
        self.assertEqual(script_scan["interface_status"], SCRIPT_DOWNLOAD_ENDPOINT_FOUND)
        self.assertEqual(challenge_scan["interface_status"], EPOINT_CHALLENGE_REQUIRED)
        self.assertEqual(login_scan["interface_status"], LOGIN_OR_CA_REQUIRED)
        self.assertEqual(empty_scan["interface_status"], NO_PUBLIC_ATTACHMENT)
        self.assertFalse(any(">" in item["raw"] for item in static_scan["discovered_endpoints"]))

    def test_attachment_list_project_samples_do_not_include_snapshots_or_parse(self) -> None:
        rows = _flow_url_project_sample_items(
            plan_item={
                "target_id": "GZ-FLOW-INTERFACE-07-CANDIDATE",
                "document_kind": "candidate_notice",
                "jurisdiction": "CN-GD",
                "required_fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
            },
            selected_candidates=[
                {
                    "candidate_key": "CAND-1",
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "某工程中标候选人公示",
                    "source_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260510/candidate.html",
                    "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                    "source_project_code": "JG2026-10815",
                    "project_match_key": "JG2026-10815",
                    "guangzhou_flow_no": "07",
                    "guangzhou_flow_title": "中标候选人公示",
                    "guangzhou_flow_code": "03",
                    "published_at_optional": "2026-05-10",
                }
            ],
            target_execution_state=ATTACHMENT_LISTED,
            failure_taxonomy=[],
            pipeline_stage=PIPELINE_STAGE_ATTACHMENT_LIST,
        )

        self.assertEqual(rows[0]["pipeline_stage"], PIPELINE_STAGE_ATTACHMENT_LIST)
        self.assertEqual(rows[0]["target_execution_state"], ATTACHMENT_LISTED)
        self.assertEqual(rows[0]["detail_snapshot_refs"], [])
        self.assertEqual(rows[0]["attachment_snapshot_refs"], [])
        self.assertEqual(rows[0]["detail_capture_status"], "NOT_RUN_ATTACHMENT_LIST")
        self.assertEqual(rows[0]["stage3_parse_state"], "NOT_RUN_ATTACHMENT_LIST")

    def test_flow_interface_coverage_marks_required_missing_and_optional_12_non_blocking(self) -> None:
        sample = _sample("candidate_notice", project_id="PROJ-CN-GD-JG2026-10815", flow_no="07", flow_code="03")
        sample["source_url"] = "https://example.test/candidate.html"
        sample["pipeline_stage"] = PIPELINE_STAGE_ATTACHMENT_LIST

        result = _build_flow_interface_coverage_manifest(
            items=[
                {
                    "guangzhou_flow_no": "01",
                    "failure_taxonomy": ["discovery_no_match"],
                    "discovery_profile_reports": [
                        {
                            "public_api_process_attempts": [
                                {
                                    "trading_process": "08",
                                    "attempted_pages": 1,
                                    "record_count": 50,
                                    "accepted_item_count": 0,
                                    "failure_taxonomy": ["flow_interface_records_rejected"],
                                }
                            ]
                        }
                    ],
                }
            ],
            project_samples=[sample],
            execute=False,
            per_flow_candidate_limit=2,
            created_at="2026-05-10T00:00:00+08:00",
            output_root=Path("tmp/test"),
        )

        summary = result["summary"]
        self.assertEqual(summary["interface_coverage_state"], "PARTIAL_REVIEW_REQUIRED")
        self.assertIn("01", summary["missing_required_flow_nos"])
        self.assertEqual(summary["attachment_snapshot_count"], 0)
        by_flow = {row["flow_no"]: row for row in result["manifest"]["flow_reports"]}
        self.assertEqual(by_flow["12"]["flow_interface_coverage_state"], OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND)
        self.assertEqual(by_flow["01"]["flow_interface_coverage_state"], FLOW_SAMPLE_NOT_FOUND)
        self.assertEqual(by_flow["02"]["flow_interface_coverage_state"], "FLOW_INTERFACE_SAMPLED")
        self.assertEqual(by_flow["02"]["human_provided_flow_seed_count"], 1)
        self.assertIn("human_provided_flow_seed_used", by_flow["02"]["failure_taxonomy"])
        self.assertEqual(by_flow["01"]["attempted_pages"], 1)
        self.assertEqual(by_flow["01"]["record_count"], 50)
        self.assertIn("flow_interface_records_rejected", by_flow["01"]["failure_taxonomy"])
        self.assertIn("optional_low_frequency_flow_no_sample", by_flow["12"]["failure_taxonomy"])
        self.assertIn("flow_interface_no_records_after_page_scan", by_flow["12"]["failure_taxonomy"])
        self.assertEqual(by_flow["07"]["sample_interface_items"][0]["interface_status"], INTERFACE_UNRESOLVED)

        manual = _build_manual_interface_check_table(result)
        rows = manual["manifest"]["items"]
        self.assertTrue(any(row["interface_status"] == FLOW_SAMPLE_NOT_FOUND for row in rows))
        self.assertTrue(any(row["interface_status"] == OPTIONAL_LOW_FREQUENCY_FLOW_NOT_FOUND for row in rows))
        flow_02_seed_rows = [
            row
            for row in rows
            if row["flow_no"] == "02" and row["sample_source_type"] == "HUMAN_PROVIDED_FLOW_SEED"
        ]
        self.assertTrue(flow_02_seed_rows)
        self.assertTrue(
            all(row["usage_scope"] == "FLOW_INTERFACE_ADAPTER_VALIDATION_ONLY" for row in flow_02_seed_rows)
        )
        self.assertTrue(all(row["adapter_validation_only"] for row in flow_02_seed_rows))
        self.assertTrue(all(row["production_crawl_source_allowed"] is False for row in flow_02_seed_rows))
        self.assertTrue(all(row["default_crawl_target_allowed"] is False for row in flow_02_seed_rows))
        self.assertTrue(
            all(row["interface_status"] in {INTERFACE_UNRESOLVED, SCRIPT_DOWNLOAD_ENDPOINT_FOUND} for row in flow_02_seed_rows)
        )
        self.assertEqual(manual["manifest"]["summary"]["flow_count"], 12)

    def test_pipeline_state_marks_attachment_list_stage_without_snapshots(self) -> None:
        sample = _sample("candidate_notice", project_id="PROJ-CN-GD-JG2026-10815", flow_no="07", flow_code="03")
        sample["source_url"] = "https://example.test/candidate.html"
        state = _build_pipeline_state_manifest(
            project_samples=[sample],
            items=[],
            created_at="2026-05-10T00:00:00+08:00",
            pipeline_stage=PIPELINE_STAGE_ATTACHMENT_LIST,
        )

        row = state["manifest"]["items"][0]
        self.assertEqual(row["state"], ATTACHMENT_LISTED)
        self.assertEqual(row["artifact_refs"]["attachment_snapshot_refs"], [])
        self.assertEqual(state["summary"]["state_counts"][ATTACHMENT_LISTED], 1)


def _sample(
    document_kind: str,
    *,
    project_id: str,
    flow_no: str = "",
    flow_code: str = "",
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "target_id": f"TARGET-{document_kind}",
        "parent_target_id": f"PARENT-{document_kind}",
        "document_kind": document_kind,
        "source_url": f"https://example.test/{document_kind}.html",
        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
        "detail_snapshot_count": 1,
        "attachment_snapshot_count": 0,
        "failure_taxonomy": [],
        "source_project_code": "JG2026-POST",
        "project_match_key": "JG2026-POST",
        "matched_project_keys": ["JG2026-POST"],
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_code": flow_code,
    }


if __name__ == "__main__":
    unittest.main()
