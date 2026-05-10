from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class BusinessDirectionStrategyContractTests(unittest.TestCase):
    def _contract(self) -> dict:
        path = ROOT / "contracts" / "evaluation" / "business_direction_strategy_contract.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_post_candidate_evidence_pack_is_default_commercial_mainline(self) -> None:
        contract = self._contract()

        self.assertEqual(contract["primary_commercial_line"], "POST_CANDIDATE_EVIDENCE_PACK")
        self.assertEqual(contract["default_when_ambiguous"], "POST_CANDIDATE_EVIDENCE_PACK")
        post_candidate = next(
            line for line in contract["product_lines"] if line["line_id"] == "POST_CANDIDATE_EVIDENCE_PACK"
        )
        self.assertEqual(post_candidate["business_priority"], "PRIMARY")
        for document_kind in ("candidate_notice", "evaluation_result", "opening_record", "award_result"):
            self.assertIn(document_kind, post_candidate["default_entry_document_kinds"])
        for backtrace_kind in ("tender_file", "clarification_or_addendum", "bid_file_publicity"):
            self.assertIn(backtrace_kind, post_candidate["required_backtrace_document_kinds"])

    def test_pre_bid_prediction_is_secondary_and_does_not_claim_candidate_outputs(self) -> None:
        contract = self._contract()
        pre_bid = next(line for line in contract["product_lines"] if line["line_id"] == "PRE_BID_PREDICTION")

        self.assertEqual(pre_bid["business_priority"], "SECONDARY")
        self.assertIn("tender_file", pre_bid["default_entry_document_kinds"])
        self.assertIn("candidate_verification", pre_bid["must_not_output"])
        self.assertIn("real_competitor_conclusion", pre_bid["must_not_output"])

    def test_source_policy_keeps_guangzhou_primary_and_deletes_incomplete_province_source(self) -> None:
        contract = self._contract()
        source_policy = contract["source_policy"]
        primary_profile_ids = {
            item["source_profile_id"] for item in source_policy["primary_friendly_sources"]
        }

        self.assertIn("GUANGZHOU-YWTB-CONSTRUCTION-LIST", primary_profile_ids)
        self.assertIn("ZHEJIANG-GGZY-JYXXGK-LIST", primary_profile_ids)
        self.assertIn("SICHUAN-GGZY-TRANSACTION-INFO", primary_profile_ids)
        self.assertNotIn("GUANGDONG-PROVINCE-INCOMPLETE-SUMMARY-SOURCE", primary_profile_ids)

    def test_run_modes_distinguish_pre_bid_smoke_from_available_backtrace(self) -> None:
        contract = self._contract()
        run_modes = {item["run_mode_id"]: item for item in contract["run_modes"]}

        self.assertEqual(run_modes["GUANGZHOU_TENDER_FILE_SMOKE"]["line_id"], "PRE_BID_PREDICTION")
        self.assertEqual(run_modes["GUANGZHOU_TENDER_FILE_SMOKE"]["status"], "AVAILABLE")
        self.assertEqual(run_modes["POST_CANDIDATE_BACKTRACE_V1"]["line_id"], "POST_CANDIDATE_EVIDENCE_PACK")
        self.assertEqual(run_modes["POST_CANDIDATE_BACKTRACE_V1"]["status"], "AVAILABLE")
        self.assertEqual(
            run_modes["POST_CANDIDATE_BACKTRACE_V1"]["script"],
            "scripts/run-guangzhou-post-candidate-backtrace-v1.ps1",
        )

    def test_project_level_audit_fields_are_required_by_contract(self) -> None:
        contract = self._contract()
        fields = set(contract["project_level_audit_required_fields"])

        for field in (
            "project_id",
            "project_name",
            "verification_urls.all_urls",
            "file_inventory",
            "replayable_file_count",
            "parsed_file_count",
            "download_completeness_state",
            "parse_completeness_state",
            "post_candidate_entry_state",
            "backtrace_stage_attempts",
            "matched_project_keys",
            "missing_stage_kinds",
            "backtrace_completeness_state",
            "ready_for_tailored_analysis",
        ):
            self.assertIn(field, fields)


if __name__ == "__main__":
    unittest.main()
