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

from storage.stage4_backfill_followup_queue import build_stage4_backfill_followup_queue


class Stage4BackfillFollowupQueueTests(unittest.TestCase):
    def test_builds_controller_consumable_followups_from_scoreboard_gap_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scoreboard = root / "scoreboard.json"
            out = root / "out"
            _write_json(
                scoreboard,
                {
                    "project_rows": [
                        {
                            "project_id": "PROJ-NO-SIGNAL",
                            "project_name": "No signal project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "AUTHORIZATION_AND_SOURCE_NOT_FOUND_REVIEW",
                            "p13b_public_source_readback_state": "NO_PUBLIC_OVERLAP_SIGNAL_REVIEW",
                            "p13b_overlap_triage_state": "NO_OVERLAP_SIGNAL_REVIEW",
                        },
                        {
                            "project_id": "PROJ-BLOCKED",
                            "project_name": "Blocked project",
                            "stage4_project_code_backfill_state": "MISSING_PROJECT_CODE_BACKFILL_INPUT",
                            "stage4_project_code_backfill_gap_detail": "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED",
                            "stage5_operational_review_bucket": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_public_source_readback_state": "PUBLIC_SOURCE_BLOCKED_REVIEW",
                            "p13b_overlap_triage_state": "SOURCE_LIMIT_DEFERRED",
                        },
                        {
                            "project_id": "PROJ-READY",
                            "stage4_project_code_backfill_state": "PUBLIC_SOURCE_IDENTIFIER_BACKFILLED_FOR_P13B_OR_STAGE4_BRIDGE_ONLY",
                            "stage4_project_code_backfill_gap_detail": "",
                        },
                    ]
                },
            )

            result = build_stage4_backfill_followup_queue(
                scoreboard_json=scoreboard,
                output_root=out,
                created_at="2026-05-25T00:00:00+00:00",
            )

        self.assertEqual(result["summary"]["followup_record_count"], 2)
        self.assertEqual(
            result["summary"]["gap_detail_counts"],
            {
                "NO_PUBLIC_OVERLAP_SIGNAL_FALLBACK_LOCAL_AUTHORITY_REQUIRED": 1,
                "PUBLIC_SOURCE_BLOCKED_RETRY_OR_LOCAL_AUTHORITY_REQUIRED": 1,
            },
        )
        routes = {record["project_id"]: record["followup_route"] for record in result["records"]}
        self.assertEqual(routes["PROJ-NO-SIGNAL"], "local_authority_fallback_source_planning")
        self.assertEqual(routes["PROJ-BLOCKED"], "public_source_retry_then_local_authority_fallback")
        for record in result["records"]:
            self.assertTrue(record["controller_consumable"])
            self.assertFalse(record["customer_visible_allowed"])
            self.assertFalse(record["live_execution_enabled"])
            self.assertTrue(record["query_miss_is_not_clearance"])


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
