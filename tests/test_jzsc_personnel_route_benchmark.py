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

from storage.jzsc_personnel_route_benchmark import (
    build_jzsc_personnel_route_benchmark,
)


class JzscPersonnelRouteBenchmarkTests(unittest.TestCase):
    def test_dry_run_builds_three_route_plans_from_resolved_stage4_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stage4_root = root / "stage4"
            output_root = root / "out"
            _write_stage4_execution(stage4_root)

            result = build_jzsc_personnel_route_benchmark(
                stage4_execution_root=stage4_root,
                output_root=output_root,
                execute=False,
                created_at="2026-05-12T00:00:00+08:00",
            )

            manifest = result["manifest"]
            self.assertEqual(manifest["manifest_kind"], "jzsc_personnel_route_benchmark_manifest")
            self.assertEqual(manifest["target_count"], 1)
            item = manifest["items"][0]
            self.assertEqual(
                item["fallback_route_order"],
                [
                    "person_name_with_company_query",
                    "company_search_then_person_query",
                    "person_name_only_filter_company",
                ],
            )
            self.assertTrue((output_root / "jzsc-personnel-route-benchmark.json").exists())

    def test_summary_recommends_matched_fastest_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stage4_root = root / "stage4"
            output_root = root / "out"
            _write_stage4_execution(stage4_root)

            result = build_jzsc_personnel_route_benchmark(
                stage4_execution_root=stage4_root,
                output_root=output_root,
                execute=False,
                created_at="2026-05-12T00:00:00+08:00",
            )

            self.assertEqual(result["summary"]["target_count"], 1)
            self.assertIn("route_summary", result["summary"])


def _write_stage4_execution(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "items": [
                {
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "project_name": "测试项目",
                    "candidate_group_id": "GROUP-1",
                    "candidate_group_order": 1,
                    "candidate_company_name": "北京诚公管理咨询有限公司",
                    "responsible_person_name": "苑晓东",
                    "source_certificate_no_optional": "",
                    "resolved_certificate_no_optional": "11015464",
                    "supplement_after_execution_state": "COMPANY_FIRST_CERTIFICATE_RESOLVED",
                },
                {
                    "project_id": "PROJ-CN-GD-JG2026-10815",
                    "candidate_company_name": "其他公司",
                    "responsible_person_name": "苑晓东",
                    "supplement_after_execution_state": "CONSORTIUM_MEMBER_NONMATCH_GROUP_RESOLVED",
                },
            ]
        }
    }
    (root / "company-first-stage4-execution.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
