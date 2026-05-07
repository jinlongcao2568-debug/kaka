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
from storage.evaluation_corpus import (
    EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE,
    EVALUATION_METHOD_SOURCE_CATALOG_OBJECT_TYPE,
    EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE,
    build_evaluation_corpus,
    load_evaluation_corpus_seeds,
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class TestEvaluationCorpus(unittest.TestCase):
    def test_dry_run_does_not_write_database_or_object_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            db_path = root / "storage.sqlite"
            object_root = root / "object-storage"
            seed_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "seed_id": "S1",
                                "source_url": "https://example.test/tender.html",
                                "document_kind": "tender_file",
                                "source_family": "offline_seed_sample",
                                "jurisdiction": "CN",
                                "project_type": "construction",
                                "probe_text_optional": "评标办法 综合评估法 技术标评分 暗标",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_evaluation_corpus(
                input_json=seed_path,
                database_url=sqlalchemy_sqlite_url(db_path),
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=False,
            )

            self.assertEqual(result["evaluation_corpus_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertFalse(db_path.exists())
            self.assertFalse(object_root.exists())
            self.assertEqual(result["summary"]["sample_manifest"]["sample_count"], 1)
            self.assertEqual(
                result["summary"]["probe_manifest"]["evaluation_method_family_counts"]["technical_scored"],
                1,
            )

    def test_seed_url_dedupe_and_source_type_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            seed_path = Path(tmp_dir) / "seed.json"
            seed_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "seed_id": "BASIS",
                                "source_url": "https://www.gov.cn/policy.html",
                                "document_kind": "official_basis",
                                "probe_text_optional": "综合评估法",
                            },
                            {
                                "seed_id": "DUP",
                                "source_url": "https://www.gov.cn/policy.html",
                                "document_kind": "official_basis",
                            },
                            {
                                "seed_id": "LOCAL",
                                "source_url": "https://ggzy.zj.gov.cn/jyxxgk/list.html",
                                "document_kind": "candidate_notice",
                                "probe_text_optional": "第一中标候选人 第二中标候选人",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            seeds = load_evaluation_corpus_seeds(seed_path)

            self.assertEqual(len(seeds), 2)
            self.assertEqual(seeds[0].source_family, "official_government_policy")
            self.assertEqual(seeds[1].source_family, "local_public_resource_trading_center")
            self.assertEqual(seeds[1].jurisdiction, "CN-ZJ")

    def test_probe_classifies_methods_candidates_dark_bright_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            seed_path = Path(tmp_dir) / "seed.json"
            seed_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "seed_id": "COMP",
                                "source_url": "https://example.test/comprehensive.html",
                                "document_kind": "tender_file",
                                "probe_text_optional": "评标办法前附表 综合评估法 技术标评分 明标",
                            },
                            {
                                "seed_id": "LOW",
                                "source_url": "https://example.test/low.html",
                                "document_kind": "tender_file",
                                "probe_text_optional": "采用经评审的最低投标价法 推荐中标候选人",
                            },
                            {
                                "seed_id": "REASONABLE",
                                "source_url": "https://example.test/reasonable.html",
                                "document_kind": "tender_file",
                                "probe_text_optional": "本项目采用合理低价法，投标报价接近评标基准价得分最高",
                            },
                            {
                                "seed_id": "SEPARATION",
                                "source_url": "https://example.test/separation.html",
                                "document_kind": "candidate_notice",
                                "probe_text_optional": "评定分离 推荐5名定标候选人 排名不分先后",
                            },
                            {
                                "seed_id": "RANKED",
                                "source_url": "https://example.test/ranked.html",
                                "document_kind": "candidate_notice",
                                "probe_text_optional": "第一中标候选人 甲公司 项目负责人 张三 注册证书编号 粤144 第二中标候选人 乙公司 公示期3日",
                            },
                            {
                                "seed_id": "DARK",
                                "source_url": "https://example.test/dark.html",
                                "document_kind": "tender_file",
                                "probe_text_optional": "技术标采用暗标评审，不得出现投标人名称",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_evaluation_corpus(input_json=seed_path)
            probes = {item["seed_id"]: item for item in result["probe_manifest"]["items"]}

            self.assertEqual(probes["COMP"]["evaluation_method_family"], "technical_scored")
            self.assertTrue(probes["COMP"]["has_bright_bid_requirement"])
            self.assertEqual(probes["LOW"]["evaluation_method_family"], "reviewed_lowest_price")
            self.assertEqual(probes["REASONABLE"]["evaluation_method_family"], "reasonable_low_price")
            self.assertEqual(probes["SEPARATION"]["candidate_selection_mode"], "bid_separation_candidates")
            self.assertEqual(probes["SEPARATION"]["candidate_count_optional"], 5)
            self.assertEqual(probes["RANKED"]["candidate_selection_mode"], "ranked_candidates")
            self.assertEqual(probes["RANKED"]["candidate_count_optional"], 2)
            self.assertTrue(probes["RANKED"]["project_manager_field_detected"])
            self.assertTrue(probes["RANKED"]["certificate_number_field_detected"])
            self.assertTrue(probes["DARK"]["has_dark_bid_requirement"])

    def test_fairness_markers_are_detected_as_review_signals_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            seed_path = Path(tmp_dir) / "seed.json"
            seed_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "seed_id": "FAIR",
                                "source_url": "https://example.test/fairness.html",
                                "document_kind": "tender_file",
                                "probe_text_optional": "类似业绩限于特定行政区域，指定品牌，不接受同等产品，限制潜在投标人。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_evaluation_corpus(input_json=seed_path)
            probe = result["probe_manifest"]["items"][0]

            self.assertIn("特定行政区域", probe["fairness_markers"])
            self.assertIn("指定品牌", probe["fairness_markers"])
            self.assertTrue(probe["review_required"])
            self.assertFalse(probe["customer_visible_allowed"])
            self.assertTrue(probe["no_legal_conclusion"])

    def test_execute_writes_three_manifests_idempotently_and_payload_has_no_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            db_path = root / "storage.sqlite"
            seed_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "seed_id": "BASIS",
                                "source_url": "https://www.gov.cn/policy.html",
                                "document_kind": "official_basis",
                                "probe_text_optional": "评标方法包括经评审的最低投标价法、综合评估法。",
                            },
                            {
                                "seed_id": "CAND",
                                "source_url": "https://example.test/candidate.html",
                                "document_kind": "candidate_notice",
                                "probe_text_optional": "<html>第一中标候选人 甲公司 项目负责人 张三 证书编号 粤144</html>",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            database_url = sqlalchemy_sqlite_url(db_path)

            first = build_evaluation_corpus(
                input_json=seed_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )
            second = build_evaluation_corpus(
                input_json=seed_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )

            self.assertTrue(first["execution"]["database_write_enabled"])
            self.assertEqual(
                first["sample_manifest"]["manifest_id"],
                second["sample_manifest"]["manifest_id"],
            )

            session = DatabaseSession(
                settings=Settings(
                    storage_backend="sqlalchemy",
                    storage_database_url_optional=database_url,
                    storage_scope="shared",
                    storage_runtime_mode="explicit-path",
                )
            )
            try:
                self.assertEqual(len(session.list_records(EVALUATION_METHOD_SOURCE_CATALOG_OBJECT_TYPE)), 1)
                self.assertEqual(len(session.list_records(EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE)), 1)
                self.assertEqual(len(session.list_records(EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE)), 1)
                for record in session.list_all_records():
                    payload_text = json.dumps(record.payload, ensure_ascii=False).lower()
                    self.assertNotIn("bytes", payload_text)
                    self.assertNotIn("%pdf", payload_text)
                    self.assertNotIn("<html", payload_text)
                    self.assertNotIn("第一中标候选人 甲公司", payload_text)
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
