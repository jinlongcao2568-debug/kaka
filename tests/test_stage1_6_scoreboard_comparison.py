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

from storage.stage1_6_scoreboard_comparison import build_stage1_6_scoreboard_comparison


class StageOneSixScoreboardComparisonTests(unittest.TestCase):
    def test_comparison_summarizes_sellable_stage4_stage5_and_long_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_a = root / "stage1-6-sellable-rate-regression-live12"
            run_b = root / "stage1-6-sellable-rate-regression-live15"
            out = root / "out"
            _write_scoreboard(
                run_a / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=12,
                limited_count=3,
                rate=0.25,
                stage4={"MATCHED": 9, "NEEDS_BROWSER": 39, "NOT_FOUND": 5},
                stage5={"RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 6},
                long_tail={"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 6},
                public_source_chain={"LOCAL_AUTHORITY_PUBLIC_API_READBACK": 4},
            )
            _write_scoreboard(
                run_b / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json",
                candidate_count=15,
                limited_count=4,
                rate=0.2667,
                stage4={"MATCHED": 11, "NEEDS_BROWSER": 45, "NOT_FOUND": 11},
                stage5={"RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 9},
                long_tail={"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 9},
                public_source_chain={
                    "LOCAL_AUTHORITY_PUBLIC_API_READBACK": 4,
                    "YGP_ORIGINAL_READBACK_BACKFILL": 7,
                },
            )

            result = build_stage1_6_scoreboard_comparison(
                run_roots=[run_a, run_b],
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )
            self.assertEqual(result["summary"]["run_count"], 2)
            self.assertEqual(result["summary"]["total_candidate_count"], 27)
            self.assertEqual(result["summary"]["total_limited_sellable_review_candidate_count"], 7)
            self.assertEqual(result["summary"]["best_rate_run_label"], "stage1-6-sellable-rate-regression-live15")
            self.assertEqual(result["comparison_rows"][0]["stage2_success_rate"], 1.0)
            self.assertEqual(result["comparison_rows"][1]["stage4_adapter_result_state_counts"]["MATCHED"], 11)
            self.assertEqual(
                result["comparison_rows"][1]["stage5_operational_review_queue_counts"],
                {"RESPONSIBLE_PERSON_CERTIFICATE_GAP_REVIEW": 9},
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage1_3_long_tail_bucket_counts"],
                {"COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED": 9},
            )
            self.assertEqual(
                result["comparison_rows"][1]["stage6_limited_sellable_review_public_source_chain_counts"],
                {
                    "LOCAL_AUTHORITY_PUBLIC_API_READBACK": 4,
                    "YGP_ORIGINAL_READBACK_BACKFILL": 7,
                },
            )
            self.assertEqual(result["delta_from_first_row"][1]["stage4_matched_delta"], 2)
            self.assertFalse(result["safety"]["customer_visible_allowed"])
            self.assertTrue((out / "stage1-6-scoreboard-comparison-v1.json").exists())
            markdown = (out / "stage1-6-scoreboard-comparison-v1.md").read_text(encoding="utf-8")
            self.assertIn("stage6 public source chain", markdown)
            self.assertIn("YGP_ORIGINAL_READBACK_BACKFILL", markdown)


def _write_scoreboard(
    path: Path,
    *,
    candidate_count: int,
    limited_count: int,
    rate: float,
    stage4: dict[str, int],
    stage5: dict[str, int],
    long_tail: dict[str, int],
    public_source_chain: dict[str, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scoreboard": {
            "candidate_count": candidate_count,
            "stage2_success_count": candidate_count,
            "stage3_success_count": candidate_count,
            "limited_sellable_review_candidate_count": limited_count,
            "strong_lead_review_candidate_count": limited_count,
            "real_public_sellable_pack_rate": rate,
            "stage4_adapter_result_state_counts": stage4,
            "stage5_operational_review_queue_counts": stage5,
            "stage1_3_long_tail_bucket_counts": long_tail,
            "stage6_limited_sellable_review_public_source_chain_counts": public_source_chain,
            "gdcic_authorized_readback_status": {
                "authorization_readiness_state": "LOGIN_OR_SSO_REQUIRED",
            },
        },
        "blocker_summary": {"active_fail_closed_reason_counts": {}},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
