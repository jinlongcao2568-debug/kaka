from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    PROVIDER_FAMILIES,
    build_provider_adapter_config_from_env,
    build_provider_adapter_readiness_summary,
    provider_adapter_bootstrap_payload,
)
from shared.settings import Settings
from storage.db import DatabaseSession
from storage.repositories.provider_adapter_config_repo import ProviderAdapterConfigRepository


class TestProviderAdapterConfig(unittest.TestCase):
    def test_default_provider_config_is_sandbox_dry_run_readback_only(self) -> None:
        config = build_provider_adapter_config_from_env({})
        summary = build_provider_adapter_readiness_summary(config)

        self.assertEqual(summary["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertTrue(summary["sandbox_enabled"])
        self.assertTrue(summary["dry_run_enabled"])
        self.assertTrue(summary["readback_only"])
        self.assertFalse(summary["provider_call_enabled"])
        self.assertFalse(summary["real_provider_call_enabled"])
        self.assertFalse(summary["live_execution_enabled"])
        self.assertEqual(summary["capability_state"], "APPROVAL_READY")
        self.assertEqual(summary["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(summary["provider_circuit_breaker_state"], "CLOSED")
        self.assertFalse(summary["provider_adapter_suspended"])
        self.assertTrue(summary["provider_status_replayable"])
        self.assertTrue(summary["provider_reliability_summary"]["health_check_visible"])
        self.assertTrue(summary["provider_reliability_summary"]["rate_limit_visible"])
        self.assertTrue(summary["provider_reliability_summary"]["timeout_visible"])
        self.assertTrue(summary["provider_reliability_summary"]["retry_visible"])
        self.assertTrue(summary["provider_reliability_summary"]["failure_taxonomy_visible"])
        self.assertTrue(summary["provider_reliability_summary"]["circuit_breaker_visible"])
        self.assertTrue(summary["provider_reliability_summary"]["replayable_provider_status"])
        self.assertFalse(summary["provider_reliability_summary"]["live_fallback_allowed"])
        self.assertEqual(set(summary["families"]), set(PROVIDER_FAMILIES))
        for family in PROVIDER_FAMILIES:
            family_summary = summary["families"][family]
            provider_reliability = family_summary["provider_reliability"]
            self.assertEqual(family_summary["family"], family)
            self.assertTrue(family_summary["sandbox_enabled"])
            self.assertTrue(family_summary["dry_run_enabled"])
            self.assertTrue(family_summary["readback_only"])
            self.assertFalse(family_summary["provider_call_enabled"])
            self.assertFalse(family_summary["real_provider_call_enabled"])
            self.assertFalse(family_summary["live_execution_enabled"])
            self.assertEqual(family_summary["provider_reliability_state"], "APPROVAL_READY")
            self.assertFalse(family_summary["provider_adapter_suspended"])
            self.assertEqual(provider_reliability["health_check"]["status"], "HEALTHY")
            self.assertEqual(provider_reliability["rate_limit"]["state"], "OK")
            self.assertEqual(provider_reliability["timeout"]["state"], "OK")
            self.assertEqual(provider_reliability["failure_taxonomy"]["failure_class"], "NONE")
            self.assertEqual(provider_reliability["circuit_breaker"]["state"], "CLOSED")
            self.assertTrue(provider_reliability["provider_status_readback"]["replayable"])
            self.assertFalse(provider_reliability["fallback_policy"]["live_fallback_allowed"])

        self.assertFalse(summary["automated_refund_program"]["present"])
        self.assertFalse(summary["automated_refund_program"]["enabled"])
        self.assertEqual(summary["automated_refund_program"]["state"], "ABSENT_BLOCKED")

    def test_credentials_are_presence_metadata_only(self) -> None:
        secret = "super-secret-provider-token"
        config = build_provider_adapter_config_from_env(
            {
                "KAKA_SALES_OUTREACH_API_KEY": secret,
                "KAKA_CRM_QUOTE_TOKEN": "crm-secret",
            }
        )
        summary = build_provider_adapter_readiness_summary(config)
        encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)

        self.assertNotIn(secret, encoded)
        self.assertNotIn("crm-secret", encoded)
        sales_metadata = summary["sales_outreach"]["credential_metadata"]
        self.assertTrue(sales_metadata["credential_present"])
        self.assertEqual(sales_metadata["present_env_vars"], ["KAKA_SALES_OUTREACH_API_KEY"])
        self.assertEqual(sales_metadata["redaction"], "present-redacted")
        self.assertFalse(sales_metadata["plaintext_persisted"])
        self.assertFalse(sales_metadata["plaintext_output_enabled"])
        sales_audit = summary["credential_redaction_audit"]["families"]["sales_outreach"]
        self.assertTrue(sales_audit["credential_presence_checked"])
        self.assertTrue(sales_audit["credential_present"])
        self.assertEqual(sales_audit["present_env_vars"], ["KAKA_SALES_OUTREACH_API_KEY"])
        self.assertFalse(sales_audit["plaintext_persisted"])
        self.assertFalse(sales_audit["plaintext_output_enabled"])

    def test_reliability_signals_suspend_fail_closed_without_live_fallback(self) -> None:
        config = build_provider_adapter_config_from_env(
            {
                "KAKA_SALES_OUTREACH_PROVIDER_HEALTH": "unhealthy",
                "KAKA_CRM_QUOTE_PROVIDER_RATE_LIMITED": "true",
                "KAKA_LEADPACK_DELIVERY_PROVIDER_TIMEOUT": "true",
                "KAKA_PAYMENT_COLLECTION_PROVIDER_CIRCUIT_OPEN": "true",
            }
        )
        summary = build_provider_adapter_readiness_summary(config)

        self.assertEqual(summary["provider_reliability_state"], "SUSPENDED")
        self.assertEqual(summary["provider_circuit_breaker_state"], "OPEN")
        self.assertTrue(summary["provider_adapter_suspended"])
        self.assertEqual(set(summary["provider_adapter_suspended_families"]), set(PROVIDER_FAMILIES))
        self.assertFalse(summary["provider_reliability_summary"]["live_fallback_allowed"])
        self.assertTrue(summary["provider_reliability_summary"]["no_silent_live_fallback"])
        self.assertIn("provider_reliability_suspended_fail_closed", summary["blocked_reasons"])

        family_reason = {
            "sales_outreach": "provider_health_unhealthy_fail_closed",
            "crm_quote": "provider_rate_limited_fail_closed",
            "leadpack_page_delivery": "provider_timeout_fail_closed",
            "payment_collection": "provider_circuit_open_fail_closed",
        }
        for family, reason in family_reason.items():
            family_summary = summary["families"][family]
            reliability = family_summary["provider_reliability"]
            self.assertEqual(family_summary["readiness_state"], "SUSPENDED")
            self.assertEqual(family_summary["provider_reliability_state"], "SUSPENDED")
            self.assertTrue(family_summary["provider_adapter_suspended"])
            self.assertIn(reason, family_summary["blocked_reasons"])
            self.assertTrue(reliability["failure_taxonomy"]["fail_closed"])
            self.assertFalse(reliability["circuit_breaker"]["live_fallback_allowed"])
            self.assertFalse(reliability["fallback_policy"]["live_fallback_allowed"])
            self.assertFalse(family_summary["real_provider_call_enabled"])

    def test_unsupported_provider_fast_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported provider adapter"):
            build_provider_adapter_config_from_env({"KAKA_PAYMENT_COLLECTION_PROVIDER": "stripe_live"})

    def test_live_provider_mode_request_stays_blocked_readback_only(self) -> None:
        config = build_provider_adapter_config_from_env(
            {
                "KAKA_PROVIDER_ADAPTER_MODE": "LIVE",
                "KAKA_PROVIDER_ADAPTER_LIVE": "true",
            }
        )
        summary = build_provider_adapter_readiness_summary(config)

        self.assertTrue(summary["requested_live_mode"])
        self.assertTrue(summary["live_request_blocked"])
        self.assertFalse(summary["live_execution_enabled"])
        self.assertFalse(summary["provider_call_enabled"])
        self.assertFalse(summary["real_provider_call_enabled"])
        self.assertIn("live_provider_mode_requested_but_blocked", summary["blocked_reasons"])
        for family in PROVIDER_FAMILIES:
            self.assertIn(
                "live_provider_mode_requested_but_blocked",
                summary["families"][family]["blocked_reasons"],
            )

    def test_settings_exposes_single_bootstrap_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = {
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_SCOPE": "process",
                "KAKA_CRM_QUOTE_PROVIDER": "hubspot_sandbox",
                "LOCALAPPDATA": tmp_dir,
            }
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_env(repo_root=str(ROOT), environment="INTERNAL_ONLY")

        bootstrap = settings.provider_adapter_bootstrap_payload()
        summary = bootstrap[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]
        self.assertEqual(bootstrap["provider_adapter_config_source"], "Settings.provider_adapter_config")
        self.assertEqual(bootstrap["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertEqual(summary["crm_quote"]["provider_id"], "hubspot_sandbox")
        self.assertFalse(bootstrap["provider_adapter_live_execution_enabled"])
        self.assertFalse(bootstrap["provider_adapter_real_provider_call_enabled"])
        self.assertEqual(bootstrap["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(bootstrap["provider_circuit_breaker_state"], "CLOSED")
        self.assertTrue(bootstrap["provider_status_replayable"])
        self.assertEqual(settings.storage_bootstrap_payload()["provider_adapter_bootstrap"], bootstrap)

    def test_repository_persists_sanitized_provider_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "provider-config.json"
            config = build_provider_adapter_config_from_env(
                {"KAKA_PAYMENT_COLLECTION_SECRET": "plain-secret"}
            )
            settings = Settings(
                storage_path_optional=str(storage_path),
                storage_scope="process",
                storage_runtime_mode="explicit-path",
                provider_adapter_config=config,
            )
            session = DatabaseSession(settings=settings)
            try:
                summary = settings.provider_adapter_readiness_summary()
                record = ProviderAdapterConfigRepository(session=session).save(
                    provider_adapter_bootstrap_payload(summary)
                )
                readback = ProviderAdapterConfigRepository(session=session).get_active_payload()
            finally:
                session.close()

        self.assertEqual(record.object_type, "provider_adapter_config_readback")
        self.assertIsNotNone(readback)
        self.assertEqual(readback["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertEqual(record.governed_state["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(record.governed_state["provider_circuit_breaker_state"], "CLOSED")
        self.assertTrue(record.governed_state["provider_status_replayable"])
        encoded = json.dumps(readback, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("plain-secret", encoded)
        self.assertFalse(readback["automated_refund_program"]["enabled"])


if __name__ == "__main__":
    unittest.main()
