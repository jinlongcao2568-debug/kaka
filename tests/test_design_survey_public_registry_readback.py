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

from storage.design_survey_public_registry_readback import (  # noqa: E402
    build_design_survey_public_registry_readback,
)


class DesignSurveyPublicRegistryReadbackTests(unittest.TestCase):
    def test_snapshot_html_executes_registered_surveyor_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fallback_root = root / "fallback"
            snapshot = root / "snapshot.html"
            _write_public_registry_fallback(fallback_root)
            snapshot.write_text(
                """
                <table>
                  <tr><td>胡昌华</td><td>广州市城市规划勘测设计研究院有限公司</td><td>粤测绘20260001</td><td>有效</td></tr>
                </table>
                """,
                encoding="utf-8",
            )

            result = build_design_survey_public_registry_readback(
                public_registry_fallback_root=fallback_root,
                snapshot_html_path=snapshot,
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["readback_record_count"], 1)
            self.assertEqual(result["summary"]["matched_count"], 1)
            record = result["manifest"]["public_registry_readback_table"]["records"][0]
            self.assertEqual(record["provider_result_state"], "READBACK_READY")
            self.assertEqual(record["verification_result"], "MATCHED")
            self.assertTrue((root / "out" / "design-survey-public-registry-readback-table.json").exists())

    def test_missing_snapshot_stays_pending_not_negative_fact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fallback_root = root / "fallback"
            _write_public_registry_fallback(fallback_root)

            result = build_design_survey_public_registry_readback(
                public_registry_fallback_root=fallback_root,
                output_root=root / "out",
                created_at="2026-05-19T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["readback_record_count"], 1)
            self.assertEqual(result["summary"]["matched_count"], 0)
            record = result["manifest"]["public_registry_readback_table"]["records"][0]
            self.assertEqual(record["provider_result_state"], "PENDING_IMPLEMENTATION_REVIEW")
            self.assertEqual(record["readback_state"], "PUBLIC_SNAPSHOT_OR_RUNTIME_ADAPTER_REQUIRED")
            self.assertTrue(record["policy"]["not_found_is_review_not_negative_fact"])


def _write_public_registry_fallback(root: Path) -> None:
    project_id = "PROJ-CN-GD-JG2026-11327"
    companies = ["广州市城市规划勘测设计研究院有限公司", "广州湾区规划勘测设计院有限公司"]
    payload = {
        "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
        "provider_role": "registered_surveyor_person_company_certificate_identity",
        "source_probe_item": {
            "project_id": project_id,
            "project_name": "规划测绘项目中标候选人公示",
        },
        "target": {
            "project_id": project_id,
            "candidate_company_name": companies[0],
            "candidate_group_members": companies,
            "responsible_person_name": "胡昌华",
            "certificate_no_optional": "粤测绘20260001",
        },
        "source_public_registry_task": {
            "public_registry_task_id": "DESIGN-SURVEY-PUBLIC-REG-TASK-1",
            "query_fields": {
                "person_name": "胡昌华",
                "registered_unit_or_candidate_company": companies[0],
                "certificate_no_optional": "粤测绘20260001",
                "candidate_group_members": companies,
            },
        },
    }
    _write_json(
        root / "design-survey-public-registry-fallback-v1.json",
        {
            "manifest": {
                "stage4_provider_jobs": {
                    "jobs": [
                        {
                            "job_id": "STAGE4-PUBLIC-REG-JOB-1",
                            "project_id": project_id,
                            "provider_id": "NATURAL_RESOURCE_REGISTERED_SURVEYOR",
                            "payload": payload,
                            "status": "QUEUED_NOT_EXECUTED",
                        }
                    ]
                }
            }
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
