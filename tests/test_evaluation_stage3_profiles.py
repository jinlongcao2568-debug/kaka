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
from storage.evaluation_corpus import EVALUATION_SNAPSHOT_KIND, build_evaluation_corpus
from storage.repositories.object_storage_repo import ObjectStorageRepository
from stage3_parsing.evaluation_profiles import (
    EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE,
    build_evaluation_stage3_profiles,
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class TestEvaluationStage3Profiles(unittest.TestCase):
    def test_dry_run_does_not_write_profile_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "profiles.sqlite")
            object_root = root / "objects"
            _prepare_evaluation_corpus(root=root, database_url=database_url, object_root=object_root)

            result = build_evaluation_stage3_profiles(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=False,
                created_at="2026-05-07T09:00:00+00:00",
            )

            self.assertEqual(result["profile_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["profile_item_count"], 4)

            session = DatabaseSession(settings=_settings(database_url=database_url, object_root=object_root))
            try:
                self.assertEqual(session.list_records(EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE), [])
            finally:
                session.close()

    def test_profiles_classify_methods_candidates_and_fairness_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "profiles-classify.sqlite")
            object_root = root / "objects"
            _prepare_evaluation_corpus(root=root, database_url=database_url, object_root=object_root)

            result = build_evaluation_stage3_profiles(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T09:05:00+00:00",
            )

            self.assertTrue(result["execution"]["executed"])
            self.assertEqual(result["execution"]["upserted_evaluation_stage3_profile_manifest_count"], 1)
            items = {item["seed_id"]: item for item in result["manifest"]["items"]}

            ranked = items["RANKED"]
            self.assertEqual(ranked["evaluation_method_profile"]["evaluation_method_family"], "technical_scored")
            self.assertTrue(ranked["evaluation_method_profile"]["has_dark_bid_requirement"])
            self.assertEqual(ranked["candidate_set_profile"]["candidate_selection_mode"], "ranked_candidates")
            self.assertEqual(ranked["candidate_set_profile"]["candidate_count_optional"], 2)
            self.assertEqual(ranked["candidate_set_profile"]["candidate_rows"][0]["candidate_name"], "甲公司")
            self.assertEqual(ranked["candidate_set_profile"]["candidate_rows"][0]["candidate_rank_optional"], 1)
            self.assertEqual(ranked["candidate_set_profile"]["candidate_rows"][0]["project_manager_optional"], "张三")
            self.assertEqual(ranked["candidate_set_profile"]["candidate_rows"][0]["certificate_no_optional"], "粤144000000001")
            self.assertEqual(ranked["candidate_set_profile"]["objection_window_optional"], "2026年05月07日至2026年05月10日")

            separation = items["SEPARATION"]
            self.assertEqual(separation["evaluation_method_profile"]["evaluation_method_family"], "bid_separation")
            self.assertEqual(separation["candidate_set_profile"]["candidate_selection_mode"], "bid_separation_candidates")
            self.assertEqual(separation["candidate_set_profile"]["candidate_count_optional"], 3)

            winner = items["WINNER"]
            self.assertEqual(winner["candidate_set_profile"]["candidate_selection_mode"], "single_winner")
            self.assertEqual(winner["candidate_set_profile"]["candidate_rows"][0]["candidate_name"], "丙公司")

            fairness = items["FAIRNESS"]
            signal_types = {signal["signal_type"] for signal in fairness["fairness_clause_probe"]["signals"]}
            self.assertIn("specified_brand_or_supplier", signal_types)
            self.assertIn("performance_threshold", signal_types)
            self.assertIn("discriminatory_scoring", signal_types)
            self.assertTrue(all(item["review_required"] for item in items.values()))
            self.assertTrue(all(item["customer_visible_allowed"] is False for item in items.values()))
            self.assertTrue(all(item["no_legal_conclusion"] is True for item in items.values()))

    def test_execute_is_idempotent_and_payload_has_no_blob_or_raw_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "profiles-idempotent.sqlite")
            object_root = root / "objects"
            _prepare_evaluation_corpus(root=root, database_url=database_url, object_root=object_root)

            first = build_evaluation_stage3_profiles(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T09:10:00+00:00",
            )
            second = build_evaluation_stage3_profiles(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T09:15:00+00:00",
            )

            self.assertEqual(first["manifest"]["manifest_id"], second["manifest"]["manifest_id"])
            session = DatabaseSession(settings=_settings(database_url=database_url, object_root=object_root))
            try:
                records = session.list_records(EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(records), 1)
                payload_text = json.dumps(records[0].payload, ensure_ascii=False, sort_keys=True)
                self.assertNotIn('"bytes"', payload_text)
                self.assertNotIn("<html", payload_text.lower())
                self.assertNotIn("%PDF", payload_text)
                self.assertLess(len(payload_text), 256_000)
            finally:
                session.close()

    def test_missing_corpus_manifests_fail_closed_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "profiles-missing.sqlite")
            object_root = root / "objects"

            result = build_evaluation_stage3_profiles(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T09:20:00+00:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("evaluation_corpus_sample_manifest_missing", result["blocking_reasons"])
            self.assertIn("evaluation_parse_probe_manifest_missing", result["blocking_reasons"])
            self.assertFalse(result["execution"]["executed"])
            session = DatabaseSession(settings=_settings(database_url=database_url, object_root=object_root))
            try:
                self.assertEqual(session.list_records(EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE), [])
            finally:
                session.close()


def _prepare_evaluation_corpus(*, root: Path, database_url: str, object_root: Path) -> None:
    settings = _settings(database_url=database_url, object_root=object_root)
    session = DatabaseSession(settings=settings)
    try:
        repo = ObjectStorageRepository(session=session, settings=settings)
        snapshots = {
            "RANKED": repo.save_snapshot(
                _html(
                    "测试工程中标候选人公示",
                    "评标办法：综合评估法 技术标评分 暗标。"
                    "第一中标候选人：甲公司 投标报价：1000万元 总得分：95.5 项目负责人：张三 注册证书编号：粤144000000001。"
                    "第二中标候选人：乙公司 投标报价：1100万元 总得分：88.1 项目负责人：李四 注册证书编号：粤144000000002。"
                    "公示时间：2026年05月07日至2026年05月10日。",
                ),
                snapshot_id="SNAP-EVAL-RANKED",
                snapshot_kind=EVALUATION_SNAPSHOT_KIND,
                content_type="text/html",
                source_url_optional="https://example.test/ranked.html",
                source_family_optional="offline_test_source",
            ).snapshot_id,
            "SEPARATION": repo.save_snapshot(
                _html(
                    "测试工程定标候选人公示",
                    "本项目采用评定分离。定标候选人：甲公司、乙公司、丁公司，排名不分先后。评标办法：评定分离。",
                ),
                snapshot_id="SNAP-EVAL-SEPARATION",
                snapshot_kind=EVALUATION_SNAPSHOT_KIND,
                content_type="text/html",
                source_url_optional="https://example.test/separation.html",
                source_family_optional="offline_test_source",
            ).snapshot_id,
            "WINNER": repo.save_snapshot(
                _html("测试工程中标结果公告", "中标结果公告。中标人名称：丙公司。中标金额：900万元。"),
                snapshot_id="SNAP-EVAL-WINNER",
                snapshot_kind=EVALUATION_SNAPSHOT_KIND,
                content_type="text/html",
                source_url_optional="https://example.test/winner.html",
                source_family_optional="offline_test_source",
            ).snapshot_id,
            "FAIRNESS": repo.save_snapshot(
                _html(
                    "测试工程招标公告",
                    "招标文件设置类似业绩和单项合同额要求，指定品牌，限制潜在投标人，存在评分倾斜复核信号。"
                    "评标办法：合理低价法。明标。",
                ),
                snapshot_id="SNAP-EVAL-FAIRNESS",
                snapshot_kind=EVALUATION_SNAPSHOT_KIND,
                content_type="text/html",
                source_url_optional="https://example.test/fairness.html",
                source_family_optional="offline_test_source",
            ).snapshot_id,
        }
    finally:
        session.close()

    seed_path = root / "seed.json"
    seed_path.write_text(
        json.dumps(
            {
                "sources": [
                    _seed("RANKED", "candidate_notice", snapshots["RANKED"], "https://example.test/ranked.html"),
                    _seed("SEPARATION", "candidate_notice", snapshots["SEPARATION"], "https://example.test/separation.html"),
                    _seed("WINNER", "award_result", snapshots["WINNER"], "https://example.test/winner.html"),
                    _seed("FAIRNESS", "tender_file", snapshots["FAIRNESS"], "https://example.test/fairness.html"),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    build_evaluation_corpus(
        input_json=seed_path,
        database_url=database_url,
        target_backend="sqlalchemy",
        object_storage_path=object_root,
        execute=True,
        created_at="2026-05-07T08:50:00+00:00",
    )


def _seed(seed_id: str, document_kind: str, snapshot_id: str, source_url: str) -> dict[str, str]:
    return {
        "seed_id": seed_id,
        "source_url": source_url,
        "document_kind": document_kind,
        "source_family": "offline_test_source",
        "jurisdiction": "CN",
        "project_type": "construction",
        "snapshot_id_optional": snapshot_id,
    }


def _html(title: str, body: str) -> bytes:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>".encode("utf-8")


def _settings(*, database_url: str, object_root: Path) -> Settings:
    return Settings(
        storage_backend="sqlalchemy",
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_root),
    )


if __name__ == "__main__":
    unittest.main()
