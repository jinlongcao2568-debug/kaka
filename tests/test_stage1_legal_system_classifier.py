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
        self.assertEqual(stage1.inputs["remedy_path_candidate"], "QUESTION_COMPLAINT")
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
        self.assertEqual(stage1.inputs["remedy_path_candidate"], "OBJECTION_COMPLAINT")

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
        self.assertEqual(stage3.record("project_base").get("procurement_regime"), "SINGLE_SOURCE")
        self.assertEqual(stage3.record("project_base").get("procurement_category"), "GOVERNMENT_PROCUREMENT")


if __name__ == "__main__":
    unittest.main()
