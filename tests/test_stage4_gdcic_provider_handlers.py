from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.provider_handlers import build_stage4_provider_handlers  # noqa: E402


def _payload(provider_id: str, *, certificate_no: str = "") -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "provider_role": "unit_test_provider",
        "target": {
            "opportunity_priority_class": "A_HIGH_CONSTRUCTION_EPC",
            "candidate_company_name": "广东测试建设有限公司",
            "responsible_person_name": "张三",
            "certificate_no_optional": certificate_no,
        },
        "source_stage4_jzsc_record": {
            "idx": 101,
            "type": "A_HIGH_CONSTRUCTION_EPC",
            "title": "广东市政道路工程施工中标候选人公示",
            "notice_url": "https://example.invalid/notice.html?projectCode=4401002605010001",
            "candidate_company": "广东测试建设有限公司",
            "responsible_person": "张三",
            "announcement_certificate_no": certificate_no,
            "matched_company_name": "广东测试建设有限公司",
        },
    }


def _fake_get_json_same_company(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    endpoint = url.replace("https://skypt.gdcic.net/api", "")
    project_code = params.get("projectCode") or params.get("prjNum") or "4401002605010001"
    if endpoint == "/openplatform/project/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [{"projectName": "广东市政道路工程", "projectCode": "4401002605010001"}],
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
    if endpoint == "/openplatform/personIntoGd/list":
        return {
            "msg": "success",
            "code": 0,
            "total": 1,
            "rows": [
                {
                    "name": "张三",
                    "entName": "广东测试建设有限公司",
                    "certificate": None,
                    "regStatus": "1",
                }
            ],
        }
    if endpoint == "/openplatform/personInGd/list":
        return {"msg": "success", "code": 0, "total": 0, "rows": []}
    return {"msg": "success", "code": 0, "total": 0, "rows": []}


class Stage4GdcicProviderHandlerTests(unittest.TestCase):
    def test_local_housing_construction_matches_same_company_person(self) -> None:
        handler = build_stage4_provider_handlers(
            enable_live_gdcic=True,
            http_get_json=_fake_get_json_same_company,
        )["LOCAL_HOUSING_CONSTRUCTION"]

        result = dict(handler(_payload("LOCAL_HOUSING_CONSTRUCTION", certificate_no="粤144202020210001")))

        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(result["provider_result_state"], "READBACK_READY")
        self.assertEqual(
            result["local_housing_construction_readback"]["same_company_candidate_count"],
            1,
        )
        self.assertFalse(
            result["local_housing_construction_readback"][
                "safety_b_certificate_substitution_allowed"
            ]
        )
        self.assertNotIn(
            "local_housing_construction_runtime_adapter_not_implemented",
            result["review_reasons"],
        )

    def test_local_housing_name_only_other_company_stays_review_required(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            if endpoint == "/openplatform/personIntoGd/list":
                return {"msg": "success", "code": 0, "total": 0, "rows": []}
            if endpoint == "/openplatform/personInGd/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [{"name": "张三", "entName": "广东其他建设有限公司"}],
                }
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        handler = build_stage4_provider_handlers(
            enable_live_gdcic=True,
            http_get_json=fake_get_json,
        )["LOCAL_HOUSING_CONSTRUCTION"]

        result = dict(handler(_payload("LOCAL_HOUSING_CONSTRUCTION")))

        self.assertEqual(result["verification_result"], "REVIEW_REQUIRED")
        self.assertIn(
            "gdcic_name_only_different_company_rows_present",
            result["failure_reasons"],
        )

    def test_project_manager_change_matches_project_role_record(self) -> None:
        handler = build_stage4_provider_handlers(
            enable_live_gdcic=True,
            http_get_json=_fake_get_json_same_company,
        )["PROJECT_MANAGER_CHANGE"]

        result = dict(handler(_payload("PROJECT_MANAGER_CHANGE")))

        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(
            result["project_manager_change_readback"]["identity_candidate_count"],
            1,
        )
        self.assertNotIn(
            "project_manager_change_notice_runtime_adapter_not_implemented",
            result["review_reasons"],
        )

    def test_project_manager_change_record_is_public_record_review(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            endpoint = url.replace("https://skypt.gdcic.net/api", "")
            project_code = params.get("projectCode") or params.get("prjNum") or "4401002605010001"
            if endpoint == "/openplatform/project/list":
                return {
                    "msg": "success",
                    "code": 0,
                    "total": 1,
                    "rows": [{"projectName": "广东市政道路工程", "projectCode": "4401002605010001"}],
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
                            "changeType": "项目经理变更",
                            "beforeProjectManager": "李四",
                            "afterProjectManager": "张三",
                            "changeDate": "2026-05-01",
                        }
                    ],
                }
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        handler = build_stage4_provider_handlers(
            enable_live_gdcic=True,
            http_get_json=fake_get_json,
        )["PROJECT_MANAGER_CHANGE"]

        result = dict(handler(_payload("PROJECT_MANAGER_CHANGE")))

        self.assertEqual(result["verification_result"], "PUBLIC_RECORD_FOUND_REVIEW")
        self.assertEqual(
            result["project_manager_change_readback"]["change_candidate_count"],
            1,
        )
        self.assertEqual(
            result["project_manager_change_readback"]["change_candidates"][0][
                "before_project_manager"
            ],
            "李四",
        )

    def test_project_manager_change_fails_closed_when_project_code_not_resolved(self) -> None:
        def fake_get_json(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
            return {"msg": "success", "code": 0, "total": 0, "rows": []}

        handler = build_stage4_provider_handlers(
            enable_live_gdcic=True,
            http_get_json=fake_get_json,
        )["PROJECT_MANAGER_CHANGE"]
        payload = _payload("PROJECT_MANAGER_CHANGE")
        payload["source_stage4_jzsc_record"]["notice_url"] = "https://example.invalid/notice.html"

        result = dict(handler(payload))

        self.assertEqual(result["verification_result"], "REVIEW_REQUIRED")
        self.assertEqual(result["provider_result_state"], "FAIL_CLOSED_PROJECT_CODE_NOT_RESOLVED")
        self.assertIn("gdcic_project_code_not_resolved", result["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
