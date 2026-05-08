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
from storage.evaluation_coverage_audit import (
    EVALUATION_SEED_COVERAGE_AUDIT_OBJECT_TYPE,
    build_evaluation_coverage_audit,
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class TestEvaluationCoverageAudit(unittest.TestCase):
    def test_dry_run_reports_covered_partial_and_missing_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            requirements_path = root / "requirements.json"
            db_path = root / "storage.sqlite"
            self._write_seed(seed_path)
            self._write_requirements(requirements_path)

            result = build_evaluation_coverage_audit(
                seed_json=seed_path,
                requirements_json=requirements_path,
                database_url=sqlalchemy_sqlite_url(db_path),
                target_backend="sqlalchemy",
                execute=False,
            )

            self.assertEqual(result["coverage_audit_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertFalse(db_path.exists())
            states = {
                item["requirement_id"]: item["coverage_state"]
                for item in result["manifest"]["items"]
            }
            self.assertEqual(states["REQ-OFFICIAL"], "COVERED")
            self.assertEqual(states["REQ-LOCAL-REGIONS"], "PARTIAL")
            self.assertEqual(states["REQ-REAL-PROJECT"], "MISSING")
            local = next(item for item in result["manifest"]["items"] if item["requirement_id"] == "REQ-LOCAL-REGIONS")
            self.assertIn("CN-SH", local["missing_values"])
            self.assertIn("REQ-REAL-PROJECT", [item["requirement_id"] for item in result["manifest"]["gap_items"]])

    def test_execute_writes_manifest_idempotently_and_payload_has_no_blob_or_raw_probe_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            requirements_path = root / "requirements.json"
            db_path = root / "storage.sqlite"
            self._write_seed(seed_path)
            self._write_requirements(requirements_path)
            database_url = sqlalchemy_sqlite_url(db_path)

            first = build_evaluation_coverage_audit(
                seed_json=seed_path,
                requirements_json=requirements_path,
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
            )
            second = build_evaluation_coverage_audit(
                seed_json=seed_path,
                requirements_json=requirements_path,
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
                records = session.list_records(EVALUATION_SEED_COVERAGE_AUDIT_OBJECT_TYPE)
                self.assertEqual(len(records), 1)
                payload_text = json.dumps(records[0].payload, ensure_ascii=False).lower()
                self.assertNotIn("bytes", payload_text)
                self.assertNotIn("%pdf", payload_text)
                self.assertNotIn("<html", payload_text)
                self.assertNotIn("第一中标候选人：甲公司", payload_text)
                self.assertFalse(records[0].governed_state["customer_visible_allowed"])
                self.assertTrue(records[0].governed_state["no_legal_conclusion"])
            finally:
                session.close()

    def test_missing_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            result = build_evaluation_coverage_audit(
                seed_json=root / "missing-seed.json",
                requirements_json=root / "missing-requirements.json",
                execute=False,
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("evaluation_seed_file_missing", result["blocking_reasons"])
            self.assertIn("evaluation_coverage_requirements_file_missing", result["blocking_reasons"])
            self.assertIn("evaluation_seed_empty", result["blocking_reasons"])
            self.assertIn("evaluation_coverage_requirements_empty", result["blocking_reasons"])

    def test_audit_covers_methods_candidate_shapes_lifecycle_and_fairness_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            requirements_path = root / "requirements.json"
            self._write_seed(seed_path)
            self._write_requirements(requirements_path)

            result = build_evaluation_coverage_audit(
                seed_json=seed_path,
                requirements_json=requirements_path,
            )
            states = {
                item["requirement_id"]: item
                for item in result["manifest"]["items"]
            }

            self.assertEqual(states["REQ-METHODS"]["coverage_state"], "COVERED")
            self.assertEqual(states["REQ-CANDIDATES"]["coverage_state"], "COVERED")
            self.assertEqual(states["REQ-LIFECYCLE"]["coverage_state"], "COVERED")
            self.assertEqual(states["REQ-BRIGHT-DARK"]["coverage_state"], "COVERED")
            self.assertEqual(states["REQ-FAIRNESS"]["coverage_state"], "COVERED")
            self.assertFalse(result["manifest"]["safety"]["download_enabled"])
            self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])

    def test_default_seed_covers_b7_review_corpus_first_cut_but_not_real_snapshots(self) -> None:
        result = build_evaluation_coverage_audit(
            seed_json=ROOT / "contracts" / "evaluation" / "evaluation_corpus_seed.json",
            requirements_json=ROOT / "contracts" / "evaluation" / "evaluation_coverage_requirements.json",
        )
        items = {
            item["requirement_id"]: item
            for item in result["manifest"]["items"]
        }

        self.assertEqual(items["REQ-B7-REVIEW-CORPUS-LIFECYCLE"]["coverage_state"], "COVERED")
        self.assertEqual(items["REQ-B7-REVIEW-CORPUS-SIGNALS"]["coverage_state"], "COVERED")
        self.assertEqual(items["REQ-REAL-PROJECT-SNAPSHOT"]["coverage_state"], "MISSING")
        self.assertFalse(result["manifest"]["safety"]["download_enabled"])
        self.assertFalse(result["manifest"]["safety"]["stage5_rule_execution_enabled"])
        self.assertTrue(all(item["no_legal_conclusion"] for item in result["manifest"]["items"]))

    def test_real_sample_execution_manifest_counts_as_real_snapshot_partial_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            execution_manifest_path = root / "execution.json"
            execution_manifest_path.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "items": [
                                {
                                    "target_id": "REAL-CANDIDATE-001",
                                    "target_execution_state": "CAPTURED_WITH_SNAPSHOTS",
                                    "document_kind": "candidate_notice",
                                    "jurisdiction": "CN-GD",
                                    "source_family": "local_public_resource_trading_center",
                                    "discovery_candidate_count": 1,
                                    "candidate_refs": [
                                        {
                                            "candidate_key": "CAND-001",
                                            "source_url": "https://example.test/candidate.html",
                                        }
                                    ],
                                    "detail_snapshot_refs": [
                                        {
                                            "snapshot_id": "SNAP-DETAIL-001",
                                            "source_url": "https://example.test/candidate.html",
                                        }
                                    ],
                                    "attachment_snapshot_refs": [
                                        {"snapshot_id": "SNAP-ATT-001"}
                                    ],
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_evaluation_coverage_audit(
                seed_json=ROOT / "contracts" / "evaluation" / "evaluation_corpus_seed.json",
                requirements_json=ROOT / "contracts" / "evaluation" / "evaluation_coverage_requirements.json",
                real_sample_execution_manifest_json=execution_manifest_path,
            )
            items = {item["requirement_id"]: item for item in result["manifest"]["items"]}

            self.assertEqual(items["REQ-REAL-PROJECT-SNAPSHOT"]["coverage_state"], "PARTIAL")
            self.assertEqual(items["REQ-REAL-PROJECT-SNAPSHOT"]["matched_seed_count"], 1)
            self.assertIn("REAL-SNAPSHOT-REAL-CANDIDATE-001", items["REQ-REAL-PROJECT-SNAPSHOT"]["matched_seed_ids"])
            self.assertEqual(result["summary"]["real_project_snapshot_execution_count"], 1)

    def test_local_region_gap_closes_when_shanghai_and_hubei_local_methods_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            seed_path = root / "seed.json"
            requirements_path = root / "requirements.json"
            self._write_seed(seed_path)
            payload = json.loads(seed_path.read_text(encoding="utf-8"))
            payload["sources"].extend(
                [
                    {
                        "seed_id": "LOCAL-SH",
                        "source_url": "https://zjw.sh.gov.cn/method.html",
                        "source_family": "local_government_policy",
                        "jurisdiction": "CN-SH",
                        "document_kind": "local_method",
                        "probe_text_optional": "上海市施工招标评标办法 经评审的合理低价法 综合评估法 推荐中标候选人。",
                        "seed_tags": ["local_method", "reasonable_low_price"],
                    },
                    {
                        "seed_id": "LOCAL-HB",
                        "source_url": "https://zjt.hubei.gov.cn/method.html",
                        "source_family": "local_government_policy",
                        "jurisdiction": "CN-HB",
                        "document_kind": "local_method",
                        "probe_text_optional": "湖北省评定分离实施办法 定标候选人 不排序中标候选人。",
                        "seed_tags": ["local_method", "bid_separation"],
                    },
                ]
            )
            seed_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self._write_requirements(requirements_path)
            requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
            for item in requirements["requirements"]:
                if item["requirement_id"] == "REQ-LOCAL-REGIONS":
                    item["required_jurisdictions"] = ["CN-GD", "CN-ZJ", "CN-SH", "CN-HB"]
                    item["minimum_seed_count"] = 4
            requirements_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")

            result = build_evaluation_coverage_audit(
                seed_json=seed_path,
                requirements_json=requirements_path,
            )
            local = next(item for item in result["manifest"]["items"] if item["requirement_id"] == "REQ-LOCAL-REGIONS")

            self.assertEqual(local["coverage_state"], "COVERED")
            self.assertEqual(local["missing_values"], [])

    def _write_seed(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "seed_id": "BASIS-LAW",
                            "source_url": "https://www.gov.cn/law.html",
                            "source_family": "official_government_policy",
                            "jurisdiction": "CN",
                            "document_kind": "official_basis",
                            "probe_text_optional": "评标方法包括综合评估法和经评审的最低投标价法。",
                            "seed_tags": ["official_basis"],
                        },
                        {
                            "seed_id": "LOCAL-GD",
                            "source_url": "https://www.gd.gov.cn/method.html",
                            "source_family": "local_government_policy",
                            "jurisdiction": "CN-GD",
                            "document_kind": "local_method",
                            "probe_text_optional": "综合评估法 技术标评分 明标",
                            "seed_tags": ["local_method", "comprehensive", "bright_bid"],
                        },
                        {
                            "seed_id": "LOCAL-ZJ",
                            "source_url": "https://jst.zj.gov.cn/method.html",
                            "source_family": "local_government_policy",
                            "jurisdiction": "CN-ZJ",
                            "document_kind": "local_method",
                            "probe_text_optional": "技术标采用暗标评审，定标候选人排名不分先后。",
                            "seed_tags": ["local_method", "dark_bid", "bid_separation"],
                        },
                        {
                            "seed_id": "METHOD-LOW",
                            "source_url": "https://example.invalid/low.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "tender_file",
                            "probe_text_optional": "采用经评审的最低投标价法。",
                            "seed_tags": ["reviewed_lowest_price"],
                        },
                        {
                            "seed_id": "METHOD-REASONABLE",
                            "source_url": "https://example.invalid/reasonable.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "tender_file",
                            "probe_text_optional": "采用合理低价法。",
                            "seed_tags": ["reasonable_low_price"],
                        },
                        {
                            "seed_id": "METHOD-PASS",
                            "source_url": "https://example.invalid/pass.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "tender_file",
                            "probe_text_optional": "技术标采用通过制。",
                            "seed_tags": ["technical_pass"],
                        },
                        {
                            "seed_id": "RANKED",
                            "source_url": "https://example.invalid/ranked.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "candidate_notice",
                            "probe_text_optional": "第一中标候选人：甲公司 项目负责人：张三 证书编号：粤144 第二中标候选人：乙公司 公示期3日",
                            "seed_tags": ["ranked_candidates"],
                        },
                        {
                            "seed_id": "UNRANKED",
                            "source_url": "https://example.invalid/unranked.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "candidate_notice",
                            "probe_text_optional": "中标候选人名单：甲公司、乙公司、丙公司，排名不分先后。",
                            "seed_tags": ["unranked_candidates"],
                        },
                        {
                            "seed_id": "SINGLE",
                            "source_url": "https://example.invalid/result.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "award_result",
                            "probe_text_optional": "中标结果公告 中标人名称：甲公司",
                            "seed_tags": ["single_winner"],
                        },
                        {
                            "seed_id": "FAIR-REGION",
                            "source_url": "https://example.invalid/fair-region.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "tender_file",
                            "probe_text_optional": "类似业绩限于特定行政区域，注册地须在本市。",
                            "seed_tags": ["fairness_region"],
                        },
                        {
                            "seed_id": "FAIR-BRAND",
                            "source_url": "https://example.invalid/fair-brand.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "tender_file",
                            "probe_text_optional": "指定品牌，不接受同等产品。",
                            "seed_tags": ["fairness_brand"],
                        },
                        {
                            "seed_id": "CLARIFICATION",
                            "source_url": "https://example.invalid/clarification.html",
                            "source_family": "offline_seed_sample",
                            "jurisdiction": "CN",
                            "document_kind": "clarification",
                            "probe_text_optional": "澄清文件：评标办法变更，技术标评分项调整。",
                            "seed_tags": ["clarification"],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _write_requirements(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "requirements_id": "test-coverage-requirements",
                    "basis_sources": [
                        {
                            "basis_id": "BASIS-1",
                            "basis_name": "测试依据",
                            "official_url": "https://www.gov.cn/law.html",
                        }
                    ],
                    "requirements": [
                        {
                            "requirement_id": "REQ-OFFICIAL",
                            "dimension": "official_basis",
                            "minimum_seed_count": 1,
                            "match": {
                                "document_kinds": ["official_basis"],
                                "source_families": ["official_government_policy"],
                            },
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补官方依据。",
                        },
                        {
                            "requirement_id": "REQ-LOCAL-REGIONS",
                            "dimension": "local_method_region",
                            "minimum_seed_count": 2,
                            "required_jurisdictions": ["CN-GD", "CN-ZJ", "CN-SH"],
                            "match": {"document_kinds": ["local_method"]},
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补地方办法。",
                        },
                        {
                            "requirement_id": "REQ-METHODS",
                            "dimension": "evaluation_method_family",
                            "minimum_seed_count": 5,
                            "required_tags_or_families": [
                                "comprehensive",
                                "reviewed_lowest_price",
                                "reasonable_low_price",
                                "technical_pass",
                                "bid_separation",
                            ],
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补评标方法。",
                        },
                        {
                            "requirement_id": "REQ-CANDIDATES",
                            "dimension": "candidate_shape",
                            "minimum_seed_count": 4,
                            "required_tags_or_modes": [
                                "ranked_candidates",
                                "unranked_candidates",
                                "bid_separation_candidates",
                                "single_winner",
                            ],
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补候选形态。",
                        },
                        {
                            "requirement_id": "REQ-LIFECYCLE",
                            "dimension": "document_lifecycle",
                            "minimum_seed_count": 4,
                            "required_document_kinds": [
                                "tender_file",
                                "candidate_notice",
                                "award_result",
                                "clarification",
                            ],
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补文档生命周期。",
                        },
                        {
                            "requirement_id": "REQ-BRIGHT-DARK",
                            "dimension": "bright_dark_bid",
                            "minimum_seed_count": 2,
                            "required_tags_or_markers": ["dark_bid", "bright_bid"],
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补明暗标。",
                        },
                        {
                            "requirement_id": "REQ-FAIRNESS",
                            "dimension": "fairness_signal",
                            "minimum_seed_count": 3,
                            "required_tags_or_markers": ["fairness_region", "fairness_brand", "clarification"],
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "补公平性样本。",
                        },
                        {
                            "requirement_id": "REQ-REAL-PROJECT",
                            "dimension": "real_project_snapshot",
                            "minimum_seed_count": 50,
                            "match": {"seed_tags": ["real_project_sample"]},
                            "basis_refs": ["BASIS-1"],
                            "gap_action": "采 50-100 个真实项目快照。",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
