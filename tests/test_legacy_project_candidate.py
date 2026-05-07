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

from shared.settings import Settings
from storage.db import DatabaseSession, PersistedRecord
from storage.legacy_attachment_parse import LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE
from storage.legacy_cluster_qa import (
    LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE,
    LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE,
    LINKED_BY_EXACT_NORMALIZED_FILENAME,
    PROJECT_NAME_HIGH_CONFIDENCE,
    PROJECT_NAME_OVEREXTRACTED_REVIEW,
    REVIEW_ONLY_UNLINKED_ATTACHMENT,
)
from storage.legacy_project_candidate import (
    LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE,
    LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE,
    LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH,
    LINKED_BY_V1_EXACT_NORMALIZED_FILENAME,
    PROJECT_CANDIDATE_REVIEW_ONLY,
    PROJECT_CANDIDATE_REVIEW_READY,
    REVIEW_ONLY_AMBIGUOUS_PARSED_PROJECT_NAME_MATCH,
    REVIEW_ONLY_ATTACHMENT_FIELD_OVEREXTRACTED,
    REVIEW_ONLY_ATTACHMENT_PARSE_MISSING,
    REVIEW_ONLY_ATTACHMENT_PARSED_PROJECT_NAME_UNMATCHED,
    REVIEW_ONLY_ATTACHMENT_PROJECT_NAME_MISSING,
    build_legacy_project_candidates,
)
from storage.legacy_snapshot_parse import (
    LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE,
    normalize_project_name,
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class LegacyProjectCandidateTests(unittest.TestCase):
    def test_builds_link_v2_and_project_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-project-candidates.sqlite")
            settings = _settings(database_url)
            session = DatabaseSession(settings=settings)
            try:
                _seed_candidate_fixture(session)
            finally:
                session.close()

            dry_run = build_legacy_project_candidates(
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=False,
                created_at="2026-05-07T08:00:00+00:00",
            )
            self.assertTrue(dry_run["safe_to_execute"])
            self.assertFalse(dry_run["execution"]["executed"])
            self.assertEqual(dry_run["summary"]["attachment_link_v2"]["linked_attachment_count"], 2)
            dry_session = DatabaseSession(settings=settings)
            try:
                self.assertEqual(dry_session.list_records(LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE), [])
                self.assertEqual(dry_session.list_records(LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE), [])
            finally:
                dry_session.close()

            executed = build_legacy_project_candidates(
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at="2026-05-07T08:00:00+00:00",
            )
            self.assertTrue(executed["execution"]["executed"])
            self.assertEqual(executed["summary"]["project_candidate"]["project_candidate_count"], 2)

            target = DatabaseSession(settings=settings)
            try:
                link_records = target.list_records(LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE)
                candidate_records = target.list_records(LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(link_records), 1)
                self.assertEqual(len(candidate_records), 1)
                links = {item["object_key"]: item for item in link_records[0].payload["items"]}
                self.assertEqual(links["objects/aa/v1.pdf"]["link_state"], LINKED_BY_V1_EXACT_NORMALIZED_FILENAME)
                self.assertEqual(links["objects/bb/parsed.docx"]["link_state"], LINKED_BY_PARSED_PROJECT_NAME_UNIQUE_MATCH)
                self.assertEqual(links["objects/cc/no-field.xlsx"]["link_state"], REVIEW_ONLY_ATTACHMENT_PROJECT_NAME_MISSING)
                candidates = {
                    item["cluster_id"]: item
                    for item in candidate_records[0].payload["items"]
                }
                self.assertEqual(candidates["CLUSTER-ROAD"]["candidate_state"], PROJECT_CANDIDATE_REVIEW_READY)
                self.assertEqual(candidates["CLUSTER-BRIDGE"]["candidate_state"], PROJECT_CANDIDATE_REVIEW_READY)
                self.assertEqual(candidates["CLUSTER-ROAD"]["linked_attachment_object_keys"], ["objects/aa/v1.pdf"])
                self.assertEqual(candidates["CLUSTER-BRIDGE"]["linked_attachment_object_keys"], ["objects/bb/parsed.docx"])
                self.assert_no_blob_payload(link_records[0].payload)
                self.assert_no_blob_payload(candidate_records[0].payload)
            finally:
                target.close()

            repeated = build_legacy_project_candidates(
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at="2026-05-07T08:05:00+00:00",
            )
            self.assertTrue(repeated["execution"]["executed"])
            repeated_session = DatabaseSession(settings=settings)
            try:
                self.assertEqual(
                    len(repeated_session.list_records(LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE)),
                    1,
                )
                self.assertEqual(
                    len(repeated_session.list_records(LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE)),
                    1,
                )
            finally:
                repeated_session.close()

    def test_review_states_for_ambiguous_overextracted_unmatched_and_missing_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-project-candidate-review.sqlite")
            settings = _settings(database_url)
            session = DatabaseSession(settings=settings)
            try:
                _seed_review_fixture(session)
            finally:
                session.close()

            result = build_legacy_project_candidates(
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at="2026-05-07T08:10:00+00:00",
            )

            links = {
                item["object_key"]: item
                for item in result["attachment_link_v2_manifest"]["items"]
            }
            self.assertEqual(
                links["objects/dd/ambiguous.pdf"]["link_state"],
                REVIEW_ONLY_AMBIGUOUS_PARSED_PROJECT_NAME_MATCH,
            )
            self.assertEqual(
                links["objects/ee/over.pdf"]["link_state"],
                REVIEW_ONLY_ATTACHMENT_FIELD_OVEREXTRACTED,
            )
            self.assertEqual(
                links["objects/ff/unmatched.pdf"]["link_state"],
                REVIEW_ONLY_ATTACHMENT_PARSED_PROJECT_NAME_UNMATCHED,
            )
            self.assertEqual(
                links["objects/gg/missing.pdf"]["link_state"],
                REVIEW_ONLY_ATTACHMENT_PARSE_MISSING,
            )
            candidates = {
                item["cluster_id"]: item
                for item in result["project_candidate_manifest"]["items"]
            }
            self.assertEqual(candidates["CLUSTER-OVER"]["candidate_state"], PROJECT_CANDIDATE_REVIEW_ONLY)
            self.assert_no_blob_payload(result["attachment_link_v2_manifest"])
            self.assert_no_blob_payload(result["project_candidate_manifest"])

    def test_missing_prerequisites_do_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_url = sqlalchemy_sqlite_url(Path(tmp_dir) / "legacy-project-candidate-missing.sqlite")
            result = build_legacy_project_candidates(
                database_url=database_url,
                target_backend="sqlalchemy",
                execute=True,
                created_at="2026-05-07T08:20:00+00:00",
            )

            self.assertFalse(result["safe_to_execute"])
            self.assertIn("legacy_attachment_parse_manifest_missing", result["blocking_reasons"])
            self.assertFalse(result["execution"]["executed"])
            session = DatabaseSession(settings=_settings(database_url))
            try:
                self.assertEqual(session.list_records(LEGACY_CLUSTER_ATTACHMENT_LINK_V2_MANIFEST_OBJECT_TYPE), [])
                self.assertEqual(session.list_records(LEGACY_PROJECT_CANDIDATE_MANIFEST_OBJECT_TYPE), [])
            finally:
                session.close()

    def assert_no_blob_payload(self, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn('"bytes"', encoded)
        self.assertNotIn("%PDF", encoded)
        self.assertNotIn("<html", encoded.lower())
        self.assertNotIn("PK\\u0003\\u0004", encoded)
        self.assertLess(len(encoded), 256_000)


def _settings(database_url: str) -> Settings:
    return Settings(
        storage_backend="sqlalchemy",
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
    )


def _seed_candidate_fixture(session: DatabaseSession) -> None:
    clusters = [
        _cluster("CLUSTER-ROAD", "测试道路工程", ["SNAP-ROAD-EVAL"], ["bid_evaluation_report"]),
        _cluster("CLUSTER-BRIDGE", "测试桥梁工程", ["SNAP-BRIDGE-TENDER"], ["tender_notice"]),
    ]
    qa_items = [
        _qa_item("CLUSTER-ROAD", "测试道路工程", PROJECT_NAME_HIGH_CONFIDENCE),
        _qa_item("CLUSTER-BRIDGE", "测试桥梁工程", PROJECT_NAME_HIGH_CONFIDENCE),
    ]
    link_items = [
        _v1_link("objects/aa/v1.pdf", "sha-aa", LINKED_BY_EXACT_NORMALIZED_FILENAME, "CLUSTER-ROAD", "测试道路工程"),
        _v1_link("objects/bb/parsed.docx", "sha-bb", REVIEW_ONLY_UNLINKED_ATTACHMENT, None, None),
        _v1_link("objects/cc/no-field.xlsx", "sha-cc", REVIEW_ONLY_UNLINKED_ATTACHMENT, None, None),
    ]
    parse_items = [
        _parse_item("objects/aa/v1.pdf", "sha-aa", "pdf", "PARSED", "测试道路工程"),
        _parse_item("objects/bb/parsed.docx", "sha-bb", "docx", "PARSED", "测试桥梁工程"),
        _parse_item("objects/cc/no-field.xlsx", "sha-cc", "xlsx", "REVIEW_REQUIRED", None),
    ]
    _upsert_prerequisites(session, clusters=clusters, qa_items=qa_items, link_items=link_items, parse_items=parse_items)


def _seed_review_fixture(session: DatabaseSession) -> None:
    clusters = [
        _cluster("CLUSTER-DUP-A", "重复工程A", ["SNAP-DUP-A"], ["tender_notice"]),
        _cluster("CLUSTER-DUP-B", "重复工程B", ["SNAP-DUP-B"], ["award_result"]),
        _cluster("CLUSTER-OVER", "过抽取工程 项目编号：P-1 资金来源：政府", ["SNAP-OVER"], ["tender_notice"]),
    ]
    duplicate_key = normalize_project_name("重复工程")
    qa_items = [
        _qa_item("CLUSTER-DUP-A", "重复工程", PROJECT_NAME_HIGH_CONFIDENCE, refined_key=duplicate_key),
        _qa_item("CLUSTER-DUP-B", "重复工程", PROJECT_NAME_HIGH_CONFIDENCE, refined_key=duplicate_key),
        _qa_item(
            "CLUSTER-OVER",
            None,
            PROJECT_NAME_OVEREXTRACTED_REVIEW,
            refined_key=None,
            reasons=["original_project_name_overextracted"],
        ),
    ]
    link_items = [
        _v1_link("objects/dd/ambiguous.pdf", "sha-dd", REVIEW_ONLY_UNLINKED_ATTACHMENT, None, None),
        _v1_link("objects/ee/over.pdf", "sha-ee", REVIEW_ONLY_UNLINKED_ATTACHMENT, None, None),
        _v1_link("objects/ff/unmatched.pdf", "sha-ff", REVIEW_ONLY_UNLINKED_ATTACHMENT, None, None),
        _v1_link("objects/gg/missing.pdf", "sha-gg", REVIEW_ONLY_UNLINKED_ATTACHMENT, None, None),
    ]
    parse_items = [
        _parse_item("objects/dd/ambiguous.pdf", "sha-dd", "pdf", "PARSED", "重复工程"),
        _parse_item("objects/ee/over.pdf", "sha-ee", "pdf", "PARSED", "海吉星公益冷库 项目编号：P-1 资金来源：政府"),
        _parse_item("objects/ff/unmatched.pdf", "sha-ff", "pdf", "PARSED", "不存在工程"),
    ]
    _upsert_prerequisites(session, clusters=clusters, qa_items=qa_items, link_items=link_items, parse_items=parse_items)


def _upsert_prerequisites(
    session: DatabaseSession,
    *,
    clusters: list[dict[str, object]],
    qa_items: list[dict[str, object]],
    link_items: list[dict[str, object]],
    parse_items: list[dict[str, object]],
) -> None:
    session.upsert_record(
        _record(
            LEGACY_PROJECT_CLUSTER_MANIFEST_OBJECT_TYPE,
            "LEGACY-PROJECT-CLUSTER-FIXTURE",
            {
                "manifest_id": "LEGACY-PROJECT-CLUSTER-FIXTURE",
                "created_at": "2026-05-07T07:30:00+00:00",
                "clusters": clusters,
                "non_project_or_review_items": [
                    {"snapshot_id": "SNAP-PLATFORM", "cluster_eligibility": "NON_PROJECT_PLATFORM_PAGE"}
                ],
            },
        )
    )
    session.upsert_record(
        _record(
            LEGACY_PROJECT_CLUSTER_QA_MANIFEST_OBJECT_TYPE,
            "LEGACY-CLUSTER-QA-FIXTURE",
            {
                "manifest_id": "LEGACY-CLUSTER-QA-FIXTURE",
                "created_at": "2026-05-07T07:35:00+00:00",
                "items": qa_items,
            },
        )
    )
    session.upsert_record(
        _record(
            LEGACY_CLUSTER_ATTACHMENT_LINK_MANIFEST_OBJECT_TYPE,
            "LEGACY-ATTACHMENT-LINK-FIXTURE",
            {
                "manifest_id": "LEGACY-ATTACHMENT-LINK-FIXTURE",
                "created_at": "2026-05-07T07:40:00+00:00",
                "items": link_items,
            },
        )
    )
    session.upsert_record(
        _record(
            LEGACY_ATTACHMENT_PARSE_MANIFEST_OBJECT_TYPE,
            "LEGACY-ATTACHMENT-PARSE-FIXTURE",
            {
                "manifest_id": "LEGACY-ATTACHMENT-PARSE-FIXTURE",
                "created_at": "2026-05-07T07:45:00+00:00",
                "items": parse_items,
            },
        )
    )


def _record(object_type: str, record_id: str, payload: dict[str, object]) -> PersistedRecord:
    return PersistedRecord(
        object_type=object_type,
        record_id=record_id,
        stage_scope=0,
        project_id=None,
        object_refs={},
        decision_states={},
        trace_refs={},
        audit_refs={},
        governed_state={"customer_visible_allowed": False, "no_legal_conclusion": True},
        writeback_state={"large_object_blob_database_import_enabled": False},
        payload=payload,
        persisted_at=str(payload["created_at"]),
    )


def _cluster(cluster_id: str, project_name: str, snapshot_ids: list[str], notice_stages: list[str]) -> dict[str, object]:
    return {
        "cluster_id": cluster_id,
        "cluster_key": normalize_project_name(project_name),
        "normalized_project_name": normalize_project_name(project_name),
        "display_project_name": project_name,
        "snapshot_ids": snapshot_ids,
        "notice_stages": notice_stages,
        "source_families": ["legacy_public_html"],
        "snapshot_count": len(snapshot_ids),
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "cluster_state": "PROJECT_CLUSTERED",
    }


def _qa_item(
    cluster_id: str,
    refined_name: str | None,
    qa_state: str,
    *,
    refined_key: str | None = None,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "cluster_id": cluster_id,
        "original_cluster_key": refined_key or normalize_project_name(refined_name),
        "original_project_name": refined_name or "",
        "refined_project_name_optional": refined_name,
        "refined_cluster_key_optional": refined_key if refined_key is not None else normalize_project_name(refined_name),
        "qa_state": qa_state,
        "name_source": "fixture",
        "snapshot_ids": [f"SNAP-{cluster_id}"],
        "snapshot_count": 1,
        "notice_stages": ["tender_notice"],
        "name_quality_reasons": list(reasons or ["fixture_project_name"]),
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _v1_link(
    object_key: str,
    sha256: str,
    link_state: str,
    cluster_id: str | None,
    project_name: str | None,
) -> dict[str, object]:
    return {
        "object_key": object_key,
        "sha256": sha256,
        "content_kind": object_key.rsplit(".", 1)[-1],
        "content_type": "application/octet-stream",
        "byte_size": 100,
        "link_state": link_state,
        "linked_cluster_id_optional": cluster_id,
        "linked_refined_project_name_optional": project_name,
        "match_basis": "fixture",
        "path_refs": [],
        "review_reasons": ["review_required_legacy_attachment_candidate"],
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _parse_item(
    object_key: str,
    sha256: str,
    content_kind: str,
    parse_state: str,
    project_name: str | None,
) -> dict[str, object]:
    fields = []
    if project_name:
        fields.append(
            {
                "field_name": "project_name",
                "field_value_optional": project_name,
                "source_slice_sha256": f"slice-{sha256}",
                "locator_type": f"{content_kind}_text",
                "confidence": 0.88,
                "review_required": False,
                "parse_warnings": [],
            }
        )
    return {
        "object_key": object_key,
        "sha256": sha256,
        "content_kind": content_kind,
        "content_type": "application/octet-stream",
        "byte_size": 100,
        "parse_state": parse_state,
        "parser_family": content_kind,
        "attachment_type": content_kind.upper(),
        "parsed_field_count": len(fields),
        "parsed_fields_summary": fields,
        "review_reasons": ["legacy_attachment_review_required"],
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


if __name__ == "__main__":
    unittest.main()
