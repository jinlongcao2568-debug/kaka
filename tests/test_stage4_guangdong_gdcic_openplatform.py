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


if __name__ == "__main__":
    unittest.main()
