from __future__ import annotations

import copy
import hashlib
import hmac
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

from helpers import load_fixture
from shared.pipeline import run_internal_chain
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    build_provider_adapter_config_from_env,
    build_provider_adapter_readiness_summary,
    provider_adapter_bootstrap_payload,
)
from shared.settings import Settings
from storage.db import DatabaseSession
from storage.repositories.provider_adapter_config_repo import ProviderAdapterConfigRepository


def _provider_env() -> dict[str, str]:
    return {
        "KAKA_SALES_OUTREACH_PROVIDER": "wecom_robot",
        "KAKA_WECOM_ROBOT_WEBHOOK_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret-key",
        "KAKA_WECOM_ROBOT_SECRET": "wecom-secret",
        "KAKA_WECOM_ROBOT_CALLBACK_SECRET": "wecom-callback-secret",
        "KAKA_CRM_QUOTE_PROVIDER": "hubspot_crm",
        "KAKA_HUBSPOT_PRIVATE_APP_TOKEN": "hubspot-secret",
        "KAKA_HUBSPOT_WEBHOOK_SECRET": "hubspot-callback-secret",
        "KAKA_LEADPACK_DELIVERY_PROVIDER": "customer_portal_delivery",
        "KAKA_CUSTOMER_PORTAL_SIGNING_KEY": "delivery-secret",
        "KAKA_DELIVERY_BASE_URL": "https://portal.example.local",
        "KAKA_DELIVERY_WEBHOOK_SECRET": "delivery-callback-secret",
        "KAKA_PAYMENT_COLLECTION_PROVIDER": "stripe_payment",
        "KAKA_STRIPE_SECRET_KEY": "stripe-secret",
        "KAKA_STRIPE_WEBHOOK_SECRET": "stripe-callback-secret",
        "KAKA_PROVIDER_BINDING_SANDBOX_PASS_STATE": "PASSED",
        "KAKA_PROVIDER_BINDING_CALLBACK_VALIDATION_STATE": "VALIDATED",
        "KAKA_PROVIDER_BINDING_APPROVAL_STATE": "APPROVED",
        "KAKA_PROVIDER_BINDING_AUDIT_STATE": "AUDITED",
        "KAKA_PROVIDER_BINDING_OPERATOR_ACTION_REF": "AUD-PROVIDER-OPERATOR-001",
        "KAKA_PROVIDER_BINDING_CREDENTIAL_VERSION_REF": "CRED-V1",
        "KAKA_PROVIDER_BINDING_CREDENTIAL_ROTATED_AT": "2026-04-27T00:00:00Z",
        "KAKA_PROVIDER_BINDING_CREDENTIAL_ROTATION_DUE_AT": "2026-07-27T00:00:00Z",
    }


def _attach_live_evidence(env: dict[str, str], root: Path) -> dict[str, str]:
    key_file = root / "provider-evidence-signing-key"
    key = b"provider-evidence-signing-key-32-bytes-value"
    key_file.write_bytes(key)
    env["KAKA_PROVIDER_LIVE_EVIDENCE_SIGNING_KEY_FILE"] = str(key_file)
    for family, provider_id, env_name in (
        (
            "sales_outreach",
            "wecom_robot",
            "KAKA_SALES_OUTREACH_PROVIDER_LIVE_EVIDENCE_FILE",
        ),
        (
            "crm_quote",
            "hubspot_crm",
            "KAKA_CRM_QUOTE_PROVIDER_LIVE_EVIDENCE_FILE",
        ),
        (
            "leadpack_page_delivery",
            "customer_portal_delivery",
            "KAKA_LEADPACK_DELIVERY_PROVIDER_LIVE_EVIDENCE_FILE",
        ),
        (
            "payment_collection",
            "stripe_payment",
            "KAKA_PAYMENT_COLLECTION_PROVIDER_LIVE_EVIDENCE_FILE",
        ),
    ):
        payload = {
            "evidence_version": 1,
            "family": family,
            "provider_id": provider_id,
            "sandbox_pass_state": "PASSED",
            "callback_validation_state": "VALIDATED",
            "sandbox_execution_ref": f"sandbox:{family}:001",
            "callback_event_ref": f"callback:{family}:001",
            "approval_ref": f"approval:{family}:001",
            "audit_ref": f"audit:{family}:001",
            "operator_action_ref": f"operator:{family}:001",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload["signature_sha256"] = hmac.new(
            key,
            canonical,
            hashlib.sha256,
        ).hexdigest()
        path = root / f"{family}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        env[env_name] = str(path)
    return env


class TestRealProviderBinding(unittest.TestCase):
    def test_provider_binding_matrix_covers_product_provider_targets(self) -> None:
        summary = build_provider_adapter_readiness_summary(
            build_provider_adapter_config_from_env(_provider_env())
        )
        binding_summary = summary["provider_binding_summary"]

        self.assertTrue(binding_summary["all_required_product_provider_bindings_registered"])
        self.assertTrue(binding_summary["sandbox_provider_call_evidence_replayable"])
        self.assertTrue(binding_summary["webhook_callback_validation_replayable"])
        self.assertFalse(binding_summary["provider_call_enabled"])
        self.assertFalse(binding_summary["real_provider_call_enabled"])
        self.assertFalse(binding_summary["automated_refund_enabled"])
        for key in (
            "wecom_robot_provider_binding",
            "email_provider_binding",
            "sms_provider_binding",
            "phone_provider_binding",
            "crm_provider_binding",
            "quote_provider_binding",
            "payment_provider_binding",
            "delivery_provider_binding",
        ):
            with self.subTest(key=key):
                self.assertTrue(binding_summary["coverage"][key])

        selected = {
            entry["provider_id"]: entry
            for entry in binding_summary["selected_provider_bindings"]
        }
        self.assertEqual(
            set(selected),
            {"wecom_robot", "hubspot_crm", "customer_portal_delivery", "stripe_payment"},
        )
        for provider_id, entry in selected.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(entry["binding_state"], "SANDBOX_VERIFIED")
                self.assertTrue(entry["sandbox_call_evidence"]["sandbox_call_verified"])
                self.assertTrue(entry["webhook_callback_validation"]["validation_replayable"])
                self.assertFalse(entry["sandbox_call_evidence"]["provider_network_call_executed"])
                self.assertFalse(entry["live_binding_gate"]["real_provider_call_enabled"])
                self.assertTrue(entry["live_binding_gate"]["no_silent_fallback"])

    def test_credentials_are_redacted_and_rotation_metadata_is_readback_only(self) -> None:
        env = _provider_env()
        summary = build_provider_adapter_readiness_summary(build_provider_adapter_config_from_env(env))
        encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)

        for secret in (
            "wecom-secret",
            "hubspot-secret",
            "delivery-secret",
            "stripe-secret",
            "stripe-callback-secret",
        ):
            self.assertNotIn(secret, encoded)
        selected = summary["provider_binding_summary"]["selected_provider_bindings"]
        for entry in selected:
            self.assertEqual(entry["credential_metadata"]["redaction"], "present-redacted")
            self.assertFalse(entry["credential_metadata"]["plaintext_persisted"])
            self.assertFalse(entry["credential_metadata"]["plaintext_output_enabled"])
            self.assertTrue(entry["credential_rotation"]["credential_version_ref_present"])
            self.assertEqual(entry["credential_rotation"]["credential_rotated_at_optional"], "2026-04-27T00:00:00Z")

    def test_kill_switch_suspends_selected_binding_fail_closed(self) -> None:
        env = {
            **_provider_env(),
            "KAKA_PROVIDER_BINDING_KILL_SWITCH": "true",
        }
        summary = build_provider_adapter_readiness_summary(build_provider_adapter_config_from_env(env))
        selected = summary["provider_binding_summary"]["selected_provider_bindings"]

        for entry in selected:
            self.assertEqual(entry["binding_state"], "SUSPENDED")
            self.assertTrue(entry["kill_switch"]["kill_switch_enabled"])
            self.assertIn("provider_kill_switch_enabled", entry["live_binding_gate"]["blocked_reasons"])
            self.assertFalse(entry["live_binding_gate"]["real_provider_call_enabled"])

    def test_explicit_live_mode_enables_only_fully_gated_selected_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = _attach_live_evidence(
                {
                    **_provider_env(),
                    "KAKA_PROVIDER_ADAPTER_MODE": "LIVE",
                },
                Path(tmp_dir),
            )
            summary = build_provider_adapter_readiness_summary(
                build_provider_adapter_config_from_env(env)
            )

        self.assertTrue(summary["requested_live_mode"])
        self.assertTrue(summary["provider_call_enabled"])
        self.assertTrue(summary["real_provider_call_enabled"])
        self.assertTrue(summary["live_execution_enabled"])
        self.assertFalse(summary["live_request_blocked"])
        self.assertFalse(summary["readback_only"])
        self.assertTrue(
            summary["provider_binding_summary"]["all_required_product_provider_bindings_registered"]
        )
        for entry in summary["provider_binding_summary"]["selected_provider_bindings"]:
            with self.subTest(provider=entry["provider_id"]):
                self.assertEqual(
                    entry["live_binding_gate"]["live_binding_readiness_state"],
                    "LIVE_READY",
                )
                self.assertTrue(entry["live_binding_gate"]["real_provider_call_enabled"])
                self.assertEqual(entry["live_binding_gate"]["blocked_reasons"], [])

        bootstrap = provider_adapter_bootstrap_payload(summary)
        self.assertTrue(bootstrap["provider_adapter_live_execution_enabled"])
        self.assertTrue(bootstrap["provider_adapter_real_provider_call_enabled"])
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_path_optional=str(Path(tmp_dir) / "provider-live.json"),
                storage_scope="process",
                storage_runtime_mode="explicit-path",
            )
            session = DatabaseSession(settings=settings)
            try:
                record = ProviderAdapterConfigRepository(session=session).save(
                    bootstrap
                )
            finally:
                session.close()
        self.assertTrue(record.governed_state["live_execution_enabled"])
        self.assertTrue(record.governed_state["provider_call_enabled"])
        self.assertTrue(record.governed_state["real_provider_call_enabled"])
        self.assertFalse(record.governed_state["automated_refund_enabled"])

    def test_live_mode_fails_closed_when_callback_validation_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = _attach_live_evidence(
                {
                    **_provider_env(),
                    "KAKA_PROVIDER_ADAPTER_MODE": "LIVE",
                    "KAKA_PAYMENT_COLLECTION_PROVIDER_CALLBACK_VALIDATION_STATE": "NOT_VALIDATED",
                },
                Path(tmp_dir),
            )
            summary = build_provider_adapter_readiness_summary(
                build_provider_adapter_config_from_env(env)
            )
        payment = summary["families"]["payment_collection"]

        self.assertFalse(summary["real_provider_call_enabled"])
        self.assertTrue(summary["live_request_blocked"])
        self.assertFalse(payment["real_provider_call_enabled"])
        self.assertIn(
            "callback_validation_state=NOT_VALIDATED",
            payment["selected_provider_bindings"][0]["live_binding_gate"]["blocked_reasons"],
        )

    def test_repository_persists_sanitized_binding_readback(self) -> None:
        env = _provider_env()
        summary = build_provider_adapter_readiness_summary(build_provider_adapter_config_from_env(env))
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                storage_path_optional=str(Path(tmp_dir) / "provider-binding.json"),
                storage_scope="process",
                storage_runtime_mode="explicit-path",
                provider_adapter_config=build_provider_adapter_config_from_env(env),
            )
            session = DatabaseSession(settings=settings)
            try:
                record = ProviderAdapterConfigRepository(session=session).save(
                    provider_adapter_bootstrap_payload(summary)
                )
                readback = ProviderAdapterConfigRepository(session=session).get_active_payload()
            finally:
                session.close()

        self.assertEqual(record.governed_state["provider_binding_mode"], "REAL_PROVIDER_BINDING_READBACK_GATED")
        self.assertIsNotNone(readback)
        self.assertTrue(readback["provider_binding_summary"]["all_required_product_provider_bindings_registered"])
        encoded = json.dumps(readback, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("stripe-secret", encoded)
        self.assertFalse(readback["automated_refund_program"]["enabled"])

    def test_stage7_stage8_stage9_consume_same_provider_binding_summary(self) -> None:
        env = _provider_env()
        settings = Settings(provider_adapter_config=build_provider_adapter_config_from_env(env))
        payload = copy.deepcopy(load_fixture("internal_chain_happy.json"))
        payload.update(
            {
                "approved_crm_quote_execution_requested": True,
                "approved_crm_sync_requested": True,
                "approved_quote_send_requested": True,
                "approved_provider_execution_requested": True,
                "payment_delivery_live_pilot_requested": True,
                "approved_payment_delivery_execution_requested": True,
                "approved_sample_size": 1,
                "requested_sample_size": 1,
                "approval_state": "APPROVED",
                "crm_approval_state": "APPROVED",
                "quote_approval_state": "APPROVED",
                "quote_audit_state": "PRESENT",
                "template_approval_state": "APPROVED",
                "operator_approval_state": "APPROVED",
                "operator_action_audit_refs": [
                    "AUD-PROVIDER-OPERATOR-001",
                ],
                "project_fact_audit_ref": "AUD-PROJECT-FACT-001",
                "candidate_projection_audit_ref": "AUD-CANDIDATE-001",
                "approval_chain_audit_ref": "AUD-APPROVAL-001",
                "quote_version_state": "APPROVED",
                "quote_expires_at_optional": "2026-05-31T00:00:00Z",
                "payment_status": "PAID",
                "payment_proof_state": "PROVIDED",
                "paid_at_optional": "2026-04-24T10:00:00Z",
                "delivery_status": "READY",
                "payment_approval_state": "APPROVED",
                "delivery_approval_state": "APPROVED",
                "finance_review_state": "APPROVED",
                "download_auth_state": "AUTHORIZED",
            }
        )

        result = run_internal_chain(payload, settings=settings)
        stage7 = result["stage7"]
        stage8 = result["stage8"]
        stage9 = result["stage9"]
        provider_summary = stage7.inputs[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]
        selected_provider_ids = {
            entry["provider_id"]
            for entry in provider_summary["provider_binding_summary"]["selected_provider_bindings"]
        }

        self.assertEqual(
            selected_provider_ids,
            {"wecom_robot", "hubspot_crm", "customer_portal_delivery", "stripe_payment"},
        )
        stage7_result = stage7.inputs["crm_quote_workbench"]["provider_result_readback"]
        stage8_result = stage8.inputs["outreach_execution_outbox_snapshot"]["provider_result_readback"]
        stage9_payment_result = stage9.inputs["payment_delivery_live_pilot"][
            "payment_provider_result_readback"
        ]
        stage9_delivery_result = stage9.inputs["payment_delivery_live_pilot"][
            "delivery_provider_result_readback"
        ]

        self.assertEqual(
            stage7_result["selected_provider_bindings"][0]["provider_id"],
            "hubspot_crm",
        )
        self.assertEqual(
            stage8_result["selected_provider_bindings"][0]["provider_id"],
            "wecom_robot",
        )
        self.assertEqual(
            stage9_payment_result["selected_provider_bindings"][0]["provider_id"],
            "stripe_payment",
        )
        self.assertEqual(
            stage9_delivery_result["selected_provider_bindings"][0]["provider_id"],
            "customer_portal_delivery",
        )
        for provider_result in (
            stage7_result,
            stage8_result,
            stage9_payment_result,
            stage9_delivery_result,
        ):
            with self.subTest(provider=provider_result["provider_id"]):
                self.assertEqual(
                    provider_result["provider_binding_mode"],
                    "REAL_PROVIDER_BINDING_READBACK_GATED",
                )
                self.assertFalse(provider_result["provider_call_executed"])
                self.assertFalse(provider_result["real_provider_call_enabled"])

        self.assertFalse(stage9.inputs["stage9_execution_ledger"]["automated_refund_enabled"])
        self.assertFalse(
            stage9.inputs["stage9_execution_ledger"]["approved_payment_delivery_execution"][
                "automated_refund_program"
            ]["enabled"]
        )


if __name__ == "__main__":
    unittest.main()
