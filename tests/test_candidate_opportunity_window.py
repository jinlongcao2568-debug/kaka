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
from stage3_parsing.candidate_opportunity_window import (
    CANDIDATE_OPPORTUNITY_WINDOW_MANIFEST_OBJECT_TYPE,
    VALUE_TIMER_ACTIVE,
    VALUE_TIMER_NO_COUNTDOWN_SINGLE_WINNER,
    WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES,
    WINDOW_REVIEW_ONLY,
    WINDOW_REVIEW_READY,
    build_candidate_opportunity_windows,
)
from stage3_parsing.evaluation_profiles import EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class CandidateOpportunityWindowTests(unittest.TestCase):
    def test_dry_run_does_not_write_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "candidate-window.sqlite")
            object_root = root / "objects"
            _prepare_profile_manifest(database_url=database_url, object_root=object_root)

            result = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=False,
                created_at="2026-05-07T10:00:00+00:00",
            )

            self.assertEqual(result["window_mode"], "DRY_RUN")
            self.assertTrue(result["safe_to_execute"])
            self.assertEqual(result["summary"]["window_item_count"], 6)
            self.assertNotIn("BASIS", {item["seed_id"] for item in result["manifest"]["items"]})

            session = DatabaseSession(settings=_settings(database_url=database_url, object_root=object_root))
            try:
                self.assertEqual(session.list_records(CANDIDATE_OPPORTUNITY_WINDOW_MANIFEST_OBJECT_TYPE), [])
            finally:
                session.close()

    def test_ranked_candidate_with_active_window_is_review_ready_high_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "candidate-window-ranked.sqlite")
            object_root = root / "objects"
            _prepare_profile_manifest(database_url=database_url, object_root=object_root)

            result = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T10:00:00+00:00",
            )

            items = {item["seed_id"]: item for item in result["manifest"]["items"]}
            ranked = items["RANKED"]
            self.assertEqual(ranked["window_state"], WINDOW_REVIEW_READY)
            self.assertEqual(ranked["review_priority"], "P1_HIGH")
            self.assertEqual(ranked["value_timer_state"], VALUE_TIMER_ACTIVE)
            self.assertEqual(ranked["candidate_count_optional"], 2)
            self.assertEqual(ranked["candidate_rows"][0]["candidate_name"], "甲公司")
            self.assertTrue(ranked["review_required"])
            self.assertFalse(ranked["customer_visible_allowed"])
            self.assertTrue(ranked["no_legal_conclusion"])

    def test_bid_separation_can_be_review_ready_but_lower_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "candidate-window-separation.sqlite")
            object_root = root / "objects"
            _prepare_profile_manifest(database_url=database_url, object_root=object_root)

            result = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T10:00:00+00:00",
            )

            item = {row["seed_id"]: row for row in result["manifest"]["items"]}["SEPARATION"]
            self.assertEqual(item["candidate_selection_mode"], "bid_separation_candidates")
            self.assertEqual(item["window_state"], WINDOW_REVIEW_READY)
            self.assertEqual(item["review_priority"], "P2_MEDIUM")
            self.assertEqual(item["candidate_count_optional"], 3)

            probe_ready = {row["seed_id"]: row for row in result["manifest"]["items"]}["PROBE_READY"]
            self.assertEqual(probe_ready["window_state"], WINDOW_REVIEW_READY)
            self.assertIn("snapshot_id_missing", probe_ready["review_reasons"])

    def test_single_winner_missing_rows_and_missing_window_fail_closed_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "candidate-window-review.sqlite")
            object_root = root / "objects"
            _prepare_profile_manifest(database_url=database_url, object_root=object_root)

            result = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T10:00:00+00:00",
            )

            items = {item["seed_id"]: item for item in result["manifest"]["items"]}
            winner = items["WINNER"]
            self.assertEqual(winner["window_state"], WINDOW_REVIEW_ONLY)
            self.assertEqual(winner["value_timer_state"], VALUE_TIMER_NO_COUNTDOWN_SINGLE_WINNER)
            self.assertIn("single_winner_or_award_result_no_preaward_countdown", winner["review_reasons"])

            missing_rows = items["MISSING_ROWS"]
            self.assertEqual(missing_rows["window_state"], WINDOW_BLOCKED_INSUFFICIENT_CANDIDATES)
            self.assertIn("candidate_rows_insufficient", missing_rows["review_reasons"])

            missing_window = items["MISSING_WINDOW"]
            self.assertEqual(missing_window["window_state"], WINDOW_REVIEW_ONLY)
            self.assertIn("objection_window_missing", missing_window["review_reasons"])
            self.assertIn("snapshot_id_missing", missing_window["review_reasons"])

    def test_execute_is_idempotent_payload_has_no_blob_and_missing_profile_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            database_url = sqlalchemy_sqlite_url(root / "candidate-window-idempotent.sqlite")
            object_root = root / "objects"
            _prepare_profile_manifest(database_url=database_url, object_root=object_root)

            first = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T10:00:00+00:00",
            )
            second = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=object_root,
                execute=True,
                created_at="2026-05-07T10:05:00+00:00",
            )
            self.assertEqual(first["manifest"]["manifest_id"], second["manifest"]["manifest_id"])

            session = DatabaseSession(settings=_settings(database_url=database_url, object_root=object_root))
            try:
                records = session.list_records(CANDIDATE_OPPORTUNITY_WINDOW_MANIFEST_OBJECT_TYPE)
                self.assertEqual(len(records), 1)
                payload_text = json.dumps(records[0].payload, ensure_ascii=False, sort_keys=True)
                self.assertNotIn('"bytes"', payload_text)
                self.assertNotIn("<html", payload_text.lower())
                self.assertNotIn("%PDF", payload_text)
                self.assertFalse(records[0].payload["safety"]["sales_action_enabled"])
            finally:
                session.close()

        with tempfile.TemporaryDirectory() as missing_dir:
            database_url = sqlalchemy_sqlite_url(Path(missing_dir) / "missing.sqlite")
            result = build_candidate_opportunity_windows(
                database_url=database_url,
                target_backend="sqlalchemy",
                object_storage_path=Path(missing_dir) / "objects",
                execute=True,
                created_at="2026-05-07T10:10:00+00:00",
            )
            self.assertFalse(result["safe_to_execute"])
            self.assertIn("evaluation_stage3_profile_manifest_missing", result["blocking_reasons"])
            self.assertFalse(result["execution"]["executed"])


def _prepare_profile_manifest(*, database_url: str, object_root: Path) -> None:
    session = DatabaseSession(settings=_settings(database_url=database_url, object_root=object_root))
    try:
        payload = {
            "manifest_id": "EVALUATION-STAGE3-PROFILE-TEST",
            "created_at": "2026-05-07T09:50:00+00:00",
            "items": [
                _profile_item(
                    seed_id="RANKED",
                    document_kind="candidate_notice",
                    snapshot_id="SNAP-RANKED",
                    mode="ranked_candidates",
                    objection_window="2026年05月07日至2026年05月10日",
                    rows=[
                        _candidate("甲公司", rank=1, price="1000万元", score="95.5", pm="张三", cert="粤144000000001"),
                        _candidate("乙公司", rank=2, price="1100万元", score="88.1", pm="李四", cert="粤144000000002"),
                    ],
                ),
                _profile_item(
                    seed_id="SEPARATION",
                    document_kind="candidate_notice",
                    snapshot_id="SNAP-SEPARATION",
                    mode="bid_separation_candidates",
                    objection_window="2026-05-07至2026-05-10",
                    rows=[_candidate("甲公司"), _candidate("乙公司"), _candidate("丁公司")],
                ),
                _profile_item(
                    seed_id="WINNER",
                    document_kind="award_result",
                    snapshot_id="SNAP-WINNER",
                    mode="single_winner",
                    objection_window=None,
                    rows=[_candidate("丙公司", rank=1)],
                ),
                _profile_item(
                    seed_id="MISSING_ROWS",
                    document_kind="candidate_notice",
                    snapshot_id="SNAP-MISSING-ROWS",
                    mode="ranked_candidates",
                    objection_window="2026-05-07至2026-05-10",
                    rows=[],
                ),
                _profile_item(
                    seed_id="MISSING_WINDOW",
                    document_kind="candidate_notice",
                    snapshot_id=None,
                    mode="ranked_candidates",
                    objection_window=None,
                    rows=[_candidate("甲公司", rank=1), _candidate("乙公司", rank=2)],
                ),
                _profile_item(
                    seed_id="PROBE_READY",
                    document_kind="candidate_notice",
                    snapshot_id=None,
                    mode="ranked_candidates",
                    objection_window="2026-05-07至2026-05-10",
                    rows=[_candidate("甲公司", rank=1), _candidate("乙公司", rank=2)],
                ),
                _profile_item(
                    seed_id="BASIS",
                    document_kind="official_basis",
                    snapshot_id=None,
                    mode="ranked_candidates",
                    objection_window="2026-05-07至2026-05-10",
                    rows=[_candidate("依据样本", rank=1), _candidate("依据样本二", rank=2)],
                ),
            ],
        }
        session.upsert_record(
            PersistedRecord(
                object_type=EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE,
                record_id="EVALUATION-STAGE3-PROFILE-TEST",
                stage_scope=3,
                project_id=None,
                object_refs={},
                decision_states={"evaluation_stage3_profile_manifest_state": "CURRENT"},
                trace_refs={},
                audit_refs={},
                governed_state={
                    "review_required": True,
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                },
                writeback_state={},
                payload=payload,
                persisted_at="2026-05-07T09:50:00+00:00",
            )
        )
    finally:
        session.close()


def _profile_item(
    *,
    seed_id: str,
    document_kind: str,
    snapshot_id: str | None,
    mode: str,
    objection_window: str | None,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "seed_id": seed_id,
        "source_url": f"https://example.test/{seed_id.lower()}.html",
        "document_kind": document_kind,
        "snapshot_id_optional": snapshot_id,
        "candidate_set_profile": {
            "candidate_selection_mode": mode,
            "candidate_count_optional": len(rows) if rows else None,
            "objection_window_optional": objection_window,
            "candidate_rows": rows,
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate(
    name: str,
    *,
    rank: int | None = None,
    price: str | None = None,
    score: str | None = None,
    pm: str | None = None,
    cert: str | None = None,
) -> dict[str, object]:
    return {
        "candidate_name": name,
        "candidate_rank_optional": rank,
        "bid_price_optional": price,
        "total_score_optional": score,
        "project_manager_optional": pm,
        "certificate_no_optional": cert,
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


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
