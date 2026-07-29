from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime.production_release_orchestrator import (
    ProductionReleaseConfig,
    suspend_production_release,
)
from shared.settings import Settings
from stage9_delivery.production_execution import (
    approve_and_execute_production_refund,
    authorize_customer_session,
    create_production_payment,
    issue_customer_artifact_grant,
    process_stripe_webhook,
    read_customer_artifact,
    request_production_refund,
    revoke_customer_artifact_grant,
    verify_stripe_webhook,
)
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.order_record_repo import OrderRecordRepository
from storage.repositories.payment_record_repo import PaymentRecordRepository


class _StripeStub:
    def create_checkout_session(self, **kwargs: object) -> dict[str, object]:
        return {
            "id": "cs_production_test_001",
            "status": "open",
            "url": "https://checkout.stripe.com/c/pay/test-session",
            "payment_intent": None,
            "request": dict(kwargs),
        }

    def create_refund(self, **kwargs: object) -> dict[str, object]:
        return {
            "id": "re_production_test_001",
            "status": "pending",
            "request": dict(kwargs),
        }

    def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, object]:
        return {
            "id": checkout_session_id,
            "status": "open",
            "url": "https://checkout.stripe.com/c/pay/test-session",
        }


class TestStage9ProductionExecution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.portal_secret = self.root / "portal-secret"
        self.payment_secret = self.root / "payment-secret"
        self.webhook_secret = self.root / "webhook-secret"
        self.portal_secret.write_bytes(b"portal-production-secret-32-bytes-value")
        self.payment_secret.write_bytes(b"payment-production-secret-32-bytes-value")
        self.webhook_secret.write_bytes(b"webhook-production-secret-32-bytes-value")
        self.settings = Settings(
            repo_root=str(ROOT),
            environment="PROD_LIVE_MODE",
            storage_backend="json-file",
            storage_path_optional=str(self.root / "runtime.json"),
            storage_scope="process",
            storage_runtime_mode="explicit-path",
            object_storage_backend="local-filesystem",
            object_storage_path_optional=str(self.root / "objects"),
        )
        self.session = DatabaseSession(settings=self.settings)
        self.objects = ObjectStorageRepository(
            session=self.session,
            settings=self.settings,
        )
        self.config = ProductionReleaseConfig(
            enabled=True,
            mode="CANARY",
            release_id="release-stage9-test",
            release_version="v1",
            tenant_id="tenant-a",
            public_base_url="https://portal.example.test",
            window_start_at="2020-01-01T00:00:00Z",
            window_end_at="2099-01-01T00:00:00Z",
            canary_customer_limit=3,
            customer_visible_enabled=True,
            payment_enabled=True,
            delivery_enabled=True,
            refund_enabled=True,
            automated_refund_enabled=False,
            kill_switch_enabled=False,
            customer_portal_signing_key_file=str(self.portal_secret),
            payment_secret_key_file=str(self.payment_secret),
            payment_webhook_secret_file=str(self.webhook_secret),
            backup_manifest_ref="backup:test",
            restore_report_ref="restore:test",
            rollback_ref="rollback:test",
            alert_dispatch_required=True,
        )
        self.release = {
            "release_active": True,
            "release_id": self.config.release_id,
            "readiness_hash": "a" * 64,
            "payment_execution_enabled": True,
            "delivery_execution_enabled": True,
            "refund_execution_enabled": True,
            "customer_visible_allowed": True,
            "active_release_window": {"request_id": "PRR-TEST-001"},
        }
        self.session.upsert_record(
            PersistedRecord(
                object_type="production_release_window",
                record_id="PRR-TEST-001",
                stage_scope=9,
                project_id=None,
                object_refs={
                    "release_id": self.config.release_id,
                    "tenant_id": self.config.tenant_id,
                },
                decision_states={"state": "ACTIVE"},
                trace_refs={},
                audit_refs={"approval": "production_release_approval:test"},
                governed_state={"state": "ACTIVE"},
                writeback_state={},
                payload={
                    "request_id": "PRR-TEST-001",
                    "release_id": self.config.release_id,
                    "tenant_id": self.config.tenant_id,
                    "state": "ACTIVE",
                    "requester_id": "owner-a",
                    "approver_id": "reviewer-a",
                    "readiness_hash": self.release["readiness_hash"],
                    "config_fingerprint_sha256": self.config.fingerprint_sha256,
                    "window": {
                        "start_at": self.config.window_start_at,
                        "end_at": self.config.window_end_at,
                    },
                    "audit_refs": ["production_release_approval:test"],
                },
                persisted_at=build_persisted_at(),
            )
        )
        self.owner = {
            "authenticated": True,
            "principal_id": "owner-a",
            "role": "owner",
        }
        self.reviewer = {
            "authenticated": True,
            "principal_id": "reviewer-a",
            "role": "reviewer",
        }
        OrderRecordRepository(session=self.session).save(
            {
                "order_id": "ORDER-PROD-001",
                "project_id": "PROJECT-PROD-001",
                "opportunity_id": "OPP-PROD-001",
                "touch_record_id": "TOUCH-PROD-001",
                "response_status": "CONNECTED",
                "saleability_status": "QUALIFIED",
                "crm_owner_state": "ASSIGNED",
                "commercial_status": "CONFIRMED",
                "order_status": "CONFIRMED",
                "approval_state": "APPROVED",
                "archival_status": "NOT_ARCHIVED",
                "amount_band": "LOW",
                "plan_status": "APPROVED",
                "touch_record_state": "RESPONDED",
                "governed_execution_mode": "PROD_LIVE_MODE",
                "permission_decision_state": "ALLOW",
                "governance_decision_state": "PASS",
                "semantic_decision_state": "PASS",
                "governed_metadata": {
                    "release_id": self.config.release_id,
                    "customer_visible_order": True,
                    "approved_amount_minor": 88_000,
                    "approved_currency": "cny",
                },
                "created_at": "2026-07-28T00:00:00Z",
            }
        )

    def tearDown(self) -> None:
        self.session.close()
        self.tmp.cleanup()

    def _signed_event(
        self,
        payload: dict[str, object],
        *,
        timestamp: int,
    ) -> tuple[bytes, str]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        secret = self.webhook_secret.read_bytes().strip()
        signature = hmac.new(
            secret,
            str(timestamp).encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        return body, f"t={timestamp},v1={signature}"

    def _create_and_reconcile_payment(self) -> dict[str, object]:
        created = create_production_payment(
            order_id="ORDER-PROD-001",
            amount_minor=88_000,
            currency="cny",
            idempotency_key="payment-request-0001",
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.owner,
            client=_StripeStub(),
        )
        timestamp = int(time.time())
        body, signature = self._signed_event(
            {
                "id": "evt_payment_success_001",
                "type": "checkout.session.completed",
                "livemode": True,
                "created": timestamp,
                "data": {
                    "object": {
                        "id": "cs_production_test_001",
                        "payment_intent": "pi_production_test_001",
                        "amount_total": 88_000,
                        "currency": "cny",
                        "payment_status": "paid",
                        "metadata": {
                            "order_id": "ORDER-PROD-001",
                            "payment_id": created["payment_id"],
                        },
                    }
                },
            },
            timestamp=timestamp,
        )
        callback = process_stripe_webhook(
            body=body,
            signature_header=signature,
            config=self.config,
            session=self.session,
            now_unix_seconds=timestamp,
        )
        self.assertEqual(callback["state"], "RECONCILED")
        return created

    def test_payment_callback_signature_reconciliation_and_idempotency(self) -> None:
        created = self._create_and_reconcile_payment()
        payment = PaymentRecordRepository(session=self.session).get_by_id(
            str(created["payment_id"])
        )
        self.assertIsNotNone(payment)
        self.assertEqual(payment.payload["payment_status"], "PAID")
        self.assertEqual(
            payment.payload["governed_metadata"]["reconciliation_state"],
            "MATCHED",
        )
        replayed_payment = create_production_payment(
            order_id="ORDER-PROD-001",
            amount_minor=88_000,
            currency="cny",
            idempotency_key="payment-request-0001",
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.owner,
            client=_StripeStub(),
        )
        self.assertTrue(replayed_payment["idempotent_replay"])
        self.assertEqual(replayed_payment["payment_status"], "PAID")
        self.assertIsNone(replayed_payment["checkout_url"])
        payment_after_replay = PaymentRecordRepository(session=self.session).get_by_id(
            str(created["payment_id"])
        )
        self.assertEqual(payment_after_replay.payload["payment_status"], "PAID")

        timestamp = int(time.time())
        body, signature = self._signed_event(
            {
                "id": "evt_payment_success_001",
                "type": "checkout.session.completed",
                "livemode": True,
                "created": timestamp,
                "data": {
                    "object": {
                        "id": "cs_production_test_001",
                        "payment_intent": "pi_production_test_001",
                        "amount_total": 88_000,
                        "currency": "cny",
                        "payment_status": "paid",
                        "metadata": {
                            "order_id": "ORDER-PROD-001",
                            "payment_id": created["payment_id"],
                        },
                    }
                },
            },
            timestamp=timestamp,
        )
        replay = process_stripe_webhook(
            body=body,
            signature_header=signature,
            config=self.config,
            session=self.session,
            now_unix_seconds=timestamp,
        )
        self.assertTrue(replay["idempotent_replay"])

        with self.assertRaisesRegex(PermissionError, "mismatch"):
            verify_stripe_webhook(
                body=body,
                signature_header=f"t={timestamp},v1={'0' * 64}",
                secret_file=str(self.webhook_secret),
                now_unix_seconds=timestamp,
            )

    def test_mismatched_amount_does_not_become_paid(self) -> None:
        created = create_production_payment(
            order_id="ORDER-PROD-001",
            amount_minor=88_000,
            currency="cny",
            idempotency_key="payment-request-0002",
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.owner,
            client=_StripeStub(),
        )
        timestamp = int(time.time())
        body, signature = self._signed_event(
            {
                "id": "evt_payment_mismatch_001",
                "type": "checkout.session.completed",
                "livemode": True,
                "created": timestamp,
                "data": {
                    "object": {
                        "id": "cs_production_test_001",
                        "payment_intent": "pi_production_test_002",
                        "amount_total": 87_000,
                        "currency": "cny",
                        "payment_status": "paid",
                        "metadata": {
                            "order_id": "ORDER-PROD-001",
                            "payment_id": created["payment_id"],
                        },
                    }
                },
            },
            timestamp=timestamp,
        )
        result = process_stripe_webhook(
            body=body,
            signature_header=signature,
            config=self.config,
            session=self.session,
            now_unix_seconds=timestamp,
        )
        self.assertEqual(result["state"], "MISMATCH_REVIEW_REQUIRED")
        payment = PaymentRecordRepository(session=self.session).get_by_id(
            str(created["payment_id"])
        )
        self.assertEqual(payment.payload["payment_status"], "PAYMENT_EXCEPTION")

    def test_payment_input_must_match_approved_order_and_live_webhook(self) -> None:
        with self.assertRaisesRegex(ValueError, "approved order"):
            create_production_payment(
                order_id="ORDER-PROD-001",
                amount_minor=87_999,
                currency="cny",
                idempotency_key="payment-request-wrong-amount",
                config=self.config,
                release_readiness=self.release,
                session=self.session,
                actor=self.owner,
                client=_StripeStub(),
            )

        created = create_production_payment(
            order_id="ORDER-PROD-001",
            amount_minor=88_000,
            currency="cny",
            idempotency_key="payment-request-test-mode",
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.owner,
            client=_StripeStub(),
        )
        timestamp = int(time.time())
        body, signature = self._signed_event(
            {
                "id": "evt_test_mode_rejected_001",
                "type": "checkout.session.completed",
                "livemode": False,
                "created": timestamp,
                "data": {
                    "object": {
                        "id": "cs_production_test_001",
                        "payment_intent": "pi_test_mode_001",
                        "amount_total": 88_000,
                        "currency": "cny",
                        "payment_status": "paid",
                        "metadata": {
                            "order_id": "ORDER-PROD-001",
                            "payment_id": created["payment_id"],
                        },
                    }
                },
            },
            timestamp=timestamp,
        )
        with self.assertRaisesRegex(PermissionError, "livemode=true"):
            process_stripe_webhook(
                body=body,
                signature_header=signature,
                config=self.config,
                session=self.session,
                now_unix_seconds=timestamp,
            )
        payment = PaymentRecordRepository(session=self.session).get_by_id(
            str(created["payment_id"])
        )
        self.assertEqual(payment.payload["payment_status"], "PENDING_PAYMENT")

    def test_suspension_invalidates_stale_execution_snapshot(self) -> None:
        suspend_production_release(
            request_id="PRR-TEST-001",
            session=self.session,
            actor={
                "authenticated": True,
                "principal_id": "reviewer-a",
                "role": "reviewer",
            },
            reason="支付服务出现异常，立即暂停所有新的生产外部动作。",
        )
        with self.assertRaisesRegex(PermissionError, "changed or was suspended"):
            create_production_payment(
                order_id="ORDER-PROD-001",
                amount_minor=88_000,
                currency="cny",
                idempotency_key="payment-after-suspension",
                config=self.config,
                release_readiness=self.release,
                session=self.session,
                actor=self.owner,
                client=_StripeStub(),
            )

    def test_customer_signed_access_download_audit_limit_and_revocation(self) -> None:
        created = self._create_and_reconcile_payment()
        artifact = self.objects.put_object(
            b"approved customer evidence package",
            content_type="application/zip",
        )
        issued = issue_customer_artifact_grant(
            payment_id=str(created["payment_id"]),
            source_opportunity_id="OPP-PROD-001",
            artifact_object_key=artifact.object_key,
            artifact_sha256=artifact.sha256,
            customer_subject="customer@example.test",
            expires_in_seconds=3600,
            max_downloads=2,
            release_readiness=self.release,
            config=self.config,
            session=self.session,
            object_repository=self.objects,
            actor=self.owner,
        )
        self.assertNotIn("customer@example.test", json.dumps(issued))
        self.assertRegex(str(issued["access_code"]), r"^\d{8}$")
        with self.assertRaisesRegex(PermissionError, "code"):
            authorize_customer_session(
                token=str(issued["token"]),
                access_code="00000000",
                config=self.config,
                session=self.session,
            )
        authorized = authorize_customer_session(
            token=str(issued["token"]),
            access_code=str(issued["access_code"]),
            config=self.config,
            session=self.session,
        )
        self.assertTrue(authorized["second_factor_verified"])
        first = read_customer_artifact(
            grant_id=str(issued["grant_id"]),
            token=str(issued["token"]),
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            object_repository=self.objects,
        )
        self.assertEqual(first["bytes"], b"approved customer evidence package")
        self.assertEqual(first["download_count"], 1)
        second = read_customer_artifact(
            grant_id=str(issued["grant_id"]),
            token=str(issued["token"]),
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            object_repository=self.objects,
        )
        self.assertEqual(second["downloads_remaining"], 0)
        with self.assertRaisesRegex(PermissionError, "limit"):
            read_customer_artifact(
                grant_id=str(issued["grant_id"]),
                token=str(issued["token"]),
                config=self.config,
                release_readiness=self.release,
                session=self.session,
                object_repository=self.objects,
            )
        with self.assertRaisesRegex(ValueError, "revoked before refund"):
            request_production_refund(
                payment_id=str(created["payment_id"]),
                amount_minor=8_000,
                reason="客户申请退款前必须先撤销仍然活动的下载授权。",
                config=self.config,
                release_readiness=self.release,
                session=self.session,
                actor=self.owner,
            )
        revoked = revoke_customer_artifact_grant(
            grant_id=str(issued["grant_id"]),
            session=self.session,
            actor=self.owner,
            reason="客户交付链接发生泄露风险，立即撤销并重新签发。",
        )
        self.assertEqual(revoked["status"], "REVOKED")

    def test_delivery_rejects_wrong_opportunity_and_locks_after_five_bad_codes(self) -> None:
        created = self._create_and_reconcile_payment()
        artifact = self.objects.put_object(
            b"approved customer evidence package",
            content_type="application/zip",
        )
        with self.assertRaisesRegex(ValueError, "opportunity"):
            issue_customer_artifact_grant(
                payment_id=str(created["payment_id"]),
                source_opportunity_id="OPP-OTHER-001",
                artifact_object_key=artifact.object_key,
                artifact_sha256=artifact.sha256,
                customer_subject="customer@example.test",
                expires_in_seconds=3600,
                max_downloads=2,
                release_readiness=self.release,
                config=self.config,
                session=self.session,
                object_repository=self.objects,
                actor=self.owner,
            )
        issued = issue_customer_artifact_grant(
            payment_id=str(created["payment_id"]),
            source_opportunity_id="OPP-PROD-001",
            artifact_object_key=artifact.object_key,
            artifact_sha256=artifact.sha256,
            customer_subject="customer@example.test",
            expires_in_seconds=3600,
            max_downloads=2,
            release_readiness=self.release,
            config=self.config,
            session=self.session,
            object_repository=self.objects,
            actor=self.owner,
        )
        for _ in range(5):
            with self.assertRaisesRegex(PermissionError, "code"):
                authorize_customer_session(
                    token=str(issued["token"]),
                    access_code="00000000",
                    config=self.config,
                    session=self.session,
                )
        with self.assertRaisesRegex(PermissionError, "locked"):
            authorize_customer_session(
                token=str(issued["token"]),
                access_code=str(issued["access_code"]),
                config=self.config,
                session=self.session,
            )

    def test_refund_requires_distinct_approval_and_remains_manual(self) -> None:
        created = self._create_and_reconcile_payment()
        requested = request_production_refund(
            payment_id=str(created["payment_id"]),
            amount_minor=8_000,
            reason="客户确认购买范围调整，按合同人工退回差额并保留审计。",
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.owner,
        )
        with self.assertRaisesRegex(ValueError, "must differ"):
            approve_and_execute_production_refund(
                refund_request_id=str(requested["refund_request_id"]),
                config=self.config,
                release_readiness=self.release,
                session=self.session,
                actor={
                    "authenticated": True,
                    "principal_id": "owner-a",
                    "role": "reviewer",
                },
                client=_StripeStub(),
            )
        approved = approve_and_execute_production_refund(
            refund_request_id=str(requested["refund_request_id"]),
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.reviewer,
            client=_StripeStub(),
        )
        self.assertEqual(approved["state"], "REFUND_SUBMITTED")
        self.assertFalse(approved["automated_refund"])
        payment = PaymentRecordRepository(session=self.session).get_by_id(
            str(created["payment_id"])
        )
        self.assertEqual(payment.payload["payment_status"], "REFUND_PENDING")
        self.assertFalse(payment.payload["governed_metadata"]["automated_refund"])

    def test_duplicate_refund_is_rejected_and_callback_reconciles(self) -> None:
        created = self._create_and_reconcile_payment()
        requested = request_production_refund(
            payment_id=str(created["payment_id"]),
            amount_minor=8_000,
            reason="客户确认购买范围调整，按合同人工退回差额并保留审计。",
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.owner,
        )
        with self.assertRaisesRegex(ValueError, "active or completed"):
            request_production_refund(
                payment_id=str(created["payment_id"]),
                amount_minor=7_000,
                reason="重复退款申请必须失败关闭并保留原申请。",
                config=self.config,
                release_readiness=self.release,
                session=self.session,
                actor=self.owner,
            )
        artifact = self.objects.put_object(
            b"refund-pending artifact",
            content_type="application/zip",
        )
        with self.assertRaisesRegex(ValueError, "active refund"):
            issue_customer_artifact_grant(
                payment_id=str(created["payment_id"]),
                source_opportunity_id="OPP-PROD-001",
                artifact_object_key=artifact.object_key,
                artifact_sha256=artifact.sha256,
                customer_subject="customer@example.test",
                expires_in_seconds=3600,
                max_downloads=2,
                release_readiness=self.release,
                config=self.config,
                session=self.session,
                object_repository=self.objects,
                actor=self.owner,
            )
        approve_and_execute_production_refund(
            refund_request_id=str(requested["refund_request_id"]),
            config=self.config,
            release_readiness=self.release,
            session=self.session,
            actor=self.reviewer,
            client=_StripeStub(),
        )
        timestamp = int(time.time())
        body, signature = self._signed_event(
            {
                "id": "evt_refund_success_001",
                "type": "refund.updated",
                "livemode": True,
                "created": timestamp,
                "data": {
                    "object": {
                        "id": "re_production_test_001",
                        "payment_intent": "pi_production_test_001",
                        "amount": 8_000,
                        "currency": "cny",
                        "status": "succeeded",
                        "metadata": {
                            "refund_request_id": requested["refund_request_id"],
                            "payment_id": created["payment_id"],
                        },
                    }
                },
            },
            timestamp=timestamp,
        )
        callback = process_stripe_webhook(
            body=body,
            signature_header=signature,
            config=self.config,
            session=self.session,
            now_unix_seconds=timestamp,
        )
        self.assertEqual(callback["state"], "REFUND_RECONCILED")
        payment = PaymentRecordRepository(session=self.session).get_by_id(
            str(created["payment_id"])
        )
        self.assertEqual(payment.payload["payment_status"], "PAID")
        self.assertEqual(payment.payload["refund_state"], "PARTIALLY_REFUNDED")


if __name__ == "__main__":
    unittest.main()
