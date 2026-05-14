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

from storage.company_first_stage4_execution import build_company_first_stage4_execution  # noqa: E402


def _provider_jobs_payload() -> dict[str, object]:
    return {
        "manifest_kind": "stage4_provider_jobs",
        "jobs": [
            {
                "job_id": "STAGE4-JOB-ALPHA",
                "provider_id": "JZSC_PERSON_IDENTITY",
                "provider_role": "person_company_certificate_identity",
                "payload": {
                    "provider_id": "JZSC_PERSON_IDENTITY",
                    "provider_role": "person_company_certificate_identity",
                    "target": {
                        "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
                        "candidate_company_name": "Alpha Construction Co",
                        "responsible_person_name": "陈庆丽",
                        "certificate_no_optional": "",
                        "person_public_id_optional": "",
                    },
                    "source_probe_item": {
                        "project_id": "PROJ-CN-GD-JG2026-00001",
                        "project_name": "测试候选公示",
                        "source_07_detail_path": "projects/CN-GD/PROJ-CN-GD-JG2026-00001/07/detail/detail.html",
                    },
                },
                "status": "QUEUED_NOT_EXECUTED",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        ],
    }


def _write_jobs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "stage4_provider_jobs.json").write_text(
        json.dumps(_provider_jobs_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class CompanyFirstStage4ExecutionTest(unittest.TestCase):
    def test_dry_run_keeps_provider_task_ready_without_live_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_root = Path(temp_dir) / "input"
            output_root = Path(temp_dir) / "out"
            _write_jobs(input_root)

            result = build_company_first_stage4_execution(
                input_root=input_root,
                output_root=output_root,
                execute=False,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["stage4_execution_state"], "QUEUED_NOT_EXECUTED")
        self.assertEqual(item["supplement_after_execution_state"], "COMPANY_FIRST_PROVIDER_TASKS_READY")
        self.assertEqual(result["summary"]["stage4_input_count"], 0)
        self.assertFalse(result["execution"]["stage4_live_provider_enabled"])

    def test_matched_browser_result_generates_stage4_input(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            self.assertEqual(
                capture_plan["capture_plan_type"],
                "JZSC_COMPANY_FIRST_PROJECT_MANAGER_VERIFICATION",
            )
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
                "personnel_project_source_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
                "matched_company_name_optional": "Alpha Construction Co",
                "matched_company_public_id_optional": "alpha",
                "rendered_company_personnel_rows": [
                    {
                        "row_text": "1 陈庆丽 372929**********69 一级注册建造师 鲁1372017201820810",
                        "detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
                        "person_public_id": "person-chen-qingli",
                        "registered_unit_name": "Alpha Construction Co",
                        "registration_at": "2025-01-01",
                        "certificate_valid_until": "2027-12-31",
                    }
                ],
                "rendered_personnel_project_rows": [],
                "failure_reasons": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            input_root = Path(temp_dir) / "input"
            output_root = Path(temp_dir) / "out"
            _write_jobs(input_root)

            result = build_company_first_stage4_execution(
                input_root=input_root,
                output_root=output_root,
                execute=True,
                browser_runner=fake_browser_runner,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["stage4_execution_state"], "READBACK_READY")
        self.assertEqual(item["supplement_after_execution_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")
        self.assertEqual(item["resolved_certificate_no_optional"], "鲁1372017201820810")
        self.assertEqual(result["summary"]["stage4_input_count"], 1)
        self.assertEqual(
            result["manifest"]["stage4_candidate_verification_inputs"]["items"][0]["certificate_no"],
            "鲁1372017201820810",
        )
        self.assertTrue(result["execution"]["stage4_live_provider_enabled"])

    def test_same_company_same_name_multiple_certificates_generates_stage4_input(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=chenggong",
                "matched_company_name_optional": "北京诚公管理咨询有限公司",
                "matched_company_public_id_optional": "chenggong",
                "rendered_company_personnel_rows": [
                    {
                        "row_text": "1 苑晓东 130633**********75 注册监理工程师 11015464",
                        "registered_unit_name": "北京诚公管理咨询有限公司",
                    },
                    {
                        "row_text": "2 苑晓东 130633**********75 一级注册建造师 京1112021202203391",
                        "registered_unit_name": "北京诚公管理咨询有限公司",
                    },
                ],
                "rendered_personnel_project_rows": [],
                "failure_reasons": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            input_root = Path(temp_dir) / "input"
            output_root = Path(temp_dir) / "out"
            _write_jobs(input_root)
            jobs_path = input_root / "stage4_provider_jobs.json"
            payload = json.loads(jobs_path.read_text(encoding="utf-8"))
            target = payload["jobs"][0]["payload"]["target"]
            target["opportunity_priority_class"] = "B_HIGH_SUPERVISION"
            target["candidate_company_name"] = "北京诚公管理咨询有限公司"
            target["responsible_person_name"] = "苑晓东"
            jobs_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            result = build_company_first_stage4_execution(
                input_root=input_root,
                output_root=output_root,
                execute=True,
                browser_runner=fake_browser_runner,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["supplement_after_execution_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")
        self.assertEqual(item["required_registration_category_optional"], "注册监理工程师")
        self.assertEqual(item["resolved_certificate_no_optional"], "11015464")
        self.assertEqual(result["summary"]["stage4_input_count"], 1)

    def test_design_survey_field_level_readback_resolves_without_default_builder_category(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            self.assertEqual(capture_plan["required_registration_category_optional"], None)
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=design",
                "matched_company_name_optional": "广东省建筑设计研究院集团股份有限公司",
                "matched_company_public_id_optional": "design",
                "rendered_company_personnel_rows": [
                    {
                        "row_text": "1 区展辉 440100**********01 注册建筑师 4401373-274",
                        "detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-ou",
                        "person_public_id": "person-ou",
                        "registered_unit_name": "广东省建筑设计研究院集团股份有限公司",
                    }
                ],
                "rendered_personnel_project_rows": [],
                "failure_reasons": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "out"
            inputs_path = Path(temp_dir) / "inputs.json"
            inputs_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "project_id": "PROJ-CN-GD-JG2026-11109",
                                "project_name": "勘察、方案设计及初步设计候选公示",
                                "candidate_company_name": "广东省建筑设计研究院集团股份有限公司",
                                "candidate_group_id": "GROUP-DESIGN",
                                "candidate_group_members": ["广东省建筑设计研究院集团股份有限公司"],
                                "responsible_person_name": "区展辉",
                                "responsible_role": "design_lead",
                                "certificate_no": "",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_company_first_stage4_execution(
                input_root=Path(temp_dir) / "missing-jobs",
                output_root=output_root,
                stage4_inputs_json=inputs_path,
                execute=True,
                browser_runner=fake_browser_runner,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["required_registration_category_optional"], "")
        self.assertEqual(item["supplement_after_execution_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")
        self.assertEqual(item["resolved_certificate_no_optional"], "4401373-274")
        self.assertTrue(item["certificate_category_review_required"])
        self.assertEqual(item["candidate_group_resolution_state"], "RESOLVED_BY_THIS_MEMBER")
        self.assertEqual(result["summary"]["stage4_input_count"], 1)

    def test_no_rendered_rows_goes_to_name_enumeration_not_final_conflict(self) -> None:
        def fake_blocked_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": str(capture_plan.get("entry_url") or ""),
                "rendered_company_personnel_rows": [],
                "failure_reasons": ["project_manager_not_found_by_company_name_person_name_after_2_attempts"],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            input_root = Path(temp_dir) / "input"
            output_root = Path(temp_dir) / "out"
            _write_jobs(input_root)

            result = build_company_first_stage4_execution(
                input_root=input_root,
                output_root=output_root,
                execute=True,
                browser_runner=fake_blocked_runner,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["stage4_execution_state"], "FAIL_CLOSED")
        self.assertEqual(item["supplement_after_execution_state"], "NAME_ENUMERATION_FALLBACK_REQUIRED")
        self.assertIn("RUN_NAME_ENUMERATION_FALLBACK", item["next_actions"])
        self.assertEqual(result["summary"]["stage4_input_count"], 0)
        self.assertTrue(item["no_name_only_final_proof"])

    def test_exhausted_name_enumeration_requires_flow08_targeted_parse(self) -> None:
        def fake_exhausted_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": str(capture_plan.get("entry_url") or ""),
                "rendered_company_personnel_rows": [],
                "failure_reasons": ["project_manager_not_found_by_company_name_person_name_after_2_attempts"],
                "browser_attempts": [
                    {
                        "attempt_type": "person_search_name_only_paginated_company_filter",
                        "result_count": 2,
                        "matched_count": 0,
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            input_root = Path(temp_dir) / "input"
            output_root = Path(temp_dir) / "out"
            _write_jobs(input_root)

            result = build_company_first_stage4_execution(
                input_root=input_root,
                output_root=output_root,
                execute=True,
                browser_runner=fake_exhausted_runner,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["supplement_after_execution_state"], "FLOW_08_TARGETED_PARSE_REQUIRED")
        self.assertEqual(
            item["stage4_readiness_state"],
            "STAGE4_BLOCKED_COMPANY_FIRST_AND_NAME_ENUMERATION_NO_MATCH",
        )
        self.assertTrue(item["flow_08_targeted_parse_required"])
        self.assertIn("FLOW_08_TARGETED_PARSE", item["next_actions"])

    def test_stage4_inputs_can_be_executed_with_light_company_normalization(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            self.assertEqual(capture_plan["target"]["company_name"], "广东水电二局集团有限公司")
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=gdsd",
                "matched_company_name_optional": "广东水电二局集团有限公司",
                "matched_company_public_id_optional": "gdsd",
                "rendered_company_personnel_rows": [
                    {
                        "row_text": "1 彭耀聪 440100**********01 一级注册建造师 粤1442024202500740",
                        "detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-peng",
                        "person_public_id": "person-peng",
                        "registered_unit_name": "广东水电二局集团有限公司",
                    }
                ],
                "rendered_personnel_project_rows": [],
                "failure_reasons": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "out"
            inputs_path = Path(temp_dir) / "inputs.json"
            inputs_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "project_id": "PROJ-CN-GD-JG2026-11029",
                                "project_name": "候选公示",
                                "candidate_company_name": "3家：(主)广东水电二局集团有限公司",
                                "responsible_person_name": "彭耀聪",
                                "certificate_no": "粤1442024202500740",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_company_first_stage4_execution(
                input_root=Path(temp_dir) / "missing-jobs",
                output_root=output_root,
                stage4_inputs_json=inputs_path,
                execute=True,
                browser_runner=fake_browser_runner,
            )

        item = result["manifest"]["items"][0]
        self.assertEqual(item["candidate_company_name"], "广东水电二局集团有限公司")
        self.assertEqual(item["supplement_after_execution_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")

    def test_consortium_group_is_resolved_when_any_member_matches(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            company = capture_plan["target"]["company_name"]
            if company == "北京神州新桥科技有限公司":
                return {
                    "browser_runner_id": "fake-jzsc-browser",
                    "live_browser_executed": True,
                    "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=shenzhou",
                    "matched_company_name_optional": "北京神州新桥科技有限公司",
                    "matched_company_public_id_optional": "shenzhou",
                    "rendered_company_personnel_rows": [
                        {
                            "row_text": "1 王立亮 110100**********01 一级注册建造师 京1112017201745983",
                            "detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-wang",
                            "person_public_id": "person-wang",
                            "registered_unit_name": "北京神州新桥科技有限公司",
                        }
                    ],
                    "rendered_personnel_project_rows": [],
                    "failure_reasons": [],
                }
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": str(capture_plan.get("entry_url") or ""),
                "rendered_company_personnel_rows": [],
                "failure_reasons": ["project_manager_not_found_by_company_name_person_name_after_2_attempts"],
                "browser_attempts": [
                    {
                        "attempt_type": "person_search_name_only_paginated_company_filter",
                        "result_count": 1,
                        "matched_count": 0,
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "out"
            inputs_path = Path(temp_dir) / "inputs.json"
            members = ["云浮市易安停科技有限公司", "中裕工程集团有限公司", "北京神州新桥科技有限公司"]
            inputs_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "project_id": "PROJ-CN-GD-JG2026-11260",
                                "project_name": "候选公示",
                                "candidate_company_name": company,
                                "candidate_group_id": "CANDIDATE-GROUP-11260-1",
                                "candidate_group_order": 1,
                                "candidate_group_members": members,
                                "consortium_member_role": "member",
                                "responsible_person_name": "王立亮",
                                "certificate_no": "京1112017201745983",
                            }
                            for company in members
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_company_first_stage4_execution(
                input_root=Path(temp_dir) / "missing-jobs",
                output_root=output_root,
                stage4_inputs_json=inputs_path,
                execute=True,
                browser_runner=fake_browser_runner,
            )

        items = result["manifest"]["items"]
        by_company = {item["candidate_company_name"]: item for item in items}
        self.assertEqual(
            by_company["北京神州新桥科技有限公司"]["candidate_group_resolution_state"],
            "RESOLVED_BY_THIS_MEMBER",
        )
        self.assertEqual(
            by_company["云浮市易安停科技有限公司"]["candidate_group_resolution_state"],
            "RESOLVED_BY_CONSORTIUM_MEMBER",
        )
        self.assertFalse(by_company["云浮市易安停科技有限公司"]["flow_08_targeted_parse_required"])
        self.assertEqual(result["summary"]["candidate_group_resolved_count"], 1)
        self.assertEqual(result["summary"]["stage4_input_count"], 1)

    def test_consortium_group_resolves_when_lead_has_field_level_readback_and_member_misses(self) -> None:
        def fake_browser_runner(capture_plan: dict[str, object]) -> dict[str, object]:
            company = capture_plan["target"]["company_name"]
            if company == "中图设计有限公司":
                return {
                    "browser_runner_id": "fake-jzsc-browser",
                    "live_browser_executed": True,
                    "company_personnel_source_url": "https://jzsc.mohurd.gov.cn/data/company/detail?id=zhongtu",
                    "matched_company_name_optional": "中图设计有限公司",
                    "matched_company_public_id_optional": "zhongtu",
                    "rendered_company_personnel_rows": [
                        {
                            "row_text": "1 林杰 520100**********01 注册建筑师 5200794-014",
                            "person_public_id": "person-linjie",
                            "registered_unit_name": "中图设计有限公司",
                        }
                    ],
                    "rendered_personnel_project_rows": [],
                    "failure_reasons": [],
                }
            return {
                "browser_runner_id": "fake-jzsc-browser",
                "live_browser_executed": True,
                "company_personnel_source_url": str(capture_plan.get("entry_url") or ""),
                "rendered_company_personnel_rows": [],
                "failure_reasons": ["project_manager_not_found_by_company_name_person_name_after_2_attempts"],
                "browser_attempts": [
                    {
                        "attempt_type": "person_search_name_only_paginated_company_filter",
                        "result_count": 1,
                        "matched_count": 0,
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "out"
            inputs_path = Path(temp_dir) / "inputs.json"
            members = ["中图设计有限公司", "鸿儒勘测设计有限公司"]
            inputs_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "project_id": "PROJ-CN-GD-JG2026-11259",
                                "project_name": "勘察和初步设计候选公示",
                                "candidate_company_name": company,
                                "candidate_group_id": "GROUP-11259-1",
                                "candidate_group_order": 1,
                                "candidate_group_members": members,
                                "consortium_member_role": "lead" if company == "中图设计有限公司" else "member",
                                "responsible_person_name": "林杰",
                                "responsible_role": "design_lead",
                                "certificate_no": "",
                            }
                            for company in members
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_company_first_stage4_execution(
                input_root=Path(temp_dir) / "missing-jobs",
                output_root=output_root,
                stage4_inputs_json=inputs_path,
                execute=True,
                browser_runner=fake_browser_runner,
            )

        by_company = {item["candidate_company_name"]: item for item in result["manifest"]["items"]}
        self.assertEqual(by_company["中图设计有限公司"]["candidate_group_resolution_state"], "RESOLVED_BY_THIS_MEMBER")
        self.assertEqual(by_company["鸿儒勘测设计有限公司"]["candidate_group_resolution_state"], "RESOLVED_BY_CONSORTIUM_MEMBER")
        self.assertFalse(by_company["鸿儒勘测设计有限公司"]["flow_08_targeted_parse_required"])
        self.assertEqual(result["summary"]["candidate_group_resolved_count"], 1)

    def test_can_filter_stage4_inputs_by_candidate_group_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "out"
            inputs_path = Path(temp_dir) / "inputs.json"
            inputs_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "project_id": "PROJ-CN-GD-JG2026-11260",
                                "project_name": "候选公示",
                                "candidate_company_name": "云浮市易安停科技有限公司",
                                "candidate_group_id": "GROUP-KEEP",
                                "candidate_group_members": ["云浮市易安停科技有限公司"],
                                "responsible_person_name": "王立亮",
                                "certificate_no": "京1112017201745983",
                            },
                            {
                                "project_id": "PROJ-CN-GD-JG2026-11260",
                                "project_name": "候选公示",
                                "candidate_company_name": "云浮市锐宝投资有限公司",
                                "candidate_group_id": "GROUP-SKIP",
                                "candidate_group_members": ["云浮市锐宝投资有限公司"],
                                "responsible_person_name": "侯延强",
                                "certificate_no": "鲁1372021202201811",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_company_first_stage4_execution(
                input_root=Path(temp_dir) / "missing-jobs",
                output_root=output_root,
                stage4_inputs_json=inputs_path,
                candidate_group_ids=["GROUP-KEEP"],
                execute=False,
            )

        self.assertEqual(result["summary"]["job_count"], 1)
        self.assertEqual(result["manifest"]["items"][0]["candidate_group_id"], "GROUP-KEEP")


if __name__ == "__main__":
    unittest.main()
