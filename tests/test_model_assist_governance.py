from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from shared.model_assist_governance import MODEL_ASSIST_INPUT_KEY, MODEL_ASSIST_SUMMARY_INPUT_KEY
from shared.settings import Settings
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository

from helpers import load_fixture, run_internal_chain_to_stage7


class ModelAssistGovernanceTests(unittest.TestCase):
    def _repo(self, tmp_dir: str) -> ObjectStorageRepository:
        settings = Settings(
            storage_backend="json-file",
            storage_path_optional=str(Path(tmp_dir) / "model-assist-storage.json"),
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(Path(tmp_dir) / "objects"),
        )
        return ObjectStorageRepository(
            session=DatabaseSession(settings=settings),
            settings=settings,
        )

    def _parsed_carrier(self) -> dict:
        html = """
        <html><body>
          <table>
            <tr><th>项目名称</th><td>模型辅助测试工程</td></tr>
            <tr><th>招标人</th><td>测试建设单位</td></tr>
          </table>
        </body></html>
        """.encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = self._repo(tmp_dir)
            repo.save_snapshot(
                html,
                snapshot_id="SNAP-MODEL-ASSIST-STAGE3",
                snapshot_kind="raw_html",
                content_type="text/html",
                source_url_optional="sandbox://local-public-resource-trading-centers/model-assist.html",
                source_family_optional="local_public_resource_trading_center",
                lineage_refs={
                    "project_id": "P-MODEL-ASSIST",
                    "source_registry_id": "SRC-REG-PROC-NATIONAL-HTML",
                    "source_family": "local_public_resource_trading_center",
                },
                created_at="2026-04-27T00:00:00+00:00",
            )
            return dict(Stage3Service().parse_raw_snapshot("SNAP-MODEL-ASSIST-STAGE3", repository=repo))

    def test_stage3_parser_outputs_model_assist_candidate_without_fact_or_customer_visibility(self) -> None:
        carrier = self._parsed_carrier()
        assist = carrier[MODEL_ASSIST_INPUT_KEY]
        summary = carrier[MODEL_ASSIST_SUMMARY_INPUT_KEY]

        self.assertEqual(assist["model_assist_mode"], "GOVERNED_ASSIST_READBACK")
        self.assertEqual(assist["output_trace"]["output_kind"], "llm_assisted_field_extraction_candidate")
        self.assertTrue(assist["human_review_required"])
        self.assertFalse(assist["real_model_provider_call_executed"])
        self.assertFalse(assist["formal_fact_write_enabled"])
        self.assertFalse(assist["customer_visible"])
        self.assertTrue(summary["model_output_not_final_fact"])
        self.assertTrue(summary["no_private_data_to_model_without_policy"])
        self.assertTrue(summary["golden_case_refs"])

    def test_stage4_verification_readback_carries_evidence_summary_assist(self) -> None:
        parsed = self._parsed_carrier()
        verification = Stage4Service().verify_public_parsed_carrier(
            parsed,
            target={
                "verification_target_id": "TARGET-MODEL-ASSIST",
                "verification_target_type": "enterprise_public_record",
                "target_identifier": "模型辅助测试工程",
            },
        )
        readback = Stage4Service().build_public_verification_readback(verification)
        assist = readback[MODEL_ASSIST_INPUT_KEY]

        self.assertEqual(assist["output_trace"]["output_kind"], "llm_assisted_evidence_summary")
        self.assertTrue(assist["human_review_required"])
        self.assertFalse(assist["customer_visible_claim_enabled"])
        self.assertFalse(assist["real_model_provider_call_executed"])
        self.assertTrue(readback[MODEL_ASSIST_SUMMARY_INPUT_KEY]["replayable"])

    def test_stage5_and_stage7_attach_review_and_sales_drafts_as_internal_only_assist(self) -> None:
        chain = run_internal_chain_to_stage7(load_fixture("internal_chain_happy.json"))
        stage5_assist = chain["stage5"].inputs[MODEL_ASSIST_INPUT_KEY]
        stage7_assist = chain["stage7"].inputs[MODEL_ASSIST_INPUT_KEY]
        workbench = chain["stage7"].inputs["crm_quote_workbench"]

        self.assertEqual(stage5_assist["output_trace"]["output_kind"], "llm_assisted_review_triage")
        self.assertTrue(stage5_assist["human_review_required"])
        self.assertFalse(stage5_assist["formal_fact_write_enabled"])
        self.assertEqual(stage7_assist["output_trace"]["output_kind"], "llm_assisted_sales_talk_track_draft")
        self.assertTrue(stage7_assist["sales_talk_track_draft"]["human_review_required"])
        self.assertFalse(stage7_assist["sales_talk_track_draft"]["customer_send_enabled"])
        self.assertEqual(workbench[MODEL_ASSIST_SUMMARY_INPUT_KEY]["output_kind"], "llm_assisted_sales_talk_track_draft")
        self.assertFalse(workbench[MODEL_ASSIST_SUMMARY_INPUT_KEY]["real_model_provider_call_executed"])


if __name__ == "__main__":
    unittest.main()
