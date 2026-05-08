from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.pipeline import run_internal_chain_until_stage6
from stage1_tasking.service import Stage1Service


class TestStage1LegalSystemClassifier(unittest.TestCase):
    def _base_payload(self) -> dict[str, object]:
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.pop("procurement_regime", None)
        payload.pop("procurement_category", None)
        return payload

    def test_government_procurement_consultation_sets_regime_category_and_remedy_path(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-LEGAL-GOV-001",
                "project_id": "PROJ-LEGAL-GOV-001",
                "project_name": "智慧校园设备政府采购项目",
                "source_title": "中国政府采购网竞争性磋商公告",
                "source_text": "采购人发布政府采购竞争性磋商公告，供应商可依法提出质疑、投诉。",
            }
        )

        stage1 = Stage1Service().run(payload)

        self.assertEqual(stage1.inputs["procurement_regime"], "NEGOTIATION")
        self.assertEqual(stage1.inputs["procurement_category"], "GOVERNMENT_PROCUREMENT")
        self.assertEqual(stage1.inputs["legal_system_type_candidate"], "GOVERNMENT_PROCUREMENT_LAW")
        self.assertEqual(stage1.inputs["regulator_route_candidate"], "FINANCE_DEPARTMENT")
        self.assertEqual(stage1.inputs["remedy_path_candidate"], "QUESTION_COMPLAINT")
        self.assertEqual(stage1.inputs["pre_notice_type"], "FORMAL_NOTICE")
        self.assertEqual(stage1.inputs["project_lifecycle_stage"], "NOTICE_ACTIVE")
        self.assertIn(
            "legal_system_type_candidate",
            stage1.inputs["stage12_extractor_trace"]["stage1"],
        )

    def test_engineering_public_resource_notice_sets_tender_bidding_category(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-LEGAL-TENDER-001",
                "project_id": "PROJ-LEGAL-TENDER-001",
                "project_name": "市政道路工程施工公开招标项目",
                "source_title": "公共资源交易中心工程建设招标公告",
                "source_text": "本项目为依法必须招标工程，招标人发布公开招标公告，投标人可在规定期限内提出异议。",
            }
        )

        stage1 = Stage1Service().run(payload)

        self.assertEqual(stage1.inputs["procurement_regime"], "OPEN_TENDER")
        self.assertEqual(stage1.inputs["procurement_category"], "MANDATORY_TENDER_ENGINEERING")
        self.assertEqual(stage1.inputs["legal_system_type_candidate"], "TENDER_BIDDING_LAW")
        self.assertEqual(
            stage1.inputs["regulator_route_candidate"],
            "DEVELOPMENT_REFORM_OR_PUBLIC_RESOURCE_SUPERVISION",
        )
        self.assertEqual(stage1.inputs["remedy_path_candidate"], "OBJECTION_COMPLAINT")

    def test_state_owned_platform_procurement_routes_to_review_without_single_law_path(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-LEGAL-SOE-001",
                "project_id": "PROJ-LEGAL-SOE-001",
                "project_name": "省属集团阳光采购平台设备项目",
                "source_title": "国企采购平台询比公告",
                "source_text": "国有企业集团采购，非依法必须招标，供应商在平台采购规则下提交响应文件。",
            }
        )

        stage1 = Stage1Service().run(payload)

        self.assertEqual(stage1.inputs["legal_system_type_candidate"], "STATE_OWNED_PLATFORM_PROCUREMENT")
        self.assertEqual(stage1.inputs["procurement_category"], "STATE_OWNED_PLATFORM_PROCUREMENT")
        self.assertEqual(stage1.inputs["fund_source_type"], "STATE_OWNED_FUNDS")
        self.assertEqual(stage1.inputs["regulator_route_candidate"], "STATE_OWNED_PLATFORM_OWNER")
        self.assertEqual(stage1.inputs["remedy_path_candidate"], "REVIEW_REQUIRED")

    def test_mixed_government_procurement_engineering_requires_review(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-LEGAL-MIXED-001",
                "project_id": "PROJ-LEGAL-MIXED-001",
                "project_name": "政府采购工程施工招标项目",
                "source_title": "公共资源交易中心政府采购工程招标公告",
                "source_text": "本项目为政府采购工程，采购人委托招标人按招标投标程序组织工程建设施工公开招标。",
            }
        )

        stage1 = Stage1Service().run(payload)

        self.assertEqual(
            stage1.inputs["legal_system_type_candidate"],
            "MIXED_GOVERNMENT_PROCUREMENT_ENGINEERING",
        )
        self.assertEqual(stage1.inputs["procurement_category"], "GOVERNMENT_PROCUREMENT_ENGINEERING")
        self.assertEqual(stage1.inputs["regulator_route_candidate"], "REVIEW_REQUIRED")
        self.assertEqual(stage1.inputs["remedy_path_candidate"], "REVIEW_REQUIRED")

    def test_procurement_intention_is_watchlist_not_formal_project(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-PRE-NOTICE-001",
                "project_id": "PROJ-PRE-NOTICE-001",
                "project_name": "医院信息化采购意向",
                "source_title": "政府采购意向公开",
                "source_text": "采购意向公开，项目名称医院信息化，预算金额1200万元，预计采购时间2026年06月。",
            }
        )

        stage1 = Stage1Service().run(payload)

        self.assertEqual(stage1.inputs["pre_notice_type"], "PROCUREMENT_INTENTION")
        self.assertEqual(stage1.inputs["project_lifecycle_stage"], "PRE_NOTICE_WATCHLIST")
        self.assertEqual(stage1.inputs["source_channel_type"], "GOVERNMENT_PROCUREMENT_SITE")
        self.assertGreaterEqual(stage1.inputs["source_quality_score"], 70)

    def test_stage3_project_base_consumes_stage1_classified_category_without_recomputing(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-LEGAL-CHAIN-001",
                "project_id": "PROJ-LEGAL-CHAIN-001",
                "project_name": "医疗设备单一来源采购项目",
                "source_title": "政府采购单一来源采购公示",
                "source_text": "采购人拟采用单一来源方式进行政府采购，供应商救济路径按质疑、投诉处理。",
            }
        )

        result = run_internal_chain_until_stage6(payload)
        stage3 = result["stage3"]

        self.assertEqual(stage3.inputs["legal_system_type_candidate"], "GOVERNMENT_PROCUREMENT_LAW")
        self.assertEqual(stage3.inputs["regulator_route_candidate"], "FINANCE_DEPARTMENT")
        self.assertEqual(stage3.record("project_base").get("procurement_regime"), "SINGLE_SOURCE")
        self.assertEqual(stage3.record("project_base").get("procurement_category"), "GOVERNMENT_PROCUREMENT")
        self.assertEqual(stage3.record("project_manager").get("project_manager_name"), "REVIEW_REQUIRED")
        self.assertEqual(stage3.inputs["project_manager_field_source_state"], "MISSING_REVIEW_REQUIRED")

    def test_stage6_trace_carries_stage16_classification_and_conservative_boundary(self) -> None:
        payload = self._base_payload()
        payload.update(
            {
                "task_id": "TASK-LEGAL-STAGE6-001",
                "project_id": "PROJ-LEGAL-STAGE6-001",
                "project_name": "市政道路工程施工公开招标项目",
                "source_title": "公共资源交易中心工程建设招标公告",
                "source_text": "依法必须招标工程建设项目，招标人发布公开招标公告。",
            }
        )

        result = run_internal_chain_until_stage6(payload)
        trace = result["stage6"].inputs["stage6_review_report_trace"]["stage16_file_analysis_trace"]

        self.assertEqual(trace["legal_system"]["legal_system_type_candidate"], "TENDER_BIDDING_LAW")
        self.assertEqual(trace["pre_notice_and_source"]["pre_notice_type"], "FORMAL_NOTICE")
        self.assertFalse(trace["output_boundary"]["customer_visible"])
        self.assertTrue(trace["output_boundary"]["no_illegality_or_reserved_winner_conclusion"])


if __name__ == "__main__":
    unittest.main()
