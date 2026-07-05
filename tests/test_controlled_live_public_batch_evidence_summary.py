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
from runtime.controlled_gray_public_source_targets import (  # noqa: E402
    build_controlled_gray_public_source_targets,
)
from runtime.controlled_gray_public_batch_segments import (  # noqa: E402
    build_controlled_gray_public_batch_segment_aggregate,
    build_controlled_gray_public_batch_segments,
)
from runtime.controlled_live_public_batch_gray_launch_review import (  # noqa: E402
    build_controlled_live_public_batch_gray_launch_review,
)
from runtime.controlled_live_public_batch_stage4_readback import (  # noqa: E402
    build_controlled_live_public_batch_stage4_readback,
)
from runtime.controlled_live_public_batch_source_remediation import (  # noqa: E402
    build_controlled_live_public_batch_source_remediation,
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

    def test_source_remediation_builds_queue_for_partial_public_source_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            execution_json = root / "real-sample-execution.json"
            storage_json = root / "storage.json"
            evidence_out = root / "evidence"
            stage4_out = root / "stage4"
            remediation_out = root / "source-remediation"
            _write_source_blocker_execution(execution_json)
            _write_storage(storage_json)
            build_controlled_live_public_batch_evidence_summary(
                real_sample_execution_json=execution_json,
                storage_json=storage_json,
                output_root=evidence_out,
                created_at="2026-07-03T00:00:00+00:00",
            )
            build_controlled_live_public_batch_stage4_readback(
                evidence_summary_json=evidence_out / "controlled-live-public-batch-evidence-summary-v1.json",
                real_sample_execution_json=execution_json,
                storage_json=storage_json,
                output_root=stage4_out,
                created_at="2026-07-03T00:00:00+00:00",
            )

            result = build_controlled_live_public_batch_source_remediation(
                evidence_summary_json=evidence_out / "controlled-live-public-batch-evidence-summary-v1.json",
                real_sample_execution_json=execution_json,
                stage4_readback_json=stage4_out / "controlled-live-public-batch-stage4-readback-v1.json",
                output_root=remediation_out,
                created_at="2026-07-03T00:00:00+00:00",
            )
            markdown_text = (
                remediation_out / "controlled-live-public-batch-source-remediation-v1.md"
            ).read_text(encoding="utf-8")

        summary = result["summary"]
        self.assertEqual(summary["source_remediation_record_count"], 1)
        self.assertEqual(summary["source_remediation_group_count"], 1)
        self.assertEqual(summary["source_remediation_ready_count"], 1)
        self.assertEqual(summary["source_remediation_closeout_state"], "SOURCE_REMEDIATION_QUEUE_READY")
        self.assertEqual(summary["next_required_step"], "execute_source_remediation_queue")
        record = result["source_remediation_queue"]["records"][0]
        self.assertEqual(record["blocker_class"], "DETAIL_TRANSPORT_RETRY_EXHAUSTED")
        self.assertEqual(record["source_remediation_state"], "SOURCE_REMEDIATION_QUEUE_READY")
        self.assertTrue(record["same_source_retry_allowed"])
        self.assertTrue(record["alternate_source_required"])
        self.assertEqual(record["alternate_public_source_route"]["alternate_source_profile_ids"], ["GGZY-DEAL-LIST"])
        self.assertFalse(record["customer_visible_allowed"])
        self.assertIn("Source Remediation", markdown_text)

    def test_controlled_gray_targets_expand_only_primary_friendly_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_targets_json = root / "targets.json"
            out = root / "gray-targets"
            _write_json(
                source_targets_json,
                {
                    "target_version": 1,
                    "target_set_id": "test-targets",
                    "targets": [
                        {
                            "target_id": "REAL-GD-CANDIDATE-001",
                            "jurisdiction": "CN-GD",
                            "platform_name": "广州交易集团",
                            "entry_seed_id": "ENTRY-GUANGZHOU-YWTB",
                            "required_fetch_profile_id_optional": "GUANGZHOU-YWTB-CONSTRUCTION-LIST",
                            "source_family": "local_public_resource_trading_center",
                            "project_type": "construction",
                            "document_kind": "candidate_notice",
                            "target_count": 4,
                            "selection_filters": ["工程建设", "中标候选人公示"],
                        },
                        {
                            "target_id": "REAL-HB-CANDIDATE-001",
                            "jurisdiction": "CN-HB",
                            "platform_name": "湖北公共资源",
                            "entry_seed_id": "ENTRY-HUBEI-BIDCLOUD",
                            "required_fetch_profile_id_optional": "HUBEI-BIDCLOUD-JYXX-LIST",
                            "source_family": "local_public_resource_trading_center",
                            "project_type": "construction",
                            "document_kind": "candidate_notice",
                            "target_count": 4,
                            "selection_filters": ["工程建设", "评标结果公示"],
                        },
                    ],
                },
            )

            result = build_controlled_gray_public_source_targets(
                source_targets_json=source_targets_json,
                output_root=out,
                per_target_sample_goal=12,
                created_at="2026-07-05T00:00:00+00:00",
            )
            derived = json.loads(
                (out / "controlled-gray-public-source-targets-v1.json").read_text(encoding="utf-8")
            )

        summary = result["summary"]
        self.assertEqual(summary["derived_target_count"], 1)
        self.assertEqual(summary["minimum_total_sample_goal"], 12)
        self.assertEqual(summary["source_profile_counts"], {"GUANGZHOU-YWTB-CONSTRUCTION-LIST": 1})
        target = derived["targets"][0]
        self.assertEqual(target["target_id"], "REAL-GD-CANDIDATE-001")
        self.assertEqual(target["target_count"], 12)
        self.assertIn("CONTROLLED_GRAY_SAMPLE_EXPANSION", target["selection_filters"])
        self.assertIn("GRAY_SAMPLE_TARGET_COUNT:12", target["selection_filters"])
        self.assertFalse(result["safety"]["customer_visible_allowed"])
        self.assertTrue(result["safety"]["query_miss_is_not_clearance"])

    def test_controlled_gray_segment_plan_groups_targets_by_source_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_json = root / "targets.json"
            out = root / "segments"
            _write_json(
                targets_json,
                {
                    "target_set_id": "controlled-gray-test-targets",
                    "targets": [
                        _gray_target("REAL-GD-TENDER-001", "CN-GD", "GUANGZHOU-YWTB-CONSTRUCTION-LIST", "tender_file", 12),
                        _gray_target("REAL-GD-AWARD-001", "CN-GD", "GUANGZHOU-YWTB-CONSTRUCTION-LIST", "award_result", 12),
                        _gray_target("REAL-ZJ-CANDIDATE-001", "CN-ZJ", "ZHEJIANG-GGZY-JYXXGK-LIST", "candidate_notice", 12),
                    ],
                },
            )

            result = build_controlled_gray_public_batch_segments(
                targets_json=targets_json,
                output_root=out,
                run_root_base=root / "runs",
                per_target_candidate_limit=12,
                target_limit=0,
                professional_source_only=True,
                execute=True,
                auto_execute_source_remediation=True,
                created_at="2026-07-05T00:00:00+00:00",
            )

        summary = result["summary"]
        records = result["segment_table"]["records"]
        self.assertEqual(summary["segment_count"], 2)
        self.assertEqual(summary["target_count"], 3)
        self.assertEqual(summary["minimum_total_sample_goal"], 36)
        self.assertEqual(records[0]["target_count"], 2)
        self.assertIn("run-controlled-live-public-batch-v1.ps1", records[0]["recommended_command"])
        self.assertIn("-TargetIds", records[0]["recommended_command"])
        self.assertIn("REAL-GD-TENDER-001,REAL-GD-AWARD-001", records[0]["recommended_command"])
        self.assertIn("REAL-GD-TENDER-001", records[0]["recommended_command"])
        self.assertIn("build-controlled-gray-public-batch-segment-aggregate-v1.ps1", result["aggregate_command"])
        self.assertIn("-SegmentRoots", result["aggregate_command"])
        segment_roots_arg = result["aggregate_command"].split("-SegmentRoots", 1)[1].split(" -OutputRoot", 1)[0]
        self.assertIn(",", segment_roots_arg)
        self.assertFalse(result["safety"]["customer_visible_allowed"])

    def test_controlled_gray_segment_plan_can_split_by_target_for_retry_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_json = root / "targets.json"
            out = root / "segments"
            _write_json(
                targets_json,
                {
                    "target_set_id": "controlled-gray-test-targets",
                    "targets": [
                        _gray_target("REAL-GD-TENDER-001", "CN-GD", "GUANGZHOU-YWTB-CONSTRUCTION-LIST", "tender_file", 12),
                        _gray_target("REAL-GD-AWARD-001", "CN-GD", "GUANGZHOU-YWTB-CONSTRUCTION-LIST", "award_result", 12),
                    ],
                },
            )

            result = build_controlled_gray_public_batch_segments(
                targets_json=targets_json,
                output_root=out,
                run_root_base=root / "runs",
                group_by="target",
                per_target_candidate_limit=12,
                target_limit=0,
                professional_source_only=True,
                execute=True,
                auto_execute_source_remediation=True,
                created_at="2026-07-05T00:00:00+00:00",
            )

        records = result["segment_table"]["records"]
        self.assertEqual(result["summary"]["group_by"], "target")
        self.assertEqual(result["summary"]["segment_count"], 2)
        self.assertEqual(records[0]["target_ids"], ["REAL-GD-AWARD-001"])
        self.assertEqual(records[1]["target_ids"], ["REAL-GD-TENDER-001"])

    def test_controlled_gray_segment_aggregate_combines_closeouts_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            segment_a = root / "seg-a"
            segment_b = root / "seg-b"
            out = root / "aggregate"
            _write_segment_closeout(segment_a, sample_count=60, fixed_count=60, readback_count=80)
            _write_segment_closeout(segment_b, sample_count=45, fixed_count=45, readback_count=54)

            result = build_controlled_gray_public_batch_segment_aggregate(
                segment_roots=[segment_a, segment_b],
                output_root=out,
                gray_sample_goal_min=100,
                gray_sample_goal_max=200,
                created_at="2026-07-05T00:00:00+00:00",
            )

        summary = result["summary"]
        self.assertEqual(summary["aggregate_gray_review_state"], "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW")
        self.assertTrue(summary["eligible_for_human_gray_launch_review"])
        self.assertEqual(summary["human_gray_launch_approval_state"], "WAITING_OPERATOR_APPROVAL")
        self.assertEqual(summary["completed_segment_count"], 2)
        self.assertEqual(summary["project_sample_count"], 105)
        self.assertEqual(summary["fixed_snapshot_sha256_count"], 105)
        self.assertEqual(summary["gray_sample_goal_state"], "MEETS_GRAY_SAMPLE_MINIMUM_GOAL")
        self.assertTrue(summary["stage4_all_required_readbacks_ready"])
        self.assertEqual(summary["source_remediation_final_record_count"], 0)
        self.assertTrue(summary["safety_boundary_closed"])
        self.assertFalse(result["safety"]["payment_execution_enabled"])

    def test_controlled_gray_segment_aggregate_accepts_comma_joined_segment_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            segment_a = root / "seg-a"
            segment_b = root / "seg-b"
            out = root / "aggregate"
            _write_segment_closeout(segment_a, sample_count=10, fixed_count=10, readback_count=10)
            _write_segment_closeout(segment_b, sample_count=11, fixed_count=11, readback_count=11)

            result = build_controlled_gray_public_batch_segment_aggregate(
                segment_roots=[f"{segment_a},{segment_b}"],
                output_root=out,
                created_at="2026-07-05T00:00:00+00:00",
            )

        summary = result["summary"]
        self.assertEqual(summary["segment_count"], 2)
        self.assertEqual(summary["completed_segment_count"], 2)
        self.assertEqual(summary["project_sample_count"], 21)

    def test_gray_launch_review_package_waits_for_operator_after_remediation_clears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            evidence_json = root / "evidence.json"
            stage4_json = root / "stage4.json"
            remediation_json = root / "remediation.json"
            remediation_execution_json = root / "remediation-execution.json"
            out = root / "gray-review"
            _write_json(
                evidence_json,
                {
                    "summary": {
                        "source_execute": True,
                        "project_sample_count": 28,
                        "fixed_snapshot_sha256_count": 38,
                        "public_source_outcome_counts": {
                            "PUBLIC_SOURCE_HIT_WITH_HASHED_SNAPSHOT": 27,
                            "PUBLIC_SOURCE_REVIEW_REQUIRED": 1,
                        },
                        "customer_visible_allowed": False,
                        "payment_execution_enabled": False,
                        "delivery_execution_enabled": False,
                        "query_miss_is_not_clearance": True,
                        "no_legal_conclusion": True,
                    }
                },
            )
            _write_json(
                stage4_json,
                {
                    "summary": {
                        "stage4_all_required_readbacks_ready": True,
                        "stage4_readback_required_sample_count": 27,
                        "stage4_readback_ready_sample_count": 27,
                        "stage4_readback_missing_sample_count": 0,
                        "stage4_public_evidence_readback_count": 47,
                        "customer_visible_allowed": False,
                        "query_miss_is_not_clearance": True,
                        "no_legal_conclusion": True,
                    }
                },
            )
            _write_json(
                remediation_json,
                {
                    "summary": {
                        "source_remediation_record_count": 1,
                        "source_remediation_closeout_state": "SOURCE_REMEDIATION_QUEUE_READY",
                        "customer_visible_allowed": False,
                    }
                },
            )
            _write_json(
                remediation_execution_json,
                {
                    "summary": {
                        "source_remediation_execution_state": "SOURCE_REMEDIATION_RERUN_EXECUTED_WITH_SNAPSHOTS",
                        "post_run_source_remediation_record_count": 0,
                        "post_run_stage4_all_required_readbacks_ready": True,
                        "next_required_step": "human_gray_launch_review",
                        "customer_visible_allowed": False,
                        "payment_execution_enabled": False,
                        "delivery_execution_enabled": False,
                    }
                },
            )

            result = build_controlled_live_public_batch_gray_launch_review(
                evidence_summary_json=evidence_json,
                stage4_readback_json=stage4_json,
                source_remediation_json=remediation_json,
                source_remediation_execution_json=remediation_execution_json,
                output_root=out,
                created_at="2026-07-03T00:00:00+00:00",
            )
            markdown_text = (
                out / "controlled-live-public-batch-gray-launch-review-v1.md"
            ).read_text(encoding="utf-8")
            approved_result = build_controlled_live_public_batch_gray_launch_review(
                evidence_summary_json=evidence_json,
                stage4_readback_json=stage4_json,
                source_remediation_json=remediation_json,
                source_remediation_execution_json=remediation_execution_json,
                output_root=root / "gray-review-approved",
                operator_decision="APPROVED",
                operator_name="chat-user",
                operator_decision_note="continue controlled gray public-source execution",
                created_at="2026-07-03T00:00:00+00:00",
            )

        summary = result["summary"]
        self.assertEqual(summary["gray_launch_review_state"], "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW")
        self.assertTrue(summary["eligible_for_human_gray_launch_review"])
        self.assertEqual(summary["human_gray_launch_approval_state"], "WAITING_OPERATOR_APPROVAL")
        self.assertFalse(summary["approved_for_controlled_gray_execution"])
        self.assertEqual(summary["gray_sample_goal_state"], "CATALOG_LIMITED_BELOW_GRAY_SAMPLE_GOAL")
        self.assertFalse(summary["gray_sample_goal_met"])
        self.assertEqual(summary["source_remediation_final_record_count"], 0)
        self.assertFalse(summary["customer_visible_allowed"])
        self.assertEqual(result["gray_run_plan"]["plan_state"], "READY_AFTER_OPERATOR_APPROVAL")
        checklist = {record["check_id"]: record for record in result["gray_launch_checklist"]["records"]}
        self.assertEqual(checklist["gray_sample_goal_observed"]["state"], "WARN")
        self.assertEqual(checklist["operator_gray_launch_approval"]["state"], "WAITING_OPERATOR_APPROVAL")
        self.assertIn("Gray Run Plan", markdown_text)
        approved_summary = approved_result["summary"]
        self.assertEqual(approved_summary["human_gray_launch_approval_state"], "APPROVED")
        self.assertTrue(approved_summary["approved_for_controlled_gray_execution"])
        self.assertEqual(
            approved_result["gray_run_plan"]["plan_state"],
            "APPROVED_FOR_CONTROLLED_GRAY_EXECUTION",
        )
        self.assertIn("build-controlled-gray-public-source-targets-v1.ps1", approved_result["gray_run_plan"]["recommended_command"])
        self.assertIn("run-controlled-gray-public-batch-segments-v1.ps1", approved_result["gray_run_plan"]["recommended_command"])
        self.assertIn("-GroupBy target", approved_result["gray_run_plan"]["recommended_command"])
        self.assertIn("-PerTargetCandidateLimit 12", approved_result["gray_run_plan"]["recommended_command"])
        self.assertTrue(approved_result["operator_decision_record"]["decision_record_sha256"])

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
        self.assertIn("TargetsJson", script)
        self.assertIn("SeedJson", script)
        self.assertIn("-UseAllTargets", script)
        self.assertIn("build-controlled-live-public-batch-evidence-summary-v1.ps1", script)
        self.assertIn("build-controlled-live-public-batch-stage4-readback-v1.ps1", script)
        self.assertIn("build-controlled-live-public-batch-source-remediation-v1.ps1", script)
        self.assertIn("AutoExecuteSourceRemediation", script)
        self.assertIn("EnableAlternatePublicSource", script)
        self.assertIn("run-controlled-live-public-batch-source-remediation-v1.ps1", script)
        self.assertIn("build-controlled-live-public-batch-gray-launch-review-v1.ps1", script)
        self.assertIn("build-professional-clean-project-archive.ps1", script)
        self.assertIn("controlled-live-public-batch-evidence-summary-v1.json", script)
        self.assertIn("controlled-live-public-batch-stage4-readback-v1.json", script)
        self.assertIn("controlled-live-public-batch-source-remediation-v1.json", script)
        self.assertIn("controlled-live-public-batch-gray-launch-review-v1.json", script)
        self.assertIn("project-file-audit.json", script)
        self.assertIn("controlled-live-public-batch-closeout.json", script)
        self.assertIn("NOT_READY_REAL_PUBLIC_EXECUTION_REQUIRED", script)
        self.assertIn("NOT_READY_STAGE4_EVIDENCE_READBACK_REQUIRED", script)
        self.assertIn("NOT_READY_SOURCE_REMEDIATION_QUEUE_READY", script)
        self.assertIn("$stage4RequiredCount -gt 0 -and -not $stage4AllRequiredReadbacksReady", script)
        self.assertIn("stage4_all_required_readbacks_ready", script)
        self.assertIn("source_remediation_closeout_state", script)
        self.assertIn("source_remediation_execution_state", script)
        self.assertIn('$runArgs += ($TargetIds -join ",")', script)
        self.assertIn("customer_visible_allowed = $false", script)
        self.assertIn("payment_execution_enabled = $false", script)
        self.assertIn("delivery_execution_enabled = $false", script)

    def test_controlled_gray_segment_runner_wires_plan_segment_runs_and_aggregate(self) -> None:
        script = (ROOT / "scripts" / "run-controlled-gray-public-batch-segments-v1.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("build-controlled-gray-public-batch-segments-v1.ps1", script)
        self.assertIn("run-controlled-live-public-batch-v1.ps1", script)
        self.assertIn("build-controlled-gray-public-batch-segment-aggregate-v1.ps1", script)
        self.assertIn("controlled-gray-public-batch-segment-aggregate-v1.json", script)
        self.assertIn("SegmentTimeoutSeconds", script)
        self.assertIn("Start-Process", script)
        self.assertIn("Stop-ControlledSegmentProcesses", script)
        self.assertIn("already complete; skipping", script)


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


def _gray_target(
    target_id: str,
    jurisdiction: str,
    source_profile_id: str,
    document_kind: str,
    target_count: int,
) -> dict:
    return {
        "target_id": target_id,
        "jurisdiction": jurisdiction,
        "platform_name": "公开平台",
        "entry_seed_id": "ENTRY-PUBLIC",
        "required_fetch_profile_id_optional": source_profile_id,
        "source_family": "local_public_resource_trading_center",
        "project_type": "construction",
        "document_kind": document_kind,
        "target_count": target_count,
        "selection_filters": ["工程建设"],
    }


def _write_segment_closeout(
    root: Path,
    *,
    sample_count: int,
    fixed_count: int,
    readback_count: int,
) -> None:
    _write_json(
        root / "controlled-live-public-batch-closeout.json",
        {
            "manifest_kind": "controlled_live_public_batch_closeout_v1",
            "run_root": str(root),
            "execute": True,
            "sample_count": sample_count,
            "fixed_snapshot_sha256_count": fixed_count,
            "stage4_evidence_readback_required_count": sample_count,
            "stage4_readback_ready_sample_count": sample_count,
            "stage4_readback_missing_sample_count": 0,
            "stage4_public_evidence_readback_count": readback_count,
            "stage4_all_required_readbacks_ready": True,
            "source_remediation_record_count": 0,
            "source_remediation_group_count": 0,
            "source_remediation_ready_count": 0,
            "alternate_public_source_required_count": 0,
            "source_remediation_closeout_state": "NO_SOURCE_REMEDIATION_REQUIRED",
            "source_remediation_execution_state": "",
            "post_run_source_remediation_record_count": 0,
            "post_run_stage4_all_required_readbacks_ready": False,
            "partial_or_blocked_count": 0,
            "no_match_count": 0,
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "gray_launch_decision": "ELIGIBLE_FOR_GRAY_LAUNCH_REVIEW",
            "next_required_step": "human_gray_launch_review",
        },
    )
    _write_json(
        root / "gray-launch-review" / "controlled-live-public-batch-gray-launch-review-v1.json",
        {
            "summary": {
                "gray_launch_review_state": "READY_FOR_HUMAN_GRAY_LAUNCH_REVIEW",
                "project_sample_count": sample_count,
                "fixed_snapshot_sha256_count": fixed_count,
                "stage4_all_required_readbacks_ready": True,
                "source_remediation_final_record_count": 0,
            }
        },
    )


def _write_source_blocker_execution(path: Path) -> None:
    blocker_sample = {
        "sample_id": "SAMPLE-SD-BLOCKED",
        "parent_target_id": "REAL-SD-TENDER-001",
        "target_id": "REAL-SD-TENDER-001::blocked",
        "project_id": "PROJ-SD-BLOCKED",
        "project_name": "山东详情页阻断项目",
        "project_match_key": "山东详情页阻断项目",
        "document_kind": "tender_file",
        "jurisdiction": "CN-SD",
        "source_profile_id": "SHANDONG-GGZY-JYXXGK-LIST",
        "source_url": "http://ggzyjy.shandong.gov.cn:80/jsgczbgg/14442079.jhtml",
        "target_execution_state": "CAPTURE_PARTIAL_REVIEW",
        "detail_capture_status": "DEGRADED",
        "stage3_parse_state": "NOT_RUN",
        "document_completeness_state": "DETAIL_SNAPSHOT_MISSING_REVIEW",
        "detail_snapshot_refs": [],
        "attachment_snapshot_refs": [],
        "detail_url_retry_audit": {
            "attempts": [
                {
                    "detail_url": "https://ggzyjy.shandong.gov.cn/jsgczbgg/14442079.jhtml",
                    "status": "DEGRADED",
                    "http_status": None,
                    "degraded_reasons": ["fetch_failed"],
                },
                {
                    "detail_url": "http://ggzyjy.shandong.gov.cn/jsgczbgg/14442079.jhtml",
                    "status": "DEGRADED",
                    "http_status": 502,
                    "degraded_reasons": ["http_status:502", "detail_body_too_small", "detail_title_missing"],
                },
            ],
            "variant_strategy": "shandong_https_without_explicit_80_first",
        },
        "parse_summary": {
            "document_quality_reasons": ["detail_snapshot_missing", "capture_failure_or_blocker_present"],
            "attachment_missing_review_count": 1,
        },
        "failure_taxonomy": [
            "detail_url_retry_strategy:shandong_https_without_explicit_80_first",
            "shandong_detail_url_variant_exhausted",
            "detail_capture_failure:http_status:502:2",
            "detail_capture_failure:detail_body_too_small:2",
            "detail_capture_failure:detail_title_missing:2",
        ],
    }
    _write_json(
        path,
        {
            "manifest": {
                "execution_mode": "EXECUTED",
                "execute": True,
                "items": [
                    {
                        "target_id": "REAL-SD-TENDER-001",
                        "jurisdiction": "CN-SD",
                        "platform_name": "山东省公共资源交易网",
                        "document_kind": "tender_file",
                        "source_profile_id": "SHANDONG-GGZY-JYXXGK-LIST",
                        "target_execution_state": "CAPTURE_PARTIAL_REVIEW",
                        "discovery_candidate_count": 1,
                        "detail_snapshot_refs": [],
                        "attachment_snapshot_refs": [],
                        "failure_taxonomy": list(blocker_sample["failure_taxonomy"]),
                    }
                ],
                "project_sample_items": [blocker_sample],
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
