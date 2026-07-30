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

from storage.stage5_real_project_rule_calibration import (  # noqa: E402
    build_stage5_real_project_rule_calibration,
)


CONTRACT = ROOT / "contracts" / "evaluation" / "stage5_rule_truth_label_contract.json"


class TestStage5RealProjectRuleCalibration(unittest.TestCase):
    def test_deduplicates_real_projects_and_withholds_unlabeled_truth_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            first = root / "run-a" / "run-manifest.json"
            second = root / "run-b" / "run-manifest.json"
            _write_run_manifest(first, [_sample(1), _sample(2)])
            _write_run_manifest(second, [_sample(1), _sample(3)])

            result = _build(root)

            summary = result["summary"]
            self.assertEqual(summary["unique_real_project_count"], 3)
            self.assertEqual(summary["raw_project_observation_count"], 4)
            self.assertEqual(
                summary["evaluation_state"],
                "BLOCKED_INSUFFICIENT_UNIQUE_REAL_PROJECTS",
            )
            self.assertEqual(summary["truth_label_required_count"], 3)
            self.assertIsNone(summary["current_truth_metrics"]["false_positive"])
            self.assertEqual(
                summary["current_truth_metrics"]["metrics_state"],
                "WITHHELD_NO_VALID_HUMAN_TRUTH_LABELS",
            )
            self.assertFalse(result["manifest"]["safety"]["ai_self_label_enabled"])

    def test_rerun_preserves_human_label_by_stable_sample_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_run_manifest(root / "run" / "run-manifest.json", [_sample(1)])
            first = _build(root)
            packet_path = root / "output" / "stage5-real-project-truth-label-packet.json"
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            packet["labels"][0].update(_human_label("PASS"))
            packet_path.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            second = _build(root)

            self.assertEqual(
                first["manifest"]["sample_results"][0]["sample_id"],
                second["manifest"]["sample_results"][0]["sample_id"],
            )
            row = second["manifest"]["sample_results"][0]
            self.assertEqual(row["truth_label"], "PASS")
            self.assertEqual(row["reviewer_id"], "human-reviewer-01")
            self.assertEqual(second["summary"]["truth_label_valid_count"], 1)

    def test_fifty_human_labeled_projects_report_before_after_fp_and_fn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            samples = []
            for index in range(50):
                if index % 3 == 0:
                    samples.append(_sample(index, tailored=True))
                elif index % 3 == 1:
                    samples.append(_sample(index, file_review=True))
                else:
                    samples.append(_sample(index))
            _write_run_manifest(root / "run" / "run-manifest.json", samples)
            _write_run_manifest(
                root / "dry-run" / "run-manifest.json",
                [_sample(999)],
                executed=False,
            )
            _build(root)
            packet_path = root / "output" / "stage5-real-project-truth-label-packet.json"
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            for row in packet["labels"]:
                project_index = int(row["project_ids"][0].rsplit("-", 1)[1])
                if project_index == 0:
                    truth = "PASS"  # current REVIEW => false positive
                elif project_index == 2:
                    truth = "REVIEW_REQUIRED"  # current PASS => false negative
                else:
                    truth = row["current_prediction"]
                row.update(_human_label(truth))
            packet_path.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = _build(root)

            summary = result["summary"]
            self.assertEqual(summary["unique_real_project_count"], 50)
            self.assertEqual(summary["accepted_execution_manifest_count"], 1)
            self.assertEqual(summary["skipped_manifest_count"], 1)
            self.assertTrue(summary["truth_labels_ready"])
            self.assertEqual(
                summary["evaluation_state"],
                "READY_FOR_HUMAN_THRESHOLD_DECISION",
            )
            self.assertGreater(summary["changed_prediction_count"], 0)
            self.assertEqual(summary["current_truth_metrics"]["false_positive"], 1)
            self.assertEqual(summary["current_truth_metrics"]["false_negative"], 1)
            self.assertEqual(
                summary["current_truth_metrics"]["metrics_state"],
                "CALCULATED_FROM_HUMAN_TRUTH_LABELS",
            )
            self.assertFalse(summary["automatic_threshold_mutation_enabled"])
            regression = json.loads(
                (root / "output" / "regression-error-samples.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(regression["summary"]["error_sample_count"], 2)


def _build(root: Path) -> dict:
    return build_stage5_real_project_rule_calibration(
        input_root=root,
        truth_label_contract_json=CONTRACT,
        output_root=root / "output",
        created_at="2026-07-20T00:00:00Z",
    )


def _write_run_manifest(
    path: Path,
    samples: list[dict],
    *,
    executed: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "real_sample_execution_mode": "EXECUTED" if executed else "DRY_RUN",
                "execute": executed,
                "execution": {"executed": executed},
                "manifest": {
                    "manifest_id": path.parent.name,
                    "created_at": "2026-07-01T00:00:00Z",
                    "project_sample_items": samples,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _sample(
    index: int,
    *,
    tailored: bool = False,
    file_review: bool = False,
) -> dict:
    state = "CAPTURE_PARTIAL_REVIEW" if file_review else "CAPTURED_WITH_SNAPSHOTS"
    document_state = (
        "ATTACHMENTS_NOT_CAPTURED_REVIEW"
        if file_review
        else "COMPLETE_WITH_ATTACHMENTS"
    )
    source_text = (
        "招标文件要求厂家授权、原厂唯一授权、本地社保、本地服务网点、"
        "CMA检测报告、技术参数精确到小数、主观分45分、现场踏勘回执。"
        if tailored
        else "本项目公开招标，符合资格的供应商均可参加，评分标准详见附件。"
    )
    return {
        "sample_id": f"OBS-{index:03d}",
        "target_id": f"TARGET-{index:03d}",
        "candidate_key": f"CAND-{index:03d}",
        "project_id": f"PROJ-{index}",
        "project_name": f"真实测试项目 {index}",
        "source_url": f"https://example.test/projects/{index}",
        "document_kind": "tender_file",
        "jurisdiction": "CN-GD",
        "source_profile_id": "TEST-PROFILE",
        "target_execution_state": state,
        "source_text": source_text,
        "detail_snapshot_refs": [
            {
                "snapshot_id": f"DETAIL-{index:03d}",
                "document_completeness_state": document_state,
                "notice_version_chain_state": "NO_SUPPLEMENT_DETECTED",
            }
        ],
        "attachment_snapshot_refs": [{"snapshot_id": f"ATT-{index:03d}"}],
        "parse_summary": {
            "document_completeness_state_counts": {document_state: 1},
            "notice_version_chain_state_counts": {"NO_SUPPLEMENT_DETECTED": 1},
            "ocr_required_count": 0,
            "attachment_ocr_required_count": 0,
            "attachment_missing_review_count": 0,
            "clarification_version_review_count": 0,
            "unknown_attachment_count": 0,
            "document_quality_reasons": [],
            "download_archive_quality_reasons": [],
        },
    }


def _human_label(truth: str) -> dict:
    return {
        "truth_label": truth,
        "truth_label_state": "HUMAN_REVIEWED",
        "reviewer_id": "human-reviewer-01",
        "reviewed_at": "2026-07-20T01:00:00Z",
        "truth_evidence_refs": ["review://fixture/evidence"],
        "review_note": "人工核对项目原文与规则输出后的测试金标。",
    }


if __name__ == "__main__":
    unittest.main()
