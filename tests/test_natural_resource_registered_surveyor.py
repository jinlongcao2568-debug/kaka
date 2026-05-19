from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage4_verification.natural_resource_registered_surveyor import (  # noqa: E402
    run_natural_resource_registered_surveyor_provider_task,
)
from stage4_verification.provider_registry import NATURAL_RESOURCE_REGISTERED_SURVEYOR  # noqa: E402


class NaturalResourceRegisteredSurveyorTests(unittest.TestCase):
    def test_snapshot_person_company_and_certificate_match_becomes_matched(self) -> None:
        result = run_natural_resource_registered_surveyor_provider_task(
            _payload(),
            snapshot_html="""
            <table>
              <tr><th>姓名</th><th>注册单位</th><th>注册证号</th><th>状态</th></tr>
              <tr><td>胡昌华</td><td>广州市城市规划勘测设计研究院有限公司</td><td>粤测绘20260001</td><td>有效</td></tr>
            </table>
            """,
            snapshot_source_url="https://rsurveyor.example.test/list",
            snapshot_ref="manual-snapshot-1",
        )

        self.assertEqual(result["provider_id"], NATURAL_RESOURCE_REGISTERED_SURVEYOR)
        self.assertEqual(result["provider_result_state"], "READBACK_READY")
        self.assertEqual(result["verification_result"], "MATCHED")
        self.assertEqual(result["identity_resolution_state"], "MATCHED_PERSON_COMPANY")
        self.assertEqual(
            result["identity_fields"]["registered_unit_name"],
            "广州市城市规划勘测设计研究院有限公司",
        )
        self.assertTrue(result["policy"]["no_name_only_final_proof"])
        self.assertFalse(result["customer_sellable_evidence_ready"])

    def test_snapshot_name_only_or_wrong_company_stays_review(self) -> None:
        result = run_natural_resource_registered_surveyor_provider_task(
            _payload(),
            snapshot_html="""
            <table>
              <tr><td>胡昌华</td><td>其他测绘设计有限公司</td><td>粤测绘20260001</td><td>有效</td></tr>
            </table>
            """,
            snapshot_source_url="https://rsurveyor.example.test/list",
            snapshot_ref="manual-snapshot-2",
        )

        self.assertEqual(result["provider_result_state"], "READBACK_READY")
        self.assertEqual(result["verification_result"], "REVIEW_REQUIRED")
        self.assertIn(
            "registered_surveyor_registered_unit_not_matched_to_candidate_company",
            result["review_reasons"],
        )
        self.assertIn("name_only_is_not_final_proof", result["review_reasons"])

    def test_without_snapshot_or_authorized_live_adapter_returns_pending(self) -> None:
        result = run_natural_resource_registered_surveyor_provider_task(_payload())

        self.assertEqual(result["provider_result_state"], "PENDING_IMPLEMENTATION_REVIEW")
        self.assertEqual(result["readback_state"], "PUBLIC_SNAPSHOT_OR_RUNTIME_ADAPTER_REQUIRED")
        self.assertIn(
            "registered_surveyor_public_snapshot_or_authorized_live_adapter_missing",
            result["review_reasons"],
        )


def _payload() -> dict[str, object]:
    companies = ["广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"]
    return {
        "provider_id": NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        "provider_role": "registered_surveyor_person_company_certificate_identity",
        "target": {
            "project_id": "PROJ-CN-GD-JG2026-11327",
            "candidate_company_name": companies[0],
            "candidate_group_members": companies,
            "responsible_person_name": "胡昌华",
            "certificate_no_optional": "粤测绘20260001",
        },
        "source_public_registry_task": {
            "query_fields": {
                "person_name": "胡昌华",
                "registered_unit_or_candidate_company": companies[0],
                "certificate_no_optional": "粤测绘20260001",
                "candidate_group_members": companies,
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
