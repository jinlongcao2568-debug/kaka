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

from storage.real_public_source_coverage_freshness import (  # noqa: E402
    build_real_public_source_coverage_freshness_report,
)


def _snapshot(
    snapshot_id: str,
    *,
    profile_id: str,
    kind: str,
    fetched_at: str,
) -> dict[str, object]:
    return {
        "payload": {
            "snapshot_id": snapshot_id,
            "snapshot_kind": kind,
            "source_url_optional": "https://example.invalid/source",
            "lineage_refs": {"entry_profile_id": profile_id},
            "fetched_at_optional": fetched_at,
            "replay_state": "READBACK_READY",
        }
    }


class RealPublicSourceCoverageFreshnessTests(unittest.TestCase):
    def _write_inputs(self, root: Path, *, execute: bool = True) -> tuple[Path, Path]:
        run_path = root / "run-manifest.json"
        storage_path = root / "storage.json"
        items = [
            {
                "source_profile_id": "CCGP-CENTRAL-NOTICES",
                "source_family": "central_government_procurement",
                "document_kind": "candidate_notice",
                "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
                "discovery_candidate_count": 2,
                "detail_snapshot_refs": [
                    {"snapshot_id": "DETAIL-CCGP-1"},
                    {"snapshot_id": "DETAIL-CCGP-2"},
                ],
                "attachment_snapshot_refs": [],
                "parse_summary": {},
                "failure_taxonomy": [],
            },
            {
                "source_profile_id": "SHANDONG-GGZY-JYXXGK-LIST",
                "source_family": "provincial_public_resource_trading_center",
                "document_kind": "tender_file",
                "target_execution_state": "CAPTURE_PARTIAL_REVIEW",
                "discovery_candidate_count": 2,
                "detail_snapshot_refs": [],
                "attachment_snapshot_refs": [],
                "parse_summary": {"attachment_missing_review_count": 2},
                "failure_taxonomy": [
                    "detail_capture_failure:http_status:502:2",
                    "attachment_unsupported_content_type",
                ],
            },
            {
                "source_profile_id": "GGZY-DEAL-LIST",
                "source_family": "national_public_resource_trading_platform",
                "document_kind": "official_case",
                "target_execution_state": "DISCOVERY_NO_MATCH_REVIEW",
                "discovery_candidate_count": 0,
                "detail_snapshot_refs": [],
                "attachment_snapshot_refs": [],
                "parse_summary": {},
                "failure_taxonomy": ["discovery_no_match"],
            },
        ]
        run_payload = {
            "real_sample_execution_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "manifest": {
                "manifest_id": "TEST-RUN-001",
                "created_at": "2026-07-20T10:00:00+00:00",
                "items": items,
            },
            "execution": {
                "executed": execute,
                "fetch_public_urls_enabled": execute,
                "storage_path_optional": str(storage_path),
            },
        }
        snapshots = {
            "ENTRY-CCGP": _snapshot(
                "ENTRY-CCGP",
                profile_id="CCGP-CENTRAL-NOTICES",
                kind="real_public_entry_html_snapshot",
                fetched_at="2026-07-20T10:00:00+00:00",
            ),
            "DETAIL-CCGP-1": _snapshot(
                "DETAIL-CCGP-1",
                profile_id="CCGP-CENTRAL-NOTICES",
                kind="real_public_detail_html_snapshot",
                fetched_at="2026-07-20T10:01:00+00:00",
            ),
            "DETAIL-CCGP-2": _snapshot(
                "DETAIL-CCGP-2",
                profile_id="CCGP-CENTRAL-NOTICES",
                kind="real_public_detail_html_snapshot",
                fetched_at="2026-07-20T10:02:00+00:00",
            ),
            "ENTRY-SD": _snapshot(
                "ENTRY-SD",
                profile_id="SHANDONG-GGZY-JYXXGK-LIST",
                kind="real_public_entry_html_snapshot",
                fetched_at="2026-07-16T10:00:00+00:00",
            ),
            "ENTRY-GGZY": _snapshot(
                "ENTRY-GGZY",
                profile_id="GGZY-DEAL-LIST",
                kind="real_public_entry_html_snapshot",
                fetched_at="2026-07-20T09:30:00+00:00",
            ),
        }
        storage_payload = {
            "tables": {"evidence_snapshot_manifest": snapshots}
        }
        run_path.write_text(
            json.dumps(run_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        storage_path.write_text(
            json.dumps(storage_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return run_path, storage_path

    def test_report_separates_fresh_covered_stale_blocked_no_match_and_unobserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_path, storage_path = self._write_inputs(root)
            result = build_real_public_source_coverage_freshness_report(
                run_manifest_json=run_path,
                storage_json=storage_path,
                output_root=root / "out",
                created_at="2026-07-20T12:00:00+00:00",
            )

            self.assertTrue(result["report_valid"])
            self.assertTrue(result["summary"]["real_observation_valid"])
            self.assertEqual(result["summary"]["observed_registered_source_count"], 3)
            self.assertGreater(result["summary"]["unobserved_registered_source_count"], 0)
            rows = {
                row["source_profile_id"]: row
                for row in result["manifest"]["source_rows"]
            }
            ccgp = rows["CCGP-CENTRAL-NOTICES"]
            self.assertEqual(ccgp["coverage_state"], "COVERED_WITH_DETAIL_SNAPSHOTS")
            self.assertEqual(ccgp["freshness_state"], "FRESH")
            self.assertEqual(ccgp["detail_coverage"]["coverage_rate"], 1.0)
            self.assertTrue(ccgp["external_claim_eligible"])

            shandong = rows["SHANDONG-GGZY-JYXXGK-LIST"]
            self.assertEqual(shandong["coverage_state"], "PARTIAL_OR_BLOCKED")
            self.assertEqual(shandong["freshness_state"], "STALE")
            self.assertEqual(shandong["detail_coverage"]["coverage_rate"], 0.0)
            self.assertEqual(shandong["blocker_metrics"]["blocked_rate"], 1.0)
            self.assertFalse(shandong["external_claim_eligible"])

            ggzy = rows["GGZY-DEAL-LIST"]
            self.assertEqual(
                ggzy["coverage_state"], "OBSERVED_NO_MATCH_IN_QUERY_SCOPE"
            )
            self.assertEqual(
                ggzy["list_coverage"]["no_match_interpretation"],
                "NO_MATCH_IN_OBSERVED_QUERY_SCOPE",
            )
            self.assertFalse(result["summary"]["not_found_clearance_allowed"])
            self.assertTrue(
                (root / "out" / "real-public-source-coverage-freshness-v1.json").exists()
            )
            self.assertTrue((root / "out" / "source-coverage-table.json").exists())
            self.assertTrue((root / "out" / "summary.md").exists())

    def test_dry_run_never_creates_source_coverage_or_external_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_path, storage_path = self._write_inputs(root, execute=False)
            result = build_real_public_source_coverage_freshness_report(
                run_manifest_json=run_path,
                storage_json=storage_path,
                output_root=root / "out",
                created_at="2026-07-20T12:00:00+00:00",
            )

            self.assertFalse(result["summary"]["real_observation_valid"])
            self.assertEqual(result["summary"]["observed_registered_source_count"], 0)
            self.assertEqual(result["summary"]["external_claim_eligible_source_count"], 0)
            self.assertTrue(
                all(
                    row["coverage_state"] == "DRY_RUN_NOT_OBSERVED"
                    for row in result["manifest"]["source_rows"]
                )
            )


if __name__ == "__main__":
    unittest.main()
