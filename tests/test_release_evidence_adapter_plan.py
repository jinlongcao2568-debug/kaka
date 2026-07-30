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

from storage.release_evidence_adapter_plan import build_release_evidence_adapter_plan  # noqa: E402


class ReleaseEvidenceAdapterPlanTests(unittest.TestCase):
    def test_normalizes_four_release_evidence_targets_into_b_c_adapter_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            summary = result["summary"]
            self.assertEqual(summary["project_plan_count"], 2)
            self.assertEqual(summary["adapter_task_count"], 4)
            self.assertEqual(
                summary["adapter_task_target_type_counts"],
                {
                    "completion_acceptance": 1,
                    "construction_permit": 1,
                    "contract_performance": 1,
                    "project_manager_change_notice": 1,
                },
            )
            self.assertEqual(
                summary["adapter_task_grade_on_match_counts"],
                {
                    "B_ENHANCEMENT_OFFICIAL_READBACK": 2,
                    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 2,
                },
            )
            task_by_type = {
                task["release_evidence_target_type"]: task
                for task in result["manifest"]["release_evidence_adapter_task_records"]
            }
            self.assertEqual(task_by_type["construction_permit"]["release_evidence_grade_on_match"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertEqual(task_by_type["contract_performance"]["release_evidence_grade_on_match"], "B_ENHANCEMENT_OFFICIAL_READBACK")
            self.assertEqual(task_by_type["completion_acceptance"]["release_evidence_grade_on_match"], "C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
            self.assertEqual(task_by_type["project_manager_change_notice"]["release_evidence_grade_on_match"], "C_REVERSE_EXPLANATION_OFFICIAL_READBACK")
            self.assertEqual(
                result["manifest"]["execution_priority_policy"]["release_evidence_query_region_rule"],
                "HISTORICAL_OVERLAP_PROJECT_JURISDICTION_FIRST",
            )
            self.assertTrue(
                result["manifest"]["execution_priority_policy"][
                    "release_evidence_follows_historical_overlap_project_jurisdiction"
                ]
            )
            self.assertEqual(
                result["manifest"]["execution_priority_policy"]["current_project_mainline_priority_region_code"],
                "CN-GD",
            )
            self.assertTrue(
                all(
                    task["allowed_adapter_result_states"] == ["MATCHED", "NOT_FOUND", "BLOCKED", "NEEDS_BROWSER"]
                    for task in task_by_type.values()
                )
            )
            self.assertTrue(all(task["query_miss_is_not_clearance"] for task in task_by_type.values()))
            self.assertTrue((root / "out" / "release-evidence-adapter-plan-v1.json").exists())
            self.assertTrue((root / "out" / "release-evidence-adapter-task-table.json").exists())

    def test_non_a_closeout_does_not_generate_release_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            plans = _records_by_project(result["manifest"]["project_release_evidence_plan_records"])
            self.assertEqual(plans["PROJ-D"]["release_evidence_project_plan_state"], "NO_A_SIGNAL_RELEASE_EVIDENCE_NOT_PLANNED")
            self.assertNotIn(
                "PROJ-D",
                {task["project_id"] for task in result["manifest"]["release_evidence_adapter_task_records"]},
            )

    def test_terminal_release_marker_suppresses_duplicate_release_evidence_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch", include_release_terminal_marker=True)
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["adapter_task_count"], 0)
            self.assertEqual(result["summary"]["runtime_blocker_ledger_count"], 0)
            self.assertEqual(result["summary"]["runtime_blocker_ledger_state_counts"], {})
            plan = _records_by_project(result["manifest"]["project_release_evidence_plan_records"])["PROJ-A"]
            self.assertEqual(
                plan["release_evidence_project_plan_state"],
                "RELEASE_EVIDENCE_TERMINAL_CLOSEOUT_SUPPRESSED",
            )
            self.assertTrue(plan["closeout_precedence_suppressed"])
            self.assertEqual(plan["closeout_precedence_state"], "SUPPRESS_TERMINAL_CLOSEOUT")
            self.assertEqual(
                plan["recommended_next_action"],
                "project_to_review_ready_status_projection_without_duplicate_dispatch",
            )
            self.assertEqual(plan["runtime_blocker_ledger_record"], {})
            self.assertEqual(plan["runtime_blocker_ledger_records"], [])
            self.assertEqual(
                plan["operator_projection"]["projection_state"],
                "RELEASE_EVIDENCE_TERMINAL_STATUS_PROJECTION",
            )
            self.assertEqual(
                plan["operator_projection"]["next_action"],
                "project_to_review_ready_status_projection_without_duplicate_dispatch",
            )
            self.assertFalse(result["manifest"]["release_evidence_adapter_task_records"])

    def test_non_guangdong_region_and_local_housing_scope_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b", region_code="CN-ZJ")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            task = result["manifest"]["release_evidence_adapter_task_records"][0]
            self.assertEqual(task["local_housing_authority_adapter_scope"], "HISTORICAL_PROJECT_JURISDICTION")
            self.assertEqual(task["local_housing_authority_adapter_region_code"], "CN-ZJ")
            self.assertEqual(task["release_evidence_query_region_rule"], "HISTORICAL_OVERLAP_PROJECT_JURISDICTION_FIRST")
            self.assertTrue(task["release_evidence_follows_historical_overlap_project_jurisdiction"])
            self.assertTrue(task["do_not_force_release_evidence_to_current_project_region"])
            self.assertEqual(task["current_project_mainline_priority_region_code"], "CN-GD")
            self.assertTrue(task["cross_region_information_checks_allowed"])
            self.assertIn("performance_public_record", task["cross_region_information_source_types"])
            self.assertIn("administrative_penalty_public_record", task["cross_region_information_source_types"])
            self.assertEqual(
                task["non_guangdong_release_adapter_rule"],
                "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER",
            )
            self.assertEqual(task["jurisdiction_adapter_resolution_state"], "JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(result["summary"]["local_housing_region_counts"]["CN-ZJ"], 4)
            self.assertEqual(
                result["summary"]["jurisdiction_adapter_resolution_state_counts"],
                {"JURISDICTION_LOCAL_HOUSING_ADAPTER_PLANNED": 4},
            )

    def test_non_guangdong_registry_fills_source_fields_for_plan_only_stub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b", region_code="CN-ZJ", include_source_fields=False)

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            task = result["manifest"]["release_evidence_adapter_task_records"][0]
            self.assertEqual(task["source_profile_id"], "ZHEJIANG-JZSC-PUBLIC-SERVICE")
            self.assertEqual(task["source_entry_id"], "ZJ-JZSC-PUBLIC-SERVICE")
            self.assertEqual(task["next_adapter"], "zhejiang_construction_market_public_service_query_adapter")
            self.assertTrue(task["no_fallback_to_guangdong_or_guangzhou"])
            self.assertEqual(
                task["jurisdiction_local_housing_adapter"]["source_selection_scope"],
                "HISTORICAL_PROJECT_JURISDICTION",
            )

    def test_project_code_candidates_from_p13b_task_top_level_are_preserved_in_query_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            numeric_project_code = "440100202605190001"
            ygp_project_code = "441900029-2025-00741"
            bucket_project_code = "E4401002701502243001"
            investment_project_code = "2605-440100-04-01-000001"
            enterprise_credit_code = "914400001903237820"
            certificate_no = "粤1332006200810171"
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")
            p13b_path = root / "p13b" / "p13b-operational-closeout-v1.json"
            payload = json.loads(p13b_path.read_text(encoding="utf-8"))
            task = payload["manifest"]["release_evidence_probe_task_records"][0]
            task["project_code_candidates"] = ["JG2026-11337"]
            task["data_ggzy_bid_show_records"] = [
                {
                    "source_url": f"https://data.ggzy.gov.cn/yjcx/index/bid_show?id=abc&projectCode={numeric_project_code}",
                    "project_no": ygp_project_code,
                    "detail": {"proofOrSerialCode": investment_project_code},
                    "unifiedSocialCreditCode": enterprise_credit_code,
                    "certificateNo": certificate_no,
                }
            ]
            task["guangdong_ygp_flow_matrix"] = {
                "manifest": {
                    "ygp_flow_bucket_records": [
                        {
                            "limited_readback": {
                                "nodeList": [
                                    {
                                        "detail": {
                                            "projectCode": bucket_project_code,
                                            "projectName": "广州历史重叠项目",
                                        },
                                        "dsList": [
                                            {
                                                "项目编号": ygp_project_code,
                                                "项目代码": investment_project_code,
                                                "统一社会信用代码": enterprise_credit_code,
                                                "证书编号": certificate_no,
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    ],
                    "ygp_flow_item_records": [
                        {
                            "resolved_project_route": {
                                "projectCode": ygp_project_code,
                                "siteCode": "441900",
                                "bizCode": "3871",
                            }
                        }
                    ],
                }
            }
            task["source_refs"] = {
                "stage6": {
                    "parsed_field_refs": [
                        {"field_name": "项目代码", "field_value_optional": numeric_project_code},
                        {"field_name": "统一社会信用代码", "field_value_optional": enterprise_credit_code},
                    ]
                }
            }
            p13b_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            task = result["manifest"]["release_evidence_adapter_task_records"][0]
            params = task["query_params"]
            self.assertEqual(params["projectCode"], numeric_project_code)
            self.assertEqual(
                params["projectCodeVariants"],
                [
                    "JG2026-11337",
                    numeric_project_code,
                    ygp_project_code,
                    investment_project_code,
                    bucket_project_code,
                ],
            )
            self.assertEqual(
                params["gdcicProjectCodeVariants"],
                [numeric_project_code, ygp_project_code, bucket_project_code],
            )
            self.assertEqual(params["tradeProjectCode"], "JG2026-11337")
            self.assertNotIn(enterprise_credit_code, params["projectCodeVariants"])
            self.assertNotIn(certificate_no, params["projectCodeVariants"])
            self.assertNotIn(enterprise_credit_code, params["gdcicProjectCodeVariants"])
            self.assertNotIn(certificate_no, params["gdcicProjectCodeVariants"])
            recall = result["summary"]["stage4_release_adapter_plan_project_code_recall_summary"]
            self.assertEqual(recall["project_code_recall_state"], "GDCIC_PROJECT_CODE_VARIANTS_PRESENT")
            self.assertEqual(recall["adapter_task_count"], 4)
            self.assertEqual(recall["with_gdcic_project_code_variant_task_count"], 2)
            self.assertEqual(recall["missing_gdcic_project_code_variant_task_count"], 2)
            self.assertEqual(recall["with_trade_project_code_task_count"], 2)
            self.assertTrue(recall["gdcic_project_code_route_ready"])
            self.assertTrue(recall["jg_trade_code_not_sent_to_gdcic_project_code"])
            self.assertIn(numeric_project_code, recall["sample_gdcic_project_code_variants"])
            self.assertIn("JG2026-11337", recall["sample_trade_project_codes"])

    def test_a_signal_without_source_tasks_is_explicitly_plan_required_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=None,
                output_root=root / "out",
            )

            plans = _records_by_project(result["manifest"]["project_release_evidence_plan_records"])
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(plans["PROJ-A"]["release_evidence_project_plan_state"], "RELEASE_EVIDENCE_SOURCE_PLAN_REQUIRED")
            self.assertEqual(result["summary"]["adapter_task_count"], 0)

    def test_output_keeps_internal_safety_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_batch_closeout(root / "batch")
            _write_p13b_operational(root / "p13b")

            result = build_release_evidence_adapter_plan(
                batch_closeout_root=root / "batch",
                p13b_operational_closeout_root=root / "p13b",
                output_root=root / "out",
            )

            text = json.dumps(result, ensure_ascii=False)
            self.assertFalse(result["manifest"]["customer_visible_allowed"])
            self.assertTrue(result["manifest"]["no_legal_conclusion"])
            self.assertTrue(result["manifest"]["query_miss_is_not_clearance"])
            for term in ("确认本人", "无风险", "无冲突", "违法成立", "造假成立", "是不是本人"):
                self.assertNotIn(term, text)
            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_sha256"], _fingerprint_without_manifest_sha(manifest))


def _write_batch_closeout(root: Path, *, include_release_terminal_marker: bool = False) -> None:
    records = [
        {
            "project_id": "PROJ-A",
            "project_name": "A 项目",
            "closeout_state": "PROMOTE_STAGE6_STAGE7_INTERNAL_PREVIEW",
            "evidence_state": "A_STRONG_TIME_OVERLAP_SIGNAL_READY",
            "evidence_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
            "next_action_label": "build_release_evidence_regional_adapter_plan_and_stage6_fact_package",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
            **(
                {
                    "terminal_closeout_markers": [
                        {
                            "task_family": "release_evidence_query",
                            "marker_state": "MATCHED",
                            "artifact_ref": "tmp/field-query/guangdong-local-field-query-probe-v1.json",
                        }
                    ]
                }
                if include_release_terminal_marker
                else {}
            ),
        },
        {
            "project_id": "PROJ-D",
            "project_name": "D 项目",
            "closeout_state": "PARK_D_INSUFFICIENT_OR_BLOCKED",
            "evidence_state": "D_INSUFFICIENT_OR_BLOCKED_READBACK",
            "evidence_grade": "D_EVIDENCE_INSUFFICIENT",
            "next_action_label": "park_or_manual_review_without_clearance_claim",
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "query_miss_is_not_clearance": True,
        },
    ]
    _write_json(
        root / "evidence-batch-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "BATCH-1",
                "closeout_records": records,
                "summary": {"project_count": 2},
            }
        },
    )


def _write_p13b_operational(root: Path, *, region_code: str = "CN-GD", include_source_fields: bool = True) -> None:
    non_gd_rule = (
        "NON_GUANGDONG_HISTORY_PROJECT_USE_JURISDICTION_LOCAL_HOUSING_AUTHORITY_ADAPTER"
        if region_code != "CN-GD"
        else ""
    )
    plan = {
        "release_evidence_probe_plan_id": "PLAN-A",
        "project_id": "PROJ-A",
        "project_name": "A 项目",
        "release_evidence_query_region_code": region_code,
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "local_housing_authority_adapter_scope": "HISTORICAL_PROJECT_JURISDICTION",
        "local_housing_authority_adapter_region_code": region_code,
        "non_guangdong_release_adapter_rule": non_gd_rule,
    }
    tasks = [
        _task(
            task_id="TASK-A-BC",
            target_types=["construction_permit", "contract_public_info"],
            subsource_id="permit_contract_public",
            region_code=region_code,
            non_gd_rule=non_gd_rule,
            include_source_fields=include_source_fields,
        ),
        _task(
            task_id="TASK-A-CC",
            target_types=["completion_filing", "project_manager_change_notice"],
            subsource_id="completion_change_public",
            region_code=region_code,
            non_gd_rule=non_gd_rule,
            include_source_fields=include_source_fields,
        ),
    ]
    _write_json(
        root / "p13b-operational-closeout-v1.json",
        {
            "manifest": {
                "manifest_id": "P13B-OPERATIONAL-1",
                "release_evidence_probe_plan_records": [plan],
                "release_evidence_probe_task_records": tasks,
                "summary": {"release_evidence_probe_task_count": len(tasks)},
            }
        },
    )


def _task(
    *,
    task_id: str,
    target_types: list[str],
    subsource_id: str,
    region_code: str,
    non_gd_rule: str,
    include_source_fields: bool = True,
) -> dict[str, Any]:
    row = {
        "release_evidence_probe_task_id": task_id,
        "release_evidence_probe_plan_id": "PLAN-A",
        "project_id": "PROJ-A",
        "project_name": "A 项目",
        "candidate_company_name": "A 公司",
        "matched_person_names": ["张三"],
        "matched_target_source_types": target_types,
        "canonical_release_evidence_source_targets": target_types,
        "initial_release_evidence_abcd_grade": "A_STRONG_TIME_OVERLAP_SIGNAL",
        "release_evidence_query_region_code": region_code,
        "release_evidence_query_region_basis": "HISTORICAL_OVERLAP_PROJECT_REGION",
        "local_housing_authority_adapter_scope": "HISTORICAL_PROJECT_JURISDICTION",
        "local_housing_authority_adapter_region_code": region_code,
        "non_guangdong_release_adapter_rule": non_gd_rule,
        "trigger_source_url": "https://data.ggzy.gov.cn/yjcx/index/bid_show?id=1",
        "query_params": {
            "projectName": "A 项目",
            "candidateCompanyName": "A 公司",
            "projectManagerName": "张三",
        },
        "runtime_status": "PLAN_ONLY_UNTIL_REGION_ADAPTER_VERIFIED",
    }
    if include_source_fields:
        row.update(
            {
                "source_entry_id": "LOCAL-HOUSING",
                "subsource_id": subsource_id,
                "source_profile_id": "LOCAL-HOUSING-PROFILE",
                "source_name": "地方住建公开源",
                "source_url": "https://example.test/local-housing",
                "next_adapter": "local_housing_authority_release_evidence_adapter_required",
            }
        )
    return row


def _records_by_project(records: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(record["project_id"]): record for record in records}


def _fingerprint_without_manifest_sha(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
