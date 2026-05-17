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

from storage.product_analysis_strategy_plan import (  # noqa: E402
    ADAPTER_VALIDATION_ONLY,
    HISTORICAL_OR_LATE_STAGE_REVIEW,
    POST_CANDIDATE_EVIDENCE_PACK,
    POST_OPENING_EVIDENCE_TRACK,
    PREDICTION_AFTER_CLARIFICATION,
    PREDICTION_BEFORE_CLARIFICATION,
    PRE_BID_PREDICTION,
    TIME_WINDOW_UNKNOWN_REVIEW,
    WATCHLIST_ONLY,
    build_product_analysis_strategy_plan,
    build_runtime_product_analysis_strategy_plan,
)


class ProductAnalysisStrategyPlanTests(unittest.TestCase):
    def test_runtime_builder_candidate_notice_routes_to_post_candidate_evidence_pack(self) -> None:
        plan = _build_runtime_plan(document_kind="candidate_notice", flow_no="07")

        self.assertEqual(plan["product_mode"], POST_CANDIDATE_EVIDENCE_PACK)
        self.assertEqual(plan["strategy_state"], "POST_CANDIDATE_READY")
        self.assertEqual(plan["flow_no"], "07")
        self.assertEqual(plan["document_kind"], "candidate_notice")
        self.assertEqual(plan["download_policy"], "DOWNLOAD_REQUIRED_IF_ATTACHMENT_PRESENT")
        self.assertEqual(plan["parse_depth"], "TEXT_PROBE")
        self.assertTrue(plan["parse_required"])
        self.assertTrue(plan["llm_allowed"])
        self.assertEqual(plan["current_sales_window_entry_flow_no"], "07")

    def test_runtime_builder_opening_routes_to_post_opening_track(self) -> None:
        plan = _build_runtime_plan(document_kind="opening_info", flow_no="05")

        self.assertEqual(plan["product_mode"], POST_OPENING_EVIDENCE_TRACK)
        self.assertEqual(plan["strategy_state"], "PRE_BID_NOT_ELIGIBLE_OPENING_STARTED")
        self.assertEqual(plan["download_policy"], "LIST_OR_DOWNLOAD_IF_ATTACHMENT_PRESENT")
        self.assertEqual(plan["parse_depth"], "TEXT_PROBE")
        self.assertTrue(plan["parse_required"])
        self.assertTrue(plan["llm_allowed"])

    def test_runtime_builder_pre_bid_standard_prediction_uses_time_window(self) -> None:
        plan = _build_runtime_plan(
            document_kind="tender_notice",
            flow_no="03",
            deadline="2026-05-20T09:00:00+08:00",
            now="2026-05-10T09:00:00+08:00",
        )

        self.assertEqual(plan["product_mode"], PRE_BID_PREDICTION)
        self.assertEqual(plan["strategy_state"], "PRE_BID_STANDARD_PREDICTION_READY")
        self.assertEqual(plan["download_policy"], "DOWNLOAD_REQUIRED")
        self.assertEqual(plan["parse_depth"], "SECTION_PARSE")
        self.assertTrue(plan["parse_required"])
        self.assertTrue(plan["llm_allowed"])

    def test_runtime_builder_short_pre_bid_window_blocks_parse(self) -> None:
        plan = _build_runtime_plan(
            document_kind="tender_notice",
            flow_no="03",
            deadline="2026-05-12T08:00:00+08:00",
            now="2026-05-10T09:00:00+08:00",
        )

        self.assertEqual(plan["product_mode"], POST_OPENING_EVIDENCE_TRACK)
        self.assertEqual(plan["strategy_state"], "PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE")
        self.assertEqual(plan["download_policy"], "SKIP")
        self.assertEqual(plan["parse_depth"], "NONE")
        self.assertFalse(plan["parse_required"])

    def test_runtime_builder_watchlist_only_blocks_parse(self) -> None:
        plan = _build_runtime_plan(document_kind="bid_plan", flow_no="01")

        self.assertEqual(plan["product_mode"], WATCHLIST_ONLY)
        self.assertEqual(plan["strategy_state"], WATCHLIST_ONLY)
        self.assertEqual(plan["download_policy"], "METADATA_ONLY")
        self.assertEqual(plan["parse_depth"], "METADATA_ONLY")
        self.assertFalse(plan["llm_allowed"])

    def test_runtime_builder_attachment_list_samples_are_adapter_validation_only(self) -> None:
        plan = _build_runtime_plan(
            document_kind="tender_file_publicity",
            flow_no="02",
            pipeline_stage="AttachmentList",
            adapter_validation_only=True,
            target_id="GZ-FLOW-INTERFACE-02",
            sample_source_type="HUMAN_PROVIDED_FLOW_SEED",
        )

        self.assertEqual(plan["product_mode"], ADAPTER_VALIDATION_ONLY)
        self.assertEqual(plan["strategy_state"], ADAPTER_VALIDATION_ONLY)
        self.assertEqual(plan["download_policy"], "SKIP")
        self.assertEqual(plan["parse_depth"], "NONE")
        self.assertFalse(plan["parse_required"])
        self.assertTrue(plan["adapter_validation_only"])

    def test_candidate_notice_routes_to_post_candidate_evidence_pack(self) -> None:
        result = _build_with_samples(
            [
                _sample("candidate_notice", flow_no="07"),
                _sample("tender_file", flow_no="03"),
            ]
        )

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], POST_CANDIDATE_EVIDENCE_PACK)
        self.assertEqual(project["strategy_state"], "POST_CANDIDATE_READY")
        self.assertEqual(project["current_sales_window_entry_flow_no"], "07")
        self.assertFalse(project["late_stage_flows_required_for_recent_candidate"])
        by_flow = {item["flow_no"]: item for item in result["manifest"]["items"]}
        self.assertEqual(by_flow["03"]["download_policy"], "DOWNLOAD_REQUIRED")
        self.assertEqual(by_flow["03"]["parse_depth"], "SECTION_PARSE")
        self.assertTrue(by_flow["03"]["llm_allowed"])

    def test_late_stage_without_candidate_is_not_current_sales_window_ready(self) -> None:
        result = _build_with_samples([_sample("award_result", flow_no="09")])

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], POST_CANDIDATE_EVIDENCE_PACK)
        self.assertEqual(project["strategy_state"], HISTORICAL_OR_LATE_STAGE_REVIEW)
        self.assertNotEqual(project["strategy_state"], "POST_CANDIDATE_READY")
        self.assertEqual(project["current_sales_window_entry_flow_no"], "")

    def test_opening_without_candidate_blocks_pre_bid_prediction(self) -> None:
        result = _build_with_samples([_sample("opening_info", flow_no="05")])

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], POST_OPENING_EVIDENCE_TRACK)
        self.assertEqual(project["strategy_state"], "PRE_BID_NOT_ELIGIBLE_OPENING_STARTED")

    def test_pre_bid_time_windows_are_applied(self) -> None:
        standard = _build_with_samples(
            [_sample("tender_file", flow_no="03", deadline="2026-05-20T09:00:00+08:00")],
            now="2026-05-10T09:00:00+08:00",
        )
        limited = _build_with_samples(
            [_sample("tender_file", flow_no="03", deadline="2026-05-15T09:00:00+08:00")],
            now="2026-05-10T09:00:00+08:00",
        )
        too_late = _build_with_samples(
            [_sample("tender_file", flow_no="03", deadline="2026-05-12T08:00:00+08:00")],
            now="2026-05-10T09:00:00+08:00",
        )

        self.assertEqual(
            standard["manifest"]["project_strategy_items"][0]["strategy_state"],
            "PRE_BID_STANDARD_PREDICTION_READY",
        )
        self.assertEqual(standard["manifest"]["project_strategy_items"][0]["product_mode"], PRE_BID_PREDICTION)
        self.assertEqual(
            limited["manifest"]["project_strategy_items"][0]["strategy_state"],
            "PRE_BID_LIMITED_FAST_REVIEW",
        )
        self.assertEqual(
            too_late["manifest"]["project_strategy_items"][0]["strategy_state"],
            "PRE_BID_NOT_ELIGIBLE_TOO_LATE_FOR_SALE",
        )
        self.assertEqual(too_late["manifest"]["project_strategy_items"][0]["product_mode"], POST_OPENING_EVIDENCE_TRACK)

    def test_pre_bid_before_clarification_requires_recalculation_when_flow_04_appears(self) -> None:
        result = _build_with_samples(
            [
                _sample("tender_file_publicity", flow_no="02", deadline="2026-05-20T09:00:00+08:00"),
                _sample("tender_file", flow_no="03", deadline="2026-05-20T09:00:00+08:00"),
            ],
            now="2026-05-10T09:00:00+08:00",
        )

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], PRE_BID_PREDICTION)
        self.assertEqual(project["pre_bid_clarification_state"], PREDICTION_BEFORE_CLARIFICATION)
        self.assertTrue(project["prediction_recalc_required_on_new_flow_04"])
        self.assertTrue(all(item["prediction_recalc_required_on_new_flow_04"] for item in result["manifest"]["items"]))

    def test_pre_bid_after_clarification_marks_prediction_after_clarification(self) -> None:
        result = _build_with_samples(
            [
                _sample("tender_file_publicity", flow_no="02", deadline="2026-05-20T09:00:00+08:00"),
                _sample("tender_file", flow_no="03", deadline="2026-05-20T09:00:00+08:00"),
                _sample("clarification_notice", flow_no="04", deadline="2026-05-20T09:00:00+08:00"),
            ],
            now="2026-05-10T09:00:00+08:00",
        )

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], PRE_BID_PREDICTION)
        self.assertEqual(project["pre_bid_clarification_state"], PREDICTION_AFTER_CLARIFICATION)
        self.assertFalse(project["prediction_recalc_required_on_new_flow_04"])

    def test_missing_deadline_keeps_pre_bid_in_time_window_review(self) -> None:
        result = _build_with_samples([_sample("tender_file", flow_no="03")])

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], PRE_BID_PREDICTION)
        self.assertEqual(project["strategy_state"], TIME_WINDOW_UNKNOWN_REVIEW)
        self.assertEqual(result["manifest"]["items"][0]["download_policy"], "SKIP")
        self.assertEqual(result["manifest"]["items"][0]["skip_reason"], "time_window_unknown_review_before_pre_bid_sale")

    def test_only_bid_plan_is_watchlist(self) -> None:
        result = _build_with_samples([_sample("bid_plan", flow_no="01")])

        project = result["manifest"]["project_strategy_items"][0]
        self.assertEqual(project["product_mode"], WATCHLIST_ONLY)
        self.assertEqual(project["strategy_state"], WATCHLIST_ONLY)
        self.assertEqual(result["manifest"]["items"][0]["parse_depth"], "METADATA_ONLY")

    def test_attachment_list_and_human_seed_are_adapter_validation_only(self) -> None:
        result = _build_with_samples(
            [
                {
                    **_sample("tender_file_publicity", flow_no="02"),
                    "target_id": "GZ-FLOW-INTERFACE-02",
                    "sample_source_type": "HUMAN_PROVIDED_FLOW_SEED",
                    "adapter_validation_only": True,
                }
            ],
            pipeline_stage="AttachmentList",
        )

        project = result["manifest"]["project_strategy_items"][0]
        item = result["manifest"]["items"][0]
        self.assertEqual(project["product_mode"], ADAPTER_VALIDATION_ONLY)
        self.assertEqual(item["download_policy"], "SKIP")
        self.assertEqual(item["parse_depth"], "NONE")
        self.assertFalse(item["llm_allowed"])
        self.assertTrue(item["adapter_validation_only"])

    def test_bid_file_publicity_is_list_then_targeted_not_default_deep_parse(self) -> None:
        result = _build_with_samples(
            [
                _sample("candidate_notice", flow_no="07"),
                _sample("bid_file_publicity", flow_no="08"),
            ]
        )

        item = next(item for item in result["manifest"]["items"] if item["flow_no"] == "08")
        self.assertEqual(item["download_policy"], "REGISTER_ONLY_THEN_TARGETED_PARSE_IF_TRIGGERED")
        self.assertFalse(item["download_required"])
        self.assertEqual(item["parse_depth"], "LIST_ONLY")
        self.assertFalse(item["parse_required"])
        self.assertFalse(item["llm_allowed"])


def _build_with_samples(
    samples: list[dict[str, object]],
    *,
    pipeline_stage: str = "FlowUrlOnly",
    now: str = "2026-05-10T09:00:00+08:00",
) -> dict:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        run_path = root / "run-manifest.json"
        run_path.write_text(
            json.dumps(
                {
                    "manifest": {
                        "manifest_kind": "evaluation_real_project_sample_execution_manifest",
                        "pipeline_stage": pipeline_stage,
                        "project_sample_items": samples,
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        output_path = root / "analysis-plan.json"
        return build_product_analysis_strategy_plan(
            real_sample_execution_manifest_json=run_path,
            output_json=output_path,
            now=now,
        )


def _build_runtime_plan(
    *,
    document_kind: str,
    flow_no: str,
    deadline: str = "",
    now: str = "2026-05-10T09:00:00+08:00",
    pipeline_stage: str = "FlowUrlOnly",
    adapter_validation_only: bool = False,
    target_id: str = "",
    sample_source_type: str = "",
) -> dict[str, object]:
    return build_runtime_product_analysis_strategy_plan(
        public_chain={
            "project_id": "PROJ-CN-GD-JG2026-10815",
            "announcement_url": f"https://example.test/{flow_no}.html",
            "source_family": "PROCUREMENT_NOTICE",
            "platform_level": "NATIONAL",
            "region_scope": "NATIONAL",
            "coverage_tier": "T0_CORE",
            "carrier_type": "HTML_PAGE",
            "first_seen_at": "2026-05-10T09:00:00+08:00",
            "last_retrieved_at": "2026-05-10T09:00:00+08:00",
        },
        clock_chain_profile={
            "current_action_deadline_at_optional": deadline,
        },
        notice_version_chain={},
        fixation_bundle={"fixation_bundle_id": "FIX-001"},
        inputs={
            "project_id": "PROJ-CN-GD-JG2026-10815",
            "project_name": "测试项目",
            "document_kind": document_kind,
            "guangzhou_flow_no": flow_no,
            "pipeline_stage": pipeline_stage,
            "current_action_deadline_at_optional": deadline,
            "adapter_validation_only": adapter_validation_only,
            "target_id": target_id,
            "sample_source_type": sample_source_type,
        },
        now=now,
    )


def _sample(document_kind: str, *, flow_no: str, deadline: str = "") -> dict[str, object]:
    return {
        "project_id": "PROJ-CN-GD-JG2026-10815",
        "project_name": "测试项目",
        "document_kind": document_kind,
        "guangzhou_flow_no": flow_no,
        "guangzhou_flow_title": f"{flow_no}流程",
        "source_url": f"https://example.test/{flow_no}.html",
        "current_action_deadline_at_optional": deadline,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
