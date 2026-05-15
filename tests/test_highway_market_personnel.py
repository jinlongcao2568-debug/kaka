from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.highway_market_personnel import query_highway_market_person_title  # noqa: E402


class HighwayMarketPersonnelTest(unittest.TestCase):
    def test_exact_certificate_matches_embedded_highway_title_certificate(self) -> None:
        def fake_post(url: str, body: dict[str, str], headers: dict[str, str]) -> dict[str, object]:
            if "getPersonListTab" in url:
                return {
                    "rows": [
                        {
                            "name": "雷明",
                            "company": "广东省交通规划设计研究院集团股份有限公司",
                            "id": "person-lei",
                            "companyId": "company-gd",
                        }
                    ]
                }
            return {
                "rows": [
                    {
                        "academicName": "高级工程师",
                        "academicID": "粤高职证字第1700101008631号",
                        "academicMajor": "路桥",
                        "acaIssueDate": "2017-03-01",
                    }
                ]
            }

        result = query_highway_market_person_title(
            {
                "target_company_name": "广东省交通规划设计研究院集团股份有限公司",
                "target_person_name": "雷明",
                "target_certificate_no": "1700101008631",
            },
            http_post=fake_post,
        )

        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(result["resolved_certificate_no_optional"], "粤高职证字第1700101008631号")
        self.assertEqual(result["registered_unit_name_optional"], "广东省交通规划设计研究院集团股份有限公司")

    def test_without_target_certificate_uses_latest_academic_record(self) -> None:
        def fake_post(url: str, body: dict[str, str], headers: dict[str, str]) -> dict[str, object]:
            if "getPersonListTab" in url:
                return {
                    "rows": [
                        {
                            "name": "查明高",
                            "company": "中交第二公路勘察设计研究院有限公司",
                            "id": "person-zha",
                            "companyId": "company-zj2",
                        }
                    ]
                }
            return {
                "rows": [
                    {
                        "academicName": "教授级高级工程师",
                        "academicID": "1150109",
                        "academicMajor": "公路工程",
                        "acaIssueDate": "2015-11-26",
                        "updateTime": "2018-05-18",
                    },
                    {
                        "academicName": "教授级高级工程师",
                        "academicID": "1191689",
                        "academicMajor": "公路工程",
                        "acaIssueDate": "2019-10-23",
                        "updateTime": "2022-05-27",
                    },
                ]
            }

        result = query_highway_market_person_title(
            {
                "target_company_name": "中交第二公路勘察设计研究院有限公司",
                "target_person_name": "查明高",
            },
            http_post=fake_post,
        )

        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(result["resolved_certificate_no_optional"], "1191689")

    def test_no_company_match_is_review_not_clearance(self) -> None:
        def fake_post(url: str, body: dict[str, str], headers: dict[str, str]) -> dict[str, object]:
            return {
                "rows": [
                    {
                        "name": "雷明",
                        "company": "其他公司",
                        "id": "person-other",
                        "companyId": "company-other",
                    }
                ]
            }

        result = query_highway_market_person_title(
            {
                "target_company_name": "广东省交通规划设计研究院集团股份有限公司",
                "target_person_name": "雷明",
            },
            http_post=fake_post,
        )

        self.assertEqual(result["query_state"], "REVIEW_REQUIRED_PERSON_COMPANY_NOT_MATCHED")
        self.assertTrue(result["query_miss_is_not_clearance"])


if __name__ == "__main__":
    unittest.main()
