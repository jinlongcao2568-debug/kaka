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
    list_stage6_review_loop_status_table_options,
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
        self.assertEqual(projection["summary"]["owner_assignment_state_counts"], {"ASSIGNED_OWNER_READY": 3})
        self.assertEqual(projection["summary"]["assigned_owner_counts"], {"卡卡罗特": 3})
        self.assertEqual(projection["summary"]["unassigned_owner_count"], 0)

        rows = {row["project_id"]: row for row in projection["project_status_rows"]}
        self.assertEqual(rows["PROJ-A"]["owner_status_label"], "下一轮受控任务已准备")
        self.assertEqual(rows["PROJ-A"]["assigned_owner"], "卡卡罗特")
        self.assertEqual(rows["PROJ-A"]["assigned_owner_role"], "single_operator")
        self.assertEqual(rows["PROJ-A"]["owner_assignment_state"], "ASSIGNED_OWNER_READY")
        self.assertEqual(rows["PROJ-A"]["project_owner_label"], "single_operator：卡卡罗特")
        self.assertTrue(rows["PROJ-A"]["automated_dispatch_available"])
        self.assertEqual(rows["PROJ-A"]["current_stage"], "Stage4_ORIGINAL_NOTICE_BACKTRACE")
        self.assertEqual(rows["PROJ-A"]["blocker_reason"], "not_blocked_controlled_dispatch_ready")
        self.assertEqual(rows["PROJ-A"]["evidence_grade"], "GRADE_NOT_PROJECTED_TO_STATUS_TABLE")
        self.assertIn("未投影证据等级", rows["PROJ-A"]["evidence_grade_label"])
        self.assertEqual(
            rows["PROJ-B"]["manual_hold_reason"],
            "terminal_source_gap_no_delta_manual_review_only",
        )
        self.assertEqual(rows["PROJ-B"]["current_stage"], "Stage4_ORIGINAL_NOTICE_BACKTRACE")
        self.assertEqual(rows["PROJ-B"]["evidence_grade"], "D_INSUFFICIENT_OR_BLOCKED_READBACK")
        self.assertIn("证据不足", rows["PROJ-B"]["evidence_grade_label"])
        self.assertEqual(rows["PROJ-B"]["blocker_reason"], "terminal_source_gap_no_delta_manual_review_only")
        self.assertIn("人工复核", rows["PROJ-B"]["blocker_reason_label"])
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
        self.assertEqual(
            rows["PROJ-C"]["release_field_query_authorization_state_counts"],
            {"LOGIN_OR_SSO_REQUIRED": 1},
        )
        self.assertEqual(
            rows["PROJ-C"]["release_field_query_authorized_session_input_state_counts"],
            {"NO_AUTHORIZED_SESSION_INPUT": 1},
        )
        self.assertEqual(
            rows["PROJ-C"]["release_field_query_operator_next_actions"],
            ["provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"],
        )
        self.assertEqual(
            rows["PROJ-C"]["release_field_query_source_hit_summary_labels"],
            ["广东建设信息网三库一平台匿名公开源；样例人员：王先耀；证书：粤1332006200810171；施工许可：441900202206061001"],
        )
        self.assertEqual(projection["summary"]["release_field_query_source_hit_summary_count"], 1)
        self.assertIn(
            "提供 GDCIC 已授权浏览器会话后重跑。",
            rows["PROJ-C"]["release_field_query_operator_next_action_labels"],
        )
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
            self.assertEqual(projection["batch_option_count"], 2)
            self.assertTrue(projection["batch_selector_visible"])
            self.assertTrue(projection["multi_batch_review_available"])
            self.assertTrue(projection["multi_project_batch_available"])
            self.assertEqual(projection["selected_batch_index"], 0)
            self.assertEqual(projection["batch_options"][0]["project_count"], 3)
            self.assertEqual(projection["batch_options"][0]["batch_id"], "latest")
            self.assertEqual(projection["batch_default_selection_strategy"], "LATEST_STATUS_TABLE")

    def test_loader_defaults_to_latest_multi_project_batch_over_newer_single_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            single = root / "newer-single-terminal" / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            multi = root / "older-three-project-overview" / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            single_payload = _status_table_payload()
            single_payload["records"] = single_payload["records"][:1]
            _write_json(single, single_payload)
            _write_json(multi, _status_table_payload())
            os.utime(multi, (1, 1))
            os.utime(single, (2, 2))

            projection = load_stage6_review_loop_operator_projection(search_root=root)

            self.assertTrue(str(projection["source_path"]).endswith(str(multi)))
            self.assertEqual(projection["summary"]["project_count"], 3)
            self.assertEqual(projection["selected_batch_index"], 1)
            self.assertFalse(projection["selected_batch_is_latest"])
            self.assertEqual(projection["latest_batch_option"]["batch_id"], "newer-single-terminal")
            self.assertEqual(projection["latest_batch_option"]["project_count"], 1)
            self.assertEqual(
                projection["batch_default_selection_strategy"],
                "LATEST_MULTI_PROJECT_OVERVIEW_OVER_NEWER_SINGLE_PROJECT_TERMINAL",
            )
            self.assertIn("默认优先显示最新多项目批次", projection["batch_default_selection_label"])

    def test_release_field_query_gap_counts_as_blocked_review_with_chinese_labels(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-D",
                        "project_name": "D project",
                        "loop_terminal_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                        "next_recommended_action": (
                            "record_release_evidence_gap_or_retry_jurisdiction_source_without_clearance_claim"
                        ),
                        "release_field_query_state": "RELEASE_FIELD_QUERY_GAP_OR_BLOCKER_REVIEW",
                        "release_field_query_downstream_abcd_grade_counts": {
                            "D_INSUFFICIENT_OR_BLOCKED_READBACK": 4
                        },
                        "release_field_query_authorization_state_counts": {"LOGIN_OR_SSO_REQUIRED": 1},
                        "release_field_query_authorized_session_input_state_counts": {
                            "NO_AUTHORIZED_SESSION_INPUT": 1
                        },
                        "release_field_query_operator_next_actions": [
                            "do_not_treat_http_dynamic_stealthy_as_login_state_replacement",
                        ],
                    }
                ],
            },
            created_at="2026-05-19T12:00:00+08:00",
        )

        self.assertEqual(projection["summary"]["blocked_or_manual_review_count"], 1)
        row = projection["project_status_rows"][0]
        self.assertIn("释放证据字段查询仍是缺口", row["owner_status_label"])
        self.assertIn("不能写成已排除风险", row["owner_next_action_label"])
        self.assertIn(
            "不要把 HTTP/Dynamic/Stealthy 当作登录态替代",
            row["release_field_query_operator_next_action_labels"][0],
        )

    def test_public_field_readback_review_state_has_distinct_label(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-PUBLIC-READBACK",
                        "project_name": "Public readback project",
                        "loop_terminal_state": "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
                        "next_recommended_action": "manual_review_public_field_readback_before_stage7_preview",
                        "release_field_query_state": "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
                        "release_field_query_adapter_result_state_counts": {"MATCHED": 1},
                    }
                ],
            },
            created_at="2026-05-20T12:00:00+08:00",
        )

        row = projection["project_status_rows"][0]
        self.assertIn("公开源字段已有读回", row["owner_status_label"])
        self.assertIn("补齐证据等级", row["owner_next_action_label"])

    def test_stage5_calibration_review_samples_are_owner_readable(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-STAGE5-CAL",
                        "project_name": "Stage5 calibration project",
                        "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                        "next_recommended_action": "manual_review_or_new_source_override_required_before_retry",
                        "stage5_rule_gate_status": "PASS",
                        "stage5_evidence_gate_status": "PASS",
                        "stage5_calibration_sample_id": "STAGE5-CALIBRATION-SAMPLE-1",
                        "stage5_calibration_review_bucket": "POTENTIAL_FALSE_POSITIVE_REVIEW",
                        "stage5_calibration_review_reasons": [
                            "stage5_passed_while_stage4_or_runtime_gap_still_exists",
                            "missing_stage4_5_source_type:contract_public_info",
                        ],
                        "calibration_truth_label_required": True,
                        "suggested_calibration_action": (
                            "review_stage5_pass_against_stage4_source_gap_before_rule_relaxation"
                        ),
                    }
                ],
            },
            created_at="2026-05-24T12:00:00+08:00",
        )

        self.assertEqual(projection["summary"]["stage5_calibration_sample_count"], 1)
        self.assertEqual(projection["summary"]["stage5_calibration_truth_label_required_count"], 1)
        self.assertEqual(
            projection["summary"]["stage5_calibration_review_bucket_counts"],
            {"POTENTIAL_FALSE_POSITIVE_REVIEW": 1},
        )
        self.assertIn(
            "review_stage5_calibration_samples_before_rule_change",
            projection["operator_decision"]["next_actions"],
        )
        self.assertIn(
            "先复核 Stage5 校准样本",
            " ".join(projection["operator_decision"]["next_action_labels"]),
        )
        row = projection["project_status_rows"][0]
        self.assertEqual(row["current_stage"], "Stage5_RULE_GATE_CALIBRATION")
        self.assertIn("规则门/证据门真实样本校准", row["current_stage_label"])
        self.assertIn("潜在误放", row["stage5_calibration_review_bucket_label"])
        self.assertIn("Stage5 通过时仍存在 Stage4 来源缺口", row["stage5_calibration_review_reason_labels"][0])
        self.assertIn("contract_public_info", row["stage5_calibration_review_reason_labels"][1])
        self.assertTrue(row["stage5_calibration_truth_label_required"])
        self.assertIn("是否冲突", row["stage5_calibration_suggested_action_label"])
        self.assertEqual(row["stage5_calibration_gate_status_label"], "规则门：PASS；证据门：PASS。")

    def test_browser_authorized_project_manager_change_summary_is_owner_readable(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-BROWSER-PM-CHANGE",
                        "project_name": "Browser project manager change",
                        "loop_terminal_state": "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
                        "next_recommended_action": "manual_review_public_field_readback_before_stage7_preview",
                        "release_field_query_state": "RELEASE_FIELD_QUERY_PUBLIC_READBACK_REVIEW_READY",
                        "release_field_query_adapter_result_state_counts": {"MATCHED": 1},
                        "release_field_query_downstream_abcd_grade_counts": {
                            "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 1
                        },
                        "release_field_query_source_hit_summaries": [
                            {
                                "source_profile_id": "GUANGDONG-GDCIC-HOME",
                                "source_specific_adapter_id": "guangdong_gdcic_browser_authorized_readback_v1",
                                "source_label": "广东建设信息网三库一平台授权浏览器读回",
                                "match_state": "MATCHED_AUTHORIZED_BROWSER_READBACK",
                                "original_project_manager_names": ["张三"],
                                "new_project_manager_names": ["李四"],
                                "project_manager_change_dates": ["2026-01-15"],
                                "project_manager_change_interpretations": [
                                    "ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"
                                ],
                                "pii_redaction_state": "ID_CARD_HASH_OR_REDACTED_ONLY",
                            }
                        ],
                        "release_field_query_source_hit_summary_labels": [
                            (
                                "广东建设信息网三库一平台授权浏览器读回；原项目经理：张三；"
                                "新项目经理：李四；变更日期：2026-01-15；"
                                "窗口解释：ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"
                            )
                        ],
                    }
                ],
            },
            created_at="2026-05-24T12:00:00+08:00",
        )

        self.assertEqual(projection["summary"]["release_field_query_source_hit_summary_count"], 1)
        row = projection["project_status_rows"][0]
        self.assertIn("公开源字段已有读回", row["owner_status_label"])
        self.assertEqual(
            row["release_field_query_source_hit_summary_labels"],
            [
                (
                    "广东建设信息网三库一平台授权浏览器读回；原项目经理：张三；"
                    "新项目经理：李四；变更日期：2026-01-15；"
                    "窗口解释：ORIGINAL_MANAGER_CHANGED_OUT_REVIEW_REQUIRED"
                )
            ],
        )
        self.assertEqual(
            row["release_field_query_source_hit_summaries"][0]["match_state"],
            "MATCHED_AUTHORIZED_BROWSER_READBACK",
        )
        text = json.dumps(projection, ensure_ascii=False)
        for forbidden in ("无风险", "无冲突", "确认本人", "违法成立", "造假成立", "是不是本人"):
            self.assertNotIn(forbidden, text)

    def test_original_readback_imported_states_are_owner_readable(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-ORIG-READY",
                        "project_name": "Original ready project",
                        "loop_terminal_state": "RELEASE_EVIDENCE_QUERY_READY_FROM_ORIGINAL_READBACK",
                        "next_recommended_action": "build_release_evidence_regional_adapter_plan",
                    },
                    {
                        "project_id": "PROJ-ORIG-RETRY",
                        "project_name": "Original retry project",
                        "loop_terminal_state": "NEXT_ORIGINAL_READBACK_SUBQUEUE_READY",
                        "next_recommended_action": "run_next_live_original_notice_backtrace_batch",
                    },
                    {
                        "project_id": "PROJ-ORIG-HOLD",
                        "project_name": "Original hold project",
                        "loop_terminal_state": "ORIGINAL_READBACK_MANUAL_HOLD",
                        "next_recommended_action": "park_without_clearance_claim",
                    },
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        self.assertEqual(projection["summary"]["automated_dispatch_available_count"], 2)
        rows = {row["project_id"]: row for row in projection["project_status_rows"]}
        self.assertIn("原文读回已具备释放证据下一步", rows["PROJ-ORIG-READY"]["owner_status_label"])
        self.assertIn("释放证据计划", rows["PROJ-ORIG-READY"]["owner_next_action_label"])
        self.assertTrue(rows["PROJ-ORIG-READY"]["automated_dispatch_available"])
        self.assertIn("原文读回下一子队列已准备", rows["PROJ-ORIG-RETRY"]["owner_status_label"])
        self.assertIn("原文回溯", rows["PROJ-ORIG-RETRY"]["owner_next_action_label"])
        self.assertTrue(rows["PROJ-ORIG-RETRY"]["automated_dispatch_available"])
        self.assertIn("原文读回停在人工复核", rows["PROJ-ORIG-HOLD"]["owner_status_label"])
        self.assertIn("保留事实，不输出排除性结论", rows["PROJ-ORIG-HOLD"]["owner_next_action_label"])
        self.assertFalse(rows["PROJ-ORIG-HOLD"]["automated_dispatch_available"])

    def test_original_readback_blocked_actions_have_chinese_labels(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-ORIG-BLOCKED-URL",
                        "project_name": "Original blocked url project",
                        "loop_terminal_state": "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
                        "next_recommended_action": (
                            "manual_review_missing_or_invalid_original_notice_url_without_clearance_claim"
                        ),
                    },
                    {
                        "project_id": "PROJ-ORIG-BLOCKED-FETCH",
                        "project_name": "Original blocked fetch project",
                        "loop_terminal_state": "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
                        "next_recommended_action": (
                            "manual_review_or_route_specific_readback_without_clearance_claim"
                        ),
                    },
                    {
                        "project_id": "PROJ-ORIG-BLOCKED-TARGETED",
                        "project_name": "Original blocked targeted project",
                        "loop_terminal_state": "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
                        "next_recommended_action": (
                            "manual_review_or_retry_targeted_person_readback_without_clearance_claim"
                        ),
                    },
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        rows = {row["project_id"]: row for row in projection["project_status_rows"]}
        self.assertIn("原文链接缺失或无效", rows["PROJ-ORIG-BLOCKED-URL"]["owner_next_action_label"])
        self.assertIn("路由专用读回", rows["PROJ-ORIG-BLOCKED-FETCH"]["owner_next_action_label"])
        self.assertIn("责任人定向读回", rows["PROJ-ORIG-BLOCKED-TARGETED"]["owner_next_action_label"])

    def test_status_table_options_summarize_multi_project_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            single = root / "single" / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            multi = root / "multi-project" / STAGE6_REVIEW_LOOP_STATUS_TABLE_FILENAME
            single_payload = _status_table_payload()
            single_payload["records"] = single_payload["records"][:1]
            _write_json(single, single_payload)
            _write_json(multi, _status_table_payload())
            os.utime(single, (1, 1))
            os.utime(multi, (2, 2))

            options = list_stage6_review_loop_status_table_options(root)

            self.assertEqual(len(options), 2)
            self.assertEqual(options[0]["batch_id"], "multi-project")
            self.assertEqual(options[0]["project_count"], 3)
            self.assertEqual(
                options[0]["project_ids"],
                ["PROJ-A", "PROJ-B", "PROJ-C"],
            )
            self.assertEqual(options[0]["manual_hold_count"], 1)
            self.assertEqual(options[0]["operator_batch_state_label"], "有项目可继续受控续跑")

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
            self.assertEqual(payload["batch_option_count"], 1)
            self.assertEqual(payload["batch_options"][0]["project_count"], 3)
            self.assertEqual(payload["selected_batch_index"], 0)
            self.assertTrue(payload["batch_selector_visible"])
            self.assertFalse(payload["live_execution_enabled"])
            self.assertFalse(payload["external_release_enabled"])
            self.assertFalse(payload["real_provider_call_enabled"])
            self.assertFalse(payload["automated_refund_enabled"])

    def test_runtime_blocker_ledger_projects_owner_readable_source_trace(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-BLOCKER-LABEL",
                        "project_name": "Blocker label project",
                        "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                        "next_recommended_action": "manual_review_or_new_source_override_required_before_retry",
                        "runtime_blocker_ledger_records": [
                            {
                                "blocker_ledger_id": "RUNTIME-BLOCKER-LABEL",
                                "ledger_scope": "stage6_review_loop",
                                "task_scope": "p13b_follow_up",
                                "task_type": "SOURCE_GAP_TARGETED_RETRY_OR_MANUAL_REVIEW",
                                "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                                "blocker_reason": "p13b_operational_closeout_marker_present",
                                "runtime_layer": "controller decision",
                                "source_ledger_scopes": [
                                    "stage6_review_action_plan",
                                    "stage6_review_loop",
                                ],
                                "source_runtime_layers": ["controller decision", "closeout"],
                                "required_input": ["operator_retry_budget", "continuation_budget_reason"],
                                "retry_policy": "retry_only_after_budget_increase_or_new_source",
                                "reopen_conditions": ["operator_override_records_scope_budget_and_reason"],
                                "operator_next_action": "operator_confirms_higher_budget_before_retry",
                            }
                        ],
                        "runtime_blocker_ledger_state_counts": {
                            "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1
                        },
                        "runtime_blocker_ledger_layer_counts": {"controller decision": 1},
                    }
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        self.assertEqual(
            projection["summary"]["runtime_blocker_ledger_scope_counts"],
            {"stage6_review_action_plan": 1, "stage6_review_loop": 1},
        )
        blocker = projection["project_status_rows"][0]["runtime_blocker_ledger_records"][0]
        self.assertEqual(blocker["ledger_scope_label"], "Stage6 复核循环")
        self.assertEqual(blocker["task_scope_label"], "P13B 历史重叠续跑")
        self.assertIn("已抑制重复派发", blocker["blocker_state_label"])
        self.assertEqual(blocker["runtime_layer_label"], "controller 判定")
        self.assertEqual(
            blocker["source_ledger_scope_labels"],
            ["Stage6 动作计划", "Stage6 复核循环"],
        )
        self.assertEqual(
            blocker["source_runtime_layer_labels"],
            ["controller 判定", "closeout 收口"],
        )
        self.assertEqual(
            blocker["required_input_labels"],
            ["操作者确认的续跑预算", "续跑预算原因"],
        )
        self.assertIn("增加预算", blocker["retry_policy_label"])
        self.assertEqual(blocker["operator_next_action_label"], "操作者确认提高预算后再重试。")
        self.assertIn("同一阻断已由Stage6 动作计划和Stage6 复核循环记录", blocker["source_trace_label"])

    def test_original_readback_retry_blocker_labels_are_owner_readable(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-ORIG-RETRY-LABEL",
                        "project_name": "Original retry label project",
                        "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                        "next_recommended_action": (
                            "operator_reviews_retry_budget_or_keeps_original_readback_suspended"
                        ),
                        "next_cycle_dispatch_block_reason": "original_notice_backtrace_budget_deferred_or_incomplete",
                        "runtime_blocker_ledger_records": [
                            {
                                "blocker_ledger_id": "BLK-ORIG-RETRY-LABEL-1",
                                "ledger_scope": "p13b_original_readback",
                                "task_scope": "original_readback",
                                "task_type": "p13b_original_notice_backtrace",
                                "blocker_state": "ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED",
                                "blocker_reason": "original_notice_backtrace_budget_deferred_or_incomplete",
                                "runtime_layer": "retry policy",
                                "required_input": ["next_original_notice_backtrace_budget_or_new_source_snapshot"],
                                "retry_policy": "retry_next_original_backtrace_batch_with_bounded_budget",
                                "reopen_conditions": [
                                    "bounded_original_notice_backtrace_budget_available",
                                    "new_machine_readable_original_notice_source_available",
                                ],
                                "operator_next_action": (
                                    "operator_reviews_retry_budget_or_keeps_original_readback_suspended"
                                ),
                                "next_action": "run_next_live_original_notice_backtrace_batch",
                            }
                        ],
                        "runtime_blocker_ledger_state_counts": {
                            "ORIGINAL_READBACK_RETRY_OR_CONTINUATION_QUEUED": 1
                        },
                        "runtime_blocker_ledger_layer_counts": {"retry policy": 1},
                    }
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        blocker = projection["project_status_rows"][0]["runtime_blocker_ledger_records"][0]
        self.assertEqual(
            blocker["blocker_state_label"],
            "原文回溯重试/续跑已入队，需等预算或新来源满足后再继续。",
        )
        self.assertEqual(
            projection["project_status_rows"][0]["blocker_reason_label"],
            "原文回溯预算不足或本轮预算已耗尽，需补预算或新来源后继续。",
        )
        self.assertEqual(
            blocker["retry_policy_label"],
            "只在拿到下一批原文回溯预算或新的官方原文来源后继续。",
        )
        self.assertEqual(
            blocker["required_input_labels"],
            ["下一批原文回溯预算或新的官方原文来源快照"],
        )
        self.assertEqual(
            blocker["reopen_condition_labels"],
            [
                "已拿到下一批原文回溯预算。",
                "已补到新的机器可读原文来源。",
            ],
        )
        self.assertEqual(
            blocker["operator_next_action_label"],
            "操作者复核原文回溯预算，或继续保持原文读回挂起。",
        )

    def test_original_readback_action_labels_are_consistent_across_owner_and_blocker_views(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-ORIG-READY-BLOCKER",
                        "project_name": "Original ready blocker project",
                        "loop_terminal_state": "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
                        "next_recommended_action": "build_release_evidence_regional_adapter_plan",
                        "runtime_blocker_ledger_records": [
                            {
                                "blocker_ledger_id": "BLK-ORIG-READY-BLOCKER-1",
                                "ledger_scope": "p13b_original_readback",
                                "task_scope": "original_readback",
                                "task_type": "p13b_original_notice_backtrace",
                                "blocker_state": "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH",
                                "blocker_reason": "terminal_source_gap_no_delta_manual_review_only",
                                "runtime_layer": "closeout",
                                "required_input": ["operator_override_reason_or_new_machine_readable_input"],
                                "retry_policy": "do_not_retry_same_worker_without_new_input_or_operator_override",
                                "reopen_conditions": [
                                    "new_machine_readable_input_artifact_available",
                                    "prior_blocker_resolved_without_clearance_claim",
                                    "operator_override_records_scope_budget_and_reason",
                                ],
                                "operator_next_action": "build_release_evidence_regional_adapter_plan",
                                "next_action": "build_release_evidence_regional_adapter_plan",
                            }
                        ],
                        "runtime_blocker_ledger_state_counts": {
                            "TERMINAL_CLOSEOUT_SUPPRESSED_DUPLICATE_DISPATCH": 1
                        },
                        "runtime_blocker_ledger_layer_counts": {"closeout": 1},
                    },
                    {
                        "project_id": "PROJ-ORIG-RETRY-ACTION",
                        "project_name": "Original retry action project",
                        "loop_terminal_state": "MANUAL_REVIEW_HOLD_NO_AUTOMATED_DISPATCH",
                        "next_recommended_action": (
                            "operator_reviews_retry_budget_or_keeps_original_readback_suspended"
                        ),
                    },
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        rows = {row["project_id"]: row for row in projection["project_status_rows"]}
        self.assertEqual(
            rows["PROJ-ORIG-READY-BLOCKER"]["owner_next_action_label"],
            "基于当前原文读回，继续生成释放证据计划。",
        )
        self.assertEqual(
            rows["PROJ-ORIG-READY-BLOCKER"]["runtime_blocker_ledger_records"][0]["operator_next_action_label"],
            "基于当前原文读回，继续生成释放证据计划。",
        )
        self.assertEqual(
            rows["PROJ-ORIG-READY-BLOCKER"]["runtime_blocker_ledger_records"][0]["reopen_condition_labels"],
            [
                "已补到新的机器可读输入 artifact。",
                "前一轮阻断已解决，但不能写成排除性结论。",
                "操作者已记录 override 范围、预算和原因。",
            ],
        )
        self.assertEqual(
            rows["PROJ-ORIG-RETRY-ACTION"]["owner_next_action_label"],
            "操作者复核原文回溯预算，或继续保持原文读回挂起。",
        )

    def test_original_readback_continuation_states_have_chinese_blocker_reason_labels(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-ORIG-BLOCKED-CODE",
                        "project_name": "Original blocked code project",
                        "loop_terminal_state": "ORIGINAL_READBACK_BLOCKER_LEDGER_REVIEW",
                        "next_recommended_action": (
                            "manual_review_or_route_specific_readback_without_clearance_claim"
                        ),
                        "next_cycle_dispatch_block_reason": "BLOCKED_OR_SOURCE_UNSUPPORTED",
                    },
                    {
                        "project_id": "PROJ-ORIG-LOWVALUE-CODE",
                        "project_name": "Original low-value code project",
                        "loop_terminal_state": "ORIGINAL_READBACK_MANUAL_HOLD",
                        "next_recommended_action": "park_or_targeted_readback_if_value_justifies",
                        "next_cycle_dispatch_block_reason": "LOW_VALUE_COMPANY_ONLY_REVIEW",
                    },
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        rows = {row["project_id"]: row for row in projection["project_status_rows"]}
        self.assertEqual(
            rows["PROJ-ORIG-BLOCKED-CODE"]["blocker_reason_label"],
            "原文来源受阻或入口不受支持，需人工复核或改走定向读回。",
        )
        self.assertEqual(
            rows["PROJ-ORIG-LOWVALUE-CODE"]["blocker_reason_label"],
            "当前只有公司级弱信号，需暂存或在价值足够时转定向读回。",
        )

    def test_runtime_blocker_worker_followup_queue_is_owner_readable(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-FOLLOWUP",
                        "project_name": "Follow-up project",
                        "assigned_owner": "卡卡罗特",
                        "assigned_owner_role": "single_operator",
                        "loop_terminal_state": "RUNTIME_BLOCKER_WORKER_FOLLOWUP_READY",
                        "next_recommended_action": (
                            "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill"
                        ),
                        "runtime_blocker_worker_followup_records": [
                            {
                                "runtime_blocker_followup_task_id": "RUNTIME-BLOCKER-FOLLOWUP-1",
                                "source_runtime_blocker_dispatch_runner_task_id": "RUNNER-TASK-1",
                                "project_id": "PROJ-FOLLOWUP",
                                "project_name": "Follow-up project",
                                "assigned_owner": "卡卡罗特",
                                "assigned_owner_role": "single_operator",
                                "formal_entrypoint_id": "guangdong_local_field_query_probe",
                                "followup_task_type": (
                                    "RUN_GUANGDONG_LOCAL_FIELD_QUERY_WITH_GDCIC_BROWSER_READBACK"
                                ),
                                "followup_readiness_state": "READY_FOR_CONTROLLED_FIELD_QUERY_BACKFILL",
                                "recommended_script": "scripts/run-guangdong-local-field-query-probe-v1.ps1",
                                "recommended_command_argv": [
                                    "pwsh",
                                    "-File",
                                    "scripts/run-guangdong-local-field-query-probe-v1.ps1",
                                    "-GdcicBrowserReadbackJson",
                                    "tmp/readback/gdcic-browser-authorized-readback-v1.json",
                                ],
                                "release_evidence_adapter_plan_json": (
                                    "tmp/plan/release-evidence-adapter-plan-v1.json"
                                ),
                                "gdcic_browser_readback_json": (
                                    "tmp/readback/gdcic-browser-authorized-readback-v1.json"
                                ),
                                "expected_output_artifact": "guangdong-local-field-query-probe-v1.json",
                                "output_root": "tmp/out/followup-field-query/PROJ-FOLLOWUP",
                                "next_action": (
                                    "run_guangdong_local_field_query_probe_then_stage6_review_loop_backfill"
                                ),
                                "execution_mode": "PLAN_ONLY_NOT_EXECUTED",
                                "live_execution_enabled": False,
                                "requires_operator_action_before_live": True,
                                "requires_operator_approval_before_execution": True,
                                "customer_visible_allowed": False,
                                "no_legal_conclusion": True,
                                "query_miss_is_not_clearance": True,
                            }
                        ],
                    }
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        self.assertEqual(projection["surface_state"], "ACTION_READY")
        self.assertEqual(projection["summary"]["runtime_blocker_worker_followup_count"], 1)
        self.assertEqual(projection["summary"]["runtime_blocker_worker_followup_project_count"], 1)
        self.assertEqual(
            projection["summary"]["runtime_blocker_worker_followup_entrypoint_counts"],
            {"guangdong_local_field_query_probe": 1},
        )
        self.assertEqual(
            projection["summary"]["runtime_blocker_worker_followup_readiness_state_counts"],
            {"READY_FOR_CONTROLLED_FIELD_QUERY_BACKFILL": 1},
        )
        row = projection["project_status_rows"][0]
        self.assertEqual(row["current_stage"], "Stage4_RELEASE_EVIDENCE_FIELD_QUERY")
        self.assertIn("阻断 worker 已产出", row["owner_status_label"])
        self.assertIn("字段查询回灌", row["owner_next_action_label"])
        self.assertTrue(row["runtime_blocker_worker_followup_available"])
        self.assertEqual(row["runtime_blocker_worker_followup_count"], 1)
        followup = row["runtime_blocker_worker_followup_records"][0]
        self.assertEqual(followup["formal_entrypoint_id"], "guangdong_local_field_query_probe")
        self.assertEqual(followup["formal_entrypoint_label"], "广东本地释放证据字段查询")
        self.assertIn("受控字段查询回灌输入", followup["followup_readiness_state_label"])
        self.assertTrue(followup["recommended_command_available"])
        self.assertFalse(followup["live_execution_enabled"])
        self.assertIn("tmp/plan/release-evidence-adapter-plan-v1.json", followup["input_artifact_refs"])
        self.assertIn("tmp/readback/gdcic-browser-authorized-readback-v1.json", followup["input_artifact_refs"])
        self.assertIn("tmp/out/followup-field-query/PROJ-FOLLOWUP", followup["output_artifact_refs"])
        self.assertTrue(followup["requires_operator_approval_before_execution"])
        self.assertIn(
            "run_ready_worker_followup_or_keep_operator_hold",
            projection["operator_decision"]["next_actions"],
        )
        text = json.dumps(projection, ensure_ascii=False)
        for forbidden in ("无风险", "无冲突", "确认本人", "违法成立", "造假成立", "是不是本人"):
            self.assertNotIn(forbidden, text)

    def test_missing_project_owner_is_machine_readable_operator_action(self) -> None:
        projection = build_stage6_review_loop_operator_projection(
            {
                "summary": {},
                "records": [
                    {
                        "project_id": "PROJ-UNASSIGNED",
                        "project_name": "Unassigned project",
                        "loop_terminal_state": "NEXT_CYCLE_DISPATCH_READY",
                        "next_recommended_action": "run_next_cycle_dispatch_or_keep_internal_review_dry_run",
                    }
                ],
            },
            created_at="2026-05-23T12:00:00+08:00",
        )

        self.assertEqual(
            projection["summary"]["owner_assignment_state_counts"],
            {"UNASSIGNED_OWNER_REVIEW_REQUIRED": 1},
        )
        row = projection["project_status_rows"][0]
        self.assertEqual(row["project_owner_label"], "待分配 owner")
        self.assertEqual(row["owner_assignment_required_inputs"], ["assigned_owner", "assigned_owner_role"])
        self.assertEqual(
            row["owner_assignment_next_action"],
            "assign_project_owner_before_next_runtime_cycle",
        )
        self.assertIn("分配项目 owner", row["owner_assignment_next_action_label"])


def _status_table_payload() -> dict:
    return {
        "summary": {
            "operator_assignment_roster": {
                "stage6": {
                    "assigned_owner": "卡卡罗特",
                    "assigned_owner_role": "single_operator",
                    "reviewer": "卡卡罗特",
                    "reviewer_role": "single_operator",
                }
            },
            "operator_assignment_roster_source_ref": "control/operator_assignment_roster_defaults.yaml#defaults",
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
                "release_field_query_authorized_session_input_state_counts": {
                    "NO_AUTHORIZED_SESSION_INPUT": 1
                },
                "release_field_query_authorization_state_counts": {"LOGIN_OR_SSO_REQUIRED": 1},
                "release_field_query_operator_next_actions": [
                    "provide_gdcic_authorized_storage_state_or_user_data_dir_then_rerun"
                ],
                "release_field_query_source_hit_summaries": [
                    {
                        "source_profile_id": "GUANGDONG-GDCIC-SKYPT-OPENPLATFORM",
                        "source_specific_adapter_id": "guangdong_gdcic_openplatform_public_api_query_v1",
                        "source_label": "广东建设信息网三库一平台匿名公开源",
                        "match_state": "MATCHED_PUBLIC_READBACK",
                        "matched_person_names": ["王先耀"],
                        "sample_certificate_nos": ["粤1332006200810171"],
                        "sample_permit_codes": ["441900202206061001"],
                        "pii_redaction_state": "ID_CARD_HASH_OR_REDACTED_ONLY",
                    }
                ],
                "release_field_query_source_hit_summary_labels": [
                    "广东建设信息网三库一平台匿名公开源；样例人员：王先耀；证书：粤1332006200810171；施工许可：441900202206061001"
                ],
            },
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
