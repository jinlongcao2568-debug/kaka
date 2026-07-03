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

from runtime.controlled_live_public_batch_evidence_summary import (  # noqa: E402
    build_controlled_live_public_batch_evidence_summary,
)
from runtime.controlled_live_public_batch_stage4_readback import (  # noqa: E402
    build_controlled_live_public_batch_stage4_readback,
)
from storage.professional_clean_project_archive import _safe_path_part as safe_path_part  # noqa: E402


class ControlledLivePublicBatchEvidenceSummaryTests(unittest.TestCase):
    def test_builds_hash_and_machine_judgement_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            execution_json = root / "real-sample-execution.json"
            storage_json = root / "storage.json"
            out = root / "out"
            _write_execution(execution_json)
            _write_storage(storage_json)

            result = build_controlled_live_public_batch_evidence_summary(
                real_sample_execution_json=execution_json,
                storage_json=storage_json,
                output_root=out,
                created_at="2026-07-03T00:00:00+00:00",
            )
            output_exists = (out / "controlled-live-public-batch-evidence-summary-v1.json").exists()
            markdown_text = (out / "controlled-live-public-batch-evidence-summary-v1.md").read_text(
                encoding="utf-8"
            )

        summary = result["summary"]
        self.assertEqual(summary["target_execution_bucket_count"], 2)
        self.assertEqual(summary["project_sample_count"], 2)
        self.assertEqual(summary["fixed_snapshot_sha256_count"], 2)
        self.assertEqual(summary["machine_judgement_ready_count"], 2)
        self.assertEqual(
            summary["public_source_outcome_counts"],
            {
                "PUBLIC_SOURCE_HIT_WITH_HASHED_SNAPSHOT": 1,
                "PUBLIC_SOURCE_NO_MATCH_REVIEW": 1,
            },
        )
        self.assertEqual(
            summary["machine_verification_decision_counts"],
            {
                "CURRENT_PUBLIC_SOURCE_RETURNED_NO_MATCH_NOT_CLEARANCE": 1,
                "PUBLIC_SOURCE_SNAPSHOT_CAPTURED_REQUIRES_STAGE4_EVIDENCE_READBACK": 1,
            },
        )
        records = {record["sample_id"]: record for record in result["sample_evidence_table"]["records"]}
        self.assertEqual(records["SAMPLE-HIT"]["evidence_fixation_state"], "SNAPSHOT_FILE_HASHED")
        self.assertEqual(records["SAMPLE-HIT"]["fixed_snapshot_sha256s"], ["abc123detail", "def456attach"])
        self.assertEqual(records["SAMPLE-NO-MATCH"]["evidence_fixation_state"], "NO_CANDIDATE_TO_HASH")
        self.assertFalse(result["customer_visible_allowed"])
        self.assertTrue(result["query_miss_is_not_clearance"])
        self.assertTrue(output_exists)
        self.assertIn("evidence_graph", result)
        self.assertIn("flowchart LR", result["evidence_graph"]["mermaid"])
        self.assertIn("## Evidence Graph", markdown_text)
        self.assertEqual(len(result["evidence_graph"]["sample_graph_records"]), 2)

    def test_safe_path_part_truncates_long_titles_for_windows_archive_paths(self) -> None:
        long_title = "新建龙岩至龙川铁路武平至梅州段广东段新建漳州至汕头高速铁路广东段" * 3

        safe = safe_path_part(long_title)

        self.assertLessEqual(len(safe), 48)
        self.assertRegex(safe, r"_[0-9a-f]{12}$")

    def test_stage4_readback_generates_ready_public_evidence_records_from_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            execution_json = root / "real-sample-execution.json"
            storage_json = root / "storage.json"
            evidence_out = root / "evidence"
            stage4_out = root / "stage4"
            _write_execution(execution_json)
            _write_storage(storage_json)
            build_controlled_live_public_batch_evidence_summary(
                real_sample_execution_json=execution_json,
                storage_json=storage_json,
                output_root=evidence_out,
                created_at="2026-07-03T00:00:00+00:00",
            )

            result = build_controlled_live_public_batch_stage4_readback(
                evidence_summary_json=evidence_out / "controlled-live-public-batch-evidence-summary-v1.json",
                real_sample_execution_json=execution_json,
                storage_json=storage_json,
                output_root=stage4_out,
                created_at="2026-07-03T00:00:00+00:00",
            )
            markdown_text = (stage4_out / "controlled-live-public-batch-stage4-readback-v1.md").read_text(
                encoding="utf-8"
            )

        summary = result["summary"]
        self.assertEqual(summary["stage4_readback_required_sample_count"], 1)
        self.assertEqual(summary["stage4_readback_ready_sample_count"], 1)
        self.assertEqual(summary["stage4_readback_missing_sample_count"], 0)
        self.assertEqual(summary["stage4_public_evidence_readback_count"], 2)
        self.assertTrue(summary["stage4_all_required_readbacks_ready"])
        self.assertFalse(summary["customer_visible_allowed"])
        records = {record["sample_id"]: record for record in result["stage4_readback_table"]["records"]}
        self.assertEqual(records["SAMPLE-HIT"]["stage4_readback_state"], "STAGE4_PUBLIC_EVIDENCE_READBACK_READY")
        self.assertEqual(
            records["SAMPLE-NO-MATCH"]["stage4_readback_state"],
            "STAGE4_PUBLIC_EVIDENCE_READBACK_NOT_REQUIRED",
        )
        readback = result["stage4_public_evidence_readbacks"][0]
        self.assertEqual(readback["readback_state"], "READBACK_READY")
        self.assertTrue(readback["replayable"])
        self.assertFalse(readback["customer_visible"])
        self.assertTrue(readback["no_legal_conclusion"])
        self.assertIn("readback_record_sha256", readback)
        self.assertIn("Stage4 Readback", markdown_text)

    def test_professional_runner_autogenerates_controlled_live_evidence_summary(self) -> None:
        script = (ROOT / "scripts" / "run-professional-clean-v1-real-samples.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("build-controlled-live-public-batch-evidence-summary-v1.ps1", script)
        self.assertIn("-RealSampleExecutionJson", script)
        self.assertIn("-StorageJson", script)
        self.assertIn("$EvidenceSummaryOutputRoot", script)
        self.assertIn('"-OutputRoot", $EvidenceSummaryOutputRoot', script)

    def test_controlled_live_entrypoint_runs_execution_summary_archive_and_closeout(self) -> None:
        script = (ROOT / "scripts" / "run-controlled-live-public-batch-v1.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("run-evaluation-real-sample-execution.ps1", script)
        self.assertIn("-UseAllTargets", script)
        self.assertIn("build-controlled-live-public-batch-evidence-summary-v1.ps1", script)
        self.assertIn("build-controlled-live-public-batch-stage4-readback-v1.ps1", script)
        self.assertIn("build-professional-clean-project-archive.ps1", script)
        self.assertIn("controlled-live-public-batch-evidence-summary-v1.json", script)
        self.assertIn("controlled-live-public-batch-stage4-readback-v1.json", script)
        self.assertIn("project-file-audit.json", script)
        self.assertIn("controlled-live-public-batch-closeout.json", script)
        self.assertIn("NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED", script)
        self.assertIn("NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED", script)
        self.assertIn("stage4_all_required_readbacks_ready", script)
        self.assertIn("customer_visible_allowed = $false", script)
        self.assertIn("payment_execution_enabled = $false", script)
        self.assertIn("delivery_execution_enabled = $false", script)


def _write_execution(path: Path) -> None:
    _write_json(
        path,
        {
            "manifest": {
                "execution_mode": "EXECUTED",
                "execute": True,
                "items": [
                    {
                        "target_id": "TARGET-HIT",
                        "jurisdiction": "CN-GD",
                        "platform_name": "公开平台",
                        "document_kind": "candidate_notice",
                        "source_profile_id": "PUBLIC-SOURCE",
                        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
                        "discovery_candidate_count": 1,
                        "detail_snapshot_refs": [{"snapshot_id": "REAL-DETAIL-abc123"}],
                        "attachment_snapshot_refs": [{"snapshot_id": "REAL-ATTACH-def456"}],
                        "failure_taxonomy": [],
                    },
                    {
                        "target_id": "TARGET-NO-MATCH",
                        "jurisdiction": "CN-GD",
                        "platform_name": "公开平台",
                        "document_kind": "award_result",
                        "source_profile_id": "PUBLIC-SOURCE",
                        "target_execution_state": "DISCOVERY_NO_MATCH_REVIEW",
                        "discovery_candidate_count": 0,
                        "detail_snapshot_refs": [],
                        "attachment_snapshot_refs": [],
                        "failure_taxonomy": ["discovery_no_match"],
                    },
                ],
                "project_sample_items": [
                    {
                        "sample_id": "SAMPLE-HIT",
                        "parent_target_id": "TARGET-HIT",
                        "target_id": "TARGET-HIT::1",
                        "project_id": "PROJ-HIT",
                        "project_name": "命中样本",
                        "document_kind": "candidate_notice",
                        "jurisdiction": "CN-GD",
                        "source_profile_id": "PUBLIC-SOURCE",
                        "source_url": "https://example.test/hit",
                        "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
                        "detail_capture_status": "FETCHED",
                        "stage3_parse_state": "PARSED_WITH_REVIEW",
                        "document_completeness_state": "PARTIAL_REVIEW_REQUIRED",
                        "detail_snapshot_refs": [{"snapshot_id": "REAL-DETAIL-abc123"}],
                        "attachment_snapshot_refs": [{"snapshot_id": "REAL-ATTACH-def456"}],
                    },
                    {
                        "sample_id": "SAMPLE-NO-MATCH",
                        "parent_target_id": "TARGET-NO-MATCH",
                        "target_id": "TARGET-NO-MATCH::1",
                        "project_id": "",
                        "project_name": "",
                        "document_kind": "award_result",
                        "jurisdiction": "CN-GD",
                        "source_profile_id": "PUBLIC-SOURCE",
                        "source_url": "",
                        "target_execution_state": "DISCOVERY_NO_MATCH_REVIEW",
                        "detail_snapshot_refs": [],
                        "attachment_snapshot_refs": [],
                    },
                ],
            }
        },
    )


def _write_storage(path: Path) -> None:
    _write_json(
        path,
        {
            "tables": {
                "object_storage_object": {
                    "objects/ab/abc123detail": {
                        "payload": {
                            "sha256": "abc123detail",
                            "object_key": "objects/ab/abc123detail",
                            "content_type": "text/html",
                            "byte_size": 10,
                        }
                    },
                    "objects/de/def456attach": {
                        "payload": {
                            "sha256": "def456attach",
                            "object_key": "objects/de/def456attach",
                            "content_type": "application/pdf",
                            "byte_size": 20,
                        }
                    },
                }
            }
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
