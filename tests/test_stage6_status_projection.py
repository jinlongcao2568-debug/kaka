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

    def test_stage7_allowed_b_or_c_does_not_create_limited_review_candidate(self) -> None:
        projection = limited_sellable_review_projection(
            {"C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1},
            stage7_commercial_input_allowed=True,
        )

        self.assertEqual(projection["strong_lead_candidate_state"], "STRONG_LEAD_REVIEW_CANDIDATE")
        self.assertEqual(projection["limited_sellable_review_candidate_state"], "NOT_READY")
        self.assertEqual(
            projection["commercialization_boundary_state"],
            "CUSTOMER_DELIVERABLE_ONLY_AFTER_STAGE7_GATE",
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
