from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime.production_alert_probe import run_production_alert_probe
from runtime.production_payment_provider_probe import (
    run_production_payment_provider_probe,
)
from runtime.production_release_orchestrator import production_alert_dispatch_readiness
from runtime.production_release_orchestrator import (
    ProductionReleaseConfig,
    production_payment_provider_probe_readiness,
)
from runtime.provider_live_evidence import create_provider_live_evidence
from shared.provider_adapter_config import (
    build_provider_adapter_config_from_env,
    build_provider_adapter_readiness_summary,
)


class TestProductionReleaseTooling(unittest.TestCase):
    def test_public_caddy_routes_root_to_customer_entry_and_keeps_default_deny(self) -> None:
        routes = (
            ROOT / "deploy" / "production" / "Caddyfile.public-routes"
        ).read_text(encoding="utf-8")

        self.assertIn("path /", routes)
        self.assertIn("redir * /customer/access 302", routes)
        self.assertIn("@public_customer path /customer/*", routes)
        self.assertIn('respond "Not Found" 404', routes)
        self.assertNotIn("/operator-console", routes)
        self.assertNotIn("/internal/login", routes)

    def test_payment_provider_probe_binds_expected_live_account(self) -> None:
        class StripeAccountStub:
            def retrieve_account(self) -> dict[str, object]:
                return {
                    "id": "acct_12345678",
                    "charges_enabled": True,
                    "payouts_enabled": True,
                    "details_submitted": True,
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            key = root / "provider-signing-key"
            key.write_bytes(b"provider-evidence-signing-key-32-bytes-value")
            evidence = root / "stripe-probe.json"
            env = {
                "KAKA_STRIPE_ACCOUNT_ID": "acct_12345678",
                "KAKA_PRODUCTION_PAYMENT_PROVIDER_PROBE_FILE": str(evidence),
                "KAKA_PROVIDER_LIVE_EVIDENCE_SIGNING_KEY_FILE": str(key),
            }
            result = run_production_payment_provider_probe(
                client=StripeAccountStub(),
                environ=env,
            )
            config = ProductionReleaseConfig(
                enabled=True,
                mode="CANARY",
                release_id="release-tooling-test",
                release_version="v1",
                tenant_id="tenant-a",
                public_base_url="https://portal.example.test",
                window_start_at="2099-01-01T00:00:00Z",
                window_end_at="2099-01-02T00:00:00Z",
                canary_customer_limit=1,
                customer_visible_enabled=True,
                payment_enabled=True,
                delivery_enabled=True,
                refund_enabled=True,
                automated_refund_enabled=False,
                kill_switch_enabled=False,
                customer_portal_signing_key_file=None,
                payment_secret_key_file=None,
                payment_webhook_secret_file=None,
                backup_manifest_ref=None,
                restore_report_ref=None,
                rollback_ref=None,
                alert_dispatch_required=True,
                payment_provider_account_id="acct_12345678",
                payment_provider_probe_ref=str(evidence),
                provider_evidence_signing_key_file=str(key),
            )
            readiness = production_payment_provider_probe_readiness(
                config=config
            )
            self.assertEqual(result["state"], "VALIDATED")
            self.assertTrue(readiness["ready"])
            self.assertTrue(readiness["signature_verified"])

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            payload["account_id"] = "acct_87654321"
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            tampered = production_payment_provider_probe_readiness(config=config)
            self.assertFalse(tampered["ready"])
            self.assertIn(
                "stripe_account_probe_account_mismatch",
                tampered["blocked_reasons"],
            )

    def test_provider_evidence_generator_creates_verifiable_immutable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            key = root / "signing-key"
            key.write_bytes(b"provider-evidence-signing-key-32-bytes-value")
            output = root / "payment-live-evidence.json"
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=30)
            ).isoformat()
            result = create_provider_live_evidence(
                family="payment_collection",
                provider_id="stripe_payment",
                signing_key_file=key,
                output_file=output,
                expires_at=expires_at,
                sandbox_execution_ref="sandbox:payment:001",
                callback_event_ref="callback:payment:001",
                approval_ref="approval:payment:001",
                audit_ref="audit:payment:001",
                operator_action_ref="operator:payment:001",
            )
            self.assertEqual(result["state"], "SIGNED")
            env = {
                "KAKA_PROVIDER_ADAPTER_MODE": "LIVE",
                "KAKA_PAYMENT_COLLECTION_PROVIDER": "stripe_payment",
                "KAKA_STRIPE_SECRET_KEY": "stripe-live-secret",
                "KAKA_STRIPE_WEBHOOK_SECRET": "stripe-webhook-secret",
                "KAKA_PROVIDER_BINDING_SANDBOX_PASS_STATE": "PASSED",
                "KAKA_PROVIDER_BINDING_CALLBACK_VALIDATION_STATE": "VALIDATED",
                "KAKA_PROVIDER_BINDING_APPROVAL_STATE": "APPROVED",
                "KAKA_PROVIDER_BINDING_AUDIT_STATE": "AUDITED",
                "KAKA_PROVIDER_BINDING_OPERATOR_ACTION_REF": "operator:payment:001",
                "KAKA_PROVIDER_LIVE_EVIDENCE_SIGNING_KEY_FILE": str(key),
                "KAKA_PAYMENT_COLLECTION_PROVIDER_LIVE_EVIDENCE_FILE": str(output),
            }
            summary = build_provider_adapter_readiness_summary(
                build_provider_adapter_config_from_env(env)
            )
            payment = summary["families"]["payment_collection"]
            self.assertTrue(payment["real_provider_call_enabled"])
            with self.assertRaises(FileExistsError):
                create_provider_live_evidence(
                    family="payment_collection",
                    provider_id="stripe_payment",
                    signing_key_file=key,
                    output_file=output,
                    expires_at=expires_at,
                    sandbox_execution_ref="sandbox:payment:002",
                    callback_event_ref="callback:payment:002",
                    approval_ref="approval:payment:002",
                    audit_ref="audit:payment:002",
                    operator_action_ref="operator:payment:002",
                )

    def test_alert_probe_only_writes_evidence_after_delivered_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            event_path = root / "events.jsonl"
            state_path = root / "alert-state.json"
            evidence_path = root / "alert-evidence.json"
            secret_path = root / "alert-secret"
            secret_path.write_bytes(b"alert-signing-secret-32-bytes-value")
            env = {
                "KAKA_OBSERVABILITY_ENABLED": "true",
                "KAKA_OBSERVABILITY_STDOUT_ENABLED": "false",
                "KAKA_OBSERVABILITY_EVENT_PATH": str(event_path),
                "KAKA_ALERT_WEBHOOK_URL": "http://127.0.0.1:18081/alerts",
                "KAKA_ALERT_ALLOWED_HOSTS": "127.0.0.1",
                "KAKA_ALERT_SIGNING_SECRET_FILE": str(secret_path),
                "KAKA_ALERT_STATE_PATH": str(state_path),
                "KAKA_PRODUCTION_ALERT_TEST_EVIDENCE_FILE": str(evidence_path),
            }
            observed_event_id: list[str] = []

            def fake_read_state(path: Path) -> dict[str, object]:
                del path
                if not observed_event_id and event_path.is_file():
                    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
                    observed_event_id.append(str(event["event_id"]))
                    return {"delivered_event_ids": []}
                return {"delivered_event_ids": list(observed_event_id)}

            with patch.dict(os.environ, env, clear=False), patch(
                "runtime.production_alert_probe.OperationalAlertConfig.from_env"
            ) as config_factory, patch(
                "runtime.production_alert_probe._read_alert_state",
                side_effect=fake_read_state,
            ):
                config_factory.return_value.state_path = state_path
                from runtime.operational_observability import reset_operational_event_sinks

                reset_operational_event_sinks()
                result = run_production_alert_probe(
                    wait_seconds=5,
                    poll_seconds=0.1,
                )
                reset_operational_event_sinks()
            self.assertTrue(evidence_path.is_file())
            self.assertEqual(result["event_id"], observed_event_id[0])
            self.assertTrue(
                json.loads(evidence_path.read_text(encoding="utf-8"))["delivered"]
            )

    def test_alert_readiness_cross_checks_probe_against_delivered_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            secret = root / "alert-secret"
            secret.write_bytes(b"alert-signing-secret-32-bytes-value")
            event_id = "OPSEVT-" + ("a" * 32)
            state = root / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "delivered_event_ids": [event_id],
                        "dead_letter_event_ids": [],
                        "attempts": {},
                    }
                ),
                encoding="utf-8",
            )
            status = root / "status.json"
            status.write_text(
                json.dumps(
                    {
                        "state": "DISPATCH_COMPLETED",
                        "completed_at_unix_seconds": time.time(),
                    }
                ),
                encoding="utf-8",
            )
            evidence = root / "evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "evidence_version": 1,
                        "event_id": event_id,
                        "delivered": True,
                    }
                ),
                encoding="utf-8",
            )
            env = {
                "KAKA_OBSERVABILITY_EVENT_PATH": str(root / "events.jsonl"),
                "KAKA_ALERT_WEBHOOK_URL": "https://alerts.example.test/kaka",
                "KAKA_ALERT_ALLOWED_HOSTS": "alerts.example.test",
                "KAKA_ALERT_SIGNING_SECRET_FILE": str(secret),
                "KAKA_ALERT_STATE_PATH": str(state),
                "KAKA_ALERT_DEAD_LETTER_PATH": str(root / "dead.jsonl"),
                "KAKA_CONTROLLED_EGRESS_PROXY_URL": "http://127.0.0.1:18080",
                "KAKA_PRIVATE_EDGE_REQUIRED": "true",
                "KAKA_ALERT_DISPATCHER_STATUS_PATH": str(status),
                "KAKA_ALERT_DISPATCHER_STATUS_MAX_AGE_SECONDS": "120",
                "KAKA_PRODUCTION_ALERT_TEST_EVIDENCE_FILE": str(evidence),
            }
            readiness = production_alert_dispatch_readiness(environ=env)
            self.assertTrue(readiness["ready"])
            self.assertTrue(readiness["production_alert_test_event_delivered"])
            self.assertEqual(
                readiness["production_alert_test_event_id"],
                event_id,
            )


if __name__ == "__main__":
    unittest.main()
