from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from shared.settings import Settings
from storage.db import DatabaseSession
from storage.evaluation_real_sample_plan import (
    BLOCKED_PROFILE_MISSING,
    EVALUATION_REAL_PROJECT_SAMPLE_PLAN_OBJECT_TYPE,
    PLAN_READY,
    build_evaluation_real_sample_plan,
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class TestEvaluationRealSamplePlan(unittest.TestCase):
    def test_dry_run_does_not_write_or_fetch_and_marks_target_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            db_path = root / "storage.sqlite"
            self._write_targets(targets_path)
            self._write_seed(seed_path)

            result = build_evaluation_real_sample_plan(
                targets_json=targets_path,
                seed_json=seed_path,
                database_url=sqlalchemy_sqlite_url(db_path),
                target_backend="sqlalchemy",
                execute=False,
            )

            self.assertEqual(result["real_sample_plan_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertFalse(db_path.exists())
            self.assertFalse(result["manifest"]["safety"]["download_enabled"])
            self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])
            states = {item["target_id"]: item["plan_state"] for item in result["manifest"]["items"]}
            self.assertEqual(states["READY-CAND"], PLAN_READY)
            self.assertEqual(states["MISSING-PROFILE"], BLOCKED_PROFILE_MISSING)
            self.assertEqual(states["MISSING-ENTRY"], BLOCKED_PROFILE_MISSING)

    def test_execute_writes_manifest_idempotently_and_payload_has_no_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            targets_path = root / "targets.json"
            seed_path = root / "seed.json"
            db_path = root / "storage.sqlite"
            self._write_targets(targets_path)
            self._write_seed(seed_path)
            database_url = sqlalchemy_sqlite_url(db_path)

            first = build_evaluation_real_sample_plan(
                targets_json=targets_path,
                seed_json=seed_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )
            second = build_evaluation_real_sample_plan(
                targets_json=targets_path,
                seed_json=seed_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )

            self.assertEqual(first["manifest"]["manifest_id"], second["manifest"]["manifest_id"])
            session = DatabaseSession(
                settings=Settings(
                    storage_backend="sqlalchemy",
                    storage_database_url_optional=database_url,
                    storage_scope="shared",
                    storage_runtime_mode="explicit-path",
                )
            )
            try:
                records = session.list_records(EVALUATION_REAL_PROJECT_SAMPLE_PLAN_OBJECT_TYPE)
                self.assertEqual(len(records), 1)
                payload_text = json.dumps(records[0].payload, ensure_ascii=False).lower()
                self.assertNotIn("bytes", payload_text)
                self.assertNotIn("%pdf", payload_text)
                self.assertNotIn("<html", payload_text)
                self.assertFalse(records[0].governed_state["customer_visible_allowed"])
                self.assertTrue(records[0].governed_state["no_legal_conclusion"])
            finally:
                session.close()

    def test_missing_input_files_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            result = build_evaluation_real_sample_plan(
                targets_json=root / "missing-targets.json",
                seed_json=root / "missing-seed.json",
                execute=False,
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("evaluation_real_sample_targets_file_missing", result["blocking_reasons"])
            self.assertIn("evaluation_seed_file_missing", result["blocking_reasons"])
            self.assertIn("evaluation_real_sample_targets_empty", result["blocking_reasons"])
            self.assertIn("evaluation_seed_empty", result["blocking_reasons"])

    def test_default_real_sample_targets_cover_b7_buckets_without_fetch_or_missing_entry(self) -> None:
        result = build_evaluation_real_sample_plan(
            targets_json=ROOT / "contracts" / "evaluation" / "evaluation_real_project_sample_targets.json",
            seed_json=ROOT / "contracts" / "evaluation" / "evaluation_corpus_seed.json",
            target_backend="json-file",
        )

        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(result["summary"]["blocked_sample_goal_count"], 0)
        self.assertNotIn(
            BLOCKED_PROFILE_MISSING,
            result["summary"]["plan_state_counts"],
        )
        document_kinds = result["summary"]["document_kind_sample_goal_counts"]
        for document_kind in (
            "tender_file",
            "candidate_notice",
            "award_result",
            "failed_bid_notice",
            "complaint_decision",
            "flow_or_re_tender_notice",
            "official_case",
        ):
            self.assertIn(document_kind, document_kinds)
            self.assertGreater(document_kinds[document_kind], 0)
        self.assertFalse(result["manifest"]["safety"]["download_enabled"])
        self.assertFalse(result["manifest"]["safety"]["fetch_public_urls_enabled"])
        self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])
        self.assertTrue(all(item["no_legal_conclusion"] for item in result["manifest"]["items"]))

    def _write_targets(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "target_set_id": "test-targets",
                    "minimum_total_sample_goal": 50,
                    "targets": [
                        {
                            "target_id": "READY-CAND",
                            "jurisdiction": "CN-GD",
                            "platform_name": "广州交易集团",
                            "entry_seed_id": "ENTRY-GD",
                            "required_fetch_profile_id_optional": "GD-PROFILE",
                            "source_family": "local_public_resource_trading_center",
                            "project_type": "construction",
                            "document_kind": "candidate_notice",
                            "target_count": 4,
                            "selection_filters": ["中标候选人公示"],
                        },
                        {
                            "target_id": "MISSING-PROFILE",
                            "jurisdiction": "CN-ZJ",
                            "platform_name": "浙江省公共资源交易服务平台",
                            "entry_seed_id": "ENTRY-ZJ",
                            "required_fetch_profile_id_optional": "ZJ-PROFILE",
                            "source_family": "local_public_resource_trading_center",
                            "project_type": "construction",
                            "document_kind": "tender_file",
                            "target_count": 3,
                            "selection_filters": ["招标公告"],
                        },
                        {
                            "target_id": "MISSING-ENTRY",
                            "jurisdiction": "CN-SH",
                            "platform_name": "上海市建设工程交易服务中心",
                            "entry_seed_id": "ENTRY-SH",
                            "required_fetch_profile_id_optional": "SH-PROFILE",
                            "source_family": "local_public_resource_trading_center",
                            "project_type": "construction",
                            "document_kind": "award_result",
                            "target_count": 3,
                            "selection_filters": ["中标结果公告"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _write_seed(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "seed_id": "ENTRY-GD",
                            "source_url": "https://example.test/gd",
                            "source_family": "local_public_resource_trading_center",
                            "jurisdiction": "CN-GD",
                            "document_kind": "candidate_notice",
                            "fetch_profile_id_optional": "GD-PROFILE",
                            "seed_tags": ["real_public_entry", "fetchable"],
                        },
                        {
                            "seed_id": "ENTRY-ZJ",
                            "source_url": "https://example.test/zj",
                            "source_family": "local_public_resource_trading_center",
                            "jurisdiction": "CN-ZJ",
                            "document_kind": "candidate_notice",
                            "seed_tags": ["real_public_entry", "fetchable"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
