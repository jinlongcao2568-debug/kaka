from __future__ import annotations

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

from storage.design_survey_flow08_targeted_readback import (  # noqa: E402
    build_design_survey_flow08_targeted_readback,
)


class DesignSurveyFlow08TargetedReadbackTests(unittest.TestCase):
    def test_dry_run_keeps_flow08_as_targeted_not_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_root = root / "plan"
            stage4_root = root / "stage4"
            _write_plan(plan_root)
            _write_stage4_flow08_required(stage4_root)

            result = build_design_survey_flow08_targeted_readback(
                design_survey_adapter_plan_root=plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                created_at="2026-05-18T20:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(
                result["summary"]["flow08_readback_state_counts"],
                {"FLOW08_TARGETED_READBACK_READY_NOT_EXECUTED": 1},
            )
            record = result["manifest"]["flow08_targeted_readback_table"]["records"][0]
            self.assertEqual(record["target_attachment_records"], [])
            self.assertFalse(result["manifest"]["safety"]["download_enabled"])
            self.assertTrue(result["manifest"]["scope_guardrails"]["do_not_parse_all_flow_08_by_default"])

    def test_execute_binds_only_target_consortium_attachment_without_default_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_root = root / "plan"
            stage4_root = root / "stage4"
            _write_plan(plan_root)
            _write_stage4_flow08_required(stage4_root)

            result = build_design_survey_flow08_targeted_readback(
                design_survey_adapter_plan_root=plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                execute=True,
                created_at="2026-05-18T20:00:00+08:00",
                flow08_discoverer=_fake_discoverer,
                detail_fetcher=_fake_detail_fetcher,
            )

            self.assertEqual(
                result["summary"]["flow08_readback_state_counts"],
                {"FLOW08_TARGET_ATTACHMENT_BOUND_DOWNLOAD_DEFERRED": 1},
            )
            attachments = result["manifest"]["target_attachment_table"]["records"]
            bound = [item for item in attachments if item["target_attachment_match_state"] == "TARGET_CANDIDATE_ATTACHMENT_BOUND"]
            self.assertEqual(len(bound), 1)
            self.assertEqual(bound[0]["attachment_url"], "https://jsgc.gzggzy.cn/download?AttachGuid=union")
            self.assertEqual(
                set(bound[0]["matched_target_company_names"]),
                {"广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"},
            )
            self.assertFalse(result["manifest"]["safety"]["download_enabled"])

    def test_execute_with_download_marks_target_attachment_fetched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_root = root / "plan"
            stage4_root = root / "stage4"
            _write_plan(plan_root)
            _write_stage4_flow08_required(stage4_root)

            result = build_design_survey_flow08_targeted_readback(
                design_survey_adapter_plan_root=plan_root,
                design_survey_stage4_execution_root=stage4_root,
                output_root=root / "out",
                execute=True,
                download_target_attachments=True,
                created_at="2026-05-18T20:00:00+08:00",
                flow08_discoverer=_fake_discoverer,
                detail_fetcher=_fake_detail_fetcher,
                attachment_fetcher=_fake_attachment_fetcher,
            )

            self.assertEqual(
                result["summary"]["flow08_readback_state_counts"],
                {"FLOW08_TARGET_ATTACHMENT_FETCHED": 1},
            )
            self.assertEqual(result["summary"]["target_attachment_fetched_project_count"], 1)
            bound = result["manifest"]["target_attachment_table"]["records"][0]
            self.assertEqual(bound["attachment_fetch_state"], "FETCHED")
            self.assertEqual(bound["attachment_fetch"]["attachment_filename"], "广州市城市规划勘测设计研究院有限公司.pdf")
            self.assertTrue(result["manifest"]["safety"]["download_enabled"])


def _write_plan(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    payload = {
        "manifest": {
            "project_table": {
                "records": [
                    {
                        "project_id": project_id,
                        "project_name": "广州南沙经济技术开发区建设中心2026-2029年度规划测绘项目中标候选人公示",
                        "candidate_company_text": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
                        "candidate_group_members": [
                            "广州市城市规划勘测设计研究院有限公司",
                            "广州湾区规划勘测设计院有限公司",
                        ],
                        "responsible_person_name": "胡昌华",
                    }
                ]
            }
        }
    }
    _write_json(root / "design-survey-responsible-adapter-plan-v1.json", payload)


def _write_stage4_flow08_required(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    members = ["广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"]
    items = [
        {
            "project_id": project_id,
            "project_name": "广州南沙经济技术开发区建设中心2026-2029年度规划测绘项目中标候选人公示",
            "candidate_company_name": company,
            "candidate_group_members": members,
            "responsible_person_name": "胡昌华",
            "stage4_execution_state": "FAIL_CLOSED",
            "supplement_after_execution_state": "FLOW_08_TARGETED_PARSE_REQUIRED",
            "flow_08_targeted_parse_required": True,
            "fail_closed_reasons": ["project_manager_not_found_by_company_name_person_name_after_1_attempts"],
        }
        for company in members
    ]
    _write_json(root / "company-first-stage4-execution.json", {"manifest": {"items": items}})


def _fake_discoverer(*, now: str, context: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "state": "FETCHED",
        "endpoint": "https://ywtb.gzggzy.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "items": [
            {
                "url": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/20260516/flow08_tb.html",
                "text": "广州南沙经济技术开发区建设中心2026-2029年度规划测绘项目[JG2026-11327]中标候选人投标文件公开",
            }
        ],
        "attempted_pages": 1,
        "record_count": 1,
        "process_attempts": [{"state": "FETCHED", "record_count": 1, "accepted_item_count": 1}],
    }


def _fake_detail_fetcher(*, url: str, project_id: str, lineage_refs: Mapping[str, str]) -> Mapping[str, Any]:
    return {
        "status": "FETCHED",
        "http_status": 200,
        "title": "Flow08",
        "detail_url": url,
        "final_url": url,
        "snapshot_id_optional": "SNAP-FLOW08",
        "same_site_attachment_link_items": [
            {"url": "https://jsgc.gzggzy.cn/download?AttachGuid=northwest", "text": "查看资料"},
            {"url": "https://jsgc.gzggzy.cn/download?AttachGuid=union", "text": "查看资料"},
            {"url": "https://jsgc.gzggzy.cn/download?AttachGuid=cccc", "text": "查看资料"},
        ],
        "raw_html_optional": """
        <table>
          <tr><td>西北综合勘察设计研究院</td><td><a href="https://jsgc.gzggzy.cn/download?AttachGuid=northwest">查看资料</a></td></tr>
          <tr><td>(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司</td><td><a href="https://jsgc.gzggzy.cn/download?AttachGuid=union">查看资料</a></td></tr>
          <tr><td>中交第四航务工程勘察设计院有限公司</td><td><a href="https://jsgc.gzggzy.cn/download?AttachGuid=cccc">查看资料</a></td></tr>
        </table>
        """,
    }


def _fake_attachment_fetcher(
    *,
    url: str,
    detail_url: str,
    project_id: str,
    lineage_refs: Mapping[str, str],
) -> Mapping[str, Any]:
    return {
        "status": "FETCHED",
        "content_type": "application/pdf",
        "attachment_filename": "广州市城市规划勘测设计研究院有限公司.pdf",
        "byte_size": 1234,
        "sha256": "abc123",
        "snapshot_id_optional": "SNAP-ATTACH",
        "degraded_reasons": [],
        "attachment_failure_taxonomy": [],
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
