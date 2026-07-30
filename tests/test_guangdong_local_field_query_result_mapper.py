from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangdong_local_field_query_result_mapper import (  # noqa: E402
    adapter_result_state,
    adapter_result_state_basis,
    downstream_release_evidence_abcd_basis,
    downstream_release_evidence_abcd_grade,
)


class GuangdongLocalFieldQueryResultMapperTests(unittest.TestCase):
    def test_adapter_result_state_keeps_miss_and_blocker_non_clearance(self) -> None:
        matched = {"field_query_probe_state": "FIELD_READBACK_READY_PUBLIC_SOURCE"}
        missed = {"field_query_probe_state": "NO_FIELD_MATCH_REVIEW_REQUIRED"}
        blocked = {"field_query_probe_state": "FAIL_CLOSED_PUBLIC_SOURCE_BLOCKED", "blocker_taxonomy": ["http_403"]}
        browser = {"field_query_probe_state": "LIVE_FIELD_QUERY_NEEDS_BROWSER"}
        region_adapter = {"field_query_probe_state": "LIVE_FIELD_QUERY_NEEDS_REGION_ADAPTER"}

        self.assertEqual(adapter_result_state(matched), "MATCHED")
        self.assertEqual(adapter_result_state(missed), "NOT_FOUND")
        self.assertEqual(adapter_result_state(blocked), "BLOCKED")
        self.assertEqual(adapter_result_state(browser), "NEEDS_BROWSER")
        self.assertEqual(adapter_result_state(region_adapter), "BLOCKED")
        self.assertIn("public_source_queried_no_field_match_not_clearance", adapter_result_state_basis("NOT_FOUND", missed))
        self.assertIn("http_403", adapter_result_state_basis("BLOCKED", blocked))

    def test_downstream_grade_separates_enhancement_reverse_blocked_and_pending(self) -> None:
        self.assertEqual(
            downstream_release_evidence_abcd_grade(
                ["contract_public_info"],
                field_query_probe_state="FIELD_READBACK_READY_PUBLIC_SOURCE",
                readback_ready=True,
            ),
            "B_ENHANCEMENT_OFFICIAL_READBACK",
        )
        self.assertEqual(
            downstream_release_evidence_abcd_grade(
                ["project_manager_change_notice"],
                field_query_probe_state="FIELD_READBACK_READY_PUBLIC_SOURCE",
                readback_ready=True,
            ),
            "C_REVERSE_EXPLANATION_OFFICIAL_READBACK",
        )
        self.assertEqual(
            downstream_release_evidence_abcd_grade(
                ["contract_public_info"],
                field_query_probe_state="NO_FIELD_MATCH_REVIEW_REQUIRED",
                readback_ready=False,
            ),
            "D_INSUFFICIENT_OR_BLOCKED_READBACK",
        )
        self.assertEqual(
            downstream_release_evidence_abcd_grade(
                ["contract_public_info"],
                field_query_probe_state="PLAN_ONLY_NOT_EXECUTED",
                readback_ready=False,
            ),
            "PENDING_NOT_EXECUTED",
        )

    def test_downstream_basis_does_not_emit_clearance_language(self) -> None:
        basis = downstream_release_evidence_abcd_basis(
            "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            ["contract_public_info"],
            field_query_probe_state="NO_FIELD_MATCH_REVIEW_REQUIRED",
        )

        joined = "|".join(basis)
        self.assertIn("targeted_source_no_hit_blocked_or_deferred_review", joined)
        self.assertNotIn("无风险", joined)
        self.assertNotIn("无冲突", joined)


if __name__ == "__main__":
    unittest.main()
