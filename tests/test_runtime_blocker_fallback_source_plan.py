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
            stage4_queue = root / "stage4-followup-queue.json"
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            pressure_root = root / "pressure"
            out = root / "out"
            _write_json(pressure_root / "stage4-release-adapter-bridge-plan.json", {"tasks": []})
            _write_json(pressure_root / "pressure-summary.json", {"summary": {"candidate_count": 1}})
            _write_json(
                scoreboard,
                {
                    "input_refs": {
                        "pressure_summary_json": str(pressure_root / "pressure-summary.json"),
                    }
                },
            )
            _write_field_query(field_query)
            _write_stage4_queue(stage4_queue)
            _write_cycle(cycle, field_query, scoreboard, stage4_queue)

            result = build_runtime_blocker_fallback_source_plan(
                stage6_review_cycle_json=cycle,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )
            json_exists = (out / "runtime-blocker-fallback-source-plan-v1.json").exists()
            bridge_json_exists = (out / "stage4-release-adapter-bridge-plan.json").exists()
            markdown_exists = (out / "runtime-blocker-fallback-source-plan-v1.md").exists()

        self.assertEqual(result["summary"]["fallback_source_plan_record_count"], 1)
        self.assertEqual(result["summary"]["project_count"], 1)
        self.assertEqual(result["summary"]["stage4_release_adapter_bridge_task_count"], 1)
        self.assertEqual(result["summary"]["stage4_release_adapter_bridge_project_count"], 1)
        self.assertEqual(
            result["summary"]["stage4_release_adapter_bridge_target_type_counts"],
            {"ygp_original_readback_backfill": 1},
        )
        self.assertEqual(result["summary"]["stage4_release_adapter_bridge_gdcic_route_allowed_count"], 0)
        self.assertEqual(result["summary"]["candidate_company_present_count"], 1)
        self.assertTrue(result["summary"]["records_are_p13b_consumable"])
        bridge_plan = result["stage4_release_adapter_bridge_plan"]
        self.assertEqual(bridge_plan["summary"]["bridge_plan_state"], "READY")
        self.assertEqual(bridge_plan["summary"]["release_evidence_adapter_task_count"], 1)
        self.assertEqual(bridge_plan["summary"]["gdcic_project_code_route_allowed_count"], 0)
        bridge_record = bridge_plan["release_evidence_adapter_task_records"][0]
        self.assertEqual(bridge_record["input_source_kind"], "runtime_blocker_fallback_source_plan")
        self.assertEqual(bridge_record["project_id"], "PROJ-FALLBACK")
        self.assertEqual(bridge_record["source_profile_id"], "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL")
        self.assertEqual(bridge_record["release_evidence_target_type"], "ygp_original_readback_backfill")
        self.assertEqual(
            bridge_record["query_params"]["ygpProjectCodeVariants"],
            ["E4413000835979563001"],
        )
        self.assertEqual(bridge_record["query_params"]["gdcicProjectCodeVariants"], [])
        self.assertEqual(
            bridge_record["query_params"]["sourceProfileId"],
            "GUANGDONG-YGP-ORIGINAL-READBACK-BACKFILL",
        )
        self.assertFalse(bridge_record["gdcic_project_code_route_allowed"])
        self.assertTrue(bridge_record["must_not_extract_from_full_text_numbers"])
        self.assertFalse(bridge_record["customer_visible_allowed"])
        self.assertTrue(bridge_record["query_miss_is_not_clearance"])
        record = result["records"][0]
        self.assertEqual(record["project_id"], "PROJ-FALLBACK")
        self.assertEqual(record["candidate_companies"], ["广州样本工程有限公司"])
        self.assertEqual(record["candidate_notice_source_urls"], ["https://ywtb.gzggzy.cn/sample.html"])
        self.assertEqual(record["followup_queue_state"], "FOLLOWUP_SOURCE_PLAN_REQUIRED")
        self.assertEqual(record["followup_route"], "official_readback_ready_stage4_bridge_followup")
        self.assertEqual(record["stage4_followup_route"], "official_readback_ready_stage4_bridge_followup")
        self.assertEqual(
            record["stage4_official_readback_context"]["ygp_project_code_variants"],
            ["E4413000835979563001"],
        )
        self.assertIn("p13b_ygp_or_public_identifier_backfill_task", record["required_input"])
        self.assertEqual(
            [step["source_kind"] for step in record["public_source_fallback_sequence"]],
            [
                "data_ggzy_company_history_search",
                "data_ggzy_bid_list_pagination",
                "data_ggzy_bid_show_readback",
                "ygp_original_notice_readback",
                "project_local_authority_public_source",
                "stage4_release_adapter_bridge",
                "stage6_limited_sellable_projection",
            ],
        )
        self.assertFalse(record["gdcic_project_code_digit_guessing_allowed"])
        self.assertFalse(record["customer_visible_allowed"])
        self.assertTrue(record["query_miss_is_not_clearance"])
        self.assertEqual(result["next_regression_execution_plan"]["plan_state"], "FALLBACK_SOURCE_PLAN_READY_FOR_P13B")
        refs = result["continuation_input_refs"]
        self.assertEqual(refs["prior_scoreboard_json"], str(scoreboard))
        self.assertEqual(refs["effective_pressure_root"], str(pressure_root))
        self.assertEqual(refs["effective_release_field_query_root"], str(field_query.parent))
        self.assertEqual(
            result["next_regression_execution_plan"]["continuation_input_refs"],
            refs,
        )
        self.assertEqual(
            result["next_regression_execution_plan"]["runner_entrypoint"],
            "scripts/run-stage1-6-sellable-rate-regression-v1.ps1",
        )
        self.assertEqual(
            result["next_regression_execution_plan"]["stage4_release_adapter_bridge_plan_json"],
            "stage4-release-adapter-bridge-plan.json",
        )
        self.assertEqual(
            result["next_regression_execution_plan"]["stage4_release_adapter_bridge_project_ids"],
            ["PROJ-FALLBACK"],
        )
        self.assertFalse(result["next_regression_execution_plan"]["live_execution_enabled_by_default"])
        self.assertTrue(json_exists)
        self.assertTrue(bridge_json_exists)
        self.assertTrue(markdown_exists)

    def test_field_query_ygp_identifiers_seed_stage4_official_backfill_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            field_query = root / "field-query.json"
            cycle = root / "cycle.json"
            stage4_queue = root / "stage4-followup-queue.json"
            out = root / "out"
            _write_field_query(field_query)
            _write_stage4_queue_without_official_context(stage4_queue)
            _write_cycle(cycle, field_query, root / "missing-scoreboard.json", stage4_queue)

            result = build_runtime_blocker_fallback_source_plan(
                stage6_review_cycle_json=cycle,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        context = result["records"][0]["stage4_official_readback_context"]
        self.assertEqual(
            context["stage4_official_readback_context_state"],
            "OFFICIAL_READBACK_READY_STAGE4_BRIDGE_FOLLOWUP_REQUIRED",
        )
        self.assertEqual(context["ygp_project_code_variants"], ["E4413000835979563001"])
        self.assertEqual(context["ygp_biz_code_variants"], ["3C52"])
        self.assertEqual(context["ygp_site_code_variants"], ["441300"])
        self.assertEqual(context["ygp_notice_id_variants"], ["7fcdf98f7cd04bc5b2a0167b4f1c5733"])
        self.assertFalse(context["gdcic_project_code_route_allowed"])
        self.assertTrue(context["must_not_extract_from_full_text_numbers"])

    def test_semicolon_field_queries_and_scoreboard_rows_seed_fallback_query_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            empty_field_query = root / "field-query-empty.json"
            ygp_field_query = root / "field-query-ygp.json"
            cycle = root / "cycle.json"
            stage4_queue = root / "stage4-followup-queue.json"
            scoreboard = root / "scoreboard" / "stage1-6-sellable-scoreboard-v1.json"
            out = root / "out"
            _write_json(empty_field_query, {"manifest": {"field_task_records": []}})
            _write_field_query_with_singular_ygp_params(ygp_field_query)
            _write_stage4_queue_without_official_context(stage4_queue)
            _write_scoreboard_project_rows(scoreboard)
            _write_cycle(cycle, Path(f"{empty_field_query};{ygp_field_query}"), scoreboard, stage4_queue)

            result = build_runtime_blocker_fallback_source_plan(
                stage6_review_cycle_json=cycle,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        self.assertEqual(result["summary"]["candidate_company_present_count"], 1)
        self.assertEqual(result["summary"]["responsible_person_present_count"], 1)
        self.assertEqual(result["summary"]["candidate_notice_url_present_count"], 1)
        self.assertEqual(result["summary"]["public_identifier_present_count"], 1)
        self.assertEqual(result["summary"]["p13b_query_input_present_count"], 1)
        record = result["records"][0]
        self.assertEqual(record["candidate_companies"], ["广州补齐工程有限公司"])
        self.assertEqual(record["responsible_person_names"], ["李四"])
        self.assertEqual(record["candidate_notice_source_urls"], ["https://ywtb.gzggzy.cn/context.html"])
        self.assertEqual(
            record["stage4_official_readback_context"]["ygp_notice_id_variants"],
            ["notice-singular", "notice-scoreboard"],
        )
        self.assertIn(";", result["input_refs"]["release_field_query_json"])

    def test_ygp_retry_fallback_with_identifiers_emits_bridge_readback_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            field_query = root / "field-query.json"
            cycle = root / "cycle.json"
            stage4_queue = root / "stage4-followup-queue.json"
            out = root / "out"
            _write_json(field_query, {"manifest": {"field_task_records": []}})
            _write_stage4_queue_for_ygp_retry(stage4_queue)
            _write_cycle(cycle, field_query, root / "missing-scoreboard.json", stage4_queue)

            result = build_runtime_blocker_fallback_source_plan(
                stage6_review_cycle_json=cycle,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

        self.assertEqual(result["summary"]["stage4_release_adapter_bridge_task_count"], 1)
        self.assertEqual(
            result["summary"]["stage4_release_adapter_bridge_target_type_counts"],
            {"ygp_original_readback_backfill": 1},
        )
        record = result["records"][0]
        self.assertEqual(record["followup_route"], "ygp_retry_then_local_authority_fallback")
        bridge_record = result["stage4_release_adapter_bridge_plan"]["release_evidence_adapter_task_records"][0]
        self.assertEqual(bridge_record["project_id"], "PROJ-FALLBACK")
        self.assertEqual(
            bridge_record["bridge_readiness_state"],
            "YGP_RETRY_STAGE4_BACKFILL_READY_FOR_PUBLIC_READBACK",
        )
        self.assertEqual(
            bridge_record["local_housing_authority_adapter_scope"],
            "YGP_RETRY_THEN_LOCAL_AUTHORITY_FALLBACK",
        )
        self.assertEqual(
            bridge_record["query_params"]["ygpProjectCodeVariants"],
            ["E4413000835979563001"],
        )
        self.assertEqual(bridge_record["query_params"]["gdcicProjectCodeVariants"], [])
        self.assertFalse(bridge_record["gdcic_project_code_route_allowed"])
        self.assertTrue(bridge_record["query_miss_is_not_clearance"])
        self.assertFalse(bridge_record["customer_visible_allowed"])


def _write_cycle(path: Path, field_query: Path, scoreboard: Path, stage4_queue: Path) -> None:
    _write_json(
        path,
        {
            "manifest": {
                "source_release_field_query_json": str(field_query),
                "source_stage1_6_scoreboard_json": str(scoreboard),
                "source_stage4_backfill_followup_queue_json": str(stage4_queue),
                "runtime_blocker_subqueue_controller_table": {
                    "records": [
                        {
                            "controller_queue_record_id": "QUEUE-1",
                            "source_next_subqueue_record_id": "SUBQUEUE-1",
                            "project_id": "PROJ-FALLBACK",
                            "task_id": "STAGE4-BACKFILL-FOLLOWUP-1",
                            "task_type": "completion_acceptance",
                            "subqueue_route": "fallback_source",
                            "blocker_state": "NOT_FOUND_REVIEW_OR_FALLBACK_SOURCE_REQUIRED",
                            "required_input": ["stage4_release_adapter_bridge_or_ygp_backfill_field_query_budget"],
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


def _write_stage4_queue(path: Path) -> None:
    _write_json(
        path,
        {
            "records": [
                {
                    "followup_record_id": "STAGE4-BACKFILL-FOLLOWUP-1",
                    "project_id": "PROJ-FALLBACK",
                    "followup_route": "official_readback_ready_stage4_bridge_followup",
                    "required_input": ["p13b_ygp_or_public_identifier_backfill_task"],
                    "stage4_official_readback_context": {
                        "ygp_project_code_variants": ["E4413000835979563001"],
                        "gdcic_project_code_route_allowed": False,
                    },
                    "public_source_fallback_sequence": [
                        {
                            "source_kind": "ygp_original_notice_readback",
                            "action": "read_ygp_original_notice_identifiers_for_p13b_or_stage4_bridge",
                        },
                        {
                            "source_kind": "stage4_release_adapter_bridge",
                            "action": "feed_public_identifier_to_release_evidence_adapter_before_limited_review",
                        },
                        {
                            "source_kind": "stage6_limited_sellable_projection",
                            "action": "project_b_or_c_official_readback_to_internal_limited_review",
                        },
                    ],
                }
            ]
        },
    )


def _write_stage4_queue_without_official_context(path: Path) -> None:
    _write_json(
        path,
        {
            "records": [
                {
                    "followup_record_id": "STAGE4-BACKFILL-FOLLOWUP-1",
                    "project_id": "PROJ-FALLBACK",
                    "followup_route": "official_readback_ready_stage4_bridge_followup",
                    "required_input": ["p13b_ygp_or_public_identifier_backfill_task"],
                }
            ]
        },
    )


def _write_stage4_queue_for_ygp_retry(path: Path) -> None:
    _write_json(
        path,
        {
            "records": [
                {
                    "followup_record_id": "STAGE4-BACKFILL-FOLLOWUP-1",
                    "project_id": "PROJ-FALLBACK",
                    "followup_route": "ygp_retry_then_local_authority_fallback",
                    "required_input": ["ygp_retry_budget_or_project_local_authority_adapter"],
                    "stage4_official_readback_context": {
                        "stage4_official_readback_context_state": "",
                        "ygp_project_code_variants": ["E4413000835979563001"],
                        "ygp_biz_code_variants": ["3C52"],
                        "ygp_site_code_variants": ["441300"],
                        "ygp_notice_id_variants": ["7fcdf98f7cd04bc5b2a0167b4f1c5733"],
                        "gdcic_project_code_route_allowed": False,
                        "gdcic_route_block_reason": "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
                    },
                    "public_source_fallback_sequence": [
                        {
                            "source_kind": "ygp_original_notice_readback",
                            "action": "read_ygp_original_notice_identifiers_for_p13b_or_stage4_bridge",
                            "input_state": "YGP_IDENTIFIER_PRESENT",
                        },
                        {
                            "source_kind": "project_local_authority_public_source",
                            "action": "query_historical_project_location_housing_or_supervisory_authority",
                            "input_state": "LOCAL_AUTHORITY_FALLBACK_REQUIRED",
                        },
                    ],
                }
            ]
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
                        "query_params": {
                            "ygpProjectCodeVariants": ["E4413000835979563001"],
                            "ygpBizCodeVariants": ["3C52"],
                            "ygpSiteCodeVariants": ["441300"],
                            "ygpNoticeIdVariants": ["7fcdf98f7cd04bc5b2a0167b4f1c5733"],
                            "gdcicProjectCodeVariants": [],
                        },
                    }
                ]
            }
        },
    )


def _write_field_query_with_singular_ygp_params(path: Path) -> None:
    _write_json(
        path,
        {
            "manifest": {
                "field_task_records": [
                    {
                        "field_query_task_id": "TASK-FALLBACK",
                        "project_id": "PROJ-FALLBACK",
                        "query_params": {
                            "ygpProjectCode": "E4413000835979563001",
                            "ygpBizCode": "3C52",
                            "ygpSiteCode": "441300",
                            "ygpNoticeId": "notice-singular",
                            "gdcicProjectCodeVariants": [],
                        },
                    }
                ]
            }
        },
    )


def _write_scoreboard_project_rows(path: Path) -> None:
    _write_json(
        path,
        {
            "project_rows": [
                {
                    "project_id": "PROJ-FALLBACK",
                    "project_name": "补齐上下文样本",
                    "candidate_companies": ["广州补齐工程有限公司"],
                    "responsible_person_names": ["李四"],
                    "candidate_notice_source_urls": ["https://ywtb.gzggzy.cn/context.html"],
                    "p13b_overlap_ygp_project_code_variants": ["E4413000835979563001"],
                    "p13b_overlap_ygp_biz_code_variants": ["3C52"],
                    "p13b_overlap_ygp_site_code_variants": ["441300"],
                    "p13b_overlap_ygp_notice_id_variants": ["notice-scoreboard"],
                    "stage4_gdcic_project_code_route_policy": "YGP_OR_TRADE_IDENTIFIERS_NOT_SENT_TO_GDCIC_PROJECT_CODE",
                }
            ]
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
