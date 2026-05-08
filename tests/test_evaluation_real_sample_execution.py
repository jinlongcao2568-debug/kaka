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

from storage.evaluation_real_sample_execution import (
    CAPTURED_WITH_SNAPSHOTS,
    CAPTURE_PARTIAL_REVIEW,
    DISCOVERY_FAILED_CLOSED,
    DISCOVERY_NO_MATCH_REVIEW,
    EXECUTION_READY,
    build_evaluation_real_sample_execution,
)


class FakeDiscoveryService:
    def __init__(self, *, candidates: list[dict] | None = None, profile_status: str = "FETCHED") -> None:
        self.calls: list[dict] = []
        self.candidates = candidates if candidates is not None else [_fake_candidate()]
        self.profile_status = profile_status

    def discover(self, payload: dict, *, now: str | None = None) -> dict:
        self.calls.append(dict(payload))
        return {
            "discovery_state": "COMPLETED" if self.candidates else "NO_CANDIDATES",
            "candidate_count": len(self.candidates),
            "candidates": list(self.candidates),
            "profile_reports": [
                {
                    "region_code": "CN-GD",
                    "profile_id": (payload.get("source_profile_ids") or [""])[0],
                    "entry_url": "https://example.test/list",
                    "status": self.profile_status,
                    "candidate_count": len(self.candidates),
                }
            ],
        }


class FakeCaptureService:
    def __init__(self, *, detail_snapshot: bool = True, parse_state: str = "PARSED_HTML") -> None:
        self.calls: list[dict] = []
        self.detail_snapshot = detail_snapshot
        self.parse_state = parse_state

    def capture_candidates(self, candidates: list[dict], **kwargs: object) -> dict:
        self.calls.append({"candidates": list(candidates), "kwargs": dict(kwargs)})
        candidate = candidates[0]
        snapshot_id = "SNAP-DETAIL-001" if self.detail_snapshot else ""
        return {
            "detail_snapshot_count": 1 if snapshot_id else 0,
            "detail_capture_failed_count": 0 if snapshot_id else 1,
            "stage3_parse_success_count": 1 if self.parse_state.startswith("PARSED") else 0,
            "stage3_parse_failed_count": 0 if self.parse_state.startswith("PARSED") else 1,
            "attachment_snapshot_count": 1,
            "captures": [
                {
                    "candidate_key": candidate["candidate_key"],
                    "project_id": candidate["project_id"],
                    "project_name": candidate["project_name"],
                    "source_url": candidate["source_url"],
                    "detail_snapshot_id_optional": snapshot_id,
                    "stage3_parse_state": self.parse_state,
                    "attachment_captures": [
                        {
                            "attachment_snapshot_id_optional": "SNAP-ATT-001",
                            "attachment_url": "https://example.test/tender.pdf",
                            "parse_state": "PARSED_PDF",
                            "attachment_role_type": "tender_file",
                        }
                    ],
                }
            ],
        }


class TestEvaluationRealSampleExecution(unittest.TestCase):
    def test_dry_run_outputs_ready_targets_without_discovery_capture_or_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)
            discovery = FakeDiscoveryService()
            capture = FakeCaptureService()

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=False,
                discovery_service=discovery,
                capture_service=capture,
            )

            self.assertEqual(result["real_sample_execution_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(discovery.calls, [])
            self.assertEqual(capture.calls, [])
            item = result["manifest"]["items"][0]
            self.assertEqual(item["target_execution_state"], EXECUTION_READY)
            self.assertEqual(item["candidate_refs"], [])
            self.assertEqual(item["detail_snapshot_refs"], [])
            self.assertFalse(result["manifest"]["safety"]["fetch_public_urls_enabled"])
            self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])
            self.assertEqual(
                result["manifest"]["coverage_quality_summary"]["coverage_quality_state"],
                "DRY_RUN_ONLY_NO_REAL_SNAPSHOT",
            )
            self.assertIn(
                "dry_run_only_no_real_snapshots",
                result["manifest"]["coverage_quality_summary"]["sample_quality_reasons"],
            )

    def test_execute_with_fake_services_outputs_snapshot_manifest_without_customer_visible_conclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)
            discovery = FakeDiscoveryService()
            capture = FakeCaptureService()

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                created_at="2026-05-01T00:00:00+00:00",
                discovery_service=discovery,
                capture_service=capture,
            )

            self.assertEqual(result["real_sample_execution_mode"], "EXECUTED")
            self.assertEqual(discovery.calls[0]["source_profile_ids"], ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"])
            self.assertTrue(discovery.calls[0]["evaluation_corpus_mode"])
            self.assertEqual(discovery.calls[0]["evaluation_document_kind"], "candidate_notice")
            self.assertEqual(len(capture.calls), 1)
            item = result["manifest"]["items"][0]
            self.assertEqual(item["target_execution_state"], CAPTURED_WITH_SNAPSHOTS)
            self.assertEqual(item["candidate_refs"][0]["candidate_key"], "CAND-001")
            self.assertEqual(item["detail_snapshot_refs"][0]["snapshot_id"], "SNAP-DETAIL-001")
            self.assertEqual(item["attachment_snapshot_refs"][0]["snapshot_id"], "SNAP-ATT-001")
            self.assertFalse(result["manifest"]["safety"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["safety"]["no_legal_conclusion"])
            self.assertFalse(result["manifest"]["safety"]["stage4_public_evidence_readback_generation_enabled"])
            self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])
            quality = result["manifest"]["coverage_quality_summary"]
            self.assertEqual(quality["coverage_quality_state"], "REAL_SNAPSHOT_COVERED")
            self.assertEqual(quality["captured_target_count"], 1)
            self.assertEqual(quality["detail_snapshot_count"], 1)
            self.assertEqual(quality["attachment_snapshot_count"], 1)
            self.assertEqual(quality["ocr_blocked_count"], 0)
            manifest_text = json.dumps(result["manifest"], ensure_ascii=False).lower()
            self.assertNotIn("<html", manifest_text)
            self.assertNotIn("%pdf", manifest_text)

    def test_execute_no_match_and_capture_partial_become_review_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)

            no_match = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                discovery_service=FakeDiscoveryService(candidates=[]),
                capture_service=FakeCaptureService(),
            )
            self.assertEqual(no_match["manifest"]["items"][0]["target_execution_state"], DISCOVERY_NO_MATCH_REVIEW)

            failed_closed = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                discovery_service=FakeDiscoveryService(candidates=[], profile_status="SOURCE_PROFILE_NOT_CONFIGURED"),
                capture_service=FakeCaptureService(),
            )
            self.assertEqual(failed_closed["manifest"]["items"][0]["target_execution_state"], DISCOVERY_FAILED_CLOSED)

            partial = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                discovery_service=FakeDiscoveryService(),
                capture_service=FakeCaptureService(detail_snapshot=False, parse_state="OCR_REQUIRED"),
            )
            self.assertEqual(partial["manifest"]["items"][0]["target_execution_state"], CAPTURE_PARTIAL_REVIEW)
            self.assertGreaterEqual(partial["manifest"]["items"][0]["parse_summary"]["ocr_required_count"], 1)
            self.assertEqual(
                partial["manifest"]["coverage_quality_summary"]["coverage_quality_state"],
                "NO_REAL_SNAPSHOT_CAPTURED_REVIEW",
            )
            self.assertIn(
                "ocr_required_blocks_full_text_extraction",
                partial["manifest"]["coverage_quality_summary"]["sample_quality_reasons"],
            )


def _fake_candidate() -> dict:
    return {
        "candidate_key": "CAND-001",
        "notice_id": "NOTICE-001",
        "project_id": "PROJ-001",
        "project_name": "广州某排水工程中标候选人公示",
        "source_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/gz-candidate.html",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "notice_stage": "candidate_notice",
    }


def _write_targets(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "target_set_id": "test-execution-targets",
                "minimum_total_sample_goal": 1,
                "targets": [
                    {
                        "target_id": "READY-CAND",
                        "jurisdiction": "CN-GD",
                        "platform_name": "广州交易集团",
                        "entry_seed_id": "ENTRY-GZ",
                        "required_fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                        "source_family": "local_public_resource_trading_center",
                        "project_type": "construction",
                        "document_kind": "candidate_notice",
                        "target_count": 1,
                        "selection_filters": ["中标候选人公示"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_seed(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "seed_id": "ENTRY-GZ",
                        "source_url": "https://ywtb.gzggzy.cn/jyfw",
                        "source_family": "local_public_resource_trading_center",
                        "jurisdiction": "CN-GD",
                        "document_kind": "candidate_notice",
                        "fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                        "seed_tags": ["real_public_entry", "fetchable"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
