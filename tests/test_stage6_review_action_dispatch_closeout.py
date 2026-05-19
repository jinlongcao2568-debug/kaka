from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.stage6_review_action_dispatch_closeout import (  # noqa: E402
    build_stage6_review_action_dispatch_closeout,
)


class Stage6ReviewActionDispatchCloseoutTests(unittest.TestCase):
    def test_closes_out_dispatch_readback_into_project_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_readback(root / "readback")

            result = build_stage6_review_action_dispatch_closeout(
                dispatch_readback_root=root / "readback",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["dispatch_closeout_count"], 4)
            self.assertEqual(summary["ready_to_feed_back_count"], 1)
            self.assertEqual(summary["waiting_for_controlled_execution_count"], 1)
            self.assertEqual(summary["blocked_or_review_count"], 1)
            records = _records_by_project(result["manifest"]["dispatch_closeout_table"]["records"])
            self.assertEqual(
                records["PROJ-A"]["dispatch_closeout_state"],
                "READY_TO_FEED_RESULT_BACK_TO_EVIDENCE_STATE",
            )
            self.assertTrue(records["PROJ-A"]["ready_to_feed_back_to_evidence_state"])
            self.assertEqual(
                records["PROJ-D"]["dispatch_closeout_state"],
                "WAITING_FOR_CONTROLLED_EXECUTION",
            )
            self.assertEqual(
                records["PROJ-SKIP"]["dispatch_closeout_state"],
                "PARKED_OPERATOR_SKIPPED_THIS_ROUND",
            )
            self.assertEqual(
                records["PROJ-BLOCKED"]["dispatch_closeout_state"],
                "BLOCKED_RESULT_REVIEW_REQUIRED",
            )
            self.assertTrue((root / "out" / "stage6-review-action-dispatch-closeout-v1.json").exists())
            self.assertTrue((root / "out" / "stage6-review-dispatch-closeout-table.json").exists())

    def test_missing_dispatch_readback_blocks_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_stage6_review_action_dispatch_closeout(
                dispatch_readback_root=root / "missing",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["stage6_review_action_dispatch_closeout_mode"], "INPUT_BLOCKED")
            self.assertIn("stage6_review_action_dispatch_readback_missing_or_invalid", result["blocking_reasons"])

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_readback(root / "readback")

            result = build_stage6_review_action_dispatch_closeout(
                dispatch_readback_root=root / "readback",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            self.assertFalse(result["manifest"]["safety"]["stage7_to_stage9_live_execution_enabled"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)
            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_sha256"], _fingerprint_without_manifest_sha(manifest))


def _write_readback(root: Path) -> None:
    records = [
        _readback_record("PROJ-A", "EXECUTION_OUTPUT_READY", result_json_exists=True),
        _readback_record("PROJ-D", "WAITING_FOR_CONTROLLED_EXECUTION"),
        _readback_record("PROJ-SKIP", "SKIPPED_BY_OPERATOR"),
        _readback_record(
            "PROJ-BLOCKED",
            "EXECUTION_OUTPUT_BLOCKED_OR_REVIEW_REQUIRED",
            result_json_exists=True,
            result_blocking_reasons=["source_blocked"],
        ),
    ]
    _write_json(
        root / "stage6-review-action-dispatch-readback-v1.json",
        {
            "manifest": {
                "manifest_id": "DISPATCH-READBACK-1",
                "dispatch_readback_table": {"records": records},
                "summary": {"dispatch_readback_count": len(records)},
            },
            "summary": {"dispatch_readback_count": len(records)},
        },
    )


def _readback_record(
    project_id: str,
    state: str,
    *,
    result_json_exists: bool = False,
    result_blocking_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "dispatch_readback_id": f"READBACK-{project_id}",
        "dispatch_task_id": f"DISPATCH-{project_id}",
        "project_id": project_id,
        "project_name": f"{project_id} 项目",
        "dispatch_task_type": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
        "dispatch_readback_state": state,
        "result_json_path": f"tmp/{project_id}.json" if result_json_exists else "",
        "result_json_exists": result_json_exists,
        "result_manifest_id": f"RESULT-{project_id}" if result_json_exists else "",
        "result_blocking_reasons": result_blocking_reasons or [],
        "next_required_input_refs": ["evidence_orchestration_state_root_or_json"] if not result_json_exists else [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "query_miss_is_not_clearance": True,
    }


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fingerprint_without_manifest_sha(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
