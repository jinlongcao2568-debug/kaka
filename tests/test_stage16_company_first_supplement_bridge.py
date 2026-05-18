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

from storage.stage16_company_first_supplement_bridge import (  # noqa: E402
    build_stage16_company_first_supplement_bridge,
)


class Stage16CompanyFirstSupplementBridgeTests(unittest.TestCase):
    def test_bridges_stage16_storage_to_company_first_jobs_and_splits_consortium(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            _write_storage(storage_json)

            result = build_stage16_company_first_supplement_bridge(
                storage_json=storage_json,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["bridge_item_count"], 1)
            self.assertEqual(result["summary"]["verification_target_count"], 2)
            self.assertEqual(result["summary"]["company_first_provider_job_count"], 2)
            self.assertTrue((root / "out" / "responsible-person-early-probe.json").exists())
            self.assertTrue((root / "out" / "stage4_provider_jobs.json").exists())

            jobs = result["company_first_certificate_supplement"]["manifest"]["stage4_provider_jobs"]["jobs"]
            self.assertEqual(
                {job["payload"]["target"]["candidate_company_name"] for job in jobs},
                {"中国化学工程第六建设有限公司", "中国市政工程华北设计研究总院有限公司"},
            )
            self.assertEqual(
                {job["payload"]["candidate_group_id"] for job in jobs},
                {"CANDIDATE-GROUP-JG2026-11398-002-COMPANY-FIRST-1"},
            )
            self.assertEqual(
                {job["payload"]["consortium_member_role"] for job in jobs},
                {"lead", "member"},
            )

    def test_skips_non_required_design_candidate_without_project_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            storage_json = root / "storage.json"
            _write_storage(
                storage_json,
                candidate_options=[
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11327",
                        "project_name": "规划测绘项目中标候选人公示",
                        "source_url": "https://example.test/11327.html",
                        "candidate_company": "(主)广州市城市规划勘测设计研究院有限公司;(成)广州湾区规划勘测设计院有限公司",
                        "primary_responsible_person_name": "胡昌华",
                        "project_manager_name": "",
                        "project_manager_certificate_no": "",
                    }
                ],
                closed_loop_results=[
                    {
                        "project_id": "PROJ-CN-GD-JG2026-11327",
                        "real_public_stage4_9_readback": {
                            "jzsc_company_first_identity_resolution_required": False,
                        },
                    }
                ],
            )

            result = build_stage16_company_first_supplement_bridge(
                storage_json=storage_json,
                output_root=root / "out",
                created_at="2026-05-18T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["bridge_item_count"], 0)
            self.assertEqual(result["summary"]["company_first_provider_job_count"], 0)


def _write_storage(
    path: Path,
    *,
    candidate_options: list[dict[str, object]] | None = None,
    closed_loop_results: list[dict[str, object]] | None = None,
) -> None:
    candidates = candidate_options or [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "project_name": "沈阳至海口国家高速公路火村至龙山段改扩建工程设计施工总承包RQSG2标段中标候选人公示",
            "source_url": "https://example.test/11398-002.html",
            "candidate_company": "（主）中国化学工程第六建设有限公司,（成）中国市政工程华北设计研究总院有限公司",
            "primary_responsible_person_name": "曾凡伟",
            "project_manager_name": "曾凡伟",
            "project_manager_certificate_no": "",
            "primary_responsible_role": "project_manager",
        }
    ]
    closed = closed_loop_results or [
        {
            "project_id": "PROJ-CN-GD-JG2026-11398-002",
            "real_public_stage4_9_readback": {
                "jzsc_company_first_identity_resolution_required": True,
                "project_manager_identifier_resolution_state": "JZSC_COMPANY_FIRST_REQUIRED",
            },
        }
    ]
    payload = {
        "storage_version": 1,
        "operator_actions": {
            "operator-autonomous-opportunity-search-runs": [
                {
                    "object_refs": {
                        "candidate_options_json": json.dumps(candidates, ensure_ascii=False),
                        "closed_loop_results_json": json.dumps(closed, ensure_ascii=False),
                    }
                }
            ]
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
