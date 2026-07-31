from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.deps import get_settings
from api.main import create_app
from storage import reset_default_storage
from storage.db import DatabaseSession


class TestProductionApiBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._environment = patch.dict(os.environ, {}, clear=False)
        self._environment.start()
        for name in tuple(os.environ):
            if name.startswith("KAKA_"):
                os.environ.pop(name, None)
        os.environ.update(
            {
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_PATH": str(root / "production-api.json"),
                "KAKA_OBJECT_STORAGE_PATH": str(root / "objects"),
                "KAKA_ENVIRONMENT": "INTERNAL_ONLY",
            }
        )
        get_settings.cache_clear()
        reset_default_storage()

    def tearDown(self) -> None:
        get_settings.cache_clear()
        DatabaseSession.close_default()
        self._environment.stop()
        self._tmp.cleanup()

    def test_public_customer_entry_bypasses_internal_login_but_management_does_not(self) -> None:
        app = create_app()
        with TestClient(app, base_url="https://delivery.example.test") as client:
            access = client.get("/customer/access")
            management = client.get("/production/readiness")
            invalid_session = client.post(
                "/customer/session",
                json={
                    "token": "invalid-customer-token-" + ("x" * 40),
                    "access_code": "12345678",
                },
            )
            invalid_webhook = client.post(
                "/production/webhooks/payments/stripe",
                content=b"{}",
                headers={"stripe-signature": "t=1,v1=invalid"},
            )

        self.assertEqual(access.status_code, 200)
        self.assertIn("客户交付验证", access.text)
        self.assertIn('window.location.hash.slice(1)', access.text)
        self.assertIn("form[hidden] { display: none; }", access.text)
        self.assertNotIn("?token=", access.text)
        self.assertEqual(access.headers["cache-control"], "no-store")
        self.assertEqual(access.headers["referrer-policy"], "no-referrer")
        self.assertIn("default-src 'none'", access.headers["content-security-policy"])
        self.assertEqual(management.status_code, 403)
        self.assertEqual(
            management.json()["detail"]["required_permission"],
            "internal_api_access",
        )
        self.assertEqual(invalid_session.status_code, 401)
        self.assertNotIn("INTERNAL_API_AUTH_REQUIRED", str(invalid_session.json()))
        self.assertIn(invalid_webhook.status_code, {400, 401})
        self.assertNotEqual(invalid_webhook.status_code, 503)

    def test_production_permissions_are_role_scoped_and_fail_closed(self) -> None:
        app = create_app()
        with TestClient(app, base_url="https://delivery.example.test") as client:
            operator_headers = {
                "x-kaka-test-operator-auth": "approved",
                "x-kaka-test-role": "operator",
                "x-kaka-test-principal-id": "operator-1",
            }
            reviewer_headers = {
                "x-kaka-test-operator-auth": "approved",
                "x-kaka-test-role": "reviewer",
                "x-kaka-test-principal-id": "reviewer-1",
            }
            owner_headers = {
                "x-kaka-test-operator-auth": "approved",
                "x-kaka-test-role": "owner",
                "x-kaka-test-principal-id": "owner-1",
            }
            operator_payment = client.post(
                "/production/payments",
                headers=operator_headers,
                json={
                    "order_id": "ORDER-PROD-001",
                        "amount_minor": 1000,
                        "currency": "cny",
                        "idempotency_key": "operator-payment-0001",
                },
            )
            reviewer_payment = client.post(
                "/production/payments",
                headers=reviewer_headers,
                json={
                    "order_id": "ORDER-PROD-001",
                        "amount_minor": 1000,
                        "currency": "cny",
                        "idempotency_key": "reviewer-payment-0001",
                },
            )
            owner_payment = client.post(
                "/production/payments",
                headers=owner_headers,
                json={
                    "order_id": "ORDER-PROD-001",
                        "amount_minor": 1000,
                        "currency": "cny",
                        "idempotency_key": "owner-payment-000001",
                },
            )
            owner_refund_approval = client.post(
                "/production/refunds/requests/REFUND-MISSING/approve",
                headers=owner_headers,
            )
            reviewer_refund_approval = client.post(
                "/production/refunds/requests/REFUND-MISSING/approve",
                headers=reviewer_headers,
            )
            owner_operations = client.get(
                "/production/operations",
                headers=owner_headers,
            )

        for response in (operator_payment, reviewer_payment):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json()["detail"]["required_permission"],
                "production_payment_execute",
            )
        self.assertEqual(owner_payment.status_code, 409)
        self.assertEqual(owner_refund_approval.status_code, 403)
        self.assertEqual(
            owner_refund_approval.json()["detail"]["required_permission"],
            "production_refund_approve",
        )
        self.assertEqual(reviewer_refund_approval.status_code, 409)
        self.assertEqual(owner_operations.status_code, 200)
        self.assertEqual(owner_operations.json()["summary"]["payment_count"], 0)
        self.assertFalse(
            owner_operations.json()["raw_provider_payload_persisted"]
        )
        self.assertTrue(app.state.internal_write_permission_policy["all_unsafe_routes_classified"])
        self.assertIn(
            "receive_stripe_payment_webhook",
            app.state.internal_write_permission_policy["exempt_routes"],
        )
        self.assertTrue(
            app.state.production_release_bootstrap[
                "fail_closed_until_active_approval"
            ]
        )
        self.assertFalse(
            app.state.production_release_bootstrap["automated_refund_enabled"]
        )
        self.assertEqual(
            app.state.transport_bootstrap["production_release"]["readiness_path"],
            "/production/readiness",
        )


if __name__ == "__main__":
    unittest.main()
