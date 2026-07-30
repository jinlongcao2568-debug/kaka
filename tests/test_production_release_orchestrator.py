from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime.production_release_orchestrator import (
    PRODUCTION_RELEASE_STATE_ACTIVE,
    PRODUCTION_RELEASE_STATE_READY_FOR_APPROVAL,
    PRODUCTION_RELEASE_STATE_SUSPENDED,
    ProductionReleaseConfig,
    approve_production_release,
    build_production_release_readiness,
    production_recovery_evidence_readiness,
    request_production_release,
    suspend_production_release,
)
from shared.provider_adapter_config import (
    build_provider_adapter_config_from_env,
    build_provider_adapter_readiness_summary,
)
from shared.settings import InternalApiPrincipal, Settings
from storage.sqlalchemy_backend import REQUIRED_STORAGE_SCHEMA_REVISION
from runtime.private_pilot_backup import compute_backup_manifest_hash


class _MemorySession:
    storage_schema_revision = REQUIRED_STORAGE_SCHEMA_REVISION

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], object] = {}

    def upsert_record(self, record: object) -> object:
        self.records[(record.object_type, record.record_id)] = record
        return record

    def get_record(self, object_type: str, record_id: str) -> object | None:
        return self.records.get((object_type, record_id))

    def list_records(self, object_type: str) -> list[object]:
        return [
            record
            for (stored_type, _), record in self.records.items()
            if stored_type == object_type
        ]


class TestProductionReleaseOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.namespace = "tenant-a-primary"
        self.principals_file = self._secret("principals.json", b"not-read-by-direct-settings")
        self.database_password_file = self._secret("postgres-password", b"database-password-32-bytes-value")
        self.portal_secret_file = self._secret("portal-signing", b"portal-signing-secret-32-bytes-value")
        self.payment_secret_file = self._secret(
            "stripe-key",
            b"sk_" + b"live_" + b"test-only-production-secret-32-bytes",
        )
        self.webhook_secret_file = self._secret(
            "stripe-webhook",
            b"wh" + b"sec_" + b"test-only-production-webhook-32-bytes",
        )
        self.delivery_webhook_file = self._secret(
            "delivery-webhook",
            b"delivery-webhook-secret-32-bytes-value",
        )
        backup_dir = self.root / "backups" / "BACKUP-PRODUCTION-001"
        backup_dir.mkdir(parents=True)
        artifacts: dict[str, dict[str, object]] = {}
        for filename, content in {
            "database.dump": b"database-backup",
            "objects.tar.gz": b"object-archive",
            "objects-inventory.jsonl": b"\n",
        }.items():
            path = backup_dir / filename
            path.write_bytes(content)
            artifacts[filename] = {
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        manifest = {
            "manifest_version": 1,
            "backup_runtime_id": "runtime.private_pilot_backup.v1",
            "backup_id": "BACKUP-PRODUCTION-001",
            "backup_state": "COMPLETE",
            "source_tenant_id": "tenant-a",
            "source_instance_id": "primary",
            "source_database_name": "tenant-a-primary",
            "source_schema_revision": REQUIRED_STORAGE_SCHEMA_REVISION,
            "artifacts": artifacts,
            "consistency": {"operator_writers_paused_acknowledged": True},
            "rpo": {"target_met_by_estimate": True},
        }
        manifest["manifest_sha256"] = compute_backup_manifest_hash(manifest)
        self.backup_manifest_file = backup_dir / "manifest.json"
        self.backup_manifest_file.write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        self.restore_report_file = self.root / "restore-report.json"
        self.restore_report_file.write_text(
            json.dumps(
                {
                    "backup_id": "BACKUP-PRODUCTION-001",
                    "restore_state": "VALIDATED_ISOLATED_RESTORE",
                    "restored_schema_revision": REQUIRED_STORAGE_SCHEMA_REVISION,
                    "isolated_target": True,
                    "active_database_mutated": False,
                    "active_object_storage_mutated": False,
                    "rto": {"target_met": True},
                }
            ),
            encoding="utf-8",
        )
        self.rollback_report_file = self.root / "rollback-report.json"
        self.rollback_report_file.write_text(
            json.dumps(
                {
                    "tenant_id": "tenant-a",
                    "instance_id": "primary",
                    "backup_id": "BACKUP-PRODUCTION-001",
                    "current_image_tag": "923df124",
                    "rollback_succeeded": True,
                    "health_gate_required": True,
                    "production_overlay_used": True,
                    "post_rollback_readiness_verified": True,
                    "current_release_restored_after_drill": True,
                }
            ),
            encoding="utf-8",
        )
        self.settings = Settings(
            repo_root=str(ROOT),
            environment="PROD_LIVE_MODE",
            deployment_tenancy_mode="PRIVATE_SINGLE_TENANT",
            deployment_tenant_id_optional="tenant-a",
            deployment_instance_id_optional="primary",
            private_edge_required=True,
            private_hostname_optional="portal.example.test",
            api_allowed_hosts=("portal.example.test",),
            api_trusted_proxy_boundary="PRIVATE_EDGE_NETWORK_ONLY",
            api_trusted_proxy_ips=("172.31.252.254",),
            storage_backend="postgresql",
            storage_database_url_optional=f"postgresql://kaka@postgres/{self.namespace}",
            storage_database_password_file_optional=str(self.database_password_file),
            storage_scope="shared",
            storage_runtime_mode="database",
            queue_backend="storage",
            worker_runtime="dedicated-core-worker",
            object_storage_backend="local-filesystem",
            object_storage_path_optional=str(self.root / self.namespace / "object-storage"),
            internal_api_principals=(
                InternalApiPrincipal("owner-a", "owner", "owner-token-0000000000000001"),
                InternalApiPrincipal("reviewer-a", "reviewer", "reviewer-token-000000000001"),
                InternalApiPrincipal("admin-a", "admin", "admin-token-0000000000000001"),
            ),
            internal_api_principals_file_optional=str(self.principals_file),
            operator_artifact_root_optional=str(
                self.root / self.namespace / "operator-artifacts"
            ),
            internal_api_cookie_secure=True,
        )
        self.config = ProductionReleaseConfig(
            enabled=True,
            mode="CANARY",
            release_id="release-20260728",
            release_version="923df124",
            tenant_id="tenant-a",
            public_base_url="https://portal.example.test",
            window_start_at="2026-07-28T00:00:00Z",
            window_end_at="2026-07-29T00:00:00Z",
            canary_customer_limit=3,
            customer_visible_enabled=True,
            payment_enabled=True,
            delivery_enabled=True,
            refund_enabled=True,
            automated_refund_enabled=False,
            kill_switch_enabled=False,
            customer_portal_signing_key_file=str(self.portal_secret_file),
            payment_secret_key_file=str(self.payment_secret_file),
            payment_webhook_secret_file=str(self.webhook_secret_file),
            backup_manifest_ref=str(self.backup_manifest_file),
            restore_report_ref=str(self.restore_report_file),
            rollback_ref=str(self.rollback_report_file),
            alert_dispatch_required=True,
        )
        provider_env = {
            "KAKA_PROVIDER_ADAPTER_MODE": "LIVE",
            "KAKA_LEADPACK_DELIVERY_PROVIDER": "customer_portal_delivery",
            "KAKA_CUSTOMER_PORTAL_SIGNING_KEY_FILE": str(self.portal_secret_file),
            "KAKA_DELIVERY_BASE_URL": "https://portal.example.test",
            "KAKA_DELIVERY_WEBHOOK_SECRET_FILE": str(self.delivery_webhook_file),
            "KAKA_PAYMENT_COLLECTION_PROVIDER": "stripe_payment",
            "KAKA_STRIPE_SECRET_KEY_FILE": str(self.payment_secret_file),
            "KAKA_STRIPE_WEBHOOK_SECRET_FILE": str(self.webhook_secret_file),
            "KAKA_PROVIDER_BINDING_SANDBOX_PASS_STATE": "PASSED",
            "KAKA_PROVIDER_BINDING_CALLBACK_VALIDATION_STATE": "VALIDATED",
            "KAKA_PROVIDER_BINDING_APPROVAL_STATE": "APPROVED",
            "KAKA_PROVIDER_BINDING_AUDIT_STATE": "AUDITED",
            "KAKA_PROVIDER_BINDING_OPERATOR_ACTION_REF": "AUD-PROVIDER-001",
        }
        provider_evidence_key = self._secret(
            "provider-evidence-signing-key",
            b"provider-evidence-signing-key-32-bytes-value",
        )
        provider_env["KAKA_PROVIDER_LIVE_EVIDENCE_SIGNING_KEY_FILE"] = str(
            provider_evidence_key
        )
        payment_probe = {
            "evidence_version": 1,
            "probe_id": "runtime.production_payment_provider_probe.v1",
            "provider_id": "stripe_payment",
            "account_id": "acct_12345678",
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
            "probed_at": "2026-07-28T11:55:00Z",
            "contains_secret_material": False,
        }
        payment_probe_canonical = json.dumps(
            payment_probe,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payment_probe["signature_sha256"] = hmac.new(
            provider_evidence_key.read_bytes(),
            payment_probe_canonical,
            hashlib.sha256,
        ).hexdigest()
        payment_probe_file = self.root / "stripe-account-probe.json"
        payment_probe_file.write_text(json.dumps(payment_probe), encoding="utf-8")
        self.config = ProductionReleaseConfig(
            **{
                **self.config.__dict__,
                "payment_provider_account_id": "acct_12345678",
                "payment_provider_probe_ref": str(payment_probe_file),
                "provider_evidence_signing_key_file": str(provider_evidence_key),
            }
        )
        for family, provider_id, env_name in (
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
            evidence = {
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
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            evidence["signature_sha256"] = hmac.new(
                provider_evidence_key.read_bytes(),
                canonical,
                hashlib.sha256,
            ).hexdigest()
            evidence_path = self.root / f"provider-evidence-{family}.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            provider_env[env_name] = str(evidence_path)
        self.provider_summary = build_provider_adapter_readiness_summary(
            build_provider_adapter_config_from_env(provider_env)
        )
        self.alert_readiness = {
            "ready": True,
            "state": "READY",
            "actual_external_dispatch_configured": True,
            "blocked_reasons": [],
        }
        self.recovery_readiness = {
            "ready": True,
            "state": "VALIDATED",
            "blocked_reasons": [],
            "backup_manifest_sha256": "a" * 64,
            "restore_report_sha256": "b" * 64,
            "rollback_report_sha256": "c" * 64,
        }
        self.session = _MemorySession()
        self.now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _secret(self, name: str, value: bytes) -> Path:
        path = self.root / name
        path.write_bytes(value)
        return path

    def test_release_requires_distinct_approval_then_enables_scoped_capabilities(self) -> None:
        readiness = build_production_release_readiness(
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        self.assertEqual(readiness["state"], PRODUCTION_RELEASE_STATE_READY_FOR_APPROVAL)
        self.assertTrue(readiness["technical_ready"])
        self.assertFalse(readiness["release_active"])
        self.assertIn("production_release_approval_missing", readiness["blocking_reasons"])

        request = request_production_release(
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            actor={
                "authenticated": True,
                "principal_id": "owner-a",
                "role": "owner",
            },
            reason="受控客户生产发布窗口，限定三个客户并保留暂停和回滚能力。",
            evidence_refs=[
                "evidence:controlled-gray-93",
                "evidence:payment-sandbox",
                "evidence:restore-rollback-drill",
            ],
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        approved = approve_production_release(
            request_id=request["request_id"],
            expected_readiness_hash=request["readiness_hash"],
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            actor={
                "authenticated": True,
                "principal_id": "reviewer-a",
                "role": "reviewer",
            },
            approval_note="已复核证据、支付回调、交付边界、告警和回滚材料，同意受控发布。",
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        self.assertEqual(approved["state"], PRODUCTION_RELEASE_STATE_ACTIVE)

        active = build_production_release_readiness(
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        self.assertTrue(active["release_active"])
        self.assertTrue(active["customer_visible_allowed"])
        self.assertTrue(active["payment_execution_enabled"])
        self.assertTrue(active["delivery_execution_enabled"])
        self.assertTrue(active["refund_execution_enabled"])
        self.assertFalse(active["automated_refund_enabled"])
        self.assertFalse(active["public_software_release_allowed"])

    def test_same_principal_cannot_approve_and_suspension_closes_all_capabilities(self) -> None:
        request = request_production_release(
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            actor={
                "authenticated": True,
                "principal_id": "admin-a",
                "role": "admin",
            },
            reason="创建生产灰度请求并等待另一位授权人复核后才允许启用。",
            evidence_refs=["evidence:a", "evidence:b", "evidence:c"],
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        with self.assertRaisesRegex(ValueError, "must differ"):
            approve_production_release(
                request_id=request["request_id"],
                expected_readiness_hash=request["readiness_hash"],
                config=self.config,
                settings=self.settings,
                provider_summary=self.provider_summary,
                session=self.session,
                actor={
                    "authenticated": True,
                    "principal_id": "admin-a",
                    "role": "reviewer",
                },
                approval_note="同一身份不能完成职责分离审批。",
                alert_readiness=self.alert_readiness,
                recovery_readiness=self.recovery_readiness,
                now=self.now,
            )
        approve_production_release(
            request_id=request["request_id"],
            expected_readiness_hash=request["readiness_hash"],
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            actor={
                "authenticated": True,
                "principal_id": "reviewer-a",
                "role": "reviewer",
            },
            approval_note="由独立复核人批准本次受控生产窗口。",
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        suspended = suspend_production_release(
            request_id=request["request_id"],
            session=self.session,
            actor={
                "authenticated": True,
                "principal_id": "admin-a",
                "role": "admin",
            },
            reason="模拟支付服务异常，立即暂停生产窗口并等待人工复核。",
        )
        self.assertEqual(suspended["state"], PRODUCTION_RELEASE_STATE_SUSPENDED)
        readiness = build_production_release_readiness(
            config=self.config,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            alert_readiness=self.alert_readiness,
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        self.assertFalse(readiness["release_active"])
        self.assertFalse(readiness["payment_execution_enabled"])
        self.assertFalse(readiness["delivery_execution_enabled"])

    def test_automated_refund_or_missing_alerts_fail_closed(self) -> None:
        unsafe = ProductionReleaseConfig(
            **{
                **self.config.__dict__,
                "automated_refund_enabled": True,
            }
        )
        readiness = build_production_release_readiness(
            config=unsafe,
            settings=self.settings,
            provider_summary=self.provider_summary,
            session=self.session,
            alert_readiness={"ready": False, "blocked_reasons": ["paging_missing"]},
            recovery_readiness=self.recovery_readiness,
            now=self.now,
        )
        self.assertFalse(readiness["technical_ready"])
        self.assertIn(
            "production_automated_refund_forbidden",
            readiness["technical_blocking_reasons"],
        )
        self.assertIn("paging_missing", readiness["technical_blocking_reasons"])

    def test_recovery_evidence_is_content_validated_and_tamper_fails_closed(self) -> None:
        ready = production_recovery_evidence_readiness(
            config=self.config,
            settings=self.settings,
        )
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["backup_id"], "BACKUP-PRODUCTION-001")

        self.rollback_report_file.write_text(
            '{"rollback_succeeded":true}',
            encoding="utf-8",
        )
        blocked = production_recovery_evidence_readiness(
            config=self.config,
            settings=self.settings,
        )
        self.assertFalse(blocked["ready"])
        self.assertIn(
            "rollback_report_deployment_mismatch",
            blocked["blocked_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
