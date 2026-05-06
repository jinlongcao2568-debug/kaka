from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.guangdong_gdcic_openplatform import (  # noqa: E402
    ADAPTER_ID,
    query_guangdong_gdcic_openplatform_hard_defect_sources,
    query_guangdong_gdcic_openplatform_person_directory,
)


def _fake_gdcic_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    endpoint = url.replace("https://skypt.gdcic.net/api", "")
    project_code = params.get("projectCode") or params.get("prjNum")
    if endpoint == "/openplatform/project/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "projectName": "广东市政道路工程",
                    "projectCode": "4401002605010001",
                    "orgName": "广州建设单位",
                }
            ],
        }
    if endpoint == "/openplatform/constructionPermit/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "projectName": "广东市政道路工程",
                    "projectCode": project_code,
                    "constructionPermitCode": "440100202605010101",
                }
            ],
        }
    if endpoint == "/openplatform/projectContract/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "projectName": "广东市政道路工程",
                    "projectCode": project_code,
                    "provinceContractCode": "4401002605010001-HZ-001",
                    "contractOrgName": "广东测试建设有限公司",
                }
            ],
        }
    if endpoint == "/openplatform/projectAcceptanceArchive/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "projectName": "广东市政道路工程",
                    "projectCode": project_code,
                    "provinceArchiveCode": "4401002605010001-JX-001",
                }
            ],
        }
    if endpoint == "/openplatform/finishCheck/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 0,
            "rows": [],
        }
    if endpoint == "/openplatform/memberInvolvedProject/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "projectName": "广东市政道路工程",
                    "projectCode": project_code,
                    "memberName": "张三",
                    "orgName": "广东测试建设有限公司",
                    "position": "项目经理",
                }
            ],
        }
    if endpoint == "/openplatform/performance/list":
        return {"msg": "success", "code": 0, "total": 0, "rows": []}
    if endpoint == "/openplatform/enterprisePunishment/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "entName": "广东测试建设有限公司",
                    "projectName": "广东市政道路工程",
                    "punishOrg": "广东省住房和城乡建设厅",
                    "punishTime": "2026-04-01",
                }
            ],
        }
    if endpoint == "/openplatform/enterpriseBackpay/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "entName": "广东测试建设有限公司",
                    "projectName": "广东市政道路工程",
                    "publishTime": "2026-03-24",
                }
            ],
        }
    if endpoint == "/openplatform/enterpriseBlacklist/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 0,
            "rows": [],
        }
    raise AssertionError(f"unexpected endpoint {endpoint}")


class GuangdongGdcicOpenplatformAdapterTests(unittest.TestCase):
    def test_queries_project_code_then_stage45_hard_defect_sources(self) -> None:
        readback = query_guangdong_gdcic_openplatform_hard_defect_sources(
            {
                "project_id": "PROJ-GD-001",
                "project_name": "广东市政道路工程",
                "candidate_company": "广东测试建设有限公司",
                "project_manager_name": "张三",
                "region_code": "CN-GD",
            },
            http_get_json=_fake_gdcic_get_json,
            now="2026-05-02T10:00:00+08:00",
        )

        self.assertEqual(readback["adapter_id"], ADAPTER_ID)
        self.assertEqual(readback["readback_state"], "READBACK_READY")
        self.assertEqual(readback["project_codes"], ["4401002605010001"])
        self.assertIn("construction_permit", readback["covered_source_types"])
        self.assertIn("contract_public_info", readback["covered_source_types"])
        self.assertIn("completion_filing", readback["covered_source_types"])
        self.assertIn("personnel_public_record", readback["covered_source_types"])
        identity_completion = readback["responsible_role_identity_completion"]
        self.assertEqual(
            identity_completion["completion_state"],
            "RESPONSIBLE_ROLE_CANDIDATE_FOUND",
        )
        self.assertEqual(identity_completion["identity_candidates"][0]["person_name"], "张三")
        self.assertEqual(identity_completion["identity_candidates"][0]["role_text"], "项目经理")
        self.assertEqual(
            identity_completion["next_action"],
            "write_back_responsible_role_then_run_company_first_identifier_resolution",
        )
        self.assertIn(
            "administrative_penalty_public_record",
            readback["covered_source_types"],
        )
        self.assertIn(
            "complaint_or_supervision_decision",
            readback["covered_source_types"],
        )
        self.assertIn("credit_penalty_blacklist", readback["queried_source_types"])
        blacklist = next(
            result
            for result in readback["source_results"]
            if result["query_role"] == "enterprise_blacklist_lookup"
        )
        self.assertEqual(blacklist["coverage_state"], "QUERY_REPLAYABLE_NO_MATCH")
        self.assertTrue(readback["no_no-risk_inference_without_sources"])

    def test_uses_guangdong_trade_source_url_project_code_before_name_lookup(self) -> None:
        requested_project_codes: list[str] = []

        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/project/list":
                return {"msg": "success", "code": 0, "total": 0, "rows": []}
            requested_project_codes.append(str(params.get("projectCode") or params.get("prjNum") or ""))
            if endpoint == "/openplatform/constructionPermit/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "projectName": "广东市政道路工程",
                            "projectCode": "E4401002701502243001",
                            "constructionPermitCode": "440100202605010101",
                        }
                    ],
                }
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        readback = query_guangdong_gdcic_openplatform_hard_defect_sources(
            {
                "project_id": "PROJ-GD-URL-CODE",
                "project_name": "广东市政道路工程",
                "candidate_company": "广东测试建设有限公司",
                "region_code": "CN-GD",
                "source_url": "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=abc&projectCode=E4401002701502243001&bizCode=3C42",
            },
            http_get_json=fake_get_json,
            now="2026-05-02T10:00:00+08:00",
        )

        self.assertEqual(readback["project_codes"][0], "E4401002701502243001")
        self.assertNotIn("gdcic_project_code_not_resolved", readback["failure_reasons"])
        self.assertIn("E4401002701502243001", requested_project_codes)
        self.assertIn("construction_permit", readback["covered_source_types"])

    def test_missing_project_name_fails_closed_without_broad_project_query(self) -> None:
        readback = query_guangdong_gdcic_openplatform_hard_defect_sources(
            {
                "project_id": "PROJ-GD-002",
                "candidate_company": "广东测试建设有限公司",
                "region_code": "CN-GD",
            },
            http_get_json=_fake_gdcic_get_json,
            now="2026-05-02T10:00:00+08:00",
        )

        self.assertIn(
            "project_name_missing_for_gdcic_project_lookup",
            readback["failure_reasons"],
        )
        self.assertNotIn("construction_permit", readback["queried_source_types"])
        self.assertNotIn("construction_permit", readback["covered_source_types"])

    def test_person_directory_flags_name_only_different_company(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/personIntoGd/list":
                return {"msg": "success", "code": 0, "total": 0, "rows": []}
            if endpoint == "/openplatform/personInGd/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "name": "*银刚",
                            "idNum": "**262819**********",
                            "entName": "深圳市新诚铭投资建设有限公司",
                            "entCode": "349924759",
                            "certificate": None,
                        }
                    ],
                }
            raise AssertionError(f"unexpected endpoint {endpoint}")

        readback = query_guangdong_gdcic_openplatform_person_directory(
            {
                "project_id": "JG2026-11125",
                "project_manager_name": "张银刚",
                "candidate_company": "中国水利水电第十四工程局有限公司",
                "project_manager_certificate_no": "云1532017201901042",
                "region_code": "CN-GD",
            },
            http_get_json=fake_get_json,
            now="2026-05-06T10:00:00+08:00",
        )

        self.assertEqual(
            readback["identity_resolution_state"],
            "LOCAL_DIRECTORY_SAME_COMPANY_PERSON_NOT_FOUND",
        )
        self.assertEqual(readback["same_company_candidate_count"], 0)
        self.assertEqual(readback["name_only_candidate_count"], 1)
        self.assertEqual(
            readback["certificate_verification_state"],
            "NOT_VERIFIED_BY_GDCIC_PERSON_DIRECTORY",
        )
        self.assertIn("gdcic_same_company_person_not_found", readback["failure_reasons"])
        self.assertIn(
            "gdcic_name_only_different_company_rows_present",
            readback["failure_reasons"],
        )
        self.assertIn(
            "announced_certificate_no_not_found_in_gdcic_person_directory_rows",
            readback["failure_reasons"],
        )
        self.assertTrue(readback["no_national_constructor_registration_substitute"])

    def test_person_directory_same_company_candidate_does_not_replace_certificate_lookup(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/personIntoGd/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "name": "*会甫",
                            "idNum": "**052519**********",
                            "entName": "中铁十八局集团有限公司",
                            "entCode": "10306009X",
                            "certificate": None,
                            "regStatus": "1",
                            "verifyStatus": "1",
                        }
                    ],
                }
            if endpoint == "/openplatform/personInGd/list":
                return {"msg": "success", "code": 0, "total": 0, "rows": []}
            raise AssertionError(f"unexpected endpoint {endpoint}")

        readback = query_guangdong_gdcic_openplatform_person_directory(
            {
                "project_id": "JG2026-11125",
                "project_manager_name": "李会甫",
                "candidate_company": "中铁十八局集团有限公司",
                "project_manager_certificate_no": "津1132018201900285",
                "region_code": "CN-GD",
            },
            http_get_json=fake_get_json,
            now="2026-05-06T10:00:00+08:00",
        )

        self.assertEqual(
            readback["identity_resolution_state"],
            "LOCAL_DIRECTORY_SAME_COMPANY_PERSON_CANDIDATE_FOUND",
        )
        self.assertEqual(readback["same_company_candidate_count"], 1)
        self.assertEqual(readback["same_company_candidates"][0]["entName"], "中铁十八局集团有限公司")
        self.assertEqual(
            readback["certificate_verification_state"],
            "NOT_VERIFIED_BY_GDCIC_PERSON_DIRECTORY",
        )
        self.assertIn(
            "gdcic_person_directory_does_not_publicly_confirm_registration_certificate_no",
            readback["failure_reasons"],
        )
        self.assertTrue(readback["no_legal_conclusion"])

    def test_person_directory_rejects_wrong_masked_name_and_b_certificate_substitution(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/personIntoGd/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "name": "*文升",
                            "idNum": "**8311",
                            "entName": "中铁五局集团有限公司",
                            "entCode": "103060082",
                            "certificate": None,
                        }
                    ],
                }
            if endpoint == "/openplatform/personInGd/list":
                return {"msg": "success", "code": 0, "total": 0, "rows": []}
            raise AssertionError(f"unexpected endpoint {endpoint}")

        readback = query_guangdong_gdcic_openplatform_person_directory(
            {
                "project_id": "JG2026-11125",
                "project_manager_name": "李文",
                "candidate_company": "中铁五局集团有限公司",
                "project_manager_certificate_no": "贵1442020202102750",
                "safety_b_certificate_no": "水安B20250001645",
                "region_code": "CN-GD",
            },
            http_get_json=fake_get_json,
            now="2026-05-06T10:00:00+08:00",
        )

        self.assertEqual(readback["same_company_candidate_count"], 0)
        self.assertEqual(
            readback["identity_resolution_state"],
            "LOCAL_DIRECTORY_SAME_COMPANY_PERSON_NOT_FOUND",
        )
        self.assertFalse(readback["safety_b_certificate_substitution_allowed"])
        self.assertIn(
            "safety_b_certificate_cannot_substitute_national_constructor_registration",
            readback["failure_reasons"],
        )

    def test_project_name_candidate_queries_resolve_long_notice_title(self) -> None:
        queried_names: list[str] = []

        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/project/list":
                queried_names.append(str(params.get("projectName") or ""))
                if params.get("projectName") == "绿色化工和氢能产业园基础设施建设－北区土方工程一期":
                    return {
                        "msg": "success",
                        "code": 0,
                        "total": 1,
                        "rows": [
                            {
                                "projectName": "绿色化工和氢能产业园基础设施建设－北区土方工程一期",
                                "projectCode": "4409002605060001",
                            }
                        ],
                    }
                return {"msg": "success", "code": 0, "total": 0, "rows": []}
            if endpoint == "/openplatform/constructionPermit/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [
                        {
                            "projectName": "绿色化工和氢能产业园基础设施建设－北区土方工程一期",
                            "projectCode": params.get("projectCode"),
                        }
                    ],
                }
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        readback = query_guangdong_gdcic_openplatform_hard_defect_sources(
            {
                "project_id": "PROJ-GD-LONG-TITLE",
                "project_name": "绿色化工和氢能产业园基础设施建设－北区土方工程一期勘察设计中标候选人公示",
                "candidate_company": "一方设计集团有限公司",
                "region_code": "CN-GD",
            },
            http_get_json=fake_get_json,
            now="2026-05-06T10:00:00+08:00",
        )

        self.assertIn("绿色化工和氢能产业园基础设施建设－北区土方工程一期", queried_names)
        self.assertEqual(readback["project_codes"], ["4409002605060001"])
        self.assertNotIn("gdcic_project_code_not_resolved", readback["failure_reasons"])

    def test_project_code_unresolved_has_classified_failure_reasons(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        readback = query_guangdong_gdcic_openplatform_hard_defect_sources(
            {
                "project_id": "PROJ-GD-NO-CODE",
                "project_name": "不存在项目施工中标候选人公示",
                "candidate_company": "广东测试建设有限公司",
                "region_code": "CN-GD",
            },
            http_get_json=fake_get_json,
            now="2026-05-06T10:00:00+08:00",
        )

        self.assertIn("gdcic_project_code_not_resolved", readback["failure_reasons"])
        self.assertIn("gdcic_project_lookup_empty_result", readback["failure_reasons"])
        self.assertIn(
            "gdcic_project_code_not_resolved_after_project_name_candidate_queries",
            readback["failure_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
