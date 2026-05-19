from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.main import create_app  # noqa: E402
from storage.stage6_review_loop_operator_projection import (  # noqa: E402
    STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME,
    build_stage6_review_loop_operator_projection,
    load_stage6_review_loop_operator_projection,
)


class Stage6ReviewLoopOperatorProjectionTests(unittest.TestCase):
    def test_projection_turns_loop_status_table_into_operator_rows(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            _status_table_payload(),
            source_path="tmp/run/stage6-review-loop-project-status-table.json",
            created_at="2026-05-19T12:00:00+08:00",
        )

        self.assertEqual(projection["surface_id"], "stage6_review_loop_operator_status")
        self.assertEqual(projection["surface_state"], "ACTION_READY")
        self.assertTrue(projection["owner_can_observe_without_raw_json"])
        self.assertFalse(projection["live_execution_enabled"])
        self.assertFalse(projection["customer_visible_allowed"])
        self.assertEqual(projection["summary"]["project_count"], 3)
        self.assertEqual(projection["summary"]["automated_dispatch_available_count"], 1)
        self.assertEqual(projection["summary"]["manual_hold_count"], 1)
        self.assertEqual(projection["summary"]["stage7_commercial_input_allowed_count"], 1)

        rows = {row["project_id"]: row for row in projection["project_status_rows"]}
        self.assertEqual(rows["PROJ-A"]["owner_status_label"], "下一轮受控任务已准备")
        self.assertTrue(rows["PROJ-A"]["automated_dispatch_available"])
        self.assertEqual(
            rows["PROJ-B"]["manual_hold_reason"],
            "terminal_source_gap_no_delta_manual_review_only",
        )
        self.assertIn(
            "new_official_original_notice_source_or_snapshot_available",
            rows["PROJ-B"]["reopen_conditions"],
        )
        self.assertIn(
            "拿到新的官方原文来源或可回放快照。",
            rows["PROJ-B"]["reopen_condition_labels"],
        )
        self.assertFalse(rows["PROJ-B"]["stage7_commercial_input_allowed"])
        self.assertIn("暂不进入第七阶段", rows["PROJ-B"]["stage7_gate_label"])
        self.assertTrue(rows["PROJ-C"]["stage7_commercial_input_allowed"])
        self.assertIn("review_stage7_commercial_boundary_before_sales_use", projection["operator_decision"]["next_actions"])
        self.assertIn("进入第七阶段前先复核商业展示边界，不能外发客户。", projection["operator_decision"]["next_action_labels"])

        text = json.dumps(projection, ensure_ascii=False)
        for forbidden in ("无风险", "无冲突", "确认本人", "违法成立", "是不是本人"):
            self.assertNotIn(forbidden, text)

    def test_loader_finds_latest_status_table_under_search_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            older = root / "older" / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            latest = root / "latest" / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            _write_json(older, {"summary": {}, "records": []})
            _write_json(latest, _status_table_payload())
            os.utime(older, (1, 1))
            os.utime(latest, (2, 2))

            projection = load_stage6_review_loop_operator_projection(search_root=root)

            self.assertEqual(projection["source_readback_state"], "READBACK_READY")
            self.assertTrue(str(projection["source_path"]).endswith(str(latest)))
            self.assertEqual(projection["summary"]["project_count"], 3)

    def test_operator_route_reads_status_table_without_live_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            _write_json(path, _status_table_payload())
            client = TestClient(create_app())

            response = client.request(
                "GET",
                "/operator-console/stage6-review-loop-status",
                params={"status_table_path": str(path)},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["surface_id"], "stage6_review_loop_operator_status")
            self.assertEqual(payload["summary"]["manual_hold_count"], 1)
            self.assertFalse(payload["live_execution_enabled"])
            self.assertFalse(payload["external_release_enabled"])
            self.assertFalse(payload["real_provider_call_enabled"])
            self.assertFalse(payload["automated_refund_enabled"])


def _status_table_payload() -> dict:
    return {
        "summary": {
            "loop_terminal_state_counts": {
                "NEXT_CYCLE_DISPATCH_READY": 1,
                "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH": 1,
                "RESULT_EXECUTED_NO_NEXT_DISPATCH": 1,
            }
        },
        "records": [
            {
                "project_id": "PROJ-A",
                "project_name": "A project",
                "dispatch_task_type": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
                "loop_terminal_state": "NEXT_CYCLE_DISPATCH_READY",
                "next_recommended_action": "run_next_cycle_dispatch_or_keep_internal_review_dry_run",
                "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                "stage6_ready": True,
                "stage7_commercial_input_allowed": False,
            },
            {
                "project_id": "PROJ-B",
                "project_name": "B project",
                "dispatch_task_type": "RUN_ORIGINAL_NOTICE_BACKTRACE_RETRY_OR_MANUAL_REVIEW",
                "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                "next_recommended_action": "manual_review_or_new_source_override_required_before_retry",
                "next_cycle_dispatch_block_reason": "terminal_source_gap_no_delta_manual_review_only",
                "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                "stage6_ready": True,
                "stage7_commercial_input_allowed": False,
            },
            {
                "project_id": "PROJ-C",
                "project_name": "C project",
                "dispatch_task_type": "NONE",
                "loop_terminal_state": "RESULT_EXECUTED_NO_NEXT_DISPATCH",
                "next_recommended_action": "review_result_artifact_and_close_project_or_generate_next_cycle_if_needed",
                "stage6_fact_package_state": "REVIEW_FACT_PACKAGE_READY",
                "stage6_ready": True,
                "stage7_commercial_input_allowed": True,
            },
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
