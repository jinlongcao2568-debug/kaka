from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.deps import get_settings
from api.main import create_app
from shared.settings import InternalApiPrincipal, Settings
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.deployment_tenancy import (
    DEPLOYMENT_BOUNDARY_OBJECT_KEY,
    DEPLOYMENT_BOUNDARY_OBJECT_TYPE,
    DEPLOYMENT_BOUNDARY_RECORD_ID,
    ensure_private_single_tenant_boundary,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository


def _private_settings(root: Path, *, tenant_id: str, instance_id: str) -> Settings:
    namespace = f"{tenant_id}-{instance_id}"
    data_root = root / namespace
    return Settings(
        repo_root=str(ROOT),
        environment="INTERNAL_ONLY",
        deployment_tenancy_mode="PRIVATE_SINGLE_TENANT",
        deployment_tenant_id_optional=tenant_id,
        deployment_instance_id_optional=instance_id,
        storage_backend="json-file",
        storage_path_optional=str(data_root / "storage" / "store.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_backend="local-filesystem",
        object_storage_path_optional=str(data_root / "object-storage"),
        operator_artifact_root_optional=str(data_root / "operator-artifacts"),
        internal_api_principals=(
            InternalApiPrincipal(
                principal_id=f"{tenant_id}-owner",
                role="owner",
                token=f"{tenant_id}-owner-private-token-20260719",
            ),
            InternalApiPrincipal(
                principal_id=f"{tenant_id}-reviewer",
                role="reviewer",
                token=f"{tenant_id}-reviewer-private-token-20260719",
            ),
        ),
        internal_api_cookie_secure=True,
    )


def _record(record_id: str, payload: dict[str, object]) -> PersistedRecord:
    return PersistedRecord(
        object_type="private_customer_record",
        record_id=record_id,
        stage_scope=0,
        project_id=None,
        object_refs={},
        decision_states={},
        trace_refs={},
        audit_refs={},
        governed_state={"internal_only": True},
        writeback_state={},
        payload=payload,
        persisted_at=build_persisted_at(),
    )


class SingleTenantDeploymentIsolationTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()
        DatabaseSession.close_default()

    def test_private_configuration_requires_explicit_isolated_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            valid = _private_settings(
                Path(tmp_dir),
                tenant_id="customer-a",
                instance_id="primary",
            )
            cases = {
                "missing tenant": replace(valid, deployment_tenant_id_optional=None),
                "legacy shared token": replace(
                    valid,
                    internal_api_token_optional="legacy-shared-private-token",
                ),
                "process storage": replace(valid, storage_scope="process"),
                "storage namespace mismatch": replace(
                    valid,
                    storage_path_optional=str(Path(tmp_dir) / "shared" / "store.json"),
                ),
                "object namespace mismatch": replace(
                    valid,
                    object_storage_path_optional=str(Path(tmp_dir) / "shared" / "objects"),
                ),
                "artifact namespace mismatch": replace(
                    valid,
                    operator_artifact_root_optional=str(Path(tmp_dir) / "shared" / "artifacts"),
                ),
                "insecure cookie": replace(valid, internal_api_cookie_secure=False),
            }

            valid_readiness = valid.deployment_tenancy_readiness()
            self.assertTrue(valid_readiness["private_single_tenant_boundary_ready"])
            self.assertFalse(valid_readiness["cross_tenant_routing_enabled"])
            self.assertFalse(valid_readiness["multi_tenant_saas_ready"])

            for label, settings in cases.items():
                with self.subTest(label=label):
                    self.assertFalse(
                        settings.deployment_tenancy_readiness()[
                            "private_single_tenant_boundary_ready"
                        ]
                    )
                    with self.assertRaisesRegex(
                        ValueError,
                        "private single-tenant deployment boundary is not ready",
                    ):
                        settings.assert_deployment_tenancy_boundary()

    def test_database_and_object_storage_are_isolated_between_customer_deployments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings_a = _private_settings(root, tenant_id="customer-a", instance_id="primary")
            settings_b = _private_settings(root, tenant_id="customer-b", instance_id="primary")
            session_a = DatabaseSession(settings=settings_a)
            session_b = DatabaseSession(settings=settings_b)
            try:
                boundary_a = ensure_private_single_tenant_boundary(
                    settings=settings_a,
                    session=session_a,
                )
                boundary_b = ensure_private_single_tenant_boundary(
                    settings=settings_b,
                    session=session_b,
                )
                self.assertTrue(boundary_a["deployment_boundary_enforced"])
                self.assertTrue(boundary_b["deployment_boundary_enforced"])
                self.assertNotEqual(boundary_a["boundary_sha256"], boundary_b["boundary_sha256"])

                session_a.upsert_record(_record("customer-a-only", {"secret": "a"}))
                self.assertIsNone(
                    session_b.get_record("private_customer_record", "customer-a-only")
                )

                objects_a = ObjectStorageRepository(session=session_a, settings=settings_a)
                objects_b = ObjectStorageRepository(session=session_b, settings=settings_b)
                objects_a.put_object(
                    b"customer-a-private-object",
                    content_type="text/plain",
                    object_key="customer/a.txt",
                )
                self.assertIsNone(objects_b.get_object_metadata("customer/a.txt"))
                self.assertFalse(
                    (Path(settings_b.object_storage_path_optional or "") / "customer" / "a.txt").exists()
                )
            finally:
                session_a.close()
                session_b.close()

    def test_copied_customer_storage_is_rejected_by_boundary_seal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings_a = _private_settings(root, tenant_id="customer-a", instance_id="primary")
            settings_b = _private_settings(root, tenant_id="customer-b", instance_id="primary")
            session_a = DatabaseSession(settings=settings_a)
            ensure_private_single_tenant_boundary(settings=settings_a, session=session_a)
            session_a.close()

            target_storage = Path(settings_b.storage_path_optional or "")
            target_storage.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(settings_a.storage_path_optional or ""), target_storage)
            source_seal = (
                Path(settings_a.object_storage_path_optional or "")
                / DEPLOYMENT_BOUNDARY_OBJECT_KEY
            )
            target_seal = (
                Path(settings_b.object_storage_path_optional or "")
                / DEPLOYMENT_BOUNDARY_OBJECT_KEY
            )
            target_seal.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_seal, target_seal)

            session_b = DatabaseSession(settings=settings_b)
            try:
                with self.assertRaisesRegex(ValueError, "refusing cross-customer storage mount"):
                    ensure_private_single_tenant_boundary(settings=settings_b, session=session_b)
            finally:
                session_b.close()

    def test_concurrent_first_boot_allows_only_one_customer_to_claim_empty_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings_a = _private_settings(root, tenant_id="customer-a", instance_id="primary")
            settings_b = _private_settings(root, tenant_id="customer-b", instance_id="primary")
            shared_root = root / "customer-a-primary" / "customer-b-primary" / "shared"
            shared_storage = str(shared_root / "storage" / "store.json")
            shared_objects = str(shared_root / "object-storage")
            shared_artifacts = str(shared_root / "operator-artifacts")
            settings_a = replace(
                settings_a,
                storage_path_optional=shared_storage,
                object_storage_path_optional=shared_objects,
                operator_artifact_root_optional=shared_artifacts,
            )
            settings_b = replace(
                settings_b,
                storage_path_optional=shared_storage,
                object_storage_path_optional=shared_objects,
                operator_artifact_root_optional=shared_artifacts,
            )
            self.assertTrue(
                settings_a.deployment_tenancy_readiness()[
                    "private_single_tenant_boundary_ready"
                ]
            )
            self.assertTrue(
                settings_b.deployment_tenancy_readiness()[
                    "private_single_tenant_boundary_ready"
                ]
            )
            session_a = DatabaseSession(settings=settings_a)
            session_b = DatabaseSession(settings=settings_b)
            barrier = Barrier(2)

            def claim(settings: Settings, session: DatabaseSession) -> str:
                barrier.wait(timeout=5)
                try:
                    ensure_private_single_tenant_boundary(settings=settings, session=session)
                except ValueError as exc:
                    return f"blocked:{exc}"
                return "claimed"

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    outcomes = list(
                        executor.map(
                            lambda pair: claim(*pair),
                            ((settings_a, session_a), (settings_b, session_b)),
                        )
                    )
                self.assertEqual(outcomes.count("claimed"), 1)
                self.assertEqual(
                    sum("refusing cross-customer storage mount" in item for item in outcomes),
                    1,
                )
            finally:
                session_a.close()
                session_b.close()

    def test_boundary_creation_is_idempotent_and_persisted_in_both_stores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = _private_settings(
                Path(tmp_dir),
                tenant_id="customer-a",
                instance_id="primary",
            )
            session = DatabaseSession(settings=settings)
            try:
                first = ensure_private_single_tenant_boundary(settings=settings, session=session)
                second = ensure_private_single_tenant_boundary(settings=settings, session=session)
                self.assertEqual(first["boundary_sha256"], second["boundary_sha256"])
                record = session.get_record(
                    DEPLOYMENT_BOUNDARY_OBJECT_TYPE,
                    DEPLOYMENT_BOUNDARY_RECORD_ID,
                )
                self.assertIsNotNone(record)
                object_seal = (
                    Path(settings.object_storage_path_optional or "")
                    / DEPLOYMENT_BOUNDARY_OBJECT_KEY
                )
                self.assertTrue(object_seal.is_file())
                payload = json.loads(object_seal.read_text(encoding="utf-8"))
                self.assertEqual(payload["boundary_sha256"], first["boundary_sha256"])
            finally:
                session.close()

    def test_private_app_startup_fails_closed_and_health_reports_only_single_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            namespace = "customer-a-primary"
            principals = json.dumps(
                [
                    {
                        "principal_id": "customer-a-owner",
                        "role": "owner",
                        "token": "customer-a-owner-private-token-20260719",
                    },
                    {
                        "principal_id": "customer-a-reviewer",
                        "role": "reviewer",
                        "token": "customer-a-reviewer-private-token-20260719",
                    },
                ]
            )
            valid_env = {
                "KAKA_DEPLOYMENT_TENANCY_MODE": "PRIVATE_SINGLE_TENANT",
                "KAKA_DEPLOYMENT_TENANT_ID": "customer-a",
                "KAKA_DEPLOYMENT_INSTANCE_ID": "primary",
                "KAKA_INTERNAL_API_PRINCIPALS_JSON": principals,
                "KAKA_INTERNAL_API_COOKIE_SECURE": "true",
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_SCOPE": "shared",
                "KAKA_STORAGE_PATH": str(root / namespace / "storage" / "store.json"),
                "KAKA_OBJECT_STORAGE_BACKEND": "local-filesystem",
                "KAKA_OBJECT_STORAGE_PATH": str(root / namespace / "object-storage"),
                "KAKA_OPERATOR_ARTIFACT_ROOT": str(root / namespace / "operator-artifacts"),
                "KAKA_QUEUE_BACKEND": "storage",
                "KAKA_WORKER_RUNTIME": "internal-storage-worker",
            }

            with patch.dict(os.environ, valid_env, clear=True):
                get_settings.cache_clear()
                app = create_app()
                try:
                    response = TestClient(app).get("/healthz")
                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body["deployment_tenancy_mode"], "PRIVATE_SINGLE_TENANT")
                    self.assertTrue(body["private_single_tenant_boundary_ready"])
                    self.assertFalse(body["cross_tenant_routing_enabled"])
                    self.assertFalse(body["multi_tenant_saas_ready"])
                    self.assertNotIn("customer-a", response.text)
                finally:
                    app.state.storage_session.close()

            invalid_env = dict(valid_env)
            invalid_env.pop("KAKA_OPERATOR_ARTIFACT_ROOT")
            with patch.dict(os.environ, invalid_env, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(
                    ValueError,
                    "PRIVATE_EXPLICIT_ARTIFACT_ROOT_REQUIRED",
                ):
                    create_app()

    def test_private_compose_is_explicitly_isolation_only(self) -> None:
        compose_text = (ROOT / "docker-compose.private-single-tenant.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("PRIVATE_SINGLE_TENANT", compose_text)
        self.assertIn("127.0.0.1:${KAKA_PRIVATE_BIND_PORT:-18000}:8000", compose_text)
        self.assertIn("shared_cross_customer_storage_allowed: false", compose_text)
        self.assertIn("multi_tenant_saas_ready: false", compose_text)
        self.assertIn("private_pilot_deployment_ready: false", compose_text)
        self.assertIn("per_customer_network_namespace: true", compose_text)
        self.assertIn("network_egress_restriction_ready: false", compose_text)
        self.assertNotIn("KAKA_INTERNAL_API_TOKEN:", compose_text)

    def test_private_edge_uses_secret_file_and_rejects_untrusted_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            namespace = "customer-a-primary"
            secret_path = root / "principals.json"
            secret_path.write_text(
                json.dumps(
                    [
                        {
                            "principal_id": "customer-a-owner",
                            "role": "owner",
                            "token": "customer-a-owner-private-token-20260719",
                        },
                        {
                            "principal_id": "customer-a-reviewer",
                            "role": "reviewer",
                            "token": "customer-a-reviewer-private-token-20260719",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            edge_env = {
                "KAKA_DEPLOYMENT_TENANCY_MODE": "PRIVATE_SINGLE_TENANT",
                "KAKA_DEPLOYMENT_TENANT_ID": "customer-a",
                "KAKA_DEPLOYMENT_INSTANCE_ID": "primary",
                "KAKA_PRIVATE_EDGE_REQUIRED": "true",
                "KAKA_PRIVATE_HOSTNAME": "pilot.localhost",
                "KAKA_API_ALLOWED_HOSTS": "pilot.localhost,localhost,127.0.0.1,app",
                "KAKA_API_TRUSTED_PROXY_BOUNDARY": "PRIVATE_EDGE_NETWORK_ONLY",
                "KAKA_API_TRUSTED_PROXY_IPS": "172.31.252.254",
                "KAKA_INTERNAL_API_PRINCIPALS_FILE": str(secret_path),
                "KAKA_INTERNAL_API_COOKIE_SECURE": "true",
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_SCOPE": "shared",
                "KAKA_STORAGE_PATH": str(root / namespace / "storage" / "store.json"),
                "KAKA_OBJECT_STORAGE_BACKEND": "local-filesystem",
                "KAKA_OBJECT_STORAGE_PATH": str(root / namespace / "object-storage"),
                "KAKA_OPERATOR_ARTIFACT_ROOT": str(root / namespace / "operator-artifacts"),
                "KAKA_QUEUE_BACKEND": "storage",
                "KAKA_WORKER_RUNTIME": "internal-storage-worker",
            }
            with patch.dict(os.environ, edge_env, clear=True):
                get_settings.cache_clear()
                settings = get_settings()
                self.assertTrue(
                    settings.deployment_tenancy_readiness()[
                        "private_edge_configuration_ready"
                    ]
                )
                self.assertEqual(
                    settings.internal_api_auth_readiness()["principal_config_source"],
                    "secret_file",
                )
                app = create_app()
                try:
                    client = TestClient(app)
                    accepted = client.get(
                        "/healthz",
                        headers={"Host": "pilot.localhost"},
                    )
                    rejected = client.get(
                        "/healthz",
                        headers={"Host": "attacker.invalid"},
                    )
                    authenticated = client.get(
                        "/openapi.json",
                        headers={
                            "Host": "pilot.localhost",
                            "Authorization": (
                                "Bearer customer-a-owner-private-token-20260719"
                            ),
                        },
                    )
                    self.assertEqual(accepted.status_code, 200)
                    self.assertTrue(accepted.json()["private_edge_configuration_ready"])
                    self.assertTrue(accepted.json()["principal_secret_file_configured"])
                    self.assertEqual(accepted.json()["api_allowed_host_count"], 4)
                    self.assertEqual(accepted.json()["api_trusted_proxy_ip_count"], 1)
                    self.assertEqual(rejected.status_code, 400)
                    self.assertEqual(authenticated.status_code, 200)
                finally:
                    app.state.storage_session.close()

            both_sources = dict(edge_env)
            both_sources["KAKA_INTERNAL_API_PRINCIPALS_JSON"] = secret_path.read_text(
                encoding="utf-8"
            )
            with patch.dict(os.environ, both_sources, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(ValueError, "configure only one"):
                    get_settings()

            environment_only = dict(edge_env)
            environment_only.pop("KAKA_INTERNAL_API_PRINCIPALS_FILE")
            environment_only["KAKA_INTERNAL_API_PRINCIPALS_JSON"] = secret_path.read_text(
                encoding="utf-8"
            )
            with patch.dict(os.environ, environment_only, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(
                    ValueError,
                    "PRIVATE_EDGE_PRINCIPAL_SECRET_FILE_REQUIRED",
                ):
                    create_app()

            missing_proxy_ip = dict(edge_env)
            missing_proxy_ip.pop("KAKA_API_TRUSTED_PROXY_IPS")
            with patch.dict(os.environ, missing_proxy_ip, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(
                    ValueError,
                    "PRIVATE_EDGE_EXPLICIT_TRUSTED_PROXY_IP_REQUIRED",
                ):
                    create_app()

            wildcard_proxy = dict(edge_env)
            wildcard_proxy["KAKA_API_TRUSTED_PROXY_IPS"] = "*"
            with patch.dict(os.environ, wildcard_proxy, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(ValueError, "must not trust every address"):
                    get_settings()

    def test_private_pilot_compose_has_tls_secret_and_no_backend_host_port(self) -> None:
        compose_text = (ROOT / "docker-compose.private-pilot.yml").read_text(
            encoding="utf-8"
        )
        caddyfile = (ROOT / "deploy" / "private-pilot" / "Caddyfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("caddy:2.11.4-alpine", compose_text)
        self.assertIn("postgres:18.4-alpine3.24", compose_text)
        self.assertIn("KAKA_STORAGE_BACKEND: postgresql", compose_text)
        self.assertIn("KAKA_STORAGE_DATABASE_PASSWORD_FILE", compose_text)
        self.assertIn("POSTGRES_PASSWORD_FILE", compose_text)
        self.assertIn("condition: service_completed_successfully", compose_text)
        self.assertIn('required_storage_schema_revision: "20260717_0002"', compose_text)
        self.assertIn("/var/lib/postgresql", compose_text)
        self.assertIn("KAKA_INTERNAL_API_PRINCIPALS_FILE", compose_text)
        self.assertIn("/run/secrets/kaka_internal_api_principals", compose_text)
        self.assertIn("backend_host_port_published: false", compose_text)
        self.assertIn('127.0.0.1:${KAKA_PRIVATE_TLS_PORT:-18443}:443', compose_text)
        self.assertIn(
            '"--forwarded-allow-ips=${KAKA_PRIVATE_EDGE_PROXY_IP:-172.31.252.254}"',
            compose_text,
        )
        self.assertNotIn("--forwarded-allow-ips=*", compose_text)
        self.assertIn("PRIVATE_EDGE_NETWORK_ONLY", compose_text)
        self.assertIn("KAKA_API_TRUSTED_PROXY_IPS", compose_text)
        self.assertNotIn("KAKA_INTERNAL_API_PRINCIPALS_JSON:", compose_text)
        self.assertNotIn("POSTGRES_PASSWORD:", compose_text)
        app_section = compose_text.split("  edge:", 1)[0]
        self.assertNotIn("    ports:", app_section)
        self.assertIn("admin off", caddyfile)
        self.assertIn("strict_sni_host on", caddyfile)
        self.assertIn("tls internal", caddyfile)
        self.assertIn("reverse_proxy app:8000", caddyfile)
        self.assertIn("request_body", caddyfile)
        self.assertIn("max_size 2MB", caddyfile)
        self.assertIn(
            'Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"',
            caddyfile,
        )
        self.assertIn("KAKA_API_MAX_REQUEST_BODY_BYTES", compose_text)
        self.assertIn("KAKA_API_EXPENSIVE_REQUESTS_PER_MINUTE", compose_text)
        self.assertIn("KAKA_API_EXPENSIVE_CONCURRENCY_PER_PRINCIPAL", compose_text)
        self.assertIn("private-backend:", compose_text)
        self.assertIn("internal: true", compose_text)
        self.assertIn(
            'ipv4_address: "${KAKA_PRIVATE_EDGE_PROXY_IP:-172.31.252.254}"',
            compose_text,
        )
        self.assertIn(
            'subnet: "${KAKA_PRIVATE_EDGE_SUBNET:-172.31.252.0/24}"',
            compose_text,
        )
        self.assertIn("  egress-proxy:", compose_text)
        self.assertIn("runtime.public_egress_proxy", compose_text)
        self.assertIn("KAKA_CONTROLLED_EGRESS_PROXY_URL: http://egress-proxy:18080", compose_text)
        self.assertIn("KAKA_EGRESS_MAX_CONCURRENT_CONNECTIONS", compose_text)
        self.assertIn("public-egress:", compose_text)
        self.assertIn("kaka.destination_policy: registered_and_deployment_explicit_hosts_only", compose_text)
        self.assertIn('kaka.public_ip_pinning_required: "true"', compose_text)
        self.assertIn('kaka.host_port_published: "false"', compose_text)
        self.assertIn("  alert-dispatcher:", compose_text)
        self.assertIn("runtime.operational_alert_dispatcher", compose_text)
        self.assertIn("KAKA_ALERT_ALLOWED_HOSTS", compose_text)
        self.assertIn("KAKA_ALERT_SIGNING_SECRET_FILE", compose_text)
        self.assertIn("KAKA_ALERT_DEAD_LETTER_PATH", compose_text)
        self.assertIn("profiles:\n      - alerting", compose_text)
        self.assertGreaterEqual(compose_text.count('KAKA_OBSERVABILITY_ENABLED: "true"'), 4)
        self.assertGreaterEqual(
            compose_text.count(
                "KAKA_OBSERVABILITY_EVENT_PATH: /app/.kaka-local/runtime/operational-events-v1.jsonl"
            ),
            4,
        )

    def test_private_pilot_splits_api_core_worker_and_browser_worker_capabilities(self) -> None:
        compose_text = (ROOT / "docker-compose.private-pilot.yml").read_text(
            encoding="utf-8"
        )
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM runtime-base AS api", dockerfile)
        self.assertIn("FROM runtime-base AS worker", dockerfile)
        self.assertIn("FROM worker AS browser-worker", dockerfile)
        self.assertIn("python -m playwright install --with-deps chromium", dockerfile)
        self.assertIn("ARG KAKA_REQUIREMENTS_FILE=requirements-api.lock.txt", dockerfile)
        self.assertIn("ARG KAKA_REQUIREMENTS_FILE=requirements.lock.txt", dockerfile)
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("target: api", compose_text)
        self.assertIn("  worker:", compose_text)
        self.assertIn("target: worker", compose_text)
        self.assertIn("  browser-worker:", compose_text)
        self.assertIn("target: browser-worker", compose_text)
        self.assertIn("kaka.worker_capability: core", compose_text)
        self.assertIn("kaka.worker_capability: browser", compose_text)
        self.assertIn("--worker-capability", compose_text)
        self.assertIn("runtime.controlled_gray_scheduler_worker", compose_text)
        self.assertIn("runtime.operator_long_task_worker", compose_text)
        self.assertIn("runtime.operator_long_task_worker", dockerfile)
        self.assertIn("long_work_in_api_process: \"false\"", compose_text)
        self.assertIn("unattended_scope: internal_prepare_only", compose_text)

    def test_private_pilot_backup_restore_and_release_rollback_are_isolated(self) -> None:
        compose_text = (ROOT / "docker-compose.private-pilot.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        backup_script = (ROOT / "scripts" / "backup-private-pilot.ps1").read_text(
            encoding="utf-8"
        )
        restore_script = (
            ROOT / "scripts" / "restore-private-pilot-isolated.ps1"
        ).read_text(encoding="utf-8")
        rollback_script = (
            ROOT / "scripts" / "rollback-private-pilot-release.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("FROM postgres:18.4-alpine3.24 AS backup-tools", dockerfile)
        self.assertIn("runtime.private_pilot_backup", dockerfile)
        self.assertIn("  backup-tools:", compose_text)
        self.assertIn("  restore-postgres:", compose_text)
        self.assertIn("  restore-tools:", compose_text)
        self.assertIn("- pilot-data:/source-data:ro", compose_text)
        self.assertIn("restore-isolated:", compose_text)
        self.assertIn("restore-postgres-data:/var/lib/postgresql", compose_text)
        self.assertIn("restore-object-data:/restore-objects", compose_text)
        self.assertIn("KAKA_BACKUP_WRITERS_PAUSED_ACK", compose_text)
        self.assertIn("KAKA_RESTORE_ISOLATED_ACK", compose_text)
        self.assertIn('kaka.active_database_mutation_enabled: "false"', compose_text)
        self.assertIn('kaka.active_object_storage_mutation_enabled: "false"', compose_text)
        self.assertGreaterEqual(compose_text.count("${KAKA_IMAGE_TAG:-local}"), 7)
        self.assertIn("[Parameter(Mandatory = $true)][switch]$PauseWriters", backup_script)
        self.assertIn("WRITERS_PAUSED:$TenantId-$InstanceId", backup_script)
        self.assertIn("[Parameter(Mandatory = $true)][switch]$ConfirmIsolatedRestore", restore_script)
        self.assertIn("RESTORE_ISOLATED:$targetDatabase", restore_script)
        self.assertIn("[Parameter(Mandatory = $true)][switch]$ConfirmReleaseRollback", rollback_script)
        self.assertIn("--no-build --wait", rollback_script)
        self.assertIn("automated_schema_downgrade_executed = $false", rollback_script)

    def test_postgresql_password_file_builds_private_namespaced_url_without_secret_readback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            namespace = "customer-a-primary"
            principal_file = root / "principals.json"
            principal_file.write_text(
                json.dumps(
                    [
                        {
                            "principal_id": "customer-a-owner",
                            "role": "owner",
                            "token": "customer-a-owner-private-token-20260719",
                        },
                        {
                            "principal_id": "customer-a-reviewer",
                            "role": "reviewer",
                            "token": "customer-a-reviewer-private-token-20260719",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            database_password = "private:A@b/20260719-very-secret"
            password_file = root / "postgres-password"
            password_file.write_text(f"{database_password}\n", encoding="utf-8")
            edge_env = {
                "KAKA_DEPLOYMENT_TENANCY_MODE": "PRIVATE_SINGLE_TENANT",
                "KAKA_DEPLOYMENT_TENANT_ID": "customer-a",
                "KAKA_DEPLOYMENT_INSTANCE_ID": "primary",
                "KAKA_PRIVATE_EDGE_REQUIRED": "true",
                "KAKA_PRIVATE_HOSTNAME": "pilot.localhost",
                "KAKA_API_ALLOWED_HOSTS": "pilot.localhost,localhost,127.0.0.1,app",
                "KAKA_API_TRUSTED_PROXY_BOUNDARY": "PRIVATE_EDGE_NETWORK_ONLY",
                "KAKA_API_TRUSTED_PROXY_IPS": "172.31.252.254",
                "KAKA_INTERNAL_API_PRINCIPALS_FILE": str(principal_file),
                "KAKA_INTERNAL_API_COOKIE_SECURE": "true",
                "KAKA_STORAGE_BACKEND": "postgresql",
                "KAKA_STORAGE_SCOPE": "shared",
                "KAKA_STORAGE_DATABASE_HOST": "postgres",
                "KAKA_STORAGE_DATABASE_PORT": "5432",
                "KAKA_STORAGE_DATABASE_USER": "kaka",
                "KAKA_STORAGE_DATABASE_NAME": namespace,
                "KAKA_STORAGE_DATABASE_PASSWORD_FILE": str(password_file),
                "KAKA_OBJECT_STORAGE_BACKEND": "local-filesystem",
                "KAKA_OBJECT_STORAGE_PATH": str(root / namespace / "object-storage"),
                "KAKA_OPERATOR_ARTIFACT_ROOT": str(
                    root / namespace / "operator-artifacts"
                ),
                "KAKA_QUEUE_BACKEND": "storage",
                "KAKA_WORKER_RUNTIME": "internal-storage-worker",
            }
            with patch.dict(os.environ, edge_env, clear=True):
                get_settings.cache_clear()
                settings = get_settings()
                self.assertEqual(settings.normalized_storage_backend(), "postgresql")
                self.assertTrue(
                    settings.storage_database_url_optional.startswith(
                        "postgresql+psycopg://kaka:private%3AA%40b%2F20260719-very-secret@"
                    )
                )
                self.assertTrue(
                    settings.deployment_tenancy_readiness()[
                        "private_single_tenant_boundary_ready"
                    ]
                )
                bootstrap = settings.storage_bootstrap_payload()
                self.assertTrue(bootstrap["storage_database_url_configured"])
                self.assertTrue(bootstrap["storage_database_password_file_configured"])
                migration = bootstrap["platform_infra_readiness"]["migration_readiness"]
                self.assertTrue(migration["migration_execution_enabled"])
                self.assertTrue(migration["deployment_migration_job_defined"])
                self.assertTrue(migration["schema_revision_gate_defined"])
                self.assertEqual(
                    migration["required_storage_schema_revision"],
                    "20260717_0002",
                )
                self.assertNotIn(database_password, repr(settings))
                self.assertNotIn(database_password, json.dumps(bootstrap))

            conflicting = dict(edge_env)
            conflicting["KAKA_STORAGE_DATABASE_URL"] = (
                "postgresql+psycopg://kaka:other@postgres:5432/customer-a-primary"
            )
            with patch.dict(os.environ, conflicting, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(ValueError, "not both"):
                    get_settings()

            missing_password_file = dict(edge_env)
            missing_password_file.pop("KAKA_STORAGE_DATABASE_PASSWORD_FILE")
            with patch.dict(os.environ, missing_password_file, clear=True):
                get_settings.cache_clear()
                with self.assertRaisesRegex(
                    ValueError,
                    "KAKA_STORAGE_DATABASE_PASSWORD_FILE is required",
                ):
                    get_settings()


if __name__ == "__main__":
    unittest.main()
