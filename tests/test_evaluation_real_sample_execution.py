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
    def __init__(
        self,
        *,
        detail_snapshot: bool = True,
        parse_state: str = "PARSED_HTML",
        document_state: str = "COMPLETE_WITH_ATTACHMENTS",
        version_state: str = "NO_SUPPLEMENT_DETECTED",
        attachment_ocr_required_count: int = 0,
        download_quality_reasons: list[str] | None = None,
        verified_attachment_refs: bool = True,
        detail_challenge_state: str = "",
        attachment_challenge_state: str = "",
    ) -> None:
        self.calls: list[dict] = []
        self.detail_snapshot = detail_snapshot
        self.parse_state = parse_state
        self.document_state = document_state
        self.version_state = version_state
        self.attachment_ocr_required_count = attachment_ocr_required_count
        self.download_quality_reasons = list(download_quality_reasons or [])
        self.verified_attachment_refs = verified_attachment_refs
        self.detail_challenge_state = detail_challenge_state
        self.attachment_challenge_state = attachment_challenge_state

    def capture_candidates(self, candidates: list[dict], **kwargs: object) -> dict:
        self.calls.append({"candidates": list(candidates), "kwargs": dict(kwargs)})
        captures: list[dict] = []
        for index, candidate in enumerate(candidates, start=1):
            snapshot_id = f"SNAP-DETAIL-{index:03d}" if self.detail_snapshot else ""
            attachment_snapshot_id = f"SNAP-ATT-{index:03d}"
            attachment_snapshot_refs = (
                [
                    {
                        "snapshot_id": attachment_snapshot_id,
                        "attachment_url": "https://example.test/tender.pdf",
                        "parse_state": "PARSED_PDF",
                        "attachment_role_type": "tender_file",
                    }
                ]
                if self.verified_attachment_refs
                else []
            )
            captures.append(
                {
                    "candidate_key": candidate["candidate_key"],
                    "project_id": candidate["project_id"],
                    "project_name": candidate["project_name"],
                    "source_url": candidate["source_url"],
                    "detail_snapshot_id_optional": snapshot_id,
                    "detail_automated_challenge_resolution_attempted": bool(self.detail_challenge_state),
                    "detail_automated_challenge_resolution_state": self.detail_challenge_state,
                    "detail_challenge_resume_audit": {
                        "challenge_resume_context_id": "detail-context"
                    }
                    if self.detail_challenge_state
                    else {},
                    "stage3_parse_state": self.parse_state,
                    "document_completeness_state": self.document_state,
                    "notice_version_chain_state": self.version_state,
                    "document_completeness_summary": {
                        "document_completeness_state": self.document_state,
                        "notice_version_chain_state": self.version_state,
                        "attachment_ocr_required_count": self.attachment_ocr_required_count,
                    },
                    "detail_fields": {
                        "detail_text_probe": "资格条件：厂家授权。本项目采用综合评分法，技术参数详见招标文件。",
                        "attachment_text_probes": [
                            {
                                "project_id": candidate["project_id"],
                                "snapshot_id": attachment_snapshot_id,
                                "source_url": "https://example.test/tender.pdf",
                                "file_role": "attachment",
                                "parse_state": "PARSED_PDF",
                                "section_flags": {
                                    "qualification_section_found": True,
                                    "scoring_section_found": True,
                                    "technical_section_found": True,
                                    "section_analysis_state": "SECTION_COMPLETE",
                                },
                                "text_sha256": "sha",
                                "text_probe": "评标办法：综合评分。技术参数：须满足服务要求。",
                            }
                        ],
                        "file_parse_attributions": [
                            {
                                "project_id": candidate["project_id"],
                                "snapshot_id": snapshot_id,
                                "source_url": candidate["source_url"],
                                "file_role": "detail",
                                "parse_state": self.parse_state,
                                "section_flags": {
                                    "qualification_section_found": True,
                                    "scoring_section_found": False,
                                    "technical_section_found": False,
                                    "section_analysis_state": "SECTION_PARTIAL_QUALIFICATION_ONLY",
                                },
                                "text_sha256": "detail-sha",
                                "text_probe": "资格条件：厂家授权。",
                            }
                        ],
                        "attachment_ocr_required_count": self.attachment_ocr_required_count,
                        "attachment_ocr_extracted_count": 0,
                        "attachment_snapshot_refs": attachment_snapshot_refs,
                        "attachment_text_parse_states": [
                            f"{attachment_snapshot_id}:PDF:PARSED_PDF"
                        ]
                        if self.verified_attachment_refs
                        else [
                            f"{attachment_snapshot_id}:ATTACHMENT_SNAPSHOT_READBACK_MISSING:MISSING_MANIFEST"
                        ],
                        "qualification_text_candidate_blocks": [
                            "资格条件：厂家授权、本地社保、CMA检测报告、主观分45分。"
                        ],
                    },
                    "download_archive_manifest": {
                        "manifest_quality_state": "REVIEW_REQUIRED" if self.download_quality_reasons else "READY",
                        "quality_reasons": list(self.download_quality_reasons),
                    },
                    "attachment_captures": [
                        {
                            "attachment_snapshot_id_optional": attachment_snapshot_id,
                            "attachment_url": "https://example.test/tender.pdf",
                            "parse_state": "PARSED_PDF",
                            "attachment_role_type": "tender_file",
                            "automated_challenge_resolution_attempted": bool(self.attachment_challenge_state),
                            "automated_challenge_resolution_state": self.attachment_challenge_state,
                        }
                    ],
                }
            )
        return {
            "detail_snapshot_count": len(captures) if self.detail_snapshot else 0,
            "detail_capture_failed_count": 0 if self.detail_snapshot else len(captures),
            "stage3_parse_success_count": len(captures) if self.parse_state.startswith("PARSED") else 0,
            "stage3_parse_failed_count": 0 if self.parse_state.startswith("PARSED") else len(captures),
            "attachment_snapshot_count": len(captures) if self.verified_attachment_refs else 0,
            "captures": captures,
        }


class TestEvaluationRealSampleExecution(unittest.TestCase):
    def test_default_real_sample_targets_keep_guangdong_on_guangzhou_source_only(self) -> None:
        payload = json.loads((ROOT / "contracts" / "evaluation" / "evaluation_real_project_sample_targets.json").read_text(encoding="utf-8"))
        gd_targets = [item for item in payload["targets"] if item["jurisdiction"] == "CN-GD"]

        self.assertTrue(gd_targets)
        self.assertEqual(
            {item.get("required_fetch_profile_id_optional") for item in gd_targets},
            {"GUANGZHOU-YWTB-CONSTRUCTION-LIST"},
        )
        self.assertEqual({item.get("entry_seed_id") for item in gd_targets}, {"ENTRY-GUANGZHOU-YWTB"})

    def test_professional_source_only_mode_keeps_guangdong_zhejiang_sichuan_primary_sources(self) -> None:
        result = build_evaluation_real_sample_execution(
            targets_json=ROOT / "contracts" / "evaluation" / "evaluation_real_project_sample_targets.json",
            seed_json=ROOT / "contracts" / "evaluation" / "evaluation_corpus_seed.json",
            target_backend="json-file",
            execute=False,
            professional_source_only=True,
        )

        manifest = result["manifest"]
        profile_ids = {item["source_profile_id"] for item in manifest["items"]}
        self.assertEqual(
            profile_ids,
            {
                "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                "ZHEJIANG-GGZY-JYXXGK-LIST",
                "SICHUAN-GGZY-TRANSACTION-INFO",
            },
        )
        self.assertEqual(
            manifest["source_quality_policy"]["source_quality_state_counts"],
            {"PRIMARY_FRIENDLY": len(manifest["items"])},
        )

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
                target_limit=1,
                discovery_service=discovery,
                capture_service=capture,
            )

            self.assertEqual(result["real_sample_execution_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(discovery.calls, [])
            self.assertEqual(capture.calls, [])
            item = result["manifest"]["items"][0]
            self.assertEqual(item["target_execution_state"], EXECUTION_READY)
            self.assertEqual(item["source_quality_state"], "PRIMARY_FRIENDLY")
            self.assertEqual(item["source_calibration_role"], "PRIMARY_CALIBRATION_SOURCE")
            self.assertTrue(item["professional_source_priority"])
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
                target_limit=1,
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

    def test_execute_does_not_promote_unverified_attachment_snapshot_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                created_at="2026-05-01T00:00:00+00:00",
                target_limit=1,
                discovery_service=FakeDiscoveryService(),
                capture_service=FakeCaptureService(verified_attachment_refs=False),
            )

            item = result["manifest"]["items"][0]
            sample = result["manifest"]["project_sample_items"][0]
            quality = result["manifest"]["coverage_quality_summary"]

            self.assertEqual(item["attachment_snapshot_refs"], [])
            self.assertEqual(sample["attachment_snapshot_refs"], [])
            self.assertEqual(quality["attachment_snapshot_count"], 0)
            self.assertIn(
                "attachment_snapshot_readback_missing",
                quality["failure_taxonomy_counts"],
            )
            self.assertIn("attachment_manifest_missing", quality["failure_taxonomy_counts"])

    def test_execute_preserves_detail_and_attachment_challenge_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                created_at="2026-05-01T00:00:00+00:00",
                target_limit=1,
                discovery_service=FakeDiscoveryService(),
                capture_service=FakeCaptureService(
                    detail_challenge_state="RESOLVED_AND_SNAPSHOT_CAPTURED",
                    attachment_challenge_state="FAILED_CLOSED_RESOLVER_ERROR",
                ),
            )

            sample = result["manifest"]["project_sample_items"][0]
            diagnostics = sample["challenge_diagnostics"]
            self.assertEqual([item["capture_kind"] for item in diagnostics], ["detail", "attachment"])
            self.assertEqual(diagnostics[0]["state"], "RESOLVED_AND_SNAPSHOT_CAPTURED")
            self.assertEqual(diagnostics[1]["state"], "FAILED_CLOSED_RESOLVER_ERROR")
            quality = result["manifest"]["coverage_quality_summary"]
            self.assertIn(
                "detail_automated_challenge_resolution_state:RESOLVED_AND_SNAPSHOT_CAPTURED",
                quality["failure_taxonomy_counts"],
            )
            self.assertIn(
                "attachment_automated_challenge_resolution_state:FAILED_CLOSED_RESOLVER_ERROR",
                quality["failure_taxonomy_counts"],
            )

    def test_execute_splits_project_sample_items_per_candidate_without_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)
            discovery = FakeDiscoveryService(
                candidates=[
                    _fake_candidate(candidate_key="CAND-001", project_id="PROJ-001"),
                    _fake_candidate(candidate_key="CAND-002", project_id="PROJ-002"),
                    _fake_candidate(candidate_key="CAND-003", project_id="PROJ-003"),
                ]
            )

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                target_ids="READY-CAND",
                per_target_candidate_limit=3,
                discovery_service=discovery,
                capture_service=FakeCaptureService(),
            )

            manifest = result["manifest"]
            self.assertEqual(len(manifest["items"]), 1)
            self.assertEqual(len(manifest["project_sample_items"]), 3)
            self.assertEqual(len(manifest["items"][0]["project_sample_items"]), 3)
            self.assertEqual(manifest["summary"]["project_sample_count"], 3)
            self.assertEqual(manifest["coverage_quality_summary"]["captured_project_sample_count"], 3)
            sample = manifest["project_sample_items"][1]
            self.assertEqual(sample["parent_target_id"], "READY-CAND")
            self.assertEqual(sample["candidate_key"], "CAND-002")
            self.assertEqual(sample["source_trading_process"], "03")
            self.assertEqual(sample["source_dataset_name"], "中标候选人公示")
            self.assertEqual(sample["source_query_process_label"], "candidate_publicity")
            self.assertEqual(sample["detail_snapshot_refs"][0]["snapshot_id"], "SNAP-DETAIL-002")
            self.assertIn("资格条件", sample["parse_summary"]["detail_text_probe"])
            self.assertTrue(sample["parse_summary"]["attachment_text_probes"])
            self.assertTrue(sample["parse_summary"]["file_parse_attributions"])
            self.assertIn("厂家授权", sample["source_text"])
            self.assertIn("技术参数", sample["source_text"])
            manifest_text = json.dumps(manifest, ensure_ascii=False).lower()
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
                target_limit=1,
                discovery_service=FakeDiscoveryService(candidates=[]),
                capture_service=FakeCaptureService(),
            )
            self.assertEqual(no_match["manifest"]["items"][0]["target_execution_state"], DISCOVERY_NO_MATCH_REVIEW)

            failed_closed = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                target_limit=1,
                discovery_service=FakeDiscoveryService(candidates=[], profile_status="SOURCE_PROFILE_NOT_CONFIGURED"),
                capture_service=FakeCaptureService(),
            )
            self.assertEqual(failed_closed["manifest"]["items"][0]["target_execution_state"], DISCOVERY_FAILED_CLOSED)

            partial = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                target_limit=1,
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

    def test_target_ids_filter_before_target_limit_and_reports_missing_requested_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=False,
                target_ids=["READY-AWARD", "MISSING-TARGET"],
                target_limit=1,
            )

            manifest = result["manifest"]
            self.assertEqual([item["target_id"] for item in manifest["items"]], ["READY-AWARD"])
            self.assertEqual(manifest["requested_target_ids"], ["READY-AWARD", "MISSING-TARGET"])
            self.assertEqual(manifest["selected_target_ids"], ["READY-AWARD"])
            self.assertEqual(manifest["missing_requested_target_ids"], ["MISSING-TARGET"])
            self.assertEqual(manifest["items"][0]["target_execution_state"], EXECUTION_READY)

    def test_fake_execute_carries_document_quality_fields_for_file_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            _write_targets(targets_path)
            _write_seed(seed_path)

            result = build_evaluation_real_sample_execution(
                targets_json=targets_path,
                seed_json=seed_path,
                target_backend="json-file",
                execute=True,
                target_ids="READY-CAND",
                discovery_service=FakeDiscoveryService(),
                capture_service=FakeCaptureService(
                    document_state="ATTACHMENTS_NOT_CAPTURED_REVIEW",
                    version_state="CLARIFICATION_OR_ADDENDUM_PRESENT",
                    attachment_ocr_required_count=1,
                    download_quality_reasons=["unknown_attachment_format"],
                ),
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(
                item["parse_summary"]["document_completeness_state_counts"],
                {"ATTACHMENTS_NOT_CAPTURED_REVIEW": 1},
            )
            self.assertEqual(
                item["parse_summary"]["notice_version_chain_state_counts"],
                {"CLARIFICATION_OR_ADDENDUM_PRESENT": 1},
            )
            self.assertEqual(item["parse_summary"]["attachment_ocr_required_count"], 1)
            self.assertEqual(item["parse_summary"]["attachment_missing_review_count"], 1)
            self.assertEqual(item["parse_summary"]["clarification_version_review_count"], 1)
            self.assertEqual(item["parse_summary"]["unknown_attachment_count"], 1)


def _fake_candidate(
    *,
    candidate_key: str = "CAND-001",
    project_id: str = "PROJ-001",
    project_name: str = "广州某排水工程中标候选人公示",
    source_trading_process: str = "03",
    source_dataset_name: str = "中标候选人公示",
    source_query_process_label: str = "candidate_publicity",
) -> dict:
    return {
        "candidate_key": candidate_key,
        "notice_id": "NOTICE-001",
        "project_id": project_id,
        "project_name": project_name,
        "source_url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260501/gz-candidate.html",
        "source_profile_id": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
        "source_trading_process": source_trading_process,
        "source_dataset_name": source_dataset_name,
        "source_query_process_label": source_query_process_label,
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
                        "target_count": 3,
                        "selection_filters": ["中标候选人公示"],
                    },
                    {
                        "target_id": "READY-AWARD",
                        "jurisdiction": "CN-GD",
                        "platform_name": "广州交易集团",
                        "entry_seed_id": "ENTRY-GZ",
                        "required_fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                        "source_family": "local_public_resource_trading_center",
                        "project_type": "construction",
                        "document_kind": "award_result",
                        "target_count": 1,
                        "selection_filters": ["中标结果公告"],
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
