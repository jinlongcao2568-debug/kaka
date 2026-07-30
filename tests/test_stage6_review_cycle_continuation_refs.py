from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage6_review_cycle_continuation_refs import (  # noqa: E402
    build_stage6_review_cycle_continuation_input_refs,
)


class Stage6ReviewCycleContinuationRefsTests(unittest.TestCase):
    def test_builds_machine_consumable_stage6_continuation_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_root = root / "stage6"
            field_query = root / "field-query" / "guangdong-local-field-query-probe-v1.json"
            supplemental_field_query = root / "field-query-ygp" / "guangdong-local-field-query-probe-v1.json"
            next_subqueue = root / "stage6" / "stage6-review-cycle-runtime-blocker-next-subqueues.json"
            status = root / "stage6" / "stage6-review-loop-project-status-table.json"
            gdcic = root / "gdcic" / "gdcic-browser-authorized-readback-v1.json"
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            for path in (field_query, supplemental_field_query, next_subqueue, status, gdcic, scoreboard):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            refs = build_stage6_review_cycle_continuation_input_refs(
                output_root=output_root,
                release_field_query_json=field_query,
                supplemental_release_field_query_json=supplemental_field_query,
                runtime_blocker_next_subqueue_json=next_subqueue,
                stage6_review_loop_status_json=status,
                gdcic_browser_readback_json=gdcic,
                stage1_6_scoreboard_json=scoreboard,
            )

        self.assertEqual(refs["prior_stage6_status_json"], str(status))
        self.assertEqual(refs["effective_release_field_query_root"], str(field_query.parent))
        self.assertEqual(refs["effective_supplemental_release_field_query_root"], str(supplemental_field_query.parent))
        self.assertEqual(refs["effective_runtime_blocker_next_subqueue_root"], str(next_subqueue.parent))
        self.assertEqual(refs["effective_gdcic_browser_readback_root"], str(gdcic.parent))
        self.assertEqual(refs["effective_stage1_6_scoreboard_json"], str(scoreboard))
        self.assertEqual(refs["release_field_query_root_resolution_state"], "RESOLVED_FROM_STAGE6_INPUT_REFS")
        self.assertFalse(refs["customer_visible_allowed"])
        self.assertTrue(refs["query_miss_is_not_clearance"])

    def test_missing_optional_inputs_remain_unresolved_without_faking_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            refs = build_stage6_review_cycle_continuation_input_refs(output_root=Path(tmp_dir) / "stage6")

        self.assertEqual(refs["effective_gdcic_browser_readback_root"], "")
        self.assertEqual(refs["gdcic_browser_readback_root_resolution_state"], "UNRESOLVED")
        self.assertEqual(refs["stage1_6_scoreboard_resolution_state"], "UNRESOLVED")
        self.assertFalse(refs["customer_visible_allowed"])


if __name__ == "__main__":
    unittest.main()
