from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.p13b_operational_closeout import build_p13b_operational_closeout  # noqa: E402


SCRIPT = ROOT / "scripts" / "run-p13b-overlap-triage-v1.ps1"


class P13BOperationalCloseoutTests(unittest.TestCase):
    def test_builds_project_next_action_and_budget_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_company_history(root / "company")
            _write_original_notice(root / "original")
            _write_closeout(root / "closeout")

            result = build_p13b_operational_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                overlap_triage_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-17T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["input_project_count"], 5)
            self.assertEqual(summary["queried_company_count"], 2)
            self.assertEqual(summary["source_limit_deferred_count"], 1)
            self.assertEqual(summary["original_notice_backtrace_required_count"], 1)
            self.assertEqual(summary["release_evidence_trigger_count"], 1)
            self.assertEqual(summary["release_evidence_probe_plan_count"], 1)
            self.assertGreater(summary["release_evidence_probe_task_count"], 0)
            self.assertEqual(summary["release_evidence_initial_abcd_grade_counts"]["A_STRONG_TIME_OVERLAP_SIGNAL"], 1)
            self.assertEqual(summary["release_evidence_query_region_basis_counts"]["HISTORICAL_OVERLAP_PROJECT_REGION"], 1)
            self.assertEqual(summary["ygp_readback_blocked_or_unsupported_count"], 1)
            self.assertEqual(summary["no_overlap_signal_review_count"], 1)
            self.assertEqual(summary["forbidden_term_scan_state"], "PASS")
            self.assertTrue((root / "out" / "p13b-operational-closeout-v1.json").exists())
            self.assertTrue((root / "out" / "p13b-project-next-action-table.json").exists())
            self.assertTrue((root / "out" / "p13b-release-evidence-probe-plan-table.json").exists())
            self.assertTrue((root / "out" / "p13b-release-evidence-probe-task-table.json").exists())
            self.assertTrue((root / "out" / "p13b-budget-audit-table.json").exists())

            next_actions = {
                record["project_id"]: record["recommended_next_action"]
                for record in result["manifest"]["project_next_action_records"]
            }
            self.assertEqual(next_actions["PROJ-1"], "targeted_release_evidence_probe")
            self.assertEqual(next_actions["PROJ-2"], "targeted_original_notice_01_to_12_backtrace")
            self.assertEqual(next_actions["PROJ-3"], "rerun_with_higher_live_budget_after_review")
            self.assertEqual(next_actions["PROJ-4"], "prepare_local_ygp_readback_or_keep_blocked_taxonomy")
            self.assertEqual(next_actions["PROJ-5"], "keep_internal_review_no_clearance_conclusion")

            release_plans = result["manifest"]["release_evidence_probe_plan_records"]
            self.assertEqual(len(release_plans), 1)
            self.assertEqual(release_plans[0]["source_stage"], "DATA_GGZY_BID_SHOW")
            self.assertEqual(release_plans[0]["source_url"], "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1")
            self.assertEqual(release_plans[0]["region_code"], "CN-GD")
            self.assertEqual(release_plans[0]["historical_project_area_code"], "广州市")
            self.assertEqual(release_plans[0]["release_evidence_query_region_basis"], "HISTORICAL_OVERLAP_PROJECT_REGION")
            self.assertEqual(release_plans[0]["non_guangdong_release_adapter_rule"], "")
            self.assertEqual(release_plans[0]["local_housing_authority_adapter_scope"], "HISTORICAL_PROJECT_JURISDICTION")
            self.assertEqual(release_plans[0]["local_housing_authority_adapter_region_code"], "CN-GD")
            self.assertEqual(release_plans[0]["initial_release_evidence_abcd_grade"], "A_STRONG_TIME_OVERLAP_SIGNAL")
            self.assertEqual(release_plans[0]["primary_release_evidence_source_scope"], "HISTORICAL_PROJECT_LOCAL_HOUSING_AUTHORITY_ONLY")
            self.assertEqual(release_plans[0]["primary_release_evidence_source_selection_state"], "PRIMARY_LOCAL_HOUSING_AUTHORITY_SOURCE_READY")
            self.assertIn("construction_permit", release_plans[0]["release_evidence_source_targets"])
            self.assertEqual(release_plans[0]["source_entry_count"], 1)
            self.assertGreater(release_plans[0]["source_plan_total_entry_count"], release_plans[0]["source_entry_count"])

            release_tasks = result["manifest"]["release_evidence_probe_task_records"]
            self.assertEqual(len(release_tasks), summary["release_evidence_probe_task_count"])
            self.assertTrue(all(task["execution_mode"] == "PLAN_ONLY_NOT_EXECUTED" for task in release_tasks))
            self.assertTrue(all(task["readback_ready"] is False for task in release_tasks))
            self.assertTrue(all(task["initial_release_evidence_abcd_grade"] == "A_STRONG_TIME_OVERLAP_SIGNAL" for task in release_tasks))
            self.assertTrue(all(task["release_evidence_query_region_basis"] == "HISTORICAL_OVERLAP_PROJECT_REGION" for task in release_tasks))
            self.assertTrue(all(task["non_guangdong_release_adapter_rule"] == "" for task in release_tasks))
            self.assertTrue(all(task["local_housing_authority_adapter_scope"] == "HISTORICAL_PROJECT_JURISDICTION" for task in release_tasks))
            self.assertTrue(all(task["local_housing_authority_adapter_region_code"] == "CN-GD" for task in release_tasks))
            self.assertTrue(all(task["trigger_source_url"] == "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1" for task in release_tasks))
            self.assertIn("contract_public_info", {source_type for task in release_tasks for source_type in task["matched_target_source_types"]})
            self.assertIn("completion_filing", {source_type for task in release_tasks for source_type in task["matched_target_source_types"]})
            self.assertNotIn("ZJ-JZSC-PUBLIC-SERVICE", {task["source_entry_id"] for task in release_tasks})
            self.assertNotIn("NATIONAL-JZSC-PM-ACTIVE-CONFLICT", {task["source_entry_id"] for task in release_tasks})
            self.assertNotIn("GD-GDCIC-SKYPT-PROJECT", {task["source_entry_id"] for task in release_tasks})
            self.assertNotIn("GD-TZXM-PROJECT-PROGRESS", {task["source_entry_id"] for task in release_tasks})
            subsource_ids = {task["subsource_id"] for task in release_tasks}
            self.assertIn("gz_zfcj_construction_permit_public_api", subsource_ids)
            self.assertIn("gz_zfcj_completion_acceptance_public_api", subsource_ids)
            self.assertIn("gz_zfcj_contract_credit_public_portal", subsource_ids)
            next_adapters = {task["next_adapter"] for task in release_tasks}
            self.assertIn("guangzhou_zfcj_construction_permit_public_api_v1", next_adapters)
            self.assertIn("guangzhou_zfcj_completion_acceptance_public_api_v1", next_adapters)

            budget_rows = {
                record["budget_scope"]: record
                for record in result["manifest"]["budget_audit_records"]
            }
            self.assertEqual(budget_rows["COMPANY_HISTORY_QUERY"]["configured_limit"], 2)
            self.assertEqual(budget_rows["COMPANY_HISTORY_QUERY"]["budget_state"], "BUDGET_LIMIT_DEFERRED")
            self.assertEqual(budget_rows["ORIGINAL_NOTICE_BACKTRACE"]["configured_limit"], 2)
            self.assertEqual(budget_rows["ORIGINAL_NOTICE_BACKTRACE"]["budget_state"], "BUDGET_WITHIN_LIMIT")
            self.assertEqual(budget_rows["BID_RECORDS_PER_COMPANY"]["configured_limit"], 10)

    def test_release_probe_prefers_historical_overlap_project_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_company_history(root / "company")
            _write_original_notice(root / "original")
            _write_closeout(
                root / "closeout",
                historical_project_area_code="浙江省杭州市",
                historical_project_region_code="CN-ZJ",
            )

            result = build_p13b_operational_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                overlap_triage_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-17T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            plan = result["manifest"]["release_evidence_probe_plan_records"][0]
            self.assertEqual(plan["region_code"], "CN-ZJ")
            self.assertEqual(plan["release_evidence_query_region_code"], "CN-ZJ")
            self.assertEqual(plan["release_evidence_query_region_basis"], "HISTORICAL_OVERLAP_PROJECT_REGION")
            self.assertEqual(plan["primary_release_evidence_source_scope"], "HISTORICAL_PROJECT_LOCAL_HOUSING_AUTHORITY_ONLY")
            self.assertEqual(
                plan["non_guangdong_release_adapter_rule"],
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER",
            )
            self.assertEqual(plan["local_housing_authority_adapter_scope"], "HISTORICAL_PROJECT_JURISDICTION")
            self.assertEqual(plan["local_housing_authority_adapter_region_code"], "CN-ZJ")
            release_tasks = result["manifest"]["release_evidence_probe_task_records"]
            task_entry_ids = {task["source_entry_id"] for task in release_tasks}
            self.assertIn("ZJ-JZSC-PUBLIC-SERVICE", task_entry_ids)
            self.assertNotIn("GZ-ZFCJ-CREDIT-DOUBLE-PUBLICITY", task_entry_ids)
            self.assertTrue(
                all(
                    task["non_guangdong_release_adapter_rule"]
                    == "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
                    for task in release_tasks
                )
            )
            self.assertTrue(
                all(task["local_housing_authority_adapter_scope"] == "HISTORICAL_PROJECT_JURISDICTION" for task in release_tasks)
            )
            self.assertTrue(all(task["local_housing_authority_adapter_region_code"] == "CN-ZJ" for task in release_tasks))

    def test_release_probe_does_not_fallback_to_guangzhou_for_non_guangzhou_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_company_history(root / "company")
            _write_original_notice(root / "original")
            _write_closeout(
                root / "closeout",
                historical_project_area_code="深圳市",
                historical_project_region_code="CN-GD",
            )

            result = build_p13b_operational_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                overlap_triage_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-17T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            plan = result["manifest"]["release_evidence_probe_plan_records"][0]
            self.assertEqual(plan["historical_project_area_code"], "深圳市")
            self.assertEqual(plan["region_code"], "CN-GD")
            self.assertEqual(plan["source_entry_count"], 0)
            self.assertEqual(plan["primary_release_evidence_source_selection_state"], "LOCAL_HOUSING_AUTHORITY_ADAPTER_REQUIRED")
            self.assertEqual(plan["non_guangdong_release_adapter_rule"], "")
            self.assertEqual(plan["local_housing_authority_adapter_scope"], "HISTORICAL_PROJECT_JURISDICTION")
            self.assertEqual(plan["local_housing_authority_adapter_region_code"], "CN-GD")
            self.assertEqual(plan["next_required_runtime_adapters"], ["local_housing_authority_release_evidence_adapter_required"])
            self.assertEqual(result["manifest"]["release_evidence_probe_task_records"], [])

    def test_forbidden_terms_are_still_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_company_history(root / "company")
            _write_original_notice(root / "original")
            _write_closeout(root / "closeout", project_name="无风险项目")

            result = build_p13b_operational_closeout(
                company_history_triage_root=root / "company",
                original_notice_backtrace_root=root / "original",
                overlap_triage_closeout_root=root / "closeout",
                output_root=root / "out",
                created_at="2026-05-17T00:00:00+08:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["summary"]["forbidden_term_scan_state"], "FAIL")

    def test_run_script_plan_only_creates_all_stage_outputs(self) -> None:
        if shutil.which("pwsh") is None:
            self.skipTest("pwsh not available")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_p12_input(root / "input")
            run_root = root / "run"

            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPT),
                    "-InputRoot",
                    str(root / "input"),
                    "-RunRoot",
                    str(run_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
            )
            self.assertTrue((run_root / "01-company-history" / "company-history-overlap-triage-v1.json").exists())
            self.assertTrue((run_root / "02-original-notice" / "original-notice-backtrace-v1.json").exists())
            self.assertTrue((run_root / "03-closeout" / "p13b-overlap-triage-closeout-v1.json").exists())
            self.assertTrue((run_root / "04-operational-closeout" / "p13b-operational-closeout-v1.json").exists())
            self.assertTrue((run_root / "04-operational-closeout" / "p13b-release-evidence-probe-plan-table.json").exists())
            self.assertTrue((run_root / "04-operational-closeout" / "p13b-release-evidence-probe-task-table.json").exists())
            self.assertTrue((run_root / "05-release-evidence-field-query" / "guangdong-local-field-query-probe-v1.json").exists())

            payload = json.loads(
                (run_root / "04-operational-closeout" / "p13b-operational-closeout-v1.json").read_text(encoding="utf-8")
            )
            field_payload = json.loads(
                (run_root / "05-release-evidence-field-query" / "guangdong-local-field-query-probe-v1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["summary"]["company_history_execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(payload["summary"]["original_notice_execution_mode"], "PLAN_ONLY_NOT_EXECUTED")
            self.assertEqual(payload["summary"]["ygp_readback_blocked_or_unsupported_count"], 0)
            self.assertEqual(field_payload["manifest"]["input_mode"], "P13B_RELEASE_EVIDENCE_TASKS")
            self.assertEqual(field_payload["summary"]["execution_mode"], "PLAN_ONLY_NOT_EXECUTED")


def _write_company_history(root: Path) -> None:
    payload = {
        "manifest": {
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "max_live_companies": 2,
            "max_bid_records_per_company": 10,
            "history_window_years": [1, 2, 3],
            "project_task_records": [
                {"project_id": "PROJ-1"},
                {"project_id": "PROJ-2"},
                {"project_id": "PROJ-3"},
                {"project_id": "PROJ-4"},
                {"project_id": "PROJ-5"},
            ],
        },
        "summary": {
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "project_task_count": 5,
            "queried_company_count": 2,
            "bid_show_record_count": 2,
        },
    }
    _write_json(root / "company-history-overlap-triage-v1.json", payload)


def _write_original_notice(root: Path) -> None:
    payload = {
        "manifest": {
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "max_live_original_notices": 2,
        },
        "summary": {
            "execution_mode": "LIVE_PUBLIC_QUERY_ATTEMPTED",
            "live_processed_count": 2,
            "original_notice_fetch_count": 2,
        },
    }
    _write_json(root / "original-notice-backtrace-v1.json", payload)


def _write_closeout(
    root: Path,
    *,
    project_name: str = "项目一",
    historical_project_area_code: str = "广州市",
    historical_project_region_code: str = "CN-GD",
) -> None:
    payload = {
        "manifest": {
            "project_overlap_triage_records": [
                {
                    "project_id": "PROJ-1",
                    "project_name": project_name,
                    "city_code": "440100",
                    "project_overlap_triage_state": "OVERLAP_SIGNAL_REVIEW_REQUIRED",
                    "candidate_companies": ["广东甲公司"],
                    "responsible_person_names": ["张三"],
                    "release_evidence_trigger_count": 1,
                    "original_notice_readback_count": 1,
                    "source_limit_deferred_count": 0,
                    "original_notice_state_counts": {"OVERLAP_SIGNAL_REVIEW_REQUIRED": 1},
                },
                {
                    "project_id": "PROJ-2",
                    "project_name": "项目二",
                    "city_code": "440200",
                    "project_overlap_triage_state": "ORIGINAL_NOTICE_READBACK_REQUIRED",
                    "candidate_companies": ["广东乙公司"],
                    "responsible_person_names": ["李四"],
                    "release_evidence_trigger_count": 0,
                    "original_notice_readback_count": 1,
                    "source_limit_deferred_count": 0,
                    "original_notice_state_counts": {"ORIGINAL_NOTICE_READBACK_REQUIRED": 1},
                },
                {
                    "project_id": "PROJ-3",
                    "project_name": "项目三",
                    "city_code": "440300",
                    "project_overlap_triage_state": "SOURCE_LIMIT_DEFERRED",
                    "candidate_companies": ["广东丙公司"],
                    "responsible_person_names": ["王五"],
                    "release_evidence_trigger_count": 0,
                    "original_notice_readback_count": 0,
                    "source_limit_deferred_count": 1,
                    "original_notice_state_counts": {"SOURCE_LIMIT_DEFERRED": 1},
                },
                {
                    "project_id": "PROJ-4",
                    "project_name": "项目四",
                    "city_code": "440400",
                    "project_overlap_triage_state": "YGP_READBACK_BLOCKED_OR_UNSUPPORTED",
                    "candidate_companies": ["广东丁公司"],
                    "responsible_person_names": ["赵六"],
                    "release_evidence_trigger_count": 0,
                    "original_notice_readback_count": 1,
                    "source_limit_deferred_count": 0,
                    "original_notice_state_counts": {"YGP_READBACK_BLOCKED_OR_UNSUPPORTED": 1},
                },
                {
                    "project_id": "PROJ-5",
                    "project_name": "项目五",
                    "city_code": "440500",
                    "project_overlap_triage_state": "NO_OVERLAP_SIGNAL_REVIEW",
                    "candidate_companies": ["广东戊公司"],
                    "responsible_person_names": ["孙七"],
                    "release_evidence_trigger_count": 0,
                    "original_notice_readback_count": 1,
                    "source_limit_deferred_count": 0,
                    "original_notice_state_counts": {"NO_OVERLAP_SIGNAL_REVIEW": 1},
                },
            ],
            "company_history_readback_records": [
                {"project_id": "PROJ-1", "triage_closeout_state": "COMPANY_HISTORY_RECORD_FOUND"},
                {"project_id": "PROJ-2", "triage_closeout_state": "COMPANY_HISTORY_RECORD_FOUND"},
                {"project_id": "PROJ-3", "triage_closeout_state": "SOURCE_LIMIT_DEFERRED"},
            ],
            "original_notice_readback_records": [
                {"project_id": "PROJ-1", "triage_closeout_state": "OVERLAP_SIGNAL_REVIEW_REQUIRED"},
                {"project_id": "PROJ-2", "triage_closeout_state": "ORIGINAL_NOTICE_READBACK_REQUIRED"},
                {"project_id": "PROJ-4", "triage_closeout_state": "YGP_READBACK_BLOCKED_OR_UNSUPPORTED"},
                {"project_id": "PROJ-5", "triage_closeout_state": "NO_OVERLAP_SIGNAL_REVIEW"},
            ],
            "release_evidence_trigger_records": [
                {
                    "release_evidence_trigger_id": "TRIGGER-1",
                    "source_stage": "DATA_GGZY_BID_SHOW",
                    "project_id": "PROJ-1",
                    "project_name": "项目一",
                    "candidate_company_name": "广东甲公司",
                    "matched_person_names": ["张三"],
                    "historical_project_area_code": historical_project_area_code,
                    "historical_project_region_code": historical_project_region_code,
                    "source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
                    "extracted_period_text": "365日历天",
                    "extracted_award_date": "2026年05月01日",
                    "time_window_review_state": "TIME_WINDOW_OVERLAP_REVIEW",
                    "estimated_performance_end_date": "2027-05-01",
                    "release_evidence_source_targets": [
                        "construction_permit",
                        "contract_filing_or_contract_credit_info",
                        "completion_or_acceptance_filing",
                        "project_manager_change_notice",
                    ],
                    "release_evidence_probe_triggered": True,
                    "suggested_next_step": "targeted_release_evidence_probe",
                }
            ],
        },
        "summary": {
            "queried_company_count": 2,
            "bid_show_record_count": 2,
            "source_limit_deferred_count": 1,
            "original_notice_readback_required_count": 1,
            "release_evidence_trigger_count": 1,
            "ygp_readback_blocked_or_unsupported_count": 1,
        },
    }
    _write_json(root / "p13b-overlap-triage-closeout-v1.json", payload)


def _write_p12_input(root: Path) -> None:
    _write_json(
        root / "project-value-table.json",
        {
            "summary": {"project_count": 2},
            "records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20001",
                    "project_name": "广州道路工程施工中标候选人公示",
                    "value_closeout_state": "EXTERNAL_CONFLICT_SOURCE_REQUIRED",
                    "candidate_notice_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-a.html"],
                    "project_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-a.html"],
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "project_name": "广州桥梁工程施工中标候选人公示",
                    "value_closeout_state": "EXTERNAL_CONFLICT_SOURCE_REQUIRED",
                    "candidate_notice_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-b.html"],
                    "project_source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-b.html"],
                },
            ],
        },
    )
    _write_json(
        root / "candidate-group-verification-table.json",
        {
            "summary": {"candidate_group_count": 2},
            "records": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-20001",
                    "project_name": "广州道路工程施工中标候选人公示",
                    "candidate_group_id": "CANDIDATE-GROUP-1",
                    "candidate_group_members": ["广东甲公司"],
                    "responsible_person_name": "张三",
                    "certificate_no": "粤244000000000",
                    "source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-a.html"],
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-20002",
                    "project_name": "广州桥梁工程施工中标候选人公示",
                    "candidate_group_id": "CANDIDATE-GROUP-2",
                    "candidate_group_members": ["广东乙公司"],
                    "responsible_person_name": "李四",
                    "source_urls": ["https://ywtb.gzggzy.cn/jyfw/07-b.html"],
                },
            ],
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
