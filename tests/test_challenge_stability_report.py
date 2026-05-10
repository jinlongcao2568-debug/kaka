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

from storage.challenge_stability_report import (  # noqa: E402
    CLASSIFIED_ONLY,
    DIRECT_FETCH_OK_NOT_CHALLENGE,
    NO_ATTACHMENT_SIGNAL,
    NO_REAL_COVERAGE,
    PARTIAL,
    STABLE,
    build_challenge_stability_report,
)


class ChallengeStabilityReportTests(unittest.TestCase):
    def test_platform_grades_distinguish_resolved_classified_and_no_coverage(self) -> None:
        payload = {
            "manifest": {
                "manifest_id": "REAL-SAMPLE-TEST",
                "items": [
                    {"target_id": "GZ", "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST"},
                    {"target_id": "JS", "source_profile_id": "JIANGSU-GGZY-HOME"},
                    {"target_id": "UNUSED", "source_profile_id": "UNUSED-PLATFORM-WITHOUT-PROJECTS"},
                    {"target_id": "SD", "source_profile_id": "SHANDONG-GGZY-JYXXGK-LIST"},
                    {"target_id": "HB", "source_profile_id": "HUBEI-BIDCLOUD-JYXX-LIST"},
                ],
                "project_sample_items": [
                    {
                        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                        "detail_snapshot_count": 1,
                        "attachment_snapshot_count": 1,
                        "challenge_diagnostics": [
                            {
                                "capture_kind": "attachment",
                                "attempted": True,
                                "state": "RESOLVED_AND_SNAPSHOT_CAPTURED",
                            }
                        ],
                        "failure_taxonomy": [],
                    },
                    {
                        "source_profile_id": "JIANGSU-GGZY-HOME",
                        "detail_snapshot_count": 0,
                        "attachment_snapshot_count": 0,
                        "challenge_diagnostics": [],
                        "failure_taxonomy": [
                            "detail_capture_failure:controlled_challenge_body_pattern:请登录:1"
                        ],
                    },
                    {
                        "source_profile_id": "SHANDONG-GGZY-JYXXGK-LIST",
                        "detail_snapshot_count": 0,
                        "attachment_snapshot_count": 0,
                        "challenge_diagnostics": [],
                        "failure_taxonomy": [
                            "detail_capture_failure:http_status:502:3",
                            "shandong_detail_url_variant_exhausted",
                        ],
                    },
                    {
                        "source_profile_id": "HUBEI-BIDCLOUD-JYXX-LIST",
                        "detail_snapshot_count": 1,
                        "attachment_snapshot_count": 1,
                        "challenge_diagnostics": [
                            {
                                "capture_kind": "attachment",
                                "attempted": True,
                                "state": "FAILED_CLOSED_RESOLVER_ERROR",
                            }
                        ],
                        "failure_taxonomy": [],
                    },
                    {
                        "source_profile_id": "HUBEI-BIDCLOUD-JYXX-LIST",
                        "detail_snapshot_count": 1,
                        "attachment_snapshot_count": 1,
                        "challenge_diagnostics": [
                            {
                                "capture_kind": "attachment",
                                "attempted": True,
                                "state": "RESOLVED_AND_SNAPSHOT_CAPTURED",
                            }
                        ],
                        "failure_taxonomy": [],
                    },
                ],
            }
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "real-sample.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            result = build_challenge_stability_report(real_sample_execution_manifest_json=path)

        reports = {
            item["source_profile_id"]: item
            for item in result["manifest"]["platform_reports"]
        }
        self.assertEqual(reports["GUANGZHOU-YWTB-CONSTRUCTION-LIST"]["stability_grade"], STABLE)
        self.assertEqual(reports["JIANGSU-GGZY-HOME"]["stability_grade"], CLASSIFIED_ONLY)
        self.assertEqual(reports["UNUSED-PLATFORM-WITHOUT-PROJECTS"]["stability_grade"], NO_REAL_COVERAGE)
        self.assertEqual(reports["SHANDONG-GGZY-JYXXGK-LIST"]["stability_grade"], NO_ATTACHMENT_SIGNAL)
        self.assertEqual(reports["HUBEI-BIDCLOUD-JYXX-LIST"]["stability_grade"], PARTIAL)
        self.assertEqual(result["summary"]["challenge_resolved_count"], 2)
        self.assertEqual(result["summary"]["challenge_failed_count"], 1)
        self.assertFalse(result["manifest"]["customer_visible_allowed"])

    def test_direct_fetch_without_challenge_is_not_marked_stable(self) -> None:
        payload = {
            "manifest": {
                "items": [{"target_id": "SC", "source_profile_id": "SICHUAN-GGZY-TRANSACTION-INFO"}],
                "project_sample_items": [
                    {
                        "source_profile_id": "SICHUAN-GGZY-TRANSACTION-INFO",
                        "detail_snapshot_count": 1,
                        "attachment_snapshot_count": 1,
                        "challenge_diagnostics": [],
                        "failure_taxonomy": [],
                    }
                ],
            }
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "real-sample.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = build_challenge_stability_report(real_sample_execution_manifest_json=path)

        report = result["manifest"]["platform_reports"][0]
        self.assertEqual(report["stability_grade"], DIRECT_FETCH_OK_NOT_CHALLENGE)


if __name__ == "__main__":
    unittest.main()
