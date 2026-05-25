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

from storage.runtime_blocker_fallback_source_plan import build_runtime_blocker_fallback_source_plan  # noqa: E402


class RuntimeBlockerFallbackSourcePlanTests(unittest.TestCase):
    def test_builds_p13b_consumable_fallback_plan_from_stage6_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            field_query = root / "field-query.json"
            cycle = root / "cycle.json"
            out = root / "out"
            _write_field_query(field_query)
            _write_cycle(cycle, field_query)

            result = build_runtime_blocker_fallback_source_plan(
                stage6_review_cycle_json=cycle,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )
            json_exists = (out / "runtime-blocker-fallback-source-plan-v1.json").exists()
            markdown_exists = (out / "runtime-blocker-fallback-source-plan-v1.md").exists()

        self.assertEqual(result["summary"]["fallback_source_plan_record_count"], 1)
        self.assertEqual(result["summary"]["project_count"], 1)
        self.assertEqual(result["summary"]["candidate_company_present_count"], 1)
        self.assertTrue(result["summary"]["records_are_p13b_consumable"])
        record = result["records"][0]
        self.assertEqual(record["project_id"], "PROJ-FALLBACK")
        self.assertEqual(record["candidate_companies"], ["广州样本工程有限公司"])
        self.assertEqual(record["candidate_notice_source_urls"], ["https://ywtb.gzggzy.cn/sample.html"])
        self.assertEqual(record["followup_queue_state"], "FOLLOWUP_SOURCE_PLAN_REQUIRED")
        self.assertEqual(record["followup_route"], "local_authority_fallback_source_planning")
        self.assertEqual(
            [step["source_kind"] for step in record["public_source_fallback_sequence"]],
            [
                "data_ggzy_company_history_search",
                "data_ggzy_bid_list_pagination",
                "data_ggzy_bid_show_readback",
                "ygp_original_notice_readback",
                "project_local_authority_public_source",
            ],
        )
        self.assertFalse(record["gdcic_project_code_digit_guessing_allowed"])
        self.assertFalse(record["customer_visible_allowed"])
        self.assertTrue(record["query_miss_is_not_clearance"])
        self.assertEqual(result["next_regression_execution_plan"]["plan_state"], "FALLBACK_SOURCE_PLAN_READY_FOR_P13B")
        self.assertFalse(result["next_regression_execution_plan"]["live_execution_enabled_by_default"])
        self.assertTrue(json_exists)
        self.assertTrue(markdown_exists)


def _write_cycle(path: Path, field_query: Path) -> None:
    _write_json(
        path,
        {
            "manifest": {
                "source_release_field_query_json": str(field_query),
                "runtime_blocker_subqueue_controller_table": {
                    "records": [
                        {
                            "controller_queue_record_id": "QUEUE-1",
                            "source_next_subqueue_record_id": "SUBQUEUE-1",
                            "project_id": "PROJ-FALLBACK",
                            "task_id": "TASK-FALLBACK",
                            "task_type": "completion_acceptance",
                            "subqueue_route": "fallback_source",
                            "blocker_state": "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED",
                        },
                        {
                            "project_id": "PROJ-BROWSER",
                            "task_id": "TASK-BROWSER",
                            "subqueue_route": "browser_worker",
                        },
                    ]
                },
            }
        },
    )


def _write_field_query(path: Path) -> None:
    _write_json(
        path,
        {
            "manifest": {
                "field_task_records": [
                    {
                        "field_query_task_id": "TASK-FALLBACK",
                        "project_id": "PROJ-FALLBACK",
                        "project_name": "广州样本项目中标候选人公示",
                        "candidate_group_members": ["广州样本工程有限公司"],
                        "matched_company_names": ["广州样本工程有限公司"],
                        "company_query_variants": ["广州样本工程有限公司"],
                        "responsible_person_name": "张三",
                        "trigger_source_url": "https://ywtb.gzggzy.cn/sample.html",
                        "source_url": "https://zfcj.gz.gov.cn/sample",
                    }
                ]
            }
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
