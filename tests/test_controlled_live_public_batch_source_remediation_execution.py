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

from runtime.controlled_live_public_batch_source_remediation_execution import (  # noqa: E402
    build_controlled_live_public_batch_source_remediation_execution,
)


class FakeDiscoveryService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def discover(self, payload: dict, *, now: str | None = None) -> dict:
        self.calls.append(dict(payload))
        profile_id = (payload.get("source_profile_ids") or [""])[0]
        return {
            "discovery_state": "COMPLETED",
            "candidate_count": 1,
            "candidates": [
                {
                    "candidate_key": "CAND-001",
                    "notice_id": "NOTICE-001",
                    "project_id": "PROJ-001",
                    "project_name": "Remediation Project Candidate Notice",
                    "source_url": "https://example.test/remediation-candidate.html",
                    "source_profile_id": profile_id,
                    "source_project_code": "JG2026-TEST",
                    "source_record_id": "JG2026-TEST",
                    "project_match_key": "JG2026-TEST",
                    "matched_project_keys": ["JG2026-TEST"],
                    "notice_stage": "candidate_notice",
                }
            ],
            "profile_reports": [
                {
                    "region_code": "CN-GD",
                    "profile_id": profile_id,
                    "entry_url": "https://example.test/list",
                    "status": "FETCHED",
                    "candidate_count": 1,
                }
            ],
        }


class FakeCaptureService:
    def __init__(self, *, snapshot_profiles: set[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.snapshot_profiles = snapshot_profiles

    def capture_candidates(self, candidates: list[dict], **kwargs: object) -> dict:
        self.calls.append({"candidates": list(candidates), "kwargs": dict(kwargs)})
        candidate = candidates[0]
        source_profile_id = str(candidate.get("source_profile_id") or "")
        detail_snapshot = self.snapshot_profiles is None or source_profile_id in self.snapshot_profiles
        snapshot_id = "SNAP-DETAIL-001" if detail_snapshot else ""
        stage3_parse_state = "PARSED_HTML" if detail_snapshot else "NOT_RUN"
        document_state = "COMPLETE_WITH_DETAIL_ONLY" if detail_snapshot else "DETAIL_SNAPSHOT_MISSING_REVIEW"
        return {
            "detail_snapshot_count": 1 if detail_snapshot else 0,
            "detail_capture_failed_count": 0 if detail_snapshot else 1,
            "stage3_parse_success_count": 1 if detail_snapshot else 0,
            "stage3_parse_failed_count": 0,
            "attachment_snapshot_count": 0,
            "captures": [
                {
                    "candidate_key": candidate["candidate_key"],
                    "project_id": candidate["project_id"],
                    "project_name": candidate["project_name"],
                    "source_url": candidate["source_url"],
                    "source_profile_id": candidate["source_profile_id"],
                    "detail_snapshot_id_optional": snapshot_id,
                    "stage3_parse_state": stage3_parse_state,
                    "document_completeness_state": document_state,
                    "notice_version_chain_state": "NO_SUPPLEMENT_DETECTED",
                    "detail_fields": {
                        "detail_text_probe": "qualification text and public evidence fields",
                        "attachment_snapshot_refs": [],
                        "attachment_text_parse_states": [],
                        "qualification_text_candidate_blocks": ["qualification text"],
                    },
                    "download_archive_manifest": {
                        "manifest_quality_state": "READY",
                        "quality_reasons": [],
                    },
                    "attachment_captures": [],
                }
            ],
        }


class ControlledLivePublicBatchSourceRemediationExecutionTests(unittest.TestCase):
    def test_dry_run_plans_only_queued_blocked_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            remediation_json = root / "source-remediation.json"
            targets_json = root / "targets.json"
            seed_json = root / "seed.json"
            out = root / "out"
            _write_source_remediation(remediation_json, target_ids=["READY-CAND", "READY-CAND"])
            _write_targets(targets_json)
            _write_seed(seed_json)

            result = build_controlled_live_public_batch_source_remediation_execution(
                source_remediation_json=remediation_json,
                targets_json=targets_json,
                seed_json=seed_json,
                target_backend="json-file",
                output_root=out,
                execute=False,
            )

        summary = result["summary"]
        self.assertEqual(summary["source_remediation_execution_state"], "SOURCE_REMEDIATION_RERUN_PLANNED")
        self.assertEqual(summary["requested_target_ids"], ["READY-CAND"])
        self.assertEqual(summary["selected_target_ids"], ["READY-CAND"])
        self.assertEqual(summary["missing_requested_target_ids"], [])
        self.assertEqual(summary["rerun_target_execution_state_counts"], {"EXECUTION_READY": 1})
        self.assertFalse(result["safety"]["fetch_public_urls_enabled"])
        self.assertFalse(result["customer_visible_allowed"])

    def test_execute_reruns_queued_targets_through_real_sample_execution_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            remediation_json = root / "source-remediation.json"
            targets_json = root / "targets.json"
            seed_json = root / "seed.json"
            out = root / "out"
            discovery = FakeDiscoveryService()
            capture = FakeCaptureService()
            _write_source_remediation(remediation_json, target_ids=["READY-CAND"])
            _write_targets(targets_json)
            _write_seed(seed_json)

            result = build_controlled_live_public_batch_source_remediation_execution(
                source_remediation_json=remediation_json,
                targets_json=targets_json,
                seed_json=seed_json,
                target_backend="json-file",
                output_root=out,
                execute=True,
                discovery_service=discovery,
                capture_service=capture,
            )
            output_exists = (
                out / "controlled-live-public-batch-source-remediation-execution-v1.json"
            ).exists()
            rerun_manifest_exists = (
                out / "controlled-live-public-batch-source-remediation-rerun-manifest.json"
            ).exists()
            evidence_summary_exists = (
                out / "evidence-summary" / "controlled-live-public-batch-evidence-summary-v1.json"
            ).exists()
            stage4_readback_exists = (
                out / "stage4-readback" / "controlled-live-public-batch-stage4-readback-v1.json"
            ).exists()
            next_source_remediation_exists = (
                out / "source-remediation" / "controlled-live-public-batch-source-remediation-v1.json"
            ).exists()

        summary = result["summary"]
        self.assertEqual(discovery.calls[0]["source_profile_ids"], ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"])
        self.assertEqual(len(capture.calls), 1)
        self.assertEqual(summary["source_remediation_execution_state"], "SOURCE_REMEDIATION_RERUN_EXECUTED_WITH_SNAPSHOTS")
        self.assertEqual(summary["rerun_project_sample_count"], 1)
        self.assertEqual(summary["rerun_detail_snapshot_count"], 1)
        self.assertEqual(summary["post_run_evidence_generation_state"], "GENERATED")
        self.assertTrue(summary["post_run_evidence_summary_json"])
        self.assertTrue(summary["post_run_stage4_readback_json"])
        self.assertTrue(summary["post_run_source_remediation_json"])
        self.assertEqual(summary["next_required_step"], "continue_source_remediation_queue")
        self.assertTrue(result["safety"]["fetch_public_urls_enabled"])
        self.assertFalse(result["safety"]["stage5_rule_execution_enabled"])
        self.assertTrue(output_exists)
        self.assertTrue(rerun_manifest_exists)
        self.assertTrue(evidence_summary_exists)
        self.assertTrue(stage4_readback_exists)
        self.assertTrue(next_source_remediation_exists)

    def test_execute_can_continue_to_alternate_public_source_when_same_source_still_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            remediation_json = root / "source-remediation.json"
            targets_json = root / "targets.json"
            seed_json = root / "seed.json"
            out = root / "out"
            discovery = FakeDiscoveryService()
            capture = FakeCaptureService(snapshot_profiles={"GGZY-DEAL-LIST"})
            _write_source_remediation(remediation_json, target_ids=["READY-CAND"])
            _write_targets(targets_json)
            _write_seed(seed_json)

            result = build_controlled_live_public_batch_source_remediation_execution(
                source_remediation_json=remediation_json,
                targets_json=targets_json,
                seed_json=seed_json,
                target_backend="json-file",
                output_root=out,
                execute=True,
                enable_alternate_public_source=True,
                discovery_service=discovery,
                capture_service=capture,
            )
            alternate_targets_exists = (
                out / "alternate-public-source" / "alternate-public-source-targets.json"
            ).exists()
            alternate_targets_payload = json.loads(
                (out / "alternate-public-source" / "alternate-public-source-targets.json").read_text(
                    encoding="utf-8"
                )
            )
            alternate_manifest_exists = (
                out / "alternate-public-source" / "controlled-live-public-batch-alternate-source-rerun-manifest.json"
            ).exists()

        summary = result["summary"]
        self.assertEqual(len(discovery.calls), 2)
        self.assertEqual(discovery.calls[0]["source_profile_ids"], ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"])
        self.assertEqual(discovery.calls[1]["source_profile_ids"], ["GGZY-DEAL-LIST"])
        self.assertEqual(summary["source_remediation_execution_state"], "SOURCE_REMEDIATION_RERUN_EXECUTED_REVIEW_REQUIRED")
        self.assertEqual(summary["alternate_public_source_execution_state"], "ALTERNATE_PUBLIC_SOURCE_EXECUTED_WITH_SNAPSHOTS")
        self.assertEqual(summary["alternate_detail_snapshot_count"], 1)
        self.assertEqual(summary["next_required_step"], "review_alternate_public_source_evidence_before_gray_launch")
        self.assertTrue(alternate_targets_exists)
        self.assertTrue(alternate_manifest_exists)
        self.assertNotIn(
            "PROJ-",
            " ".join(alternate_targets_payload["targets"][0]["selection_filters"]),
        )

    def test_source_remediation_execution_script_invokes_runtime_runner(self) -> None:
        script = (ROOT / "scripts" / "run-controlled-live-public-batch-source-remediation-v1.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("runtime.controlled_live_public_batch_source_remediation_execution", script)
        self.assertIn("--source-remediation-json", script)
        self.assertIn("--per-target-candidate-limit", script)
        self.assertIn("--execute", script)
        self.assertIn("--enable-alternate-public-source", script)
        self.assertIn("KAKA_STAGE2_ENABLE_ATTACHMENT_CHALLENGE_RESOLVER", script)


def _write_source_remediation(path: Path, *, target_ids: list[str]) -> None:
    records = [
        {
            "remediation_record_id": f"SRCREM-{index}",
            "sample_id": f"SAMPLE-{index}",
            "parent_target_id": target_id,
            "minimum_rerun_target_ids": [target_id],
            "source_remediation_state": "SOURCE_REMEDIATION_QUEUE_READY",
            "blocker_class": "DETAIL_TRANSPORT_RETRY_EXHAUSTED",
            "jurisdiction": "CN-SD",
            "project_id": f"PROJ-{index}",
            "project_name": "山东备用公开源测试项目",
            "document_kind": "candidate_notice",
            "alternate_public_source_route": {
                "alternate_source_required": True,
                "alternate_source_profile_ids": ["GGZY-DEAL-LIST"],
                "alternate_query_terms": ["山东备用公开源测试项目"],
                "must_not_treat_no_match_as_clearance": True,
            },
            "customer_visible_allowed": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        }
        for index, target_id in enumerate(target_ids, start=1)
    ]
    path.write_text(
        json.dumps(
            {
                "manifest_kind": "controlled_live_public_batch_source_remediation_v1",
                "manifest_sha256": "source-remediation-sha",
                "source_remediation_queue": {"records": records},
                "source_remediation_groups": {
                    "records": [
                        {
                            "source_remediation_group_id": "SRCGRP-1",
                            "recommended_execution": {
                                "primary_action": "rerun_blocked_targets_same_source_with_backoff",
                                "blocked_parent_target_ids": target_ids,
                                "execute_customer_visible": False,
                                "execute_payment": False,
                                "execute_delivery": False,
                            },
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_targets(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "target_set_id": "source-remediation-execution-targets",
                "minimum_total_sample_goal": 1,
                "targets": [
                    {
                        "target_id": "READY-CAND",
                        "jurisdiction": "CN-GD",
                        "platform_name": "Guangzhou Trading Group",
                        "entry_seed_id": "ENTRY-GZ",
                        "required_fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                        "source_family": "local_public_resource_trading_center",
                        "project_type": "construction",
                        "document_kind": "candidate_notice",
                        "target_count": 1,
                        "selection_filters": ["candidate notice"],
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
                        "source_url": "https://example.test/list",
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
