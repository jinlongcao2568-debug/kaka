from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.guangzhou_post_candidate_backtrace import (  # noqa: E402
    _annotate_project_samples,
    _backtrace_targets_for_entries,
)


class TestGuangzhouPostCandidateBacktrace(unittest.TestCase):
    def test_backtrace_targets_start_from_post_candidate_entry_and_include_project_filters(self) -> None:
        targets = _backtrace_targets_for_entries(
            [
                {
                    "project_id": "PROJ-CN-GD-JG2026-POST",
                    "project_name": "南沙区排水设施小修项目施工中标候选人公示",
                    "source_project_code": "JG2026-POST",
                    "project_match_key": "JG2026-POST",
                }
            ]
        )

        self.assertEqual(len(targets["targets"]), 3)
        self.assertEqual(
            {target["document_kind"] for target in targets["targets"]},
            {"tender_file", "candidate_notice", "award_result"},
        )
        for target in targets["targets"]:
            filters = target["selection_filters"]
            self.assertIn("BACKTRACE_PROJECT_CODE:JG2026-POST", filters)
            self.assertTrue(any(item.startswith("BACKTRACE_PROJECT_NAME:") for item in filters))
            self.assertIn("BACKTRACE_BASE_PROJECT_NAME:南沙区排水设施小修项目施工", filters)
            self.assertIn("BACKTRACE_QUERY_VARIANT:南沙区排水设施小修项目", filters)
            self.assertIn("南沙区排水设施小修项目", target["backtrace_query_variants"])
            self.assertEqual(target["required_fetch_profile_id_optional"], "GUANGZHOU-YWTB-CONSTRUCTION-LIST")

    def test_backtrace_targets_skip_entry_stage_already_captured(self) -> None:
        targets = _backtrace_targets_for_entries(
            [
                {
                    "project_id": "PROJ-CN-GD-JG2026-POST",
                    "project_name": "南沙区排水设施小修项目施工中标候选人公示",
                    "source_project_code": "JG2026-POST",
                    "project_match_key": "JG2026-POST",
                    "present_document_kinds": ["candidate_notice", "award_result"],
                }
            ]
        )

        self.assertEqual([target["document_kind"] for target in targets["targets"]], ["tender_file"])

    def test_annotates_missing_and_complete_backtrace_states(self) -> None:
        complete = _annotate_project_samples(
            [
                _sample("tender_file", project_id="PROJ-1"),
                _sample("candidate_notice", project_id="PROJ-1"),
                _sample("award_result", project_id="PROJ-1"),
            ]
        )
        partial = _annotate_project_samples(
            [
                _sample("candidate_notice", project_id="PROJ-2"),
            ]
        )

        self.assertTrue(all(item["backtrace_completeness_state"] == "BACKTRACE_CORE_COMPLETE" for item in complete))
        self.assertTrue(all(item["post_candidate_entry_state"] == "POST_CANDIDATE_ENTRY_PRESENT" for item in complete))
        self.assertEqual(partial[0]["backtrace_completeness_state"], "BACKTRACE_PARTIAL")
        self.assertEqual(partial[0]["missing_stage_kinds"], ["tender_file", "award_result"])

    def test_no_match_backtrace_target_attempt_is_attached_to_project(self) -> None:
        annotated = _annotate_project_samples(
            [_sample("candidate_notice", project_id="PROJ-1")],
            target_items=[
                {
                    "target_id": "GZ-BACKTRACE-JG2026-POST-TENDER",
                    "document_kind": "tender_file",
                    "selection_filters": ["BACKTRACE_PROJECT_CODE:JG2026-POST"],
                    "base_project_name": "南沙区排水设施小修项目施工",
                    "backtrace_query_variants": ["JG2026-POST", "南沙区排水设施小修项目施工"],
                    "target_execution_state": "DISCOVERY_NO_MATCH_REVIEW",
                    "failure_taxonomy": ["discovery_no_match"],
                }
            ],
        )

        attempts = annotated[0]["backtrace_stage_attempts"]
        self.assertTrue(any(attempt["document_kind"] == "tender_file" for attempt in attempts))
        tender_attempt = next(attempt for attempt in attempts if attempt["document_kind"] == "tender_file")
        self.assertEqual(tender_attempt["target_execution_state"], "DISCOVERY_NO_MATCH_REVIEW")
        self.assertIn("discovery_no_match", tender_attempt["failure_taxonomy"])
        self.assertEqual(tender_attempt["base_project_name"], "南沙区排水设施小修项目施工")
        self.assertIn("南沙区排水设施小修项目施工", tender_attempt["backtrace_query_variants"])


def _sample(document_kind: str, *, project_id: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "target_id": f"TARGET-{document_kind}",
        "parent_target_id": f"PARENT-{document_kind}",
        "document_kind": document_kind,
        "source_url": f"https://example.test/{document_kind}.html",
        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
        "detail_snapshot_count": 1,
        "attachment_snapshot_count": 0,
        "failure_taxonomy": [],
        "source_project_code": "JG2026-POST",
        "project_match_key": "JG2026-POST",
        "matched_project_keys": ["JG2026-POST"],
    }


if __name__ == "__main__":
    unittest.main()
