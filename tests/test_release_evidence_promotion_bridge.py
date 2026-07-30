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

from storage.release_evidence_promotion_bridge import build_release_evidence_promotion_bridge  # noqa: E402


class ReleaseEvidencePromotionBridgeTests(unittest.TestCase):
    def test_builds_stage4_release_adapter_tasks_from_latest_diagnostic_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            diagnostic = root / "diagnostic.json"
            out = root / "out"
            _write_json(
                diagnostic,
                {
                    "release_evidence_promotion_queue": {
                        "records": [
                            {
                                "project_id": "PROJ-A",
                                "project_name": "Public identifier only project",
                                "promotion_state": "PUBLIC_IDENTIFIER_READY_NEEDS_B_OR_C_RELEASE_EVIDENCE_READBACK",
                                "stage4_public_identifier_backfill_source": "YGP_PROJECT_CODE",
                                "ygp_project_code_variants": ["E4413000835979563001"],
                                "ygp_biz_code_variants": ["3C52"],
                                "ygp_site_code_variants": ["441300"],
                                "ygp_notice_id_variants": ["notice-1"],
                                "gdcic_project_code_route_allowed": False,
                            }
                        ],
                        "customer_visible_allowed": False,
                    },
                },
            )

            result = build_release_evidence_promotion_bridge(
                diagnostic_json=diagnostic,
                output_root=out,
                created_at="2026-05-25T00:00:00+08:00",
            )

            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["source_promotion_queue_record_count"], 1)
            self.assertEqual(result["summary"]["release_evidence_adapter_task_count"], 4)
            self.assertEqual(
                result["summary"]["target_type_counts"],
                {
                    "completion_acceptance": 1,
                    "construction_permit": 1,
                    "contract_performance": 1,
                    "project_manager_change_notice": 1,
                },
            )
            self.assertEqual(
                result["summary"]["grade_on_match_counts"],
                {
                    "B_ENHANCEMENT_OFFICIAL_READBACK": 2,
                    "C_REVERSE_EXPLANATION_OFFICIAL_READBACK": 2,
                },
            )
            tasks = result["manifest"]["release_evidence_adapter_task_records"]
            self.assertTrue(all(task["gdcic_project_code_route_allowed"] is False for task in tasks))
            self.assertTrue(all(task["customer_visible_allowed"] is False for task in tasks))
            self.assertTrue(all(task["query_miss_is_not_clearance"] is True for task in tasks))
            self.assertTrue(all(task["adapter_result_state"] == "PLAN_ONLY_NOT_EXECUTED" for task in tasks))
            for task in tasks:
                params = task["query_params"]
                self.assertEqual(params["gdcicProjectCodeVariants"], [])
                self.assertEqual(params["projectCode"], "")
                self.assertFalse(params["gdcic_project_code_route_allowed"])
                self.assertFalse(params["gdcicProjectCodeRouteAllowed"])
                self.assertEqual(params["ygpProjectCodeVariants"], ["E4413000835979563001"])
                self.assertIn("E4413000835979563001", params["projectCodeVariants"])
            self.assertTrue((out / "stage4-release-adapter-bridge-plan.json").exists())
            self.assertTrue((out / "release-evidence-adapter-plan-v1.json").exists())
            bridge = json.loads((out / "stage4-release-adapter-bridge-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(len(bridge["release_evidence_adapter_task_records"]), 4)
            self.assertFalse(bridge["customer_visible_allowed"])
            self.assertTrue(bridge["query_miss_is_not_clearance"])

    def test_missing_diagnostic_is_structured_input_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_release_evidence_promotion_bridge(
                diagnostic_json=root / "missing.json",
                output_root=root / "out",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertEqual(result["release_evidence_promotion_bridge_mode"], "INPUT_BLOCKED")
            self.assertIn("stage1_6_latest_scoreboard_diagnostic_missing", result["blocking_reasons"])


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
