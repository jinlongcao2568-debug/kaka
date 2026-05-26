from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage6_status_projection import (  # noqa: E402
    limited_sellable_review_projection,
    runtime_blocker_projection_fields,
)


class Stage6StatusProjectionTests(unittest.TestCase):
    def test_b_or_c_readback_projects_to_internal_limited_review_only(self) -> None:
        projection = limited_sellable_review_projection(
            {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
            stage7_commercial_input_allowed=False,
        )

        self.assertEqual(projection["strong_lead_candidate_state"], "STRONG_LEAD_REVIEW_CANDIDATE")
        self.assertEqual(projection["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(
            projection["commercialization_boundary_state"],
            "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        )

    def test_stage7_requested_b_or_c_without_evidence_chain_stays_limited_review(self) -> None:
        projection = limited_sellable_review_projection(
            {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            stage7_commercial_input_allowed=True,
        )

        self.assertEqual(projection["strong_lead_candidate_state"], "STRONG_LEAD_REVIEW_CANDIDATE")
        self.assertEqual(projection["limited_sellable_review_candidate_state"], "REVIEW_CANDIDATE")
        self.assertEqual(
            projection["commercialization_boundary_state"],
            "INTERNAL_REVIEW_ONLY_NOT_CUSTOMER_DELIVERABLE",
        )
        self.assertFalse(projection["stage7_governed_preview_allowed"])
        self.assertEqual(projection["stage7_governed_preview_gate_state"], "BLOCKED_EVIDENCE_CHAIN_INCOMPLETE")
        self.assertIn("official_readback_record_missing", projection["stage7_governed_preview_missing_reasons"])

    def test_stage7_requested_b_or_c_with_complete_evidence_chain_enters_internal_preview_gate(self) -> None:
        projection = limited_sellable_review_projection(
            {"B_ENHANCEMENT_OFFICIAL_READBACK": 1},
            stage7_commercial_input_allowed=True,
            field_tasks=[
                {
                    "field_query_task_id": "FIELD-GATE",
                    "project_id": "PROJ-GATE",
                    "source_profile_id": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                    "source_specific_adapter_id": "guangdong_ygp_original_readback_backfill_adapter_v1",
                    "adapter_result_state": "MATCHED",
                    "field_readback_state": "YGP_ORIGINAL_NOTICE_READBACK_READY_REVIEW_REQUIRED",
                    "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                    "field_match_summary": {
                        "source_specific_records": [
                            {
                                "url": "https://ygp.example/detail?projectCode=E4401002701501867001",
                                "source_text_sha256": "abc123",
                            }
                        ],
                    },
                }
            ],
        )

        self.assertTrue(projection["stage7_governed_preview_allowed"])
        self.assertEqual(projection["stage7_governed_preview_gate_state"], "ALLOWED_INTERNAL_GOVERNED_PREVIEW")
        self.assertEqual(projection["stage7_governed_preview_missing_reasons"], [])
        self.assertEqual(projection["limited_sellable_review_candidate_state"], "NOT_READY")
        self.assertFalse(projection["stage7_governed_preview_customer_visible_allowed"])

    def test_limited_review_records_public_source_chain_and_gdcic_route_policy(self) -> None:
        projection = limited_sellable_review_projection(
            {"B_ENHANCEMENT_OFFICIAL_READBACK": 1, "D_INSUFFICIENT_OR_BLOCKED_READBACK": 1},
            stage7_commercial_input_allowed=False,
            field_tasks=[
                {
                    "field_query_task_id": "FIELD-1",
                    "project_id": "PROJ-YGP",
                    "release_evidence_target_type": "ygp_original_readback_backfill",
                    "source_profile_id": "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
                    "source_specific_adapter_id": "guangdong_ygp_original_readback_backfill_adapter_v1",
                    "adapter_result_state": "MATCHED",
                    "field_readback_state": "YGP_ORIGINAL_NOTICE_READBACK_READY_REVIEW_REQUIRED",
                    "downstream_release_evidence_abcd_grade": "B_ENHANCEMENT_OFFICIAL_READBACK",
                    "field_match_summary": {
                        "source_specific_records": [
                            {
                                "url": "https://ygp.example/detail?projectCode=E4401002701501867001",
                                "source_text_sha256": "abc123",
                                "ygp_project_code_variants": ["E4401002701501867001"],
                                "ygp_biz_code": "3C52",
                                "ygp_site_code": "440100",
                                "ygp_notice_id": "notice-1",
                            }
                        ],
                    },
                }
            ],
        )

        record = projection["limited_sellable_review_official_readback_records"][0]
        self.assertEqual(record["public_source_chain"], "YGP_ORIGINAL_READBACK_BACKFILL")
        self.assertEqual(
            record["stage4_bridge_backfill_state"],
            "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
        )
        self.assertFalse(record["gdcic_project_code_route_allowed"])
        self.assertEqual(
            record["gdcic_project_code_route_policy"],
            "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
        )
        self.assertEqual(
            projection["limited_sellable_review_public_source_chain_counts"],
            {"YGP_ORIGINAL_READBACK_BACKFILL": 1},
        )
        self.assertEqual(
            projection["limited_sellable_review_stage4_bridge_backfill_state_counts"],
            {"PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY": 1},
        )
        self.assertEqual(
            projection["limited_sellable_review_gdcic_project_code_route_policy_counts"],
            {"YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE": 1},
        )

    def test_runtime_blocker_projection_keeps_routes_and_counts_together(self) -> None:
        projection = runtime_blocker_projection_fields(
            [
                {
                    "blocker_state": "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED",
                    "runtime_layer": "browser worker",
                    "required_input": ["browser_worker_session_or_same_session_retry_budget"],
                },
                {
                    "blocker_state": "FALLBACK_SOURCE_REQUIRED",
                    "runtime_layer": "source adapter",
                    "required_input": ["fallback_source_or_project_local_authority_path"],
                },
            ]
        )

        self.assertEqual(
            projection["runtime_blocker_ledger_state_counts"],
            {
                "BROWSER_WORKER_OR_SAME_SESSION_RETRY_REQUIRED": 1,
                "FALLBACK_SOURCE_REQUIRED": 1,
            },
        )
        self.assertEqual(
            projection["runtime_blocker_ledger_layer_counts"],
            {"browser worker": 1, "source adapter": 1},
        )
        self.assertEqual(
            projection["runtime_blocker_subqueue_counts"],
            {"browser_worker": 1, "fallback_source": 1, "retry": 1},
        )


if __name__ == "__main__":
    unittest.main()
