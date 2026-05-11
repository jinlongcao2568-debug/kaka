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

from storage.company_first_certificate_supplement_probe import (  # noqa: E402
    build_company_first_certificate_supplement_probe,
)


class CompanyFirstCertificateSupplementProbeTests(unittest.TestCase):
    def test_builds_company_first_jobs_for_supplement_required_items_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "early"
            _write_early_probe(input_root)

            result = build_company_first_certificate_supplement_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["project_count"], 2)
            self.assertEqual(
                result["summary"]["supplement_probe_state_counts"],
                {"COMPANY_FIRST_PROVIDER_TASKS_READY": 2},
            )
            jobs = result["manifest"]["stage4_provider_jobs"]["jobs"]
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["provider_id"], "JZSC_PERSON_IDENTITY")
            self.assertFalse(jobs[0]["stage4_live_provider_enabled"])
            self.assertEqual(result["manifest"]["stage4_candidate_verification_inputs"]["summary"]["stage4_input_count"], 0)

    def test_builds_company_first_jobs_for_each_consortium_target_without_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "early"
            payload = {
                "manifest": {
                    "manifest_kind": "responsible_person_early_probe_manifest",
                    "items": [
                        {
                            "project_id": "PROJ-CN-GD-JG2026-10815",
                            "project_name": "监理服务中标候选人公示",
                            "candidate_company_candidates": [
                                {"value": "华夏邮电咨询监理有限公司"},
                                {"value": "北京诚公管理咨询有限公司"},
                            ],
                            "responsible_person_candidates": [{"value": "陈光理"}],
                            "certificate_no_candidates": [],
                            "verification_targets": [
                                {
                                    "candidate_group_id": "G1",
                                    "candidate_group_members": ["华夏邮电咨询监理有限公司", "北京诚公管理咨询有限公司"],
                                    "candidate_company_name": "华夏邮电咨询监理有限公司",
                                    "consortium_member_role": "lead",
                                    "responsible_person_name": "陈光理",
                                    "certificate_no": "",
                                },
                                {
                                    "candidate_group_id": "G1",
                                    "candidate_group_members": ["华夏邮电咨询监理有限公司", "北京诚公管理咨询有限公司"],
                                    "candidate_company_name": "北京诚公管理咨询有限公司",
                                    "consortium_member_role": "member",
                                    "responsible_person_name": "陈光理",
                                    "certificate_no": "",
                                },
                            ],
                            "responsible_role": "chief_supervision_engineer",
                            "early_probe_state": "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED",
                            "stage4_readiness_state": "SUPPLEMENT_REQUIRED_COMPANY_FIRST",
                            "customer_visible_allowed": False,
                            "no_legal_conclusion": True,
                        }
                    ],
                }
            }
            input_root.mkdir(parents=True, exist_ok=True)
            (input_root / "responsible-person-early-probe.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            result = build_company_first_certificate_supplement_probe(
                input_root=input_root,
                output_root=root / "out",
                created_at="2026-05-11T00:00:00+08:00",
            )

            jobs = result["manifest"]["stage4_provider_jobs"]["jobs"]
            self.assertEqual(len(jobs), 2)
            self.assertEqual(
                {job["payload"]["target"]["candidate_company_name"] for job in jobs},
                {"华夏邮电咨询监理有限公司", "北京诚公管理咨询有限公司"},
            )
            self.assertTrue(all(job["payload"]["candidate_group_id"] == "G1" for job in jobs))

    def test_company_first_no_match_requires_name_enumeration_not_flow08_yet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "early"
            _write_early_probe(input_root)

            result = build_company_first_certificate_supplement_probe(
                input_root=input_root,
                output_root=root / "out",
                company_first_result_state="NO_MATCH",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["supplement_probe_state"], "NAME_ENUMERATION_FALLBACK_REQUIRED")
            self.assertFalse(item["flow_08_targeted_parse_required"])
            self.assertIn("RUN_NAME_ENUMERATION_FALLBACK", item["next_actions"])

    def test_company_first_and_name_enumeration_no_match_triggers_flow08_without_final_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "early"
            _write_early_probe(input_root)

            result = build_company_first_certificate_supplement_probe(
                input_root=input_root,
                output_root=root / "out",
                company_first_result_state="NO_MATCH",
                name_enumeration_result_state="NO_MATCH",
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["supplement_probe_state"], "FLOW_08_TARGETED_PARSE_REQUIRED")
            self.assertTrue(item["flow_08_targeted_parse_required"])
            self.assertEqual(item["risk_escalation_state"], "HIGH_CLUE_REVIEW")
            self.assertIn("DO_NOT_OUTPUT_FINAL_CONFLICT", item["next_actions"])

    def test_matched_source_stage4_record_generates_stage4_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "early"
            records_path = root / "records.json"
            _write_early_probe(input_root, project_ids=("PROJ-CN-GD-JG2026-10815",))
            records_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "project_id": "PROJ-CN-GD-JG2026-10815",
                                "normalized_stage4_outcome": "JZSC_PERSON_COMPANY_CERT_MATCHED",
                                "matched_company_name": "华夏邮电咨询监理有限公司",
                                "matched_company_public_id": "COMPANY-001",
                                "jzsc_registered_unit": "华夏邮电咨询监理有限公司",
                                "jzsc_certificate_no": "4101234567",
                                "person_public_id": "PERSON-001",
                                "personnel_detail_url": "https://example.test/person/001",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_company_first_certificate_supplement_probe(
                input_root=input_root,
                output_root=root / "out",
                source_stage4_records_json=records_path,
                created_at="2026-05-11T00:00:00+08:00",
            )

            item = result["manifest"]["items"][0]
            self.assertEqual(item["supplement_probe_state"], "COMPANY_FIRST_CERTIFICATE_RESOLVED")
            self.assertEqual(item["stage4_readiness_state"], "READY_FOR_STAGE4_CERTIFICATE_VERIFICATION")
            stage4_items = result["manifest"]["stage4_candidate_verification_inputs"]["items"]
            self.assertEqual(len(stage4_items), 1)
            self.assertEqual(stage4_items[0]["project_manager_certificate_no"], "4101234567")
            self.assertFalse(stage4_items[0]["stage4_live_provider_enabled"])

    def test_writes_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_root = root / "early"
            output_root = root / "out"
            _write_early_probe(input_root)

            result = build_company_first_certificate_supplement_probe(
                input_root=input_root,
                output_root=output_root,
                created_at="2026-05-11T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertTrue((output_root / "company-first-certificate-supplement.json").exists())
            self.assertTrue((output_root / "stage4_provider_jobs.json").exists())
            self.assertTrue((output_root / "stage4_candidate_verification_inputs.json").exists())


def _write_early_probe(input_root: Path, *, project_ids: tuple[str, ...] | None = None) -> None:
    ids = project_ids or ("PROJ-CN-GD-JG2026-10815", "PROJ-CN-GD-JG2026-11021", "PROJ-CN-GD-JG2026-11029")
    items = []
    for project_id in ids:
        if project_id.endswith("11029"):
            state = "CERTIFICATE_READY_FROM_07"
            certs = [{"value": "粤1442024202500740"}]
        else:
            state = "COMPANY_FIRST_CERTIFICATE_SUPPLEMENT_REQUIRED"
            certs = []
        items.append(
            {
                "project_id": project_id,
                "project_name": f"{project_id} 中标候选人公示",
                "source_07_detail_path": f"projects/CN-GD/{project_id}/07/detail.html",
                "candidate_company_candidates": [
                    {"value": "华夏邮电咨询监理有限公司"},
                    {"value": "北京诚公管理咨询有限公司"},
                ],
                "responsible_person_candidates": [
                    {"value": "陈光理"},
                    {"value": "苑晓东"},
                ],
                "certificate_no_candidates": certs,
                "responsible_role": "chief_supervision_engineer",
                "early_probe_state": state,
                "stage4_readiness_state": "SUPPLEMENT_REQUIRED_COMPANY_FIRST" if not certs else "READY_FOR_STAGE4_INPUT",
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            }
        )
    payload = {
        "manifest": {
            "manifest_kind": "responsible_person_early_probe_manifest",
            "items": items,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    }
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "responsible-person-early-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
