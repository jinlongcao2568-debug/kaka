from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.pipeline import run_internal_chain
from storage.internal_object_approval import (
    approval_for_resource,
    decide_object_approval,
    request_object_approval,
    revoke_object_approval,
)
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.saleable_opportunity_repo import SaleableOpportunityRepository
from storage_test_support import IsolatedStorageTestMixin
import storage.internal_object_approval as approval_module


class TestInternalObjectApproval(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="internal-object-approval.json")
        stage7 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage7"]
        self.opportunity = dict(stage7.record("saleable_opportunity").data)
        SaleableOpportunityRepository().save(self.opportunity)
        self.opportunity_id = str(self.opportunity["opportunity_id"])
        self.scope_sha256 = "a" * 64

    def tearDown(self) -> None:
        self.tearDown_storage_test_env()

    def _request(self) -> dict[str, object]:
        return request_object_approval(
            resource_type="opportunity",
            resource_id=self.opportunity_id,
            action="internal_preview_download",
            reason="concurrency approval test",
            requested_by="operator-a",
            requested_by_role="operator",
            approval_scope_sha256=self.scope_sha256,
        )

    def test_concurrent_request_and_decision_are_each_unique(self) -> None:
        original_append = approval_module._append_unique
        request_barrier = Barrier(8)

        def synchronized_request_append(repository, event, *, conflict_message):
            if event.action_id == "REQUEST_OBJECT_APPROVAL":
                request_barrier.wait(timeout=10)
            return original_append(repository, event, conflict_message=conflict_message)

        def request_worker() -> str:
            try:
                self._request()
                return "created"
            except ValueError:
                return "conflict"

        with patch.object(
            approval_module,
            "_append_unique",
            side_effect=synchronized_request_append,
        ):
            with ThreadPoolExecutor(max_workers=8) as executor:
                request_results = list(executor.map(lambda _: request_worker(), range(8)))

        self.assertEqual(request_results.count("created"), 1)
        self.assertEqual(request_results.count("conflict"), 7)
        request_events = [
            event
            for event in OperatorActionRepository().list_all()
            if event.action_id == "REQUEST_OBJECT_APPROVAL"
        ]
        self.assertEqual(len(request_events), 1)
        request_id = request_events[0].action_event_id

        decision_barrier = Barrier(8)

        def synchronized_decision_append(repository, event, *, conflict_message):
            if event.action_id.startswith("DECIDE_OBJECT_APPROVAL_"):
                decision_barrier.wait(timeout=10)
            return original_append(repository, event, conflict_message=conflict_message)

        def decision_worker(index: int) -> str:
            try:
                decide_object_approval(
                    request_id=request_id,
                    decision="APPROVED" if index % 2 == 0 else "REJECTED",
                    reason="concurrent independent decision",
                    reviewer=f"reviewer-{index}",
                    reviewer_role="reviewer",
                    current_approval_scope_sha256=self.scope_sha256,
                )
                return "decided"
            except ValueError:
                return "conflict"

        with patch.object(
            approval_module,
            "_append_unique",
            side_effect=synchronized_decision_append,
        ):
            with ThreadPoolExecutor(max_workers=8) as executor:
                decision_results = list(executor.map(decision_worker, range(8)))

        self.assertEqual(decision_results.count("decided"), 1)
        self.assertEqual(decision_results.count("conflict"), 7)
        decision_events = [
            event
            for event in OperatorActionRepository().list_all()
            if event.action_id.startswith("DECIDE_OBJECT_APPROVAL_")
        ]
        self.assertEqual(len(decision_events), 1)

    def test_rejected_same_target_requires_change_before_resubmission(self) -> None:
        requested = self._request()
        rejected = decide_object_approval(
            request_id=str(requested["request_id"]),
            decision="REJECTED",
            reason="target needs revision",
            reviewer="reviewer-a",
            reviewer_role="reviewer",
            current_approval_scope_sha256=self.scope_sha256,
        )
        self.assertEqual(rejected["state"], "REJECTED")

        with self.assertRaisesRegex(ValueError, "only be re-requested after the target changes"):
            self._request()

        changed = dict(self.opportunity)
        changed["crm_owner_state"] = "ASSIGNED"
        SaleableOpportunityRepository().save(changed)
        resubmitted = self._request()
        self.assertNotEqual(resubmitted["request_id"], requested["request_id"])

    def test_approved_request_expires_and_same_target_can_be_requested_again(self) -> None:
        approved_at = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)
        with patch.object(approval_module, "_now", return_value=approved_at):
            requested = self._request()
            approved = decide_object_approval(
                request_id=str(requested["request_id"]),
                decision="APPROVED",
                reason="time limited internal preview",
                reviewer="reviewer-a",
                reviewer_role="reviewer",
                current_approval_scope_sha256=self.scope_sha256,
                valid_for_seconds=60,
            )
        self.assertTrue(approved["approval_satisfied"])
        self.assertFalse(approved["approval_expired"])
        self.assertEqual(
            approved["valid_until"],
            (approved_at + timedelta(seconds=60)).isoformat(),
        )

        with patch.object(
            approval_module,
            "_now",
            return_value=approved_at + timedelta(seconds=61),
        ):
            expired = approval_for_resource(
                resource_type="opportunity",
                resource_id=self.opportunity_id,
                action="internal_preview_download",
                current_approval_scope_sha256=self.scope_sha256,
            )
            resubmitted = self._request()
        self.assertIsNotNone(expired)
        self.assertTrue(expired["approval_expired"])
        self.assertFalse(expired["approval_satisfied"])
        self.assertNotEqual(resubmitted["request_id"], requested["request_id"])

    def test_reviewer_can_revoke_and_revoked_target_can_be_requested_again(self) -> None:
        requested = self._request()
        approved = decide_object_approval(
            request_id=str(requested["request_id"]),
            decision="APPROVED",
            reason="short lived internal preview",
            reviewer="reviewer-a",
            reviewer_role="reviewer",
            current_approval_scope_sha256=self.scope_sha256,
        )
        revoked = revoke_object_approval(
            request_id=str(requested["request_id"]),
            reason="masking concern discovered",
            revoked_by="reviewer-a",
            revoked_by_role="reviewer",
            current_approval_scope_sha256=self.scope_sha256,
        )
        self.assertTrue(approved["approval_satisfied"])
        self.assertEqual(revoked["state"], "REVOKED")
        self.assertTrue(revoked["approval_revoked"])
        self.assertFalse(revoked["approval_satisfied"])
        with self.assertRaisesRegex(ValueError, "only an approved"):
            revoke_object_approval(
                request_id=str(requested["request_id"]),
                reason="duplicate revoke",
                revoked_by="reviewer-a",
                revoked_by_role="reviewer",
                current_approval_scope_sha256=self.scope_sha256,
            )
        resubmitted = self._request()
        self.assertNotEqual(resubmitted["request_id"], requested["request_id"])


if __name__ == "__main__":
    unittest.main()
