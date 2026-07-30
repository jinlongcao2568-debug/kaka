from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from api.deps import get_settings
from api.main import (
    INTERNAL_BROWSER_SESSION_COOKIE,
    _ExpensiveRequestLimiter,
    _audit_internal_write_request_contract_policy,
    _audit_internal_write_permission_policy,
    _audit_internal_write_response_contract_policy,
    _decode_browser_session,
    _encode_browser_session,
    _request_model_for_operation,
    create_app,
)
from api.routes.stage1 import register_stage1_routes
from api.routes.stage2 import register_stage2_routes
from api.routes.stage3 import register_stage3_routes
from api.routes.stage4 import register_stage4_routes
from api.routes.stage5 import register_stage5_routes
from api.routes.stage6 import (
    register_stage1_to_stage6_internal_orchestration_routes,
    register_stage6_routes,
)
from helpers import load_fixture
from shared.provider_adapter_config import (
    PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY,
    PROVIDER_FAMILIES,
)
from shared.pipeline import run_internal_chain
from storage import persist_stage_bundle, reset_default_storage
from storage.db import DatabaseSession
from storage.repositories.leadpack_delivery_package_repo import LeadpackDeliveryPackageRepository
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.saleable_opportunity_repo import SaleableOpportunityRepository


RESERVED_ENTRY_PLAN_READBACK_KEYS = (
    "stage_scope",
    "availability_state",
    "transport_state",
    "reserved_entry_state",
    "reserved_operation_id",
    "reserved_path",
    "reserved_method",
    "handoff_refs",
    "http_entry_enabled",
    "real_transport_enabled",
    "orchestrator_enabled",
    "internal_orchestration_entry_available",
    "internal_orchestration_operation_id",
    "internal_orchestration_path",
    "internal_orchestration_method",
    "internal_orchestration_payload_boundary",
    "stage6_readback_mode",
    "stage1_to_stage5_external_live_transport_state",
    "route_registrar",
)
RESERVED_ENTRY_EXPECTATIONS = {
    1: {
        "reserved_operation_id": "reservedStage1TaskingEntry",
        "reserved_path": "/reserved/stage1/tasking",
        "reserved_method": "POST",
        "handoff_refs": ["H-01-STAGE1-TO-STAGE2"],
    },
    2: {
        "reserved_operation_id": "reservedStage2IngestionEntry",
        "reserved_path": "/reserved/stage2/ingestion",
        "reserved_method": "POST",
        "handoff_refs": ["H-01-STAGE1-TO-STAGE2", "H-02-STAGE2-TO-STAGE3"],
    },
    3: {
        "reserved_operation_id": "reservedStage3ParsingEntry",
        "reserved_path": "/reserved/stage3/parsing",
        "reserved_method": "POST",
        "handoff_refs": ["H-02-STAGE2-TO-STAGE3", "H-03-STAGE3-TO-STAGE4"],
    },
    4: {
        "reserved_operation_id": "reservedStage4VerificationEntry",
        "reserved_path": "/reserved/stage4/verification",
        "reserved_method": "POST",
        "handoff_refs": ["H-03-STAGE3-TO-STAGE4", "H-04-STAGE4-TO-STAGE5"],
    },
    5: {
        "reserved_operation_id": "reservedStage5RulesEvidenceEntry",
        "reserved_path": "/reserved/stage5/rules-evidence",
        "reserved_method": "POST",
        "handoff_refs": ["H-04-STAGE4-TO-STAGE5", "H-05-STAGE5-TO-STAGE6"],
    },
}
RESERVED_INFRA_BACKENDS = {
    "alembic",
    "redis",
    "dramatiq",
    "minio",
    "s3",
    "docker-compose",
}
RESERVED_OR_NOT_CONFIGURED = {"RESERVED_NOT_LIVE", "NOT_CONFIGURED"}
STORAGE_ENV_KEYS = (
    "KAKA_STORAGE_BACKEND",
    "KAKA_STORAGE_PATH",
    "KAKA_STORAGE_DATABASE_URL",
    "KAKA_STORAGE_DATABASE_PASSWORD_FILE",
    "KAKA_STORAGE_DATABASE_HOST",
    "KAKA_STORAGE_DATABASE_PORT",
    "KAKA_STORAGE_DATABASE_USER",
    "KAKA_STORAGE_DATABASE_NAME",
    "KAKA_STORAGE_SCOPE",
    "KAKA_STORAGE_TEST_ISOLATION",
    "KAKA_OBJECT_STORAGE_BACKEND",
    "KAKA_OBJECT_STORAGE_PATH",
)


def sqlalchemy_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def expected_reserved_entry_plan(stage_scope: int) -> dict[str, object]:
    return {
        "stage_scope": stage_scope,
        "availability_state": "CONTROLLED_UNAVAILABLE",
        "transport_state": "TRANSPORT_NOT_WIRED",
        "reserved_entry_state": "RESERVED_NOT_LIVE",
        **RESERVED_ENTRY_EXPECTATIONS[stage_scope],
        "http_entry_enabled": False,
        "real_transport_enabled": False,
        "orchestrator_enabled": False,
        "internal_orchestration_entry_available": True,
        "internal_orchestration_operation_id": "runStage1ToStage6InternalOrchestration",
        "internal_orchestration_path": "/internal/stage1-6/orchestrations",
        "internal_orchestration_method": "POST",
        "internal_orchestration_payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
        "stage6_readback_mode": "repository_backed_preview",
        "stage1_to_stage5_external_live_transport_state": "BLOCKED_CONTROLLED_UNAVAILABLE",
        "route_registrar": f"register_stage{stage_scope}_routes",
    }


class TestApiTransportBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self._storage_tmp = tempfile.TemporaryDirectory()
        tmp_root = Path(self._storage_tmp.name)
        self._storage_env = patch.dict(
            os.environ,
            {
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_PATH": str(tmp_root / "api-transport-default.json"),
                "KAKA_OBJECT_STORAGE_PATH": str(tmp_root / "objects"),
                "LOCALAPPDATA": str(tmp_root / "local-app-data"),
            },
            clear=False,
        )
        self._storage_env.start()
        for key in (
            "KAKA_STORAGE_DATABASE_URL",
            "KAKA_STORAGE_DATABASE_PASSWORD_FILE",
            "KAKA_STORAGE_DATABASE_HOST",
            "KAKA_STORAGE_DATABASE_PORT",
            "KAKA_STORAGE_DATABASE_USER",
            "KAKA_STORAGE_DATABASE_NAME",
            "KAKA_STORAGE_SCOPE",
            "KAKA_STORAGE_TEST_ISOLATION",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()
        reset_default_storage()

    def tearDown(self) -> None:
        get_settings.cache_clear()
        DatabaseSession.close_default()
        self._storage_env.stop()
        self._storage_tmp.cleanup()

    def test_get_settings_returns_formal_internal_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir}, clear=False):
                for key in STORAGE_ENV_KEYS:
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                settings = get_settings()
                resolved_storage_path = settings.resolved_storage_path()

        self.assertEqual(settings.environment, "INTERNAL_ONLY")
        self.assertEqual(Path(settings.repo_root).resolve(), ROOT.resolve())
        self.assertEqual(settings.storage_backend, "json-file")
        self.assertIsNone(settings.storage_path_optional)
        self.assertIsNone(settings.storage_database_url_optional)
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")
        self.assertEqual(
            resolved_storage_path,
            Path(tmp_dir) / "kaka" / "internal_operator_loop_store.json",
        )

    def test_network_client_requires_configured_bearer_token(self) -> None:
        async def exercise(app: object) -> tuple[httpx.Response, ...]:
            transport = httpx.ASGITransport(
                app=app,
                client=("127.0.0.1", 12345),
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://kaka.internal",
            ) as client:
                health = await client.get("/healthz")
                missing = await client.get("/openapi.json")
                wrong = await client.get(
                    "/openapi.json",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                accepted = await client.get(
                    "/openapi.json",
                    headers={"Authorization": "Bearer test-internal-token"},
                )
            return health, missing, wrong, accepted

        with patch.dict(
            os.environ,
            {"KAKA_INTERNAL_API_TOKEN": "test-internal-token"},
            clear=False,
        ):
            get_settings.cache_clear()
            health, missing, wrong, accepted = asyncio.run(exercise(create_app()))

        self.assertEqual(health.status_code, 200)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.json()["detail"]["code"], "INTERNAL_API_AUTH_REQUIRED")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.headers["cache-control"], "no-store")
        self.assertFalse(health.json()["object_approval_workflow_ready"])

    def test_unclassified_write_route_fails_the_central_permission_audit(self) -> None:
        app = create_app()
        try:
            policy = app.state.internal_write_permission_policy
            permissions_by_operation = {
                entry["operation_id"]: entry["permission"]
                for entry in policy["classified_operations"]
            }
            self.assertTrue(policy["all_unsafe_routes_classified"])
            self.assertFalse(policy["production_live_actions_enabled"])
            self.assertEqual(
                permissions_by_operation["createPaymentRecord"],
                "internal_sandbox_finance_write",
            )
            self.assertEqual(
                permissions_by_operation["submitStage8OperatorAction"],
                "internal_draft_write",
            )
            self.assertEqual(
                permissions_by_operation["runOwnerRealPublicSourceCapture"],
                "owner_source_capture",
            )
            self.assertEqual(
                permissions_by_operation["createOperatorAgentToolPlan"],
                "internal_agent_plan",
            )
            self.assertEqual(
                permissions_by_operation["mutateOperatorAgentMemory"],
                "internal_agent_memory",
            )
            app.add_api_route(
                "/test-only-unclassified-write",
                lambda: {"ok": True},
                methods=["POST"],
                operation_id="testOnlyUnclassifiedWrite",
            )
            with self.assertRaisesRegex(RuntimeError, "missing an explicit internal write"):
                _audit_internal_write_permission_policy(app)
        finally:
            app.state.storage_session.close()

    def test_all_internal_write_contracts_reject_unknown_fields(self) -> None:
        cases = {
            "runStage1ToStage6InternalOrchestration": "/internal/stage1-6/orchestrations",
            "submitStage6OperatorAction": "/review-report-workbench/PF-STRICT/operator-actions",
            "refreshSaleableOpportunity": "/saleable-opportunities/OPP-STRICT/refresh",
            "submitStage7OperatorAction": "/saleable-opportunities/OPP-STRICT/operator-actions",
            "requestLeadpackExternalDeliveryCandidateReview": (
                "/leadpack-external-delivery-candidates/OPP-STRICT/review-requests"
            ),
            "simulateLeadpackExternalDeliveryExport": (
                "/leadpack-external-delivery-candidates/OPP-STRICT/export-simulations"
            ),
            "requestLeadpackActivationPrepReview": (
                "/leadpack-external-delivery-candidates/OPP-STRICT/activation-prep-review-requests"
            ),
            "requestLeadpackActivationDesignImplementationPrepReview": (
                "/leadpack-external-delivery-candidates/OPP-STRICT/"
                "activation-design-implementation-prep-review-requests"
            ),
            "checkContactCompliance": "/contact-targets/compliance-check",
            "createOutreachPlan": "/outreach-plans",
            "createTouchRecord": "/touch-records",
            "submitStage8OperatorAction": "/outreach-workbench/OPP-STRICT/operator-actions",
            "submitStage9OperatorAction": (
                "/order-delivery-workbench/OPP-STRICT/operator-actions"
            ),
            "createOrder": "/orders",
            "createPaymentRecord": "/payments",
            "createDeliveryRecord": "/deliveries",
            "createOpportunityOutcomeEvent": "/opportunity-outcomes",
            "createGovernanceFeedbackEvent": "/governance-feedback-events",
            "createOperatorTask": "/operator-console/tasks",
            "createOperatorAgentTurn": "/operator-console/agent/turns",
            "createOperatorAgentToolPlan": "/operator-console/agent/plans",
            "mutateOperatorAgentMemory": "/operator-console/agent/memories",
            "mutateProductOnboardingConfig": "/operator-console/onboarding/configs",
            "runProductOnboardingConfigTest": (
                "/operator-console/onboarding/config-test-runs"
            ),
            "retryOperatorSupportTask": "/operator-console/support/task-actions",
            "runOperatorAutonomousOpportunitySearch": (
                "/operator-console/autonomous-opportunity-search"
            ),
            "clearOperatorAutonomousSearchRuns": (
                "/operator-console/autonomous-search-runs/clear"
            ),
            "runOwnerRealPublicSourceCapture": "/operator-console/real-source-runs",
            "prepareControlledGrayPublicOrchestrator": (
                "/operator-console/controlled-gray-orchestrator/prepare"
            ),
            "enqueueControlledGrayPublicOrchestratorWorker": (
                "/operator-console/controlled-gray-orchestrator/worker/enqueue"
            ),
            "runControlledGrayPublicOrchestratorWorkerOnce": (
                "/operator-console/controlled-gray-orchestrator/worker/run-once"
            ),
            "cancelControlledGrayPublicOrchestratorWorkerJob": (
                "/operator-console/controlled-gray-orchestrator/worker/cancel"
            ),
            "cancelOperatorLongTask": "/operator-console/long-tasks/cancel",
            "importOperatorProject": "/operator-console/project-imports",
        }
        client = TestClient(create_app())
        try:
            self.assertEqual(len(cases), 34)
            policy = _audit_internal_write_request_contract_policy(client.app)
            self.assertTrue(policy["all_unsafe_operations_strict"])
            self.assertTrue(policy["actor_identity_transport_controlled"])
            self.assertEqual(policy["strict_operation_count"], 34)
            response_policy = _audit_internal_write_response_contract_policy(client.app)
            self.assertTrue(response_policy["all_unsafe_operations_strict"])
            self.assertEqual(response_policy["strict_operation_count"], 34)
            for operation_id, path in cases.items():
                with self.subTest(operation_id=operation_id):
                    model = _request_model_for_operation(operation_id)
                    self.assertIsNotNone(model)
                    self.assertFalse(model.model_json_schema()["additionalProperties"])
                    response = client.post(path, json={"unexpected_field": "must be rejected"})
                    self.assertEqual(response.status_code, 400)
                    errors = response.json()["detail"]["errors"]
                    self.assertTrue(
                        any(
                            error.get("type") == "extra_forbidden"
                            and error.get("loc", [])[-1] == "unexpected_field"
                            for error in errors
                        )
                    )
                    route_schema = client.app.openapi()["paths"][path.replace(
                        "PF-STRICT", "{project_fact_id}"
                    ).replace(
                        "OPP-STRICT", "{opportunity_id}"
                    )]["post"]
                    request_schema = route_schema["requestBody"]["content"][
                        "application/json"
                    ]["schema"]
                    request_ref = request_schema.get("$ref") or request_schema.get(
                        "anyOf", [{}]
                    )[0].get("$ref")
                    response_ref = route_schema["responses"]["200"]["content"][
                        "application/json"
                    ]["schema"]["$ref"]
                    components = client.app.openapi()["components"]["schemas"]
                    self.assertFalse(
                        components[request_ref.rsplit("/", 1)[-1]]["additionalProperties"]
                    )
                    self.assertFalse(
                        components[response_ref.rsplit("/", 1)[-1]]["additionalProperties"]
                    )
            query_response = client.post(
                "/operator-console/autonomous-search-runs/clear?requested_by=forged-admin",
                json={},
            )
            self.assertEqual(query_response.status_code, 400)
            self.assertEqual(
                query_response.json()["detail"]["code"],
                "WRITE_QUERY_PARAMETERS_NOT_ALLOWED",
            )
        finally:
            client.app.state.storage_session.close()

    def test_streaming_body_limit_and_principal_expensive_rate_limit_fail_closed(self) -> None:
        with patch.dict(
            os.environ,
            {
                "KAKA_API_MAX_REQUEST_BODY_BYTES": "256",
                "KAKA_API_EXPENSIVE_REQUESTS_PER_MINUTE": "2",
                "KAKA_API_EXPENSIVE_CONCURRENCY_PER_PRINCIPAL": "1",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            reset_default_storage()
            app = create_app()
            client = TestClient(app)
            headers = {
                "content-type": "application/json",
                "x-kaka-test-operator-auth": "approved",
                "x-kaka-test-role": "admin",
                "x-kaka-test-principal-id": "sec005-principal",
            }
            oversized = client.post(
                "/operator-console/autonomous-opportunity-search",
                headers=headers,
                content=iter([b'{"query":"', b"x" * 300, b'"}']),
            )
            accepted_one = client.post(
                "/operator-console/autonomous-opportunity-search",
                headers=headers,
                json={"async_execution": True},
            )
            accepted_two = client.post(
                "/operator-console/autonomous-opportunity-search",
                headers=headers,
                json={"async_execution": True},
            )
            limited = client.post(
                "/operator-console/autonomous-opportunity-search",
                headers=headers,
                json={"async_execution": True},
            )
            health = client.get("/healthz")

            self.assertEqual(oversized.status_code, 413, oversized.text)
            self.assertTrue(oversized.json()["detail"]["streaming_count_enforced"])
            self.assertEqual(accepted_one.status_code, 200, accepted_one.text)
            self.assertEqual(accepted_two.status_code, 200, accepted_two.text)
            self.assertEqual(accepted_one.headers["x-kaka-ratelimit-limit"], "2")
            self.assertEqual(limited.status_code, 429, limited.text)
            self.assertEqual(
                limited.json()["detail"]["code"],
                "EXPENSIVE_REQUEST_RATE_LIMITED",
            )
            self.assertIn("retry-after", limited.headers)
            self.assertTrue(health.json()["streaming_request_body_limit_ready"])
            self.assertTrue(health.json()["expensive_request_rate_limit_ready"])
            app.state.storage_session.close()
        get_settings.cache_clear()
        reset_default_storage()

    def test_expensive_request_limiter_rejects_concurrent_work_without_consuming_rate(self) -> None:
        limiter = _ExpensiveRequestLimiter(
            requests_per_minute=3,
            concurrency_per_principal=1,
            time_factory=lambda: 100.0,
        )

        first = limiter.acquire("tenant:principal:expensive-write")
        concurrent = limiter.acquire("tenant:principal:expensive-write")
        limiter.release("tenant:principal:expensive-write")
        after_release = limiter.acquire("tenant:principal:expensive-write")

        self.assertTrue(first["accepted"])
        self.assertFalse(concurrent["accepted"])
        self.assertEqual(
            concurrent["reason"],
            "EXPENSIVE_REQUEST_CONCURRENCY_LIMITED",
        )
        self.assertTrue(after_release["accepted"])

    def test_network_roles_and_object_approval_are_separate_from_authentication(self) -> None:
        chain = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = chain["stage6"]
        stage7 = chain["stage7"]
        persist_stage_bundle(stage6)
        persist_stage_bundle(stage7)
        project_id = str(stage6.record("project_fact").get("project_id"))
        project_fact_id = str(stage6.record("project_fact").get("project_fact_id"))
        opportunity_id = str(stage7.record("saleable_opportunity").get("opportunity_id"))
        leadpack_package = copy.deepcopy(stage7.inputs["leadpack_delivery_package"])
        principals = [
            {"principal_id": "owner-1", "role": "owner", "token": "owner-token-00000001"},
            {"principal_id": "operator-1", "role": "operator", "token": "operator-token-0001"},
            {"principal_id": "operator-2", "role": "operator", "token": "operator-token-0002"},
            {"principal_id": "reviewer-1", "role": "reviewer", "token": "reviewer-token-0001"},
            {"principal_id": "admin-1", "role": "admin", "token": "admin-token-0000001"},
        ]

        async def exercise(app: object) -> dict[str, httpx.Response]:
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://kaka.internal",
            ) as client:
                operator_headers = {"Authorization": "Bearer operator-token-0001"}
                other_operator_headers = {"Authorization": "Bearer operator-token-0002"}
                owner_headers = {"Authorization": "Bearer owner-token-00000001"}
                reviewer_headers = {"Authorization": "Bearer reviewer-token-0001"}
                admin_headers = {"Authorization": "Bearer admin-token-0000001"}
                health = await client.get("/healthz")
                session = await client.get("/internal/auth/session", headers=operator_headers)
                owner_session = await client.get("/internal/auth/session", headers=owner_headers)
                operator_source_capture = await client.post(
                    "/operator-console/real-source-runs",
                    headers=operator_headers,
                    json={},
                )
                bound_operator_action = await client.post(
                    f"/review-report-workbench/{project_fact_id}/operator-actions",
                    headers=operator_headers,
                    json={
                        "project_id": project_id,
                        "action_id": "stage6_return_for_revision",
                        "button_flow_id": "submit_stage6_return_for_revision",
                        "reason": "authenticated actor must own the audit event",
                    },
                )
                forged_operator_action = await client.post(
                    f"/review-report-workbench/{project_fact_id}/operator-actions",
                    headers=operator_headers,
                    json={
                        "project_id": project_id,
                        "action_id": "stage6_return_for_revision",
                        "button_flow_id": "submit_stage6_return_for_revision",
                        "reason": "request identity fields must be rejected",
                        "requested_by_role": "admin",
                        "requested_by": "forged-admin",
                    },
                )
                bound_clear_action = await client.post(
                    "/operator-console/autonomous-search-runs/clear",
                    headers=operator_headers,
                    json={
                        "clear_scope": "local_test_autonomous_search_runs_only",
                        "explicit_operator_action": True,
                    },
                )
                forged_clear_action = await client.post(
                    "/operator-console/autonomous-search-runs/clear",
                    headers=operator_headers,
                    json={
                        "requested_by_role": "admin",
                        "requested_by": "forged-admin",
                    },
                )
                before_approval = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=operator_headers,
                )
                reviewer_write = await client.post(
                    "/operator-console/autonomous-opportunity-search",
                    headers=reviewer_headers,
                    json={},
                )
                reviewer_stage8_write = await client.post(
                    "/contact-targets/compliance-check",
                    headers=reviewer_headers,
                    json={},
                )
                reviewer_stage9_write = await client.post(
                    "/orders",
                    headers=reviewer_headers,
                    json={},
                )
                reviewer_request = await client.post(
                    "/internal/approvals/requests",
                    headers=reviewer_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": opportunity_id,
                        "action": "internal_preview_download",
                        "reason": "reviewer must not request",
                    },
                )
                requested = await client.post(
                    "/internal/approvals/requests",
                    headers=operator_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": opportunity_id,
                        "action": "internal_preview_download",
                        "reason": "internal acceptance download",
                    },
                )
                request_id = str(requested.json()["request_id"])
                operator_decision = await client.post(
                    f"/internal/approvals/requests/{request_id}/decision",
                    headers=operator_headers,
                    json={"decision": "APPROVED", "reason": "cannot self approve"},
                )
                decided = await client.post(
                    f"/internal/approvals/requests/{request_id}/decision",
                    headers=reviewer_headers,
                    json={"decision": "APPROVED", "reason": "reviewed masking policy"},
                )
                replayed_decision = await client.post(
                    f"/internal/approvals/requests/{request_id}/decision",
                    headers=reviewer_headers,
                    json={"decision": "REJECTED", "reason": "decision replay must fail"},
                )
                duplicate_active_request = await client.post(
                    "/internal/approvals/requests",
                    headers=operator_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": opportunity_id,
                        "action": "internal_preview_download",
                        "reason": "active approval must not be replaced",
                    },
                )
                missing_resource_request = await client.post(
                    "/internal/approvals/requests",
                    headers=operator_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": "OPP-DOES-NOT-EXIST",
                        "action": "internal_preview_download",
                        "reason": "missing objects cannot be pre-approved",
                    },
                )
                reviewer_download = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=reviewer_headers,
                )
                other_operator_download = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=other_operator_headers,
                )
                operator_download = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=operator_headers,
                )
                readback = await client.get(
                    f"/internal/approvals/requests/{request_id}",
                    headers=operator_headers,
                )
                changed_package = copy.deepcopy(leadpack_package)
                changed_package["package_manifest"]["evidence_items"][0][
                    "masking_policy"
                ] = "blocked_after_approval"
                LeadpackDeliveryPackageRepository().save(changed_package)
                stale_package_download = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=operator_headers,
                )
                LeadpackDeliveryPackageRepository().save(leadpack_package)
                revoked = await client.post(
                    f"/internal/approvals/requests/{request_id}/revoke",
                    headers=reviewer_headers,
                    json={"reason": "revoke before masking policy re-review"},
                )
                after_revoke_download = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=operator_headers,
                )
                requested_again = await client.post(
                    "/internal/approvals/requests",
                    headers=operator_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": opportunity_id,
                        "action": "internal_preview_download",
                        "reason": "request again after explicit revocation",
                    },
                )
                approved_again = await client.post(
                    f"/internal/approvals/requests/{requested_again.json()['request_id']}/decision",
                    headers=admin_headers,
                    json={"decision": "APPROVED", "reason": "admin independently re-reviewed"},
                )
                changed_opportunity = dict(stage7.record("saleable_opportunity").data)
                changed_opportunity["crm_owner_state"] = "ASSIGNED"
                SaleableOpportunityRepository().save(changed_opportunity)
                stale_download = await client.get(
                    f"/customer-artifact-portal-download/{opportunity_id}",
                    headers=operator_headers,
                )
                admin_request = await client.post(
                    "/internal/approvals/requests",
                    headers=admin_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": opportunity_id,
                        "action": "internal_preview_download",
                        "reason": "separation test request",
                    },
                )
                admin_self_decision = await client.post(
                    f"/internal/approvals/requests/{admin_request.json()['request_id']}/decision",
                    headers=admin_headers,
                    json={"decision": "APPROVED", "reason": "self decision must fail"},
                )
                admin_rejected = await client.post(
                    f"/internal/approvals/requests/{admin_request.json()['request_id']}/decision",
                    headers=reviewer_headers,
                    json={"decision": "REJECTED", "reason": "target needs revision"},
                )
                admin_retry_same_target = await client.post(
                    "/internal/approvals/requests",
                    headers=admin_headers,
                    json={
                        "resource_type": "opportunity",
                        "resource_id": opportunity_id,
                        "action": "internal_preview_download",
                        "reason": "unchanged rejected target cannot be resubmitted",
                    },
                )
            return {
                "health": health,
                "session": session,
                "owner_session": owner_session,
                "operator_source_capture": operator_source_capture,
                "bound_operator_action": bound_operator_action,
                "forged_operator_action": forged_operator_action,
                "bound_clear_action": bound_clear_action,
                "forged_clear_action": forged_clear_action,
                "before_approval": before_approval,
                "reviewer_write": reviewer_write,
                "reviewer_stage8_write": reviewer_stage8_write,
                "reviewer_stage9_write": reviewer_stage9_write,
                "reviewer_request": reviewer_request,
                "requested": requested,
                "operator_decision": operator_decision,
                "decided": decided,
                "replayed_decision": replayed_decision,
                "duplicate_active_request": duplicate_active_request,
                "missing_resource_request": missing_resource_request,
                "reviewer_download": reviewer_download,
                "other_operator_download": other_operator_download,
                "operator_download": operator_download,
                "readback": readback,
                "stale_package_download": stale_package_download,
                "revoked": revoked,
                "after_revoke_download": after_revoke_download,
                "requested_again": requested_again,
                "approved_again": approved_again,
                "stale_download": stale_download,
                "admin_self_decision": admin_self_decision,
                "admin_rejected": admin_rejected,
                "admin_retry_same_target": admin_retry_same_target,
            }

        with patch.dict(
            os.environ,
            {
                "KAKA_INTERNAL_API_PRINCIPALS_JSON": json.dumps(principals),
                "KAKA_INTERNAL_API_TOKEN": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            responses = asyncio.run(exercise(create_app()))

        session = responses["session"].json()
        self.assertTrue(responses["health"].json()["object_approval_workflow_ready"])
        self.assertTrue(responses["health"].json()["internal_write_policy_ready"])
        self.assertTrue(
            responses["health"].json()["internal_write_request_contracts_ready"]
        )
        self.assertTrue(
            responses["health"].json()["internal_write_response_contracts_ready"]
        )
        self.assertEqual(
            responses["health"].json()["classified_write_operation_count"],
            34,
        )
        self.assertEqual(
            responses["health"].json()["strict_write_request_operation_count"],
            34,
        )
        self.assertEqual(
            responses["health"].json()["strict_write_response_operation_count"],
            34,
        )
        self.assertEqual(session["role"], "operator")
        self.assertIn("object_approval_request", session["permissions"])
        self.assertFalse(session["approval_audit_confirmed"])
        self.assertFalse(session["authentication_implies_object_approval"])
        self.assertEqual(responses["owner_session"].json()["role"], "owner")
        self.assertIn("owner_source_capture", responses["owner_session"].json()["permissions"])
        self.assertNotIn("owner_source_capture", session["permissions"])
        self.assertEqual(responses["operator_source_capture"].status_code, 403)
        self.assertEqual(
            responses["operator_source_capture"].json()["detail"]["required_permission"],
            "owner_source_capture",
        )
        self.assertEqual(responses["bound_operator_action"].status_code, 200)
        bound_action = responses["bound_operator_action"].json()["action_result"]
        self.assertEqual(bound_action["requested_by"], "operator-1")
        self.assertEqual(bound_action["requested_by_role"], "operator")
        self.assertEqual(responses["forged_operator_action"].status_code, 400)
        self.assertEqual(responses["bound_clear_action"].status_code, 200)
        self.assertEqual(responses["forged_clear_action"].status_code, 400)
        clear_events = OperatorActionRepository().list(
            work_item_id="operator-autonomous-opportunity-search-run-clears"
        )
        self.assertEqual(clear_events[-1].requested_by, "operator-1")
        self.assertEqual(clear_events[-1].requested_by_role, "operator")
        self.assertEqual(responses["before_approval"].status_code, 403)
        self.assertEqual(
            responses["before_approval"].json()["detail"]["object_approval"]["state"],
            "NOT_REQUESTED",
        )
        self.assertEqual(responses["reviewer_write"].status_code, 403)
        self.assertEqual(responses["reviewer_stage8_write"].status_code, 403)
        self.assertEqual(
            responses["reviewer_stage8_write"].json()["detail"]["required_permission"],
            "internal_draft_write",
        )
        self.assertEqual(responses["reviewer_stage9_write"].status_code, 403)
        self.assertEqual(
            responses["reviewer_stage9_write"].json()["detail"]["required_permission"],
            "internal_sandbox_finance_write",
        )
        self.assertEqual(responses["reviewer_request"].status_code, 403)
        self.assertEqual(responses["requested"].status_code, 201)
        self.assertEqual(responses["operator_decision"].status_code, 403)
        self.assertEqual(responses["decided"].status_code, 200)
        self.assertTrue(responses["decided"].json()["approval_satisfied"])
        self.assertTrue(responses["decided"].json()["resource_version_matches"])
        self.assertTrue(responses["decided"].json()["approval_scope_matches"])
        self.assertEqual(responses["replayed_decision"].status_code, 409)
        self.assertEqual(responses["duplicate_active_request"].status_code, 409)
        self.assertEqual(responses["missing_resource_request"].status_code, 404)
        self.assertEqual(responses["reviewer_download"].status_code, 403)
        self.assertEqual(responses["other_operator_download"].status_code, 403)
        self.assertIn(
            "approval_subject_matches",
            responses["other_operator_download"].json()["detail"]["blocked_reasons"],
        )
        self.assertEqual(responses["operator_download"].status_code, 200)
        self.assertEqual(responses["readback"].status_code, 200)
        self.assertEqual(responses["readback"].json()["state"], "APPROVED")
        self.assertNotEqual(
            responses["readback"].json()["requested_by"],
            responses["readback"].json()["reviewer"],
        )
        self.assertEqual(responses["stale_package_download"].status_code, 403)
        self.assertIn(
            "object_approval_confirmed",
            responses["stale_package_download"].json()["detail"]["blocked_reasons"],
        )
        self.assertEqual(responses["revoked"].status_code, 200)
        self.assertEqual(responses["revoked"].json()["state"], "REVOKED")
        self.assertFalse(responses["revoked"].json()["approval_satisfied"])
        self.assertEqual(responses["after_revoke_download"].status_code, 403)
        self.assertEqual(responses["requested_again"].status_code, 201)
        self.assertNotEqual(
            responses["requested_again"].json()["request_id"],
            responses["requested"].json()["request_id"],
        )
        self.assertEqual(responses["approved_again"].status_code, 200)
        self.assertTrue(responses["approved_again"].json()["approval_satisfied"])
        self.assertEqual(responses["approved_again"].json()["reviewer"], "admin-1")
        self.assertEqual(responses["stale_download"].status_code, 403)
        self.assertFalse(
            responses["stale_download"].json()["detail"]["object_approval"][
                "authentication_implies_approval"
            ]
        )
        self.assertEqual(responses["admin_self_decision"].status_code, 403)
        self.assertEqual(
            responses["admin_self_decision"].json()["detail"]["code"],
            "APPROVAL_SEPARATION_OF_DUTIES_REQUIRED",
        )
        self.assertEqual(responses["admin_rejected"].status_code, 200)
        self.assertEqual(responses["admin_rejected"].json()["state"], "REJECTED")
        self.assertEqual(responses["admin_retry_same_target"].status_code, 409)

    def test_browser_session_supports_navigation_csrf_and_logout(self) -> None:
        async def exercise(app: object) -> dict[str, httpx.Response]:
            transport = httpx.ASGITransport(
                app=app,
                client=("127.0.0.1", 12345),
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://kaka.internal",
                follow_redirects=False,
            ) as client:
                missing_page = await client.get("/operator-console")
                missing_api = await client.get("/operator-console/readiness")
                login = await client.get(missing_page.headers["location"])
                invalid = await client.post(
                    "/internal/auth/session",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                created = await client.post(
                    "/internal/auth/session",
                    headers={"Authorization": "Bearer test-internal-token"},
                )
                csrf_token = str(created.json()["csrf_token"])
                session_readback = await client.get("/internal/auth/session")
                operator_page = await client.get("/operator-console")
                missing_csrf = await client.delete("/internal/auth/session")
                wrong_csrf = await client.delete(
                    "/internal/auth/session",
                    headers={"x-kaka-csrf-token": "wrong-csrf"},
                )
                logout = await client.delete(
                    "/internal/auth/session",
                    headers={"x-kaka-csrf-token": csrf_token},
                )
                after_logout = await client.get("/operator-console")
            return {
                "missing_page": missing_page,
                "missing_api": missing_api,
                "login": login,
                "invalid": invalid,
                "created": created,
                "session_readback": session_readback,
                "operator_page": operator_page,
                "missing_csrf": missing_csrf,
                "wrong_csrf": wrong_csrf,
                "logout": logout,
                "after_logout": after_logout,
            }

        with patch.dict(
            os.environ,
            {
                "KAKA_INTERNAL_API_TOKEN": "test-internal-token",
                "KAKA_INTERNAL_API_COOKIE_SECURE": "true",
                "KAKA_INTERNAL_API_SESSION_TTL_SECONDS": "3600",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            responses = asyncio.run(exercise(create_app()))

        self.assertEqual(responses["missing_page"].status_code, 303)
        self.assertTrue(responses["missing_page"].headers["location"].startswith("/internal/login?next="))
        self.assertNotIn("test-internal-token", responses["missing_page"].headers["location"])
        self.assertEqual(responses["missing_api"].status_code, 401)
        self.assertEqual(responses["login"].status_code, 200)
        self.assertIn('type="password"', responses["login"].text)
        self.assertNotIn("test-internal-token", responses["login"].text)
        login_csp = responses["login"].headers["content-security-policy"]
        self.assertIn("frame-ancestors 'none'", login_csp)
        self.assertIn("script-src 'nonce-", login_csp)
        self.assertNotIn("'unsafe-inline'", login_csp)
        self.assertEqual(responses["login"].headers["x-frame-options"], "DENY")
        self.assertEqual(responses["login"].headers["x-content-type-options"], "nosniff")
        self.assertEqual(responses["invalid"].status_code, 401)

        created = responses["created"]
        self.assertEqual(created.status_code, 200)
        self.assertNotIn("test-internal-token", created.text)
        set_cookie = created.headers["set-cookie"].lower()
        self.assertIn(f"{INTERNAL_BROWSER_SESSION_COOKIE}=", set_cookie)
        self.assertIn("httponly", set_cookie)
        self.assertIn("secure", set_cookie)
        self.assertIn("samesite=strict", set_cookie)
        self.assertIn("max-age=3600", set_cookie)

        session_readback = responses["session_readback"].json()
        self.assertEqual(responses["session_readback"].status_code, 200)
        self.assertEqual(session_readback["auth_method"], "browser_session")
        self.assertEqual(session_readback["csrf_token"], created.json()["csrf_token"])
        self.assertEqual(responses["operator_page"].status_code, 200)
        self.assertIn("x-kaka-csrf-token", responses["operator_page"].text)
        self.assertIn("退出内部会话", responses["operator_page"].text)
        self.assertNotIn("test-internal-token", responses["operator_page"].text)

        self.assertEqual(responses["missing_csrf"].status_code, 403)
        self.assertEqual(
            responses["missing_csrf"].json()["detail"]["code"],
            "BROWSER_SESSION_CSRF_REQUIRED",
        )
        self.assertEqual(responses["wrong_csrf"].status_code, 403)
        self.assertEqual(responses["logout"].status_code, 200)
        self.assertTrue(responses["logout"].json()["session_deleted"])
        self.assertEqual(responses["after_logout"].status_code, 303)

    def test_browser_session_rejects_tampering_and_expiry(self) -> None:
        with patch("api.main.time.time", return_value=1_000):
            cookie, payload = _encode_browser_session(
                configured_token="test-internal-token",
                principal_id="operator-1",
                role="internal_operator",
                ttl_seconds=60,
            )
        with patch("api.main.time.time", return_value=1_030):
            self.assertEqual(
                _decode_browser_session(
                    cookie,
                    configured_token="test-internal-token",
                    max_ttl_seconds=60,
                )["csrf_token"],
                payload["csrf_token"],
            )
            self.assertIsNone(
                _decode_browser_session(
                    f"{cookie}tampered",
                    configured_token="test-internal-token",
                    max_ttl_seconds=60,
                )
            )
            self.assertIsNone(
                _decode_browser_session(
                    cookie,
                    configured_token="rotated-token",
                    max_ttl_seconds=60,
                )
            )
        with patch("api.main.time.time", return_value=1_061):
            self.assertIsNone(
                _decode_browser_session(
                    cookie,
                    configured_token="test-internal-token",
                    max_ttl_seconds=60,
                )
            )

    def test_stage9_http_create_uses_formal_schema_and_persists_idempotently(self) -> None:
        stage9 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage9"]
        client = TestClient(create_app())
        schema = client.get("/openapi.json").json()
        cases = (
            ("order_record", "/orders", "order_id", "order_create_request", "order_create_response"),
            ("payment_record", "/payments", "payment_id", "payment_create_request", "payment_create_response"),
            ("delivery_record", "/deliveries", "delivery_id", "delivery_create_request", "delivery_create_response"),
            (
                "opportunity_outcome_event",
                "/opportunity-outcomes",
                "outcome_event_id",
                "opportunity_outcome_create_request",
                "opportunity_outcome_create_response",
            ),
            (
                "governance_feedback_event",
                "/governance-feedback-events",
                "governance_feedback_event_id",
                "governance_feedback_create_request",
                "governance_feedback_create_response",
            ),
        )
        for object_type, path, id_field, request_ref, response_ref in cases:
            with self.subTest(object_type=object_type):
                operation = schema["paths"][path]["post"]
                request_schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]
                model_name = request_schema_ref["anyOf"][0]["$ref"].rsplit("/", 1)[-1]
                formal_schema = schema["components"]["schemas"][model_name]
                payload = {
                    key: value
                    for key, value in dict(stage9.record(object_type).data).items()
                    if key in formal_schema["properties"]
                }

                self.assertEqual(operation["x-kaka-request-schema-ref"], request_ref)
                self.assertEqual(operation["x-kaka-response-schema-ref"], response_ref)
                self.assertTrue(set(formal_schema["required"]).issubset(payload))
                self.assertFalse(formal_schema["additionalProperties"])

                invalid = client.post(path, json={id_field: f"{object_type}-INCOMPLETE"})
                created = client.post(path, json=payload)
                replayed = client.post(path, json=payload)

                self.assertEqual(invalid.status_code, 400)
                self.assertEqual(invalid.json()["detail"]["code"], "REQUEST_VALIDATION_FAILED")
                self.assertEqual(created.status_code, 200, created.text)
                self.assertTrue(created.json()["persistence"]["created"])
                self.assertEqual(
                    created.json()["persistence"]["persistence_state"],
                    "PERSISTED_CREATED",
                )
                self.assertEqual(replayed.status_code, 200, replayed.text)
                self.assertTrue(replayed.json()["persistence"]["idempotent_replay"])

    def test_get_settings_consumes_storage_backend_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "postgres",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                settings = get_settings()

        self.assertEqual(settings.storage_backend, "postgres")
        self.assertEqual(settings.storage_scope, "shared")
        self.assertEqual(settings.storage_runtime_mode, "stable-default")

    def test_create_app_mounts_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "json-file",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "KAKA_STORAGE_SCOPE": "process",
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()

        self.assertEqual(app.state.settings.storage_backend, "json-file")
        self.assertEqual(app.state.settings.storage_path_optional, str(explicit_path))
        self.assertEqual(app.state.settings.storage_scope, "process")
        self.assertEqual(app.state.settings.storage_runtime_mode, "explicit-path")
        self.assertEqual(app.state.storage_session.storage_backend, "json-file")
        self.assertEqual(app.state.storage_session.storage_path, explicit_path)
        storage_bootstrap = app.state.storage_bootstrap
        self.assertEqual(storage_bootstrap["storage_backend"], "json-file")
        self.assertEqual(storage_bootstrap["storage_path"], str(explicit_path))
        self.assertEqual(storage_bootstrap["storage_path_optional"], str(explicit_path))
        self.assertFalse(storage_bootstrap["storage_database_url_configured"])
        self.assertIsNone(storage_bootstrap["storage_schema_revision"])
        self.assertEqual(
            storage_bootstrap["required_storage_schema_revision"],
            "20260717_0002",
        )
        self.assertTrue(storage_bootstrap["storage_schema_revision_ready"])
        self.assertIsNone(storage_bootstrap["storage_database_url_redacted"])
        self.assertEqual(storage_bootstrap["storage_scope"], "process")
        self.assertEqual(storage_bootstrap["storage_runtime_mode"], "explicit-path")
        self.assertEqual(storage_bootstrap["queue_backend"], "storage")
        self.assertEqual(storage_bootstrap["worker_runtime"], "internal-storage-worker")
        self.assertEqual(storage_bootstrap["active_object_storage_backend"], "local-filesystem")
        self.assertEqual(storage_bootstrap["object_storage_backend"], "local-filesystem")
        self.assertEqual(
            storage_bootstrap["object_storage_path"],
            str(explicit_path.parent / "object-storage"),
        )
        self.assertTrue(storage_bootstrap["worker_queue_bootstrap"]["durable_queue_enabled"])
        self.assertTrue(storage_bootstrap["worker_queue_bootstrap"]["worker_lease_enabled"])
        self.assertFalse(storage_bootstrap["worker_queue_bootstrap"]["external_queue_connection_enabled"])
        self.assertIn("backup_restore_readiness", storage_bootstrap)
        self.assertIn("rollback_readiness", storage_bootstrap)
        self.assertTrue(storage_bootstrap["backup_restore_readiness"]["backup_manifest_enabled"])
        self.assertTrue(storage_bootstrap["backup_restore_readiness"]["restore_dry_run_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["destructive_restore_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["external_backup_service_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["external_service_connection_enabled"])
        self.assertFalse(storage_bootstrap["backup_restore_readiness"]["migration_execution_enabled"])
        self.assertFalse(storage_bootstrap["rollback_readiness"]["rollback_execution_enabled"])
        self.assertFalse(storage_bootstrap["rollback_readiness"]["destructive_restore_enabled"])
        self.assertTrue(storage_bootstrap["rollback_readiness"]["approval_required"])
        self.assertTrue(storage_bootstrap["rollback_readiness"]["audit_required"])
        self.assertIn("monitoring_alerting_readiness", storage_bootstrap)
        self.assertIn("monitoring_readiness", storage_bootstrap)
        self.assertIn("alert_rule_catalog", storage_bootstrap)
        self.assertIn("alert_readiness", storage_bootstrap)
        self.assertIn("incident_readiness", storage_bootstrap)
        self.assertIn("production_slo_incident_readiness", storage_bootstrap)
        self.assertIn("production_slo_readiness", storage_bootstrap)
        self.assertIn("production_monitoring_dashboard", storage_bootstrap)
        self.assertIn("production_alert_rule_catalog", storage_bootstrap)
        self.assertIn("simulated_alert_evaluation_readback", storage_bootstrap)
        self.assertIn("production_incident_runbook", storage_bootstrap)
        self.assertIn("production_drill_evidence", storage_bootstrap)
        self.assertIn("suspended_state_operation_readback", storage_bootstrap)
        self.assertEqual(
            storage_bootstrap["monitoring_readiness"]["readiness_state"],
            "INTERNAL_READBACK_READY",
        )
        self.assertIn("storage.backend", storage_bootstrap["monitoring_readiness"]["component_ids"])
        self.assertIn("queue.worker", storage_bootstrap["monitoring_readiness"]["component_ids"])
        self.assertFalse(storage_bootstrap["alert_readiness"]["notification_enabled"])
        self.assertFalse(storage_bootstrap["alert_readiness"]["live_dispatch_enabled"])
        self.assertGreaterEqual(len(storage_bootstrap["alert_rule_catalog"]), 6)
        self.assertEqual(
            storage_bootstrap["incident_readiness"]["incident_state"],
            "MANUAL_OWNER_ACTION_READY",
        )
        self.assertTrue(storage_bootstrap["incident_readiness"]["manual_owner_action_required"])
        self.assertFalse(storage_bootstrap["incident_readiness"]["incident_automation_enabled"])
        self.assertFalse(storage_bootstrap["incident_readiness"]["external_paging_enabled"])
        production = storage_bootstrap["production_slo_incident_readiness"]
        self.assertEqual(production["target_capability_state"], "PRODUCTION_READY")
        self.assertTrue(production["repository_backed_readback"])
        self.assertTrue(production["validation"]["valid"])
        self.assertTrue(
            all(
                evaluation["alert_fired"]
                for evaluation in production["simulated_alert_evaluation_readback"]
            )
        )
        self.assertFalse(production["controlled_opening_requirements"]["real_alert_dispatch_enabled"])
        self.assertFalse(production["controlled_opening_requirements"]["incident_automation_enabled"])
        self.assertFalse(production["controlled_opening_requirements"]["destructive_restore_enabled"])
        self.assertFalse(production["controlled_opening_requirements"]["rollback_execution_enabled"])
        approved_drill = storage_bootstrap["approved_production_live_dependency_drill"]
        self.assertEqual(approved_drill["controlled_drill_state"], "NOT_REQUESTED")
        self.assertFalse(approved_drill["approved_production_live_dependency_drill_enabled"])
        self.assertFalse(approved_drill["container_stack_drill_record"]["docker_compose_up_executed"])
        self.assertFalse(approved_drill["alert_dispatch_drill_record"]["real_alert_dispatch_enabled"])
        self.assertFalse(approved_drill["backup_restore_drill_record"]["destructive_restore_enabled"])
        self.assertFalse(approved_drill["rollback_drill_record"]["rollback_execution_enabled"])
        self.assertFalse(approved_drill["incident_manual_execution_record"]["incident_automation_enabled"])
        self.assertIn("platform_infra_readiness", storage_bootstrap)
        self.assertIn("provider_adapter_bootstrap", storage_bootstrap)
        provider_bootstrap = storage_bootstrap["provider_adapter_bootstrap"]
        self.assertEqual(provider_bootstrap["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(provider_bootstrap["provider_adapter_live_execution_enabled"])
        self.assertFalse(provider_bootstrap["provider_adapter_real_provider_call_enabled"])
        self.assertEqual(
            set(provider_bootstrap[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["families"]),
            set(PROVIDER_FAMILIES),
        )

        readiness = storage_bootstrap["platform_infra_readiness"]
        self.assertEqual(readiness["active_backend"], "json-file")
        self.assertEqual(
            [entry["backend"] for entry in readiness["executable_backends"] if entry["executable"]],
            ["json-file", "sqlite"],
        )
        executable_by_backend = {
            entry["backend"]: entry
            for entry in readiness["executable_backends"]
        }
        self.assertTrue(executable_by_backend["json-file"]["configured"])
        self.assertFalse(executable_by_backend["sqlite"]["configured"])
        self.assertEqual(set(executable_by_backend), {"json-file", "sqlite", "sqlalchemy", "postgresql"})
        self.assertEqual(executable_by_backend["sqlalchemy"]["readiness_state"], "NOT_CONFIGURED")
        self.assertEqual(executable_by_backend["postgresql"]["readiness_state"], "NOT_CONFIGURED")
        reserved_by_backend = {
            entry["backend"]: entry
            for entry in readiness["reserved_backends"]
        }
        self.assertEqual(set(reserved_by_backend), RESERVED_INFRA_BACKENDS)
        for backend, entry in reserved_by_backend.items():
            self.assertFalse(entry["executable"], backend)
            self.assertIn(entry["readiness_state"], RESERVED_OR_NOT_CONFIGURED, backend)
        self.assertFalse(readiness["postgresql_readiness"]["executable"])
        self.assertFalse(readiness["postgresql_readiness"]["database_url_configured"])
        self.assertFalse(readiness["sqlalchemy_readiness"]["executable"])
        self.assertFalse(readiness["sqlalchemy_readiness"]["database_url_configured"])
        self.assertEqual(readiness["migration_readiness"]["readiness_state"], "CLI_AVAILABLE")
        self.assertTrue(readiness["migration_readiness"]["manual_migration_cli_available"])
        self.assertFalse(readiness["migration_readiness"]["app_bootstrap_auto_migration_enabled"])
        self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
        self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["queue_readiness"]["internal_durable_queue"]["repository_backed"])
        self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
        self.assertEqual(readiness["worker_runtime_readiness"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["worker_runtime_readiness"]["heartbeat_persistence_enabled"])
        self.assertTrue(readiness["worker_runtime_readiness"]["dead_letter_persistence_enabled"])
        self.assertFalse(readiness["worker_runtime_readiness"]["stage1_scheduler_enabled"])
        self.assertEqual(readiness["object_storage_readiness"]["active_backend"], "local-filesystem")
        self.assertEqual(readiness["object_storage_readiness"]["readiness_state"], "EXECUTABLE")
        self.assertTrue(readiness["object_storage_readiness"]["local_filesystem"]["executable"])
        self.assertTrue(
            readiness["object_storage_readiness"]["snapshot_durability"][
                "manifest_repository_backed"
            ]
        )
        self.assertTrue(
            readiness["object_storage_readiness"]["snapshot_durability"][
                "readback_replay_enabled"
            ]
        )
        self.assertFalse(readiness["object_storage_readiness"]["connection_enabled"])
        self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
        self.assertEqual(
            readiness["backup_restore_readiness"],
            storage_bootstrap["backup_restore_readiness"],
        )
        self.assertEqual(
            readiness["rollback_readiness"],
            storage_bootstrap["rollback_readiness"],
        )
        self.assertTrue(readiness["backup_restore_readiness"]["manifest_hash_enabled"])
        self.assertFalse(readiness["backup_restore_readiness"]["restore_execution_enabled"])
        self.assertFalse(readiness["backup_restore_readiness"]["active_storage_write_enabled"])
        self.assertFalse(readiness["rollback_readiness"]["rollback_execution_enabled"])
        self.assertEqual(
            readiness["monitoring_alerting_readiness"],
            storage_bootstrap["monitoring_alerting_readiness"],
        )
        self.assertEqual(readiness["monitoring_readiness"], storage_bootstrap["monitoring_readiness"])
        self.assertEqual(readiness["alert_readiness"], storage_bootstrap["alert_readiness"])
        self.assertEqual(readiness["alert_rule_catalog"], storage_bootstrap["alert_rule_catalog"])
        self.assertEqual(readiness["incident_readiness"], storage_bootstrap["incident_readiness"])
        self.assertEqual(
            readiness["production_slo_incident_readiness"],
            storage_bootstrap["production_slo_incident_readiness"],
        )
        self.assertEqual(
            readiness["production_slo_readiness"],
            storage_bootstrap["production_slo_readiness"],
        )
        self.assertIn("local_stack_readiness", storage_bootstrap)
        self.assertEqual(storage_bootstrap["local_stack_readiness"], readiness["compose_readiness"])
        self.assertTrue(readiness["compose_readiness"]["dockerfile_present"])
        self.assertTrue(readiness["compose_readiness"]["compose_file_present"])
        self.assertTrue(readiness["compose_readiness"]["docker_compose_config_present"])
        self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
        self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
        self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
        self.assertEqual(
            readiness["compose_readiness"]["service_dependency_summary"]["postgres"]["readiness_state"],
            "RESERVED_NOT_LIVE",
        )
        self.assertTrue(
            readiness["compose_readiness"]["service_dependency_summary"]["app-postgres"][
                "migration_required_before_bootstrap"
            ]
        )
        self.assertFalse(
            readiness["compose_readiness"]["service_dependency_summary"]["app-postgres"][
                "external_service_connection_enabled"
            ]
        )
        self.assertFalse(
            readiness["compose_readiness"]["service_dependency_summary"]["redis"][
                "external_service_connection_enabled"
            ]
        )
        self.assertFalse(
            readiness["compose_readiness"]["service_dependency_summary"]["minio"][
                "external_service_connection_enabled"
            ]
        )
        self.assertTrue(readiness["backend_policy"]["unsupported_backend_fast_fail"])
        self.assertTrue(readiness["backend_policy"]["missing_database_url_fast_fail"])
        self.assertTrue(readiness["backend_policy"]["no_silent_fallback"])
        self.assertTrue(readiness["backend_policy"]["no_migration_execution"])
        self.assertTrue(readiness["backend_policy"]["no_external_service_connection"])
        self.assertTrue(readiness["backend_policy"]["readback_only"])
        self.assertFalse(readiness["backend_policy"]["runtime_behavior_changed"])

    def test_create_app_mounts_sqlite_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "sqlite",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()
                try:
                    self.assertEqual(app.state.settings.storage_backend, "sqlite")
                    self.assertEqual(app.state.storage_session.storage_backend, "sqlite")
                    self.assertEqual(app.state.storage_session.storage_path, explicit_path.with_suffix(".sqlite"))
                    storage_bootstrap = app.state.storage_bootstrap
                    self.assertEqual(storage_bootstrap["active_backend"], "sqlite")
                    self.assertEqual(storage_bootstrap["storage_backend"], "sqlite")
                    self.assertEqual(storage_bootstrap["storage_path"], str(explicit_path))
                    readiness = storage_bootstrap["platform_infra_readiness"]
                    self.assertEqual(readiness["active_backend"], "sqlite")
                    executable_by_backend = {
                        entry["backend"]: entry
                        for entry in readiness["executable_backends"]
                    }
                    self.assertEqual(set(executable_by_backend), {"json-file", "sqlite", "sqlalchemy", "postgresql"})
                    self.assertTrue(executable_by_backend["json-file"]["executable"])
                    self.assertFalse(executable_by_backend["json-file"]["configured"])
                    self.assertTrue(executable_by_backend["sqlite"]["executable"])
                    self.assertTrue(executable_by_backend["sqlite"]["configured"])
                    reserved_by_backend = {
                        entry["backend"]: entry
                        for entry in readiness["reserved_backends"]
                    }
                    self.assertEqual(set(reserved_by_backend), RESERVED_INFRA_BACKENDS)
                    self.assertFalse(readiness["postgresql_readiness"]["executable"])
                    self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
                    self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["active_storage_backend"], "sqlite")
                    self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
                    self.assertTrue(readiness["worker_runtime_readiness"]["suspend_resume_persistence_enabled"])
                    self.assertEqual(readiness["object_storage_readiness"]["readiness_state"], "EXECUTABLE")
                    self.assertTrue(
                        readiness["object_storage_readiness"]["snapshot_durability"][
                            "readback_replay_enabled"
                        ]
                    )
                    self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
                    self.assertTrue(readiness["backend_policy"]["unsupported_backend_fast_fail"])
                    self.assertTrue(readiness["backend_policy"]["no_silent_fallback"])
                    self.assertTrue(readiness["backend_policy"]["no_external_service_connection"])
                finally:
                    app.state.storage_session.close()

    def test_create_app_keeps_minio_object_storage_reserved_not_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_path = Path(tmp_dir) / "storage" / "custom-store.json"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "json-file",
                    "KAKA_STORAGE_PATH": str(explicit_path),
                    "KAKA_OBJECT_STORAGE_BACKEND": "minio",
                    "KAKA_OBJECT_STORAGE_PATH": str(Path(tmp_dir) / "objects"),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in ("KAKA_STORAGE_DATABASE_URL", "KAKA_STORAGE_SCOPE", "KAKA_STORAGE_TEST_ISOLATION"):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()

        readiness = app.state.storage_bootstrap["platform_infra_readiness"]
        object_readiness = readiness["object_storage_readiness"]
        self.assertEqual(app.state.storage_bootstrap["active_object_storage_backend"], "minio")
        self.assertEqual(object_readiness["active_backend"], "minio")
        self.assertEqual(object_readiness["readiness_state"], "RESERVED_NOT_LIVE")
        self.assertFalse(object_readiness["executable"])
        self.assertFalse(object_readiness["connection_enabled"])
        self.assertFalse(object_readiness["external_service_connection_enabled"])
        self.assertFalse(object_readiness["minio_connection_enabled"])
        self.assertFalse(object_readiness["s3_connection_enabled"])
        self.assertFalse(app.state.transport_bootstrap["controlled_opening_requirements"]["minio_connection_enabled"])
        reserved_by_backend = {
            entry["backend"]: entry
            for entry in readiness["reserved_backends"]
        }
        self.assertEqual(reserved_by_backend["minio"]["readiness_state"], "RESERVED_NOT_LIVE")

    def test_create_app_mounts_sqlalchemy_storage_bootstrap_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "storage" / "sqlalchemy-store.sqlite"
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "sqlalchemy",
                    "KAKA_STORAGE_DATABASE_URL": sqlalchemy_sqlite_url(database_path),
                    "LOCALAPPDATA": str(Path(tmp_dir) / "local-app-data"),
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()
                app = create_app()
                try:
                    storage_bootstrap = app.state.storage_bootstrap
                    readiness = storage_bootstrap["platform_infra_readiness"]
                    self.assertEqual(app.state.storage_session.storage_backend, "sqlalchemy")
                    self.assertEqual(app.state.storage_session.storage_path, database_path)
                    self.assertEqual(storage_bootstrap["active_backend"], "sqlalchemy")
                    self.assertEqual(storage_bootstrap["storage_backend"], "sqlalchemy")
                    self.assertTrue(storage_bootstrap["storage_database_url_configured"])
                    self.assertEqual(storage_bootstrap["storage_database_url_dialect"], "sqlite")
                    self.assertEqual(readiness["active_backend"], "sqlalchemy")
                    self.assertEqual(readiness["sqlalchemy_readiness"]["readiness_state"], "EXECUTABLE")
                    self.assertTrue(readiness["sqlalchemy_readiness"]["executable"])
                    self.assertTrue(readiness["sqlalchemy_readiness"]["configured"])
                    self.assertEqual(readiness["sqlalchemy_readiness"]["database_url_dialect"], "sqlite")
                    self.assertEqual(readiness["postgresql_readiness"]["readiness_state"], "NOT_CONFIGURED")
                    self.assertFalse(readiness["postgresql_readiness"]["configured"])
                    self.assertFalse(readiness["migration_readiness"]["migration_execution_enabled"])
                    self.assertEqual(readiness["queue_readiness"]["internal_durable_queue"]["active_storage_backend"], "sqlalchemy")
                    self.assertFalse(readiness["queue_readiness"]["external_service_connection_enabled"])
                    self.assertTrue(readiness["worker_runtime_readiness"]["retry_persistence_enabled"])
                    self.assertEqual(readiness["object_storage_readiness"]["readiness_state"], "EXECUTABLE")
                    self.assertTrue(readiness["object_storage_readiness"]["local_filesystem"]["executable"])
                    self.assertFalse(readiness["object_storage_readiness"]["external_service_connection_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["compose_runtime_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["container_execution_enabled"])
                    self.assertFalse(readiness["compose_readiness"]["docker_compose_up_executed"])
                    self.assertEqual(app.state.transport_bootstrap["storage_bootstrap"], storage_bootstrap)
                    self.assertEqual(app.state.transport_bootstrap["platform_infra_readiness"], readiness)
                    self.assertEqual(
                        app.state.transport_bootstrap["local_stack_readiness"],
                        readiness["compose_readiness"],
                    )
                    self.assertEqual(
                        app.state.transport_bootstrap["worker_queue_bootstrap"],
                        storage_bootstrap["worker_queue_bootstrap"],
                    )
                    self.assertTrue(app.state.transport_bootstrap["queue_worker_readiness"]["durable_queue_enabled"])
                finally:
                    app.state.storage_session.close()

    def test_create_app_exposes_single_transport_bootstrap_readback_projection(self) -> None:
        app = create_app()

        self.assertTrue(hasattr(app.state, "transport_bootstrap"))
        bootstrap = app.state.transport_bootstrap
        self.assertTrue(bootstrap["internal_only"])
        self.assertFalse(bootstrap["live_execution_enabled"])
        self.assertIn("provider_adapter_bootstrap", bootstrap)
        self.assertEqual(bootstrap["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertEqual(bootstrap["provider_reliability_state"], "APPROVAL_READY")
        self.assertEqual(bootstrap["provider_circuit_breaker_state"], "CLOSED")
        self.assertFalse(bootstrap["provider_adapter_suspended"])
        self.assertTrue(bootstrap["provider_status_replayable"])
        self.assertTrue(bootstrap["provider_reliability_summary"]["circuit_breaker_visible"])
        self.assertFalse(
            bootstrap["provider_adapter_bootstrap"]["provider_adapter_live_execution_enabled"]
        )
        self.assertFalse(
            bootstrap["provider_adapter_bootstrap"]["provider_adapter_real_provider_call_enabled"]
        )
        self.assertEqual(
            set(bootstrap[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["families"]),
            set(PROVIDER_FAMILIES),
        )
        self.assertEqual(
            app.state.provider_adapter_config_readback.payload["mode"],
            "SANDBOX_DRY_RUN_READBACK",
        )
        self.assertEqual(
            app.state.provider_adapter_config_readback.governed_state["provider_reliability_state"],
            "APPROVAL_READY",
        )
        model_assist_bootstrap = bootstrap["model_assist_governance_bootstrap"]
        self.assertEqual(model_assist_bootstrap["assist_mode"], "GOVERNED_ASSIST_READBACK")
        self.assertEqual(model_assist_bootstrap["provider_execution_surface"], "LOCAL_DETERMINISTIC_ASSIST")
        self.assertFalse(model_assist_bootstrap["real_model_provider_call_executed"])
        self.assertFalse(model_assist_bootstrap["formal_fact_write_enabled"])
        self.assertTrue(model_assist_bootstrap["human_review_required"])
        self.assertTrue(
            model_assist_bootstrap["controlled_opening_requirements"]["model_output_not_customer_conclusion"]
        )

        disabled_registry = bootstrap["stage1_to_stage5_transport_state"]
        self.assertEqual(disabled_registry, app.state.disabled_stage_transports)
        reserved_entry_plan = bootstrap["stage1_to_stage5_reserved_entry_plan"]
        self.assertEqual(set(reserved_entry_plan), {f"stage{stage_scope}" for stage_scope in range(1, 6)})
        for stage_scope in range(1, 6):
            stage_key = f"stage{stage_scope}"
            self.assertIn(stage_key, disabled_registry)
            self.assertEqual(len(disabled_registry[stage_key]), 1)
            transport_status = disabled_registry[stage_key][0]
            self.assertEqual(transport_status["stage_scope"], stage_scope)
            self.assertEqual(transport_status["availability_state"], "CONTROLLED_UNAVAILABLE")
            self.assertEqual(transport_status["transport_state"], "TRANSPORT_NOT_WIRED")
            self.assertFalse(transport_status["live_execution_enabled"])
            self.assertTrue(transport_status["internal_only"])
            self.assertEqual(
                reserved_entry_plan[stage_key],
                [
                    {
                        key: transport_status[key]
                        for key in RESERVED_ENTRY_PLAN_READBACK_KEYS
                    }
                ],
            )
            self.assertEqual(reserved_entry_plan[stage_key][0], expected_reserved_entry_plan(stage_scope))
            self.assertFalse(reserved_entry_plan[stage_key][0]["http_entry_enabled"])
            self.assertFalse(reserved_entry_plan[stage_key][0]["real_transport_enabled"])
            self.assertFalse(reserved_entry_plan[stage_key][0]["orchestrator_enabled"])

        mounted_operations = bootstrap["stage6_to_stage9_mounted_operations"]
        mounted_by_id = {operation["operationId"]: operation for operation in mounted_operations}
        expected_operations = {
            "runStage1ToStage6InternalOrchestration",
            "previewStage6ReviewReportWorkbench",
            "listSaleableOpportunities",
            "listContactTargets",
            "listOrders",
            "createOutreachPlan",
            "createOrder",
        }
        self.assertTrue(expected_operations.issubset(mounted_by_id))
        for operation_id in expected_operations:
            operation = mounted_by_id[operation_id]
            for key in (
                "stage_scope",
                "operationId",
                "method",
                "path",
                "surface_mode",
                "internal_only",
                "live_execution_enabled",
                "blocked_by_default",
            ):
                self.assertIn(key, operation)
            self.assertTrue(operation["internal_only"])
            self.assertFalse(operation["live_execution_enabled"])
            if operation["stage_scope"] in (7, 8, 9):
                self.assertEqual(operation["provider_adapter_mode"], "SANDBOX_DRY_RUN_READBACK")
                self.assertEqual(operation["provider_reliability_state"], "APPROVAL_READY")
                self.assertEqual(operation["provider_circuit_breaker_state"], "CLOSED")
                self.assertFalse(operation["provider_adapter_suspended"])
                self.assertFalse(operation["provider_adapter_live_execution_enabled"])
                self.assertFalse(operation["provider_adapter_real_provider_call_enabled"])
                self.assertIn(PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY, operation)

        orchestration_operation = mounted_by_id["runStage1ToStage6InternalOrchestration"]
        self.assertEqual(orchestration_operation["stage_scope"], 6)
        self.assertEqual(orchestration_operation["method"], "POST")
        self.assertEqual(orchestration_operation["path"], "/internal/stage1-6/orchestrations")
        self.assertEqual(
            orchestration_operation["accepted_payload_boundary"],
            "SANITIZED_OFFLINE_INTERNAL",
        )
        self.assertTrue(orchestration_operation["repository_backed_readback"])
        self.assertEqual(orchestration_operation["orchestrates_stage_scope"], "stage1_to_stage6")
        self.assertEqual(mounted_by_id["previewStage6ReviewReportWorkbench"]["stage_scope"], 6)
        self.assertEqual(mounted_by_id["listSaleableOpportunities"]["stage_scope"], 7)
        self.assertEqual(mounted_by_id["listContactTargets"]["stage_scope"], 8)
        self.assertIn("createPaymentRecord", mounted_by_id)
        self.assertIn("createDeliveryRecord", mounted_by_id)
        self.assertTrue(
            mounted_by_id["createPaymentRecord"]["payment_sandbox_provider_records"]["readback_ready"]
        )
        self.assertFalse(
            mounted_by_id["createPaymentRecord"]["payment_sandbox_provider_records"]["payment_capture_enabled"]
        )
        self.assertTrue(
            mounted_by_id["createDeliveryRecord"]["delivery_sandbox_provider_records"]["version_lock_enabled"]
        )
        self.assertFalse(
            mounted_by_id["createDeliveryRecord"]["delivery_sandbox_provider_records"]["real_delivery_enabled"]
        )
        self.assertFalse(
            mounted_by_id["createPaymentRecord"]["manual_refund_exception_record"][
                "automated_refund_enabled"
            ]
        )
        live_pilot_metadata = mounted_by_id["createPaymentRecord"]["payment_delivery_live_pilot"]
        self.assertEqual(
            live_pilot_metadata["readiness_scope"],
            "gated_small_sample_payment_delivery_live_pilot_readback",
        )
        self.assertFalse(live_pilot_metadata["batch_execution_enabled"])
        self.assertTrue(live_pilot_metadata["payment_approval_required"])
        self.assertTrue(live_pilot_metadata["delivery_approval_required"])
        self.assertTrue(live_pilot_metadata["finance_review_required"])
        self.assertTrue(live_pilot_metadata["operator_action_audit_required"])
        self.assertTrue(live_pilot_metadata["artifact_version_lock_required"])
        self.assertTrue(live_pilot_metadata["download_auth_required"])
        self.assertFalse(live_pilot_metadata["provider_call_enabled"])
        self.assertFalse(live_pilot_metadata["real_provider_call_enabled"])
        self.assertFalse(live_pilot_metadata["real_charge_attempted"])
        self.assertFalse(live_pilot_metadata["real_delivery_fulfillment_attempted"])
        self.assertFalse(live_pilot_metadata["real_refund_attempted"])
        self.assertFalse(live_pilot_metadata["automated_refund_enabled"])
        approved_execution_metadata = mounted_by_id["createPaymentRecord"][
            "approved_payment_delivery_execution"
        ]
        self.assertEqual(
            approved_execution_metadata["readiness_scope"],
            "approved_payment_delivery_provider_execution_readback",
        )
        self.assertEqual(
            approved_execution_metadata["controlled_provider_adapter_scope"],
            "LOCAL_CONTROLLED_FAKE_PROVIDER",
        )
        self.assertTrue(approved_execution_metadata["requires_payment_approval"])
        self.assertTrue(approved_execution_metadata["requires_delivery_approval"])
        self.assertTrue(approved_execution_metadata["requires_callback_verification"])
        self.assertTrue(approved_execution_metadata["requires_settlement_reconciliation"])
        self.assertFalse(approved_execution_metadata["provider_call_enabled"])
        self.assertFalse(approved_execution_metadata["real_provider_call_enabled"])
        self.assertFalse(approved_execution_metadata["real_refund_attempted"])
        self.assertFalse(approved_execution_metadata["automated_refund_enabled"])
        self.assertEqual(mounted_by_id["listOrders"]["stage_scope"], 9)
        self.assertTrue(mounted_by_id["listContactTargets"]["blocked_by_default"])
        self.assertTrue(
            mounted_by_id["listContactTargets"]["stage8_execution_outbox_readiness"][
                "sandbox_execution_record_enabled"
            ]
        )
        self.assertEqual(
            mounted_by_id["listContactTargets"]["stage8_execution_outbox_readiness"][
                "sandbox_adapter_families"
            ],
            ["email", "sms", "phone_call", "wecom_im"],
        )
        self.assertTrue(
            mounted_by_id["listContactTargets"]["stage8_execution_outbox_readiness"][
                "execution_timeline_visible"
            ]
        )
        self.assertTrue(mounted_by_id["createOutreachPlan"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["listOrders"]["blocked_by_default"])
        self.assertTrue(mounted_by_id["createOrder"]["blocked_by_default"])

        leadpack_candidate = mounted_by_id["previewLeadpackExternalDeliveryCandidate"]
        self.assertTrue(leadpack_candidate["candidate_only"])
        self.assertTrue(leadpack_candidate["readiness_only"])
        self.assertTrue(leadpack_candidate["review_only"])
        self.assertFalse(leadpack_candidate["external_delivery_enabled"])
        self.assertFalse(leadpack_candidate["direct_export_enabled"])

        self.assertFalse(leadpack_candidate["external_ready_direct_export"])
        self.assertFalse(leadpack_candidate["customer_visible_export_enabled"])
        self.assertFalse(leadpack_candidate["client_page_release_enabled"])
        self.assertFalse(leadpack_candidate["page_layer_release_enabled"])
        self.assertFalse(leadpack_candidate["external_release_enabled"])
        self.assertFalse(leadpack_candidate["export_artifact_generation_enabled"])
        self.assertFalse(leadpack_candidate["page_publication_enabled"])
        self.assertTrue(leadpack_candidate["projection_only"])
        self.assertTrue(leadpack_candidate["non_live"])
        self.assertTrue(leadpack_candidate["release_blocked"])
        self.assertTrue(leadpack_candidate["requires_review"])
        formal_export_page_readiness = leadpack_candidate["formal_client_export_page_layer_readiness"]
        self.assertEqual(
            formal_export_page_readiness["surface_id"],
            "formal_client_export_page_layer_readiness",
        )
        self.assertTrue(formal_export_page_readiness["internal_only"])
        self.assertTrue(formal_export_page_readiness["readiness_only"])
        self.assertTrue(formal_export_page_readiness["projection_only"])
        self.assertTrue(formal_export_page_readiness["review_only"])
        self.assertTrue(formal_export_page_readiness["release_blocked"])
        self.assertFalse(formal_export_page_readiness["customer_visible_export_enabled"])
        self.assertFalse(formal_export_page_readiness["client_page_release_enabled"])
        self.assertFalse(formal_export_page_readiness["external_release_enabled"])
        self.assertFalse(formal_export_page_readiness["external_delivery_enabled"])
        self.assertFalse(formal_export_page_readiness["direct_export_enabled"])
        self.assertFalse(formal_export_page_readiness["export_artifact_generation_enabled"])
        self.assertFalse(formal_export_page_readiness["page_publication_enabled"])
        leadpack_readiness = leadpack_candidate["leadpack_external_delivery_candidate_readiness"]
        self.assertTrue(leadpack_readiness["approval_audit_readiness_only"])
        self.assertTrue(leadpack_readiness["candidate_only"])
        self.assertTrue(leadpack_readiness["review_only"])
        self.assertFalse(leadpack_readiness["external_delivery_enabled"])
        self.assertFalse(leadpack_readiness["direct_export_enabled"])
        self.assertFalse(leadpack_readiness["customer_visible_export_enabled"])
        self.assertFalse(leadpack_readiness["client_page_release_enabled"])
        self.assertFalse(leadpack_readiness["page_layer_release_enabled"])
        package_readiness = leadpack_candidate["leadpack_delivery_package_readiness"]
        self.assertTrue(package_readiness["owner_operated_workbench"])
        self.assertTrue(package_readiness["package_manifest_visible"])
        self.assertTrue(package_readiness["evidence_item_manifest_visible"])
        self.assertTrue(package_readiness["field_masking_summary_visible"])
        self.assertTrue(package_readiness["field_allowlist_blacklist_visible"])
        self.assertTrue(package_readiness["customer_visible_artifact_candidate_visible"])
        self.assertTrue(package_readiness["watermark_visible"])
        self.assertTrue(package_readiness["artifact_version_hash_visible"])
        self.assertTrue(package_readiness["download_audit_visible"])
        self.assertTrue(package_readiness["export_page_replay_visible"])
        self.assertTrue(package_readiness["page_draft_visible"])
        self.assertTrue(package_readiness["delivery_readiness_visible"])
        self.assertFalse(package_readiness["customer_visible_enabled"])
        self.assertFalse(package_readiness["external_delivery_enabled"])
        self.assertFalse(package_readiness["page_publication_enabled"])
        for operation_id in (
            "requestLeadpackExternalDeliveryCandidateReview",
            "simulateLeadpackExternalDeliveryExport",
            "previewLeadpackActivationPrepPacket",
            "requestLeadpackActivationPrepReview",
            "previewLeadpackActivationDesignImplementationPrepPacket",
            "requestLeadpackActivationDesignImplementationPrepReview",
            "previewLeadpackImplementationDecisionReadinessPacket",
        ):
            operation = mounted_by_id[operation_id]
            self.assertTrue(operation["candidate_only"], operation_id)
            self.assertTrue(operation["readiness_only"], operation_id)
            self.assertTrue(operation["review_only"], operation_id)
            self.assertFalse(operation["external_delivery_enabled"], operation_id)
            self.assertFalse(operation["direct_export_enabled"], operation_id)
            self.assertFalse(operation["client_page_release_enabled"], operation_id)
            self.assertFalse(operation["page_layer_release_enabled"], operation_id)
            self.assertFalse(operation["external_release_enabled"], operation_id)
            self.assertFalse(operation["export_artifact_generation_enabled"], operation_id)
            self.assertFalse(operation["page_publication_enabled"], operation_id)
            self.assertTrue(operation["projection_only"], operation_id)
            self.assertTrue(operation["release_blocked"], operation_id)
            self.assertIn("formal_client_export_page_layer_readiness", operation, operation_id)
            self.assertIn("leadpack_delivery_package_readiness", operation, operation_id)
            self.assertIn("package_page_delivery_summary", operation, operation_id)

        entry_strategy = bootstrap["entry_strategy"]
        self.assertFalse(entry_strategy["stage1_to_stage5"]["http_entry_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["real_transport_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["orchestrator_enabled"])
        self.assertFalse(entry_strategy["stage1_to_stage5"]["external_live_transport_enabled"])
        self.assertTrue(entry_strategy["stage1_to_stage5"]["internal_orchestration_entry_available"])
        self.assertEqual(
            entry_strategy["stage1_to_stage5"]["internal_orchestration_entry"]["internal_orchestration_path"],
            "/internal/stage1-6/orchestrations",
        )
        self.assertEqual(entry_strategy["stage1_to_stage5"]["reserved_entry_plan"], reserved_entry_plan)
        self.assertTrue(entry_strategy["stage6"]["http_entry_enabled"])
        self.assertIn(
            "previewStage6ReviewReportWorkbench",
            entry_strategy["stage6"]["mounted_operations"],
        )
        self.assertTrue(entry_strategy["stage7_to_stage9"]["http_entry_enabled"])
        self.assertIn(
            "listSaleableOpportunities",
            entry_strategy["stage7_to_stage9"]["mounted_operations_by_stage"]["stage7"],
        )
        self.assertFalse(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_stage1_to_stage5_transport"]
        )
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["http_entry_enabled"])
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["internal_only"])
        self.assertFalse(entry_strategy["stage1_to_stage6_full_chain_entry"]["live_execution_enabled"])
        self.assertEqual(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["accepted_payload_boundary"],
            "SANITIZED_OFFLINE_INTERNAL",
        )
        self.assertEqual(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["operation_id"],
            "runStage1ToStage6InternalOrchestration",
        )
        self.assertFalse(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_external_live_transport"]
        )
        self.assertFalse(entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_real_orchestrator"])
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["executes_existing_internal_chain"])
        self.assertTrue(entry_strategy["stage1_to_stage6_full_chain_entry"]["persists_stage6_bundle"])
        self.assertEqual(
            entry_strategy["stage1_to_stage6_full_chain_entry"]["stage6_readback_mode"],
            "repository_backed_preview",
        )
        self.assertEqual(entry_strategy["queue_worker"]["effective_queue_backend"], "storage")
        self.assertTrue(entry_strategy["queue_worker"]["repository_backed"])
        self.assertFalse(entry_strategy["queue_worker"]["redis_connection_enabled"])
        self.assertFalse(entry_strategy["queue_worker"]["stage1_scheduler_enabled"])
        self.assertEqual(entry_strategy["object_storage"]["object_storage_backend"], "local-filesystem")
        self.assertEqual(entry_strategy["object_storage"]["effective_backend"], "local-filesystem")
        self.assertTrue(entry_strategy["object_storage"]["local_filesystem_executable"])
        self.assertTrue(entry_strategy["object_storage"]["snapshot_manifest_repository_backed"])
        self.assertTrue(entry_strategy["object_storage"]["snapshot_readback_replay_enabled"])
        self.assertFalse(entry_strategy["object_storage"]["external_service_connection_enabled"])
        self.assertTrue(entry_strategy["backup_restore"]["backup_manifest_enabled"])
        self.assertTrue(entry_strategy["backup_restore"]["restore_dry_run_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["safe_to_restore"])
        self.assertFalse(entry_strategy["backup_restore"]["destructive_restore_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["restore_execution_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["rollback_execution_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["external_backup_service_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["external_service_connection_enabled"])
        self.assertFalse(entry_strategy["backup_restore"]["migration_execution_enabled"])
        self.assertEqual(
            entry_strategy["backup_restore"]["rollback_readiness"],
            bootstrap["rollback_readiness"],
        )
        monitoring_entry = entry_strategy["monitoring_alerting"]
        self.assertEqual(monitoring_entry["monitoring_readiness_state"], "INTERNAL_READBACK_READY")
        self.assertEqual(monitoring_entry["alert_readiness_state"], "CATALOG_READY_READBACK_ONLY")
        self.assertEqual(monitoring_entry["incident_state"], "MANUAL_OWNER_ACTION_READY")
        self.assertTrue(monitoring_entry["repository_backed_readback"])
        self.assertTrue(monitoring_entry["replayable_readback"])
        self.assertFalse(monitoring_entry["notification_enabled"])
        self.assertFalse(monitoring_entry["live_dispatch_enabled"])
        self.assertFalse(monitoring_entry["external_observability_provider_enabled"])
        self.assertFalse(monitoring_entry["external_paging_enabled"])
        self.assertFalse(monitoring_entry["incident_automation_enabled"])
        production_entry = entry_strategy["production_slo_incident_readiness"]
        self.assertEqual(production_entry["capability_state"], "PRODUCTION_READY")
        self.assertEqual(production_entry["readiness_state"], "PRODUCTION_READY")
        self.assertTrue(production_entry["repository_backed_readback"])
        self.assertTrue(production_entry["replayable_readback"])
        self.assertGreaterEqual(production_entry["slo_objective_count"], 10)
        self.assertGreaterEqual(production_entry["alert_rule_count"], 7)
        self.assertTrue(production_entry["simulated_alerts_fire"])
        self.assertEqual(production_entry["incident_runbook_state"], "PRODUCTION_READY")
        self.assertEqual(production_entry["backup_restore_drill_mode"], "DRY_RUN_ONLY")
        self.assertEqual(production_entry["rollback_drill_mode"], "DRY_RUN_ONLY")
        self.assertEqual(production_entry["suspension_state"], "SUSPENDED")
        self.assertTrue(production_entry["manual_resume_required"])
        self.assertFalse(production_entry["real_alert_dispatch_enabled"])
        self.assertFalse(production_entry["incident_automation_enabled"])
        self.assertFalse(production_entry["destructive_restore_enabled"])
        self.assertFalse(production_entry["rollback_execution_enabled"])
        approved_drill_entry = entry_strategy["approved_production_live_dependency_drill"]
        self.assertEqual(approved_drill_entry["controlled_drill_state"], "NOT_REQUESTED")
        self.assertFalse(
            approved_drill_entry["approved_production_live_dependency_drill_enabled"]
        )
        self.assertFalse(approved_drill_entry["docker_compose_up_executed"])
        self.assertFalse(approved_drill_entry["real_alert_dispatch_enabled"])
        self.assertFalse(approved_drill_entry["destructive_restore_enabled"])
        self.assertFalse(approved_drill_entry["rollback_execution_enabled"])
        self.assertFalse(approved_drill_entry["incident_automation_enabled"])

        queue_worker = bootstrap["queue_worker_readiness"]
        self.assertEqual(queue_worker["effective_queue_backend"], "storage")
        self.assertEqual(queue_worker["readiness_state"], "EXECUTABLE")
        self.assertTrue(queue_worker["durable_queue_enabled"])
        self.assertTrue(queue_worker["worker_lease_enabled"])
        self.assertTrue(queue_worker["retry_enabled"])
        self.assertTrue(queue_worker["suspend_resume_enabled"])
        self.assertTrue(queue_worker["audit_replay_enabled"])
        self.assertFalse(queue_worker["external_queue_connection_enabled"])
        self.assertFalse(queue_worker["real_provider_execution_enabled"])

        controlled_opening_requirements = bootstrap["controlled_opening_requirements"]
        self.assertFalse(controlled_opening_requirements["new_http_endpoint_added"])
        self.assertTrue(controlled_opening_requirements["internal_stage1_to_stage6_http_endpoint_added"])
        self.assertFalse(controlled_opening_requirements["new_external_or_live_http_endpoint_added"])
        self.assertFalse(controlled_opening_requirements["stage1_to_stage5_real_transport_enabled"])
        self.assertFalse(controlled_opening_requirements["stage1_to_stage5_external_live_transport_enabled"])
        self.assertFalse(controlled_opening_requirements["external_software_release_enabled"])
        self.assertTrue(controlled_opening_requirements["external_leadpack_delivery_requires_approval_and_audit"])
        self.assertFalse(controlled_opening_requirements["stage8_real_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["stage9_real_payment_delivery_refund_enabled"])
        self.assertFalse(controlled_opening_requirements["provider_adapter_live_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["provider_adapter_provider_call_enabled"])
        self.assertFalse(controlled_opening_requirements["provider_adapter_real_provider_call_enabled"])
        self.assertFalse(controlled_opening_requirements["redis_connection_enabled"])
        self.assertFalse(controlled_opening_requirements["external_queue_connection_enabled"])
        self.assertFalse(controlled_opening_requirements["external_worker_process_enabled"])
        self.assertFalse(controlled_opening_requirements["minio_connection_enabled"])
        self.assertFalse(controlled_opening_requirements["s3_connection_enabled"])
        self.assertFalse(controlled_opening_requirements["external_object_storage_connection_enabled"])
        self.assertFalse(controlled_opening_requirements["external_backup_service_enabled"])
        self.assertFalse(controlled_opening_requirements["destructive_restore_enabled"])
        self.assertFalse(controlled_opening_requirements["restore_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["rollback_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["migration_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["compose_runtime_enabled"])
        self.assertFalse(controlled_opening_requirements["container_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["docker_compose_up_executed"])
        self.assertFalse(controlled_opening_requirements["real_provider_execution_enabled"])
        self.assertFalse(controlled_opening_requirements["real_payment_delivery_enabled"])
        self.assertFalse(controlled_opening_requirements["provider_credentials_plaintext_persisted"])
        self.assertFalse(controlled_opening_requirements["external_observability_provider_enabled"])
        self.assertFalse(controlled_opening_requirements["external_apm_enabled"])
        self.assertFalse(controlled_opening_requirements["external_paging_enabled"])
        self.assertFalse(controlled_opening_requirements["notification_enabled"])
        self.assertFalse(controlled_opening_requirements["live_alert_dispatch_enabled"])
        self.assertFalse(controlled_opening_requirements["real_alert_dispatch_enabled"])
        self.assertFalse(controlled_opening_requirements["incident_automation_enabled"])
        self.assertFalse(controlled_opening_requirements["active_storage_mutation_enabled"])
        self.assertFalse(controlled_opening_requirements["automated_refund_program_present"])
        self.assertFalse(controlled_opening_requirements["automated_refund_program_enabled"])
        self.assertFalse(controlled_opening_requirements["automated_refund_enabled"])
        stage9_live_pilot = app.state.transport_bootstrap["entry_strategy"][
            "stage9_payment_delivery_live_pilot"
        ]
        self.assertFalse(stage9_live_pilot["batch_execution_enabled"])
        self.assertTrue(stage9_live_pilot["payment_approval_required"])
        self.assertTrue(stage9_live_pilot["delivery_approval_required"])
        self.assertTrue(stage9_live_pilot["finance_review_required"])
        self.assertTrue(stage9_live_pilot["operator_action_audit_required"])
        self.assertTrue(stage9_live_pilot["artifact_version_lock_required"])
        self.assertTrue(stage9_live_pilot["download_auth_required"])
        self.assertFalse(stage9_live_pilot["provider_call_enabled"])
        self.assertFalse(stage9_live_pilot["real_provider_call_enabled"])
        self.assertFalse(stage9_live_pilot["real_charge_attempted"])
        self.assertFalse(stage9_live_pilot["real_delivery_fulfillment_attempted"])
        self.assertFalse(stage9_live_pilot["real_customer_download_attempted"])
        self.assertFalse(stage9_live_pilot["real_refund_attempted"])
        self.assertFalse(stage9_live_pilot["automated_refund_enabled"])

        local_stack = app.state.transport_bootstrap["local_stack_readiness"]
        self.assertTrue(local_stack["dockerfile_present"])
        self.assertTrue(local_stack["compose_file_present"])
        self.assertTrue(local_stack["docker_compose_config_present"])
        self.assertFalse(local_stack["compose_runtime_enabled"])
        self.assertFalse(local_stack["container_execution_enabled"])
        self.assertFalse(local_stack["docker_compose_up_executed"])
        self.assertEqual(
            app.state.transport_bootstrap["entry_strategy"]["local_stack"]["reserved_services"],
            ["postgres", "redis", "minio"],
        )
        for reserved_service in ("postgres", "redis", "minio"):
            dependency = local_stack["service_dependency_summary"][reserved_service]
            self.assertEqual(dependency["readiness_state"], "RESERVED_NOT_LIVE")
            self.assertFalse(dependency["external_service_connection_enabled"])
            self.assertFalse(dependency["container_execution_enabled"])

        self.assertEqual(len(app.state.disabled_stage_transports), 5)
        self.assertEqual(
            app.state.mounted_transport_operations,
            [operation["operationId"] for operation in mounted_operations],
        )
        self.assertEqual(app.state.storage_bootstrap, app.state.settings.storage_bootstrap_payload())
        self.assertIn("platform_infra_readiness", app.state.storage_bootstrap)
        self.assertEqual(app.state.transport_bootstrap["storage_bootstrap"], app.state.storage_bootstrap)
        self.assertEqual(
            app.state.transport_bootstrap["platform_infra_readiness"],
            app.state.storage_bootstrap["platform_infra_readiness"],
        )
        self.assertEqual(
            app.state.transport_bootstrap["monitoring_alerting_readiness"],
            app.state.storage_bootstrap["monitoring_alerting_readiness"],
        )
        self.assertEqual(
            app.state.monitoring_alerting_readback.payload["readiness_id"],
            "MONITORING_ALERTING_READINESS_CURRENT",
        )
        self.assertEqual(
            app.state.production_slo_incident_readback.payload["readiness_id"],
            "PRODUCTION_SLO_INCIDENT_READINESS_CURRENT",
        )
        self.assertEqual(
            app.state.production_slo_incident_readback.payload,
            app.state.storage_bootstrap["production_slo_incident_readiness"],
        )

    def test_provider_circuit_breaker_status_is_visible_in_api_bootstrap_and_route_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": tmp_dir,
                    "KAKA_PROVIDER_ADAPTER_CIRCUIT_OPEN": "true",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                app = create_app()
                try:
                    bootstrap = app.state.transport_bootstrap
                    mounted_by_id = {
                        operation["operationId"]: operation
                        for operation in bootstrap["stage6_to_stage9_mounted_operations"]
                    }
                    provider_readback = app.state.provider_adapter_config_readback
                finally:
                    app.state.storage_session.close()

        self.assertEqual(bootstrap["provider_reliability_state"], "SUSPENDED")
        self.assertEqual(bootstrap["provider_circuit_breaker_state"], "OPEN")
        self.assertTrue(bootstrap["provider_adapter_suspended"])
        self.assertEqual(set(bootstrap["provider_adapter_suspended_families"]), set(PROVIDER_FAMILIES))
        self.assertTrue(bootstrap["provider_reliability_summary"]["replayable_provider_status"])
        self.assertFalse(bootstrap["provider_reliability_summary"]["live_fallback_allowed"])
        self.assertEqual(provider_readback.governed_state["provider_reliability_state"], "SUSPENDED")
        self.assertEqual(provider_readback.governed_state["provider_circuit_breaker_state"], "OPEN")
        for operation_id in ("listSaleableOpportunities", "listContactTargets", "listOrders"):
            operation = mounted_by_id[operation_id]
            self.assertEqual(operation["provider_reliability_state"], "SUSPENDED")
            self.assertEqual(operation["provider_circuit_breaker_state"], "OPEN")
            self.assertTrue(operation["provider_adapter_suspended"])
            self.assertFalse(operation["provider_adapter_real_provider_call_enabled"])

    def test_create_app_fast_fails_postgres_without_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "postgres",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()

                with self.assertRaisesRegex(ValueError, "KAKA_STORAGE_DATABASE_URL"):
                    create_app()

    def test_create_app_fast_fails_unsupported_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(
                os.environ,
                {
                    "KAKA_STORAGE_BACKEND": "unsupported-backend",
                    "LOCALAPPDATA": tmp_dir,
                },
                clear=False,
            ):
                for key in (
                    "KAKA_STORAGE_PATH",
                    "KAKA_STORAGE_DATABASE_URL",
                    "KAKA_STORAGE_SCOPE",
                    "KAKA_STORAGE_TEST_ISOLATION",
                    "KAKA_OBJECT_STORAGE_BACKEND",
                    "KAKA_OBJECT_STORAGE_PATH",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()

                with self.assertRaisesRegex(ValueError, "unsupported storage backend"):
                    create_app()

    def test_stage1_to_stage5_route_registrars_are_controlled_unavailable(self) -> None:
        registrars = [
            register_stage1_routes,
            register_stage2_routes,
            register_stage3_routes,
            register_stage4_routes,
            register_stage5_routes,
        ]

        for stage_scope, registrar in enumerate(registrars, start=1):
            routes = registrar()
            self.assertEqual(len(routes), 1)
            transport_status = routes[0]
            self.assertEqual(transport_status["stage_scope"], stage_scope)
            self.assertEqual(transport_status["availability_state"], "CONTROLLED_UNAVAILABLE")
            self.assertEqual(transport_status["contract_state"], "CONTRACT_READY")
            self.assertEqual(transport_status["transport_state"], "TRANSPORT_NOT_WIRED")
            self.assertTrue(transport_status["internal_only"])
            self.assertFalse(transport_status["live_execution_enabled"])
            self.assertEqual(
                {
                    key: transport_status[key]
                    for key in RESERVED_ENTRY_PLAN_READBACK_KEYS
                },
                expected_reserved_entry_plan(stage_scope),
            )

    def test_stage6_route_registrar_exposes_internal_queue_surface(self) -> None:
        routes = register_stage6_routes()

        self.assertEqual(len(routes), 3)
        preview_route = next(route for route in routes if route["operationId"] == "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["operationId"], "previewStage6ReviewReportWorkbench")
        self.assertEqual(preview_route["method"], "GET")
        self.assertEqual(preview_route["path"], "/review-report-workbench")
        self.assertEqual(preview_route["surface_mode"], "preview-only")
        self.assertTrue(preview_route["internal_only"])
        self.assertFalse(preview_route["live_execution_enabled"])
        self.assertFalse(preview_route["blocked_by_default"])
        list_route = next(route for route in routes if route["operationId"] == "listStage6WorkItems")
        action_route = next(route for route in routes if route["operationId"] == "submitStage6OperatorAction")
        self.assertEqual(list_route["method"], "GET")
        self.assertEqual(list_route["path"], "/review-report-work-items")
        self.assertEqual(action_route["method"], "POST")
        self.assertEqual(action_route["path"], "/review-report-workbench/{project_fact_id}/operator-actions")
        self.assertTrue(action_route["internal_only"])
        self.assertFalse(action_route["live_execution_enabled"])

    def test_stage1_to_stage6_internal_orchestration_route_registrar_is_separate(self) -> None:
        routes = register_stage1_to_stage6_internal_orchestration_routes()

        self.assertEqual(len(routes), 1)
        orchestration_route = next(
            route for route in routes if route["operationId"] == "runStage1ToStage6InternalOrchestration"
        )
        self.assertEqual(orchestration_route["method"], "POST")
        self.assertEqual(orchestration_route["path"], "/internal/stage1-6/orchestrations")
        self.assertTrue(orchestration_route["internal_only"])
        self.assertFalse(orchestration_route["live_execution_enabled"])
        self.assertEqual(
            orchestration_route["accepted_payload_boundary"],
            "SANITIZED_OFFLINE_INTERNAL",
        )
        self.assertTrue(orchestration_route["repository_backed_readback"])

    def test_create_app_mounts_stage7_to_stage9_transport_routes(self) -> None:
        app = create_app()

        mounted_operation_ids = {
            route.operation_id
            for route in app.routes
            if getattr(route, "operation_id", None)
        }
        self.assertTrue(
            {
                "previewStage6ReviewReportWorkbench",
                "runStage1ToStage6InternalOrchestration",
                "listStage6WorkItems",
                "submitStage6OperatorAction",
                "listSaleableOpportunities",
                "listContactTargets",
                "listOrders",
                "createOutreachPlan",
                "createOrder",
            }.issubset(mounted_operation_ids)
        )
        self.assertEqual(len(app.state.disabled_stage_transports), 5)
        self.assertIn("stage1", app.state.disabled_stage_transports)
        self.assertNotIn("stage6", app.state.disabled_stage_transports)

        reserved_operation_ids = {
            expected["reserved_operation_id"]
            for expected in RESERVED_ENTRY_EXPECTATIONS.values()
        }
        reserved_paths = {
            expected["reserved_path"]
            for expected in RESERVED_ENTRY_EXPECTATIONS.values()
        }
        mounted_paths = {
            getattr(route, "path", None)
            for route in app.routes
        }
        self.assertTrue(reserved_operation_ids.isdisjoint(mounted_operation_ids))
        self.assertTrue(reserved_paths.isdisjoint(mounted_paths))

    def test_stage1_to_stage6_internal_orchestration_runs_repository_backed_readback(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "source_mode": "OFFLINE_FIXTURE",
                "run_mode": "DRY_RUN",
            }
        )

        client = TestClient(create_app())
        response = client.post("/internal/stage1-6/orchestrations", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["operation_id"], "runStage1ToStage6InternalOrchestration")
        self.assertEqual(body["orchestration_scope"], "stage1_to_stage6")
        self.assertEqual(body["payload_boundary"], "SANITIZED_OFFLINE_INTERNAL")
        self.assertTrue(body["internal_only"])
        self.assertFalse(body["live_execution_enabled"])
        self.assertFalse(body["external_live_transport_enabled"])
        self.assertEqual(body["stage1_to_stage5_transport_state"], "BLOCKED_CONTROLLED_UNAVAILABLE")
        self.assertFalse(body["stage1_to_stage5_http_entry_enabled"])
        self.assertFalse(body["stage1_to_stage5_real_transport_enabled"])
        self.assertFalse(body["stage1_to_stage5_external_live_transport_enabled"])
        self.assertTrue(body["stage6_repository_backed_preview"])
        self.assertTrue(body["stage6_persisted"])

        readback = body["stage6_readback"]
        self.assertEqual(readback["surface_id"], "review_report_workbench")
        self.assertEqual(readback["surface_mode"], "preview-only")
        self.assertTrue(readback["internal_only"])
        self.assertFalse(readback["live_execution_enabled"])
        self.assertEqual(readback["operational_context_status"], "persisted")
        self.assertEqual(
            readback["formal_object_refs"]["project_fact"]["object_id"],
            body["stage6_project_fact_id"],
        )
        self.assertEqual(
            readback["preview_projection"]["project_fact_summary"]["project_id"],
            body["stage6_project_id"],
        )

    def test_stage1_to_stage6_internal_orchestration_rejects_live_payloads(self) -> None:
        payload = load_fixture("internal_chain_happy.json")
        payload.update(
            {
                "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "source_mode": "OFFLINE_FIXTURE",
                "run_mode": "LIVE",
                "live_execution_enabled": True,
            }
        )

        client = TestClient(create_app())
        response = client.post("/internal/stage1-6/orchestrations", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            any(
                error.get("type") == "literal_error"
                and error.get("loc", [])[-1] == "run_mode"
                for error in response.json()["detail"]["errors"]
            )
        )

    def test_stage6_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = result["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")

        client = TestClient(create_app())
        response = client.request("GET", "/review-report-workbench", json={"project_id": project_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "review_report_workbench")
        self.assertEqual(payload["surface_mode"], "preview-only")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["blocked_by_default"])
        self.assertEqual(
            payload["formal_object_refs"]["project_fact"]["object_id"],
            stage6.record("project_fact").get("project_fact_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["report_record"]["object_id"],
            stage6.record("report_record").get("report_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["review_queue_profile"]["object_id"],
            stage6.record("review_queue_profile").get("queue_profile_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["challenger_candidate_profile"]["object_id"],
            stage6.record("challenger_candidate_profile").get("challenger_profile_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["legal_action_recommendation"]["object_id"],
            stage6.record("legal_action_recommendation").get("action_id"),
        )
        self.assertEqual(
            payload["preview_projection"]["project_fact_summary"]["sale_gate_status"],
            stage6.record("project_fact").get("sale_gate_status"),
        )

    def test_stage6_http_transport_lists_and_submits_operator_actions(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage6 = result["stage6"]
        persist_stage_bundle(stage6)
        project_id = stage6.record("project_fact").get("project_id")
        project_fact_id = stage6.record("project_fact").get("project_fact_id")

        client = TestClient(create_app())
        list_response = client.request("GET", "/review-report-work-items", json={"project_id": project_id})
        action_response = client.request(
            "POST",
            f"/review-report-workbench/{project_fact_id}/operator-actions",
            json={
                "project_id": project_id,
                "action_id": "stage6_return_for_revision",
                "button_flow_id": "submit_stage6_return_for_revision",
                "reason": "transport-level stage6 revision return",
            },
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(action_response.status_code, 200)
        list_payload = list_response.json()
        action_payload = action_response.json()
        self.assertEqual(len(list_payload["work_items"]), 1)
        self.assertEqual(list_payload["work_items"][0]["primary_object_type"], "project_fact")
        self.assertEqual(action_payload["action_result"]["action_id"], "stage6_return_for_revision")
        self.assertEqual(
            action_payload["persisted_operational_context"]["current_operational_state"],
            "action_returned_for_revision",
        )
        self.assertEqual(action_payload["persisted_operational_context"]["pending_actions"], ["stage6_mark_reviewed"])

    def test_stage7_to_stage9_write_responses_match_explicit_contracts(self) -> None:
        chain = run_internal_chain(load_fixture("internal_chain_happy.json"))
        for stage_scope in range(6, 10):
            persist_stage_bundle(chain[f"stage{stage_scope}"])
        opportunity_id = str(
            chain["stage7"].record("saleable_opportunity").get("opportunity_id")
        )
        contact_target_id = str(
            chain["stage8"].record("contact_target").get("contact_target_id")
        )
        cases = (
            (
                "/saleable-opportunities/{opportunity_id}/refresh",
                {"opportunity_id": opportunity_id, "refresh_reason": "contract regression"},
            ),
            (
                "/saleable-opportunities/{opportunity_id}/operator-actions",
                {
                    "opportunity_id": opportunity_id,
                    "action_id": "stage7_mark_reviewed",
                    "button_flow_id": "submit_stage7_mark_reviewed",
                    "reason": "contract regression",
                },
            ),
            (
                "/leadpack-external-delivery-candidates/{opportunity_id}/review-requests",
                {"opportunity_id": opportunity_id},
            ),
            (
                "/leadpack-external-delivery-candidates/{opportunity_id}/export-simulations",
                {"opportunity_id": opportunity_id},
            ),
            (
                "/leadpack-external-delivery-candidates/{opportunity_id}/activation-prep-review-requests",
                {"opportunity_id": opportunity_id},
            ),
            (
                "/leadpack-external-delivery-candidates/{opportunity_id}/activation-design-implementation-prep-review-requests",
                {"opportunity_id": opportunity_id},
            ),
            (
                "/contact-targets/compliance-check",
                {
                    "opportunity_id": opportunity_id,
                    "contact_target_id": contact_target_id,
                },
            ),
            (
                "/outreach-plans",
                {"opportunity_id": opportunity_id, "plan_status": "DRAFT"},
            ),
            (
                "/touch-records",
                {"opportunity_id": opportunity_id, "response_status": "NO_RESPONSE"},
            ),
            (
                "/outreach-workbench/{opportunity_id}/operator-actions",
                {
                    "opportunity_id": opportunity_id,
                    "action_id": "stage8_request_governed_review",
                    "button_flow_id": "submit_stage8_request_governed_review",
                    "reason": "contract regression",
                },
            ),
            (
                "/order-delivery-workbench/{opportunity_id}/operator-actions",
                {
                    "opportunity_id": opportunity_id,
                    "action_id": "stage9_submit_draft_writeback",
                    "button_flow_id": "submit_stage9_draft_writeback",
                    "reason": "contract regression",
                },
            ),
        )
        client = TestClient(create_app())
        try:
            for path_template, payload in cases:
                with self.subTest(path=path_template):
                    path = path_template.format(opportunity_id=opportunity_id)
                    response = client.post(path, json=payload)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn("surface_id", response.json())
        finally:
            client.app.state.storage_session.close()

    def test_stage7_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/saleable-opportunities", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "opportunity_pool")
        self.assertTrue(payload["internal_only"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_ONLY")
        self.assertIn("refreshSaleableOpportunity", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["offer_recommendation"]["object_id"],
            stage7.record("offer_recommendation").get("offer_recommendation_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["buyer_fit"]["object_id"],
            stage7.record("buyer_fit").get("buyer_fit_id"),
        )
        self.assertEqual(
            payload["crm_quote_workbench"]["quote_draft_id"],
            stage7.inputs["crm_quote_workbench"]["quote_draft_id"],
        )
        self.assertFalse(payload["crm_quote_workbench"]["live_execution_enabled"])
        self.assertFalse(payload["crm_quote_workbench"]["real_external_quote_sent"])
        self.assertEqual(
            payload["crm_quote_workbench_readiness_summary"]["crm_action_id"],
            stage7.inputs["crm_quote_workbench"]["crm_action_id"],
        )
        self.assertEqual(
            payload["leadpack_delivery_package"]["package_id"],
            stage7.inputs["leadpack_delivery_package"]["package_id"],
        )
        self.assertEqual(
            payload["leadpack_delivery_readiness_summary"]["page_draft_id"],
            stage7.inputs["leadpack_delivery_package"]["page_draft_id"],
        )
        self.assertFalse(payload["leadpack_delivery_package"]["customer_visible_enabled"])
        self.assertFalse(payload["leadpack_delivery_package"]["external_delivery_enabled"])
        self.assertFalse(payload["package_page_delivery_summary"]["page_publication_enabled"])

    def test_stage7_crm_quote_readiness_metadata_is_non_live_in_bootstrap_and_readback(self) -> None:
        app = create_app()
        mounted_by_id = {
            operation["operationId"]: operation
            for operation in app.state.transport_bootstrap["stage6_to_stage9_mounted_operations"]
        }
        stage7_metadata = mounted_by_id["listSaleableOpportunities"]["crm_quote_prerequisite_readiness"]
        provider_metadata = mounted_by_id["listSaleableOpportunities"][PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]

        self.assertTrue(stage7_metadata["readiness_only"])
        self.assertEqual(provider_metadata["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(provider_metadata["provider_call_enabled"])
        self.assertFalse(provider_metadata["real_provider_call_enabled"])
        self.assertIn("crm_quote", provider_metadata["families"])
        self.assertIn("leadpack_page_delivery", provider_metadata["families"])
        self.assertTrue(stage7_metadata["prerequisite_only"])
        self.assertTrue(stage7_metadata["blocked_by_default"])
        self.assertEqual(stage7_metadata["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(stage7_metadata["crm_runtime_enabled"])
        self.assertFalse(stage7_metadata["external_quote_enabled"])
        self.assertFalse(stage7_metadata["external_delivery_enabled"])
        self.assertFalse(mounted_by_id["listSaleableOpportunities"]["crm_runtime_enabled"])
        self.assertFalse(mounted_by_id["listSaleableOpportunities"]["external_quote_enabled"])
        self.assertFalse(mounted_by_id["listSaleableOpportunities"]["external_delivery_enabled"])
        self.assertTrue(mounted_by_id["listSaleableOpportunities"]["readiness_only"])
        workbench_metadata = mounted_by_id["listSaleableOpportunities"]["crm_quote_workbench_readiness"]
        self.assertTrue(workbench_metadata["readiness_only"])
        self.assertTrue(workbench_metadata["draft_only"])
        self.assertTrue(workbench_metadata["blocked_live"])
        self.assertTrue(workbench_metadata["repository_backed_readback"])
        self.assertTrue(workbench_metadata["crm_account_sandbox_sync_record_visible"])
        self.assertTrue(workbench_metadata["crm_opportunity_sandbox_sync_record_visible"])
        self.assertTrue(workbench_metadata["crm_activity_sandbox_sync_record_visible"])
        self.assertTrue(workbench_metadata["quote_sandbox_record_visible"])
        self.assertTrue(workbench_metadata["deal_tracking_record_visible"])
        self.assertTrue(workbench_metadata["sales_note_callback_record_visible"])
        self.assertEqual(workbench_metadata["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertFalse(workbench_metadata["live_execution_enabled"])
        self.assertFalse(workbench_metadata["real_external_quote_sent"])
        approved_crm_quote_metadata = mounted_by_id["listSaleableOpportunities"][
            "stage7_approved_crm_quote_provider_execution_readiness"
        ]
        self.assertEqual(
            approved_crm_quote_metadata["readiness_scope"],
            "approved_crm_quote_provider_execution_readback",
        )
        self.assertEqual(
            approved_crm_quote_metadata["provider_adapter_scope"],
            "LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER",
        )
        self.assertTrue(approved_crm_quote_metadata["requires_provider_config"])
        self.assertTrue(approved_crm_quote_metadata["requires_sandbox_pass"])
        self.assertTrue(approved_crm_quote_metadata["requires_operator_action_audit"])
        self.assertTrue(approved_crm_quote_metadata["provider_result_readback_visible"])
        self.assertTrue(approved_crm_quote_metadata["deal_tracking_timeline_visible"])
        self.assertFalse(approved_crm_quote_metadata["provider_call_enabled"])
        self.assertFalse(approved_crm_quote_metadata["real_provider_call_enabled"])
        self.assertFalse(approved_crm_quote_metadata["real_crm_sync_enabled"])
        self.assertFalse(approved_crm_quote_metadata["external_quote_sent"])
        package_metadata = mounted_by_id["listSaleableOpportunities"]["leadpack_delivery_package_readiness"]
        self.assertTrue(package_metadata["repository_backed_readback"])
        self.assertTrue(package_metadata["package_manifest_visible"])
        self.assertTrue(package_metadata["customer_visible_artifact_candidate_visible"])
        self.assertTrue(package_metadata["artifact_version_hash_visible"])
        self.assertTrue(package_metadata["download_audit_visible"])
        self.assertTrue(package_metadata["page_draft_visible"])
        self.assertFalse(package_metadata["customer_visible_enabled"])
        self.assertFalse(package_metadata["external_delivery_enabled"])

        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage7 = result["stage7"]
        persist_stage_bundle(stage7)
        opportunity_id = stage7.record("saleable_opportunity").get("opportunity_id")

        client = TestClient(app)
        response = client.request("GET", "/saleable-opportunities", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        carrier = response.json()["crm_quote_prerequisite_readiness"]
        self.assertEqual(carrier["governed_execution_mode"], "INTERNAL_GOVERNED")
        self.assertTrue(carrier["readiness_only"])
        self.assertFalse(carrier["crm_runtime_enabled"])
        self.assertFalse(carrier["external_quote_enabled"])
        self.assertFalse(carrier["external_delivery_enabled"])
        self.assertEqual(
            carrier["source_object_refs"]["saleable_opportunity"]["object_id"],
            stage7.record("saleable_opportunity").get("opportunity_id"),
        )
        body = response.json()
        self.assertEqual(body[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(body["crm_quote_workbench"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertFalse(body["leadpack_delivery_package"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertEqual(
            body["crm_quote_workbench"]["quote_draft_id"],
            stage7.inputs["crm_quote_workbench"]["quote_draft_id"],
        )
        self.assertEqual(
            set(body["crm_quote_workbench"]["crm_sandbox_sync_records"]),
            {"account", "opportunity", "activity"},
        )
        self.assertEqual(
            body["crm_quote_workbench"]["quote_sandbox_record"]["quote_sandbox_record_id"],
            stage7.inputs["crm_quote_workbench"]["quote_sandbox_record"]["quote_sandbox_record_id"],
        )
        self.assertFalse(body["crm_quote_workbench"]["live_execution_enabled"])
        self.assertFalse(body["crm_quote_workbench"]["real_external_quote_sent"])
        self.assertIn("approved_crm_quote_execution_summary", body["crm_quote_workbench"])
        self.assertIn("provider_result_readback", body["crm_quote_workbench"])
        self.assertIn("deal_tracking_timeline", body["crm_quote_workbench"])
        self.assertIn("approved_crm_quote_execution_summary", body)
        self.assertIn("provider_result_readback", body)
        self.assertIn("deal_tracking_timeline", body)
        self.assertFalse(body["crm_quote_workbench"]["provider_result_readback"]["provider_call_executed"])
        self.assertFalse(body["crm_quote_workbench"]["provider_result_readback"]["real_provider_call_enabled"])
        self.assertFalse(body["crm_quote_workbench"]["quote_send_record"]["external_quote_sent"])
        self.assertEqual(
            body["crm_quote_workbench"]["provider_execution_id"],
            stage7.inputs["crm_quote_workbench"]["provider_execution_id"],
        )
        self.assertEqual(
            body["crm_quote_workbench_readiness_summary"]["quote_draft_id"],
            stage7.inputs["crm_quote_workbench"]["quote_draft_id"],
        )
        self.assertEqual(
            body["leadpack_delivery_package"]["artifact_manifest_id"],
            stage7.inputs["leadpack_delivery_package"]["artifact_manifest_id"],
        )
        self.assertEqual(
            body["leadpack_delivery_package"]["artifact_version_hash"],
            stage7.inputs["leadpack_delivery_package"]["artifact_version_hash"],
        )
        self.assertEqual(
            body["package_page_delivery_summary"]["export_page_replay"]["replay_id"],
            stage7.inputs["leadpack_delivery_package"]["export_page_replay"]["replay_id"],
        )
        self.assertFalse(body["leadpack_delivery_readiness_summary"]["delivery_ready"])

    def test_stage8_http_transport_reads_repository_backed_preview(self) -> None:
        app = create_app()
        mounted_by_id = {
            operation["operationId"]: operation
            for operation in app.state.transport_bootstrap["stage6_to_stage9_mounted_operations"]
        }
        live_pilot_metadata = mounted_by_id["listContactTargets"]["stage8_live_pilot_readiness"]
        approved_provider_metadata = mounted_by_id["listContactTargets"][
            "stage8_approved_provider_execution_readiness"
        ]
        self.assertEqual(live_pilot_metadata["readiness_scope"], "gated_small_sample_live_pilot_readback")
        self.assertEqual(
            approved_provider_metadata["readiness_scope"],
            "approved_small_sample_provider_execution_readback",
        )
        self.assertEqual(
            set(live_pilot_metadata["supported_adapter_families"]),
            {"email", "sms", "phone_call", "wecom_im"},
        )
        self.assertEqual(
            set(approved_provider_metadata["supported_adapter_families"]),
            {"email", "sms", "phone_call", "wecom_im"},
        )
        self.assertFalse(live_pilot_metadata["batch_send_enabled"])
        self.assertFalse(approved_provider_metadata["batch_send_enabled"])
        self.assertFalse(approved_provider_metadata["bulk_send_enabled"])
        self.assertTrue(approved_provider_metadata["requires_provider_config"])
        self.assertTrue(approved_provider_metadata["requires_sandbox_pass"])
        self.assertTrue(approved_provider_metadata["requires_operator_action_audit"])
        self.assertFalse(live_pilot_metadata["provider_call_enabled"])
        self.assertFalse(live_pilot_metadata["real_provider_call_enabled"])
        self.assertFalse(approved_provider_metadata["provider_call_enabled"])
        self.assertFalse(approved_provider_metadata["real_provider_call_enabled"])
        self.assertEqual(
            approved_provider_metadata["provider_adapter_scope"],
            "LOCAL_CONTROLLED_FAKE_PROVIDER",
        )
        self.assertFalse(live_pilot_metadata["real_send_attempted"])
        self.assertFalse(approved_provider_metadata["real_send_attempted"])
        self.assertFalse(live_pilot_metadata["stage9_payment_delivery_refund_enabled"])
        self.assertFalse(live_pilot_metadata["automated_refund_enabled"])
        self.assertFalse(app.state.transport_bootstrap["entry_strategy"]["stage8_live_pilot"]["real_send_attempted"])
        self.assertFalse(
            app.state.transport_bootstrap["entry_strategy"]["stage8_approved_provider_execution"][
                "real_send_attempted"
            ]
        )

        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage8 = result["stage8"]
        persist_stage_bundle(stage8)
        opportunity_id = stage8.record("touch_record").get("opportunity_id")

        client = TestClient(app)
        response = client.request("GET", "/contact-targets", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "outreach_workbench")
        self.assertTrue(payload["blocked_by_default"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertTrue(payload["outreach_execution_outbox"]["execution_id"].startswith("EXEC-"))
        self.assertEqual(payload["outreach_execution_outbox"]["adapter_family"], "email")
        self.assertEqual(payload["outreach_execution_outbox"]["pilot_scope"], "small_sample")
        self.assertFalse(payload["outreach_execution_outbox"]["batch_send_enabled"])
        self.assertEqual(payload["outreach_execution_outbox"]["live_pilot_readiness_state"], "BLOCKED")
        self.assertFalse(payload["outreach_execution_outbox"]["approved_provider_execution_enabled"])
        self.assertEqual(payload["outreach_execution_outbox"]["execution_request_state"], "BLOCKED")
        self.assertIn("approved_provider_execution_summary", payload["outreach_execution_outbox"])
        self.assertIn("approved_provider_execution_summary", payload)
        self.assertIn("provider_result_readback", payload)
        self.assertIn("execution_timeline", payload)
        self.assertFalse(payload["outreach_execution_outbox"]["provider_result_readback"]["provider_call_executed"])
        self.assertIn("execution_timeline", payload["outreach_execution_outbox"])
        self.assertEqual(
            payload["outbox_readiness_summary"]["execution_id"],
            payload["outreach_execution_outbox"]["execution_id"],
        )
        self.assertIn("live_pilot_readiness_summary", payload["outbox_readiness_summary"])
        self.assertFalse(payload["outreach_execution_outbox"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertFalse(payload["outreach_execution_outbox"]["real_send_attempted"])
        self.assertFalse(payload["outreach_execution_outbox"]["external_delivery_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        self.assertIn("createOutreachPlan", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["contact_target"]["object_id"],
            stage8.record("contact_target").get("contact_target_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["outreach_plan"]["object_id"],
            stage8.record("outreach_plan").get("outreach_plan_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["touch_record"]["object_id"],
            stage8.record("touch_record").get("touch_record_id"),
        )

    def test_stage9_http_transport_reads_repository_backed_preview(self) -> None:
        result = run_internal_chain(load_fixture("internal_chain_happy.json"))
        stage9 = result["stage9"]
        persist_stage_bundle(stage9)
        opportunity_id = stage9.record("order_record").get("opportunity_id")

        client = TestClient(create_app())
        response = client.request("GET", "/orders", json={"opportunity_id": opportunity_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "order_delivery_workbench")
        self.assertTrue(payload["blocked_by_default"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY]["mode"], "SANDBOX_DRY_RUN_READBACK")
        self.assertFalse(payload["stage9_execution_ledger"]["provider_adapter_readiness"]["real_provider_call_enabled"])
        self.assertEqual(payload["operational_context_status"], "persisted")
        self.assertEqual(payload["operator_loop_projection"]["context_key"], "persisted_operational_context")
        self.assertEqual(payload["operator_loop_projection"]["workbench_replay_source"], "repository_readback")
        self.assertTrue(payload["operator_loop_projection"]["queue_materialized"])
        self.assertEqual(
            payload["operator_loop_projection"]["action_controls_source"],
            "persisted_operational_context.pending_actions",
        )
        self.assertEqual(payload["workbench_replay"]["replay_source"], "repository_readback")
        self.assertEqual(payload["surface_state"], payload["semantic_envelope"]["surface_state"])
        self.assertEqual(
            payload["semantic_envelope"]["surface_state_source"],
            "storage.repository_boundary._surface_state_for_bundle",
        )
        self.assertEqual(payload["capability_envelope"]["surface_capability_mode"], "INTERNAL_GOVERNED")
        self.assertIn("createOrder", payload["governance_envelope"]["action_availability"])
        self.assertEqual(
            payload["formal_object_refs"]["payment_record"]["object_id"],
            stage9.record("payment_record").get("payment_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["delivery_record"]["object_id"],
            stage9.record("delivery_record").get("delivery_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["opportunity_outcome_event"]["object_id"],
            stage9.record("opportunity_outcome_event").get("outcome_event_id"),
        )
        self.assertEqual(
            payload["formal_object_refs"]["governance_feedback_event"]["object_id"],
            stage9.record("governance_feedback_event").get("governance_feedback_event_id"),
        )
        self.assertEqual(
            payload["stage9_execution_ledger"]["order_id"],
            stage9.record("order_record").get("order_id"),
        )
        self.assertTrue(payload["stage9_execution_ledger_readiness"]["owner_operable"])
        self.assertTrue(payload["stage9_execution_ledger_readiness"]["payment_recording_enabled"])
        self.assertTrue(payload["stage9_execution_ledger_readiness"]["delivery_recording_enabled"])
        self.assertFalse(payload["stage9_execution_ledger_readiness"]["automated_refund_enabled"])
        self.assertEqual(
            payload["payment_sandbox_provider_records"],
            stage9.record("payment_record").get("payment_sandbox_provider_records"),
        )
        self.assertEqual(
            payload["delivery_sandbox_provider_records"],
            stage9.record("delivery_record").get("delivery_sandbox_provider_records"),
        )
        self.assertEqual(
            payload["manual_refund_exception_record"],
            stage9.record("payment_record").get("manual_refund_exception_record"),
        )
        self.assertEqual(
            payload["payment_delivery_live_pilot"],
            stage9.inputs["payment_delivery_live_pilot"],
        )
        self.assertEqual(
            payload["preview_projection"]["payment_delivery_live_pilot_preview"],
            stage9.inputs["payment_delivery_live_pilot"],
        )
        self.assertEqual(
            payload["approved_payment_delivery_execution"],
            stage9.inputs["approved_payment_delivery_execution"],
        )
        self.assertEqual(
            payload["preview_projection"]["approved_payment_delivery_execution_preview"],
            stage9.inputs["approved_payment_delivery_execution"],
        )
        self.assertFalse(
            payload["approved_payment_delivery_execution"][
                "approved_payment_delivery_execution_enabled"
            ]
        )
        self.assertFalse(payload["approved_payment_delivery_execution"]["provider_call_executed"])
        self.assertFalse(payload["approved_payment_delivery_execution"]["real_refund_attempted"])
        self.assertFalse(
            payload["approved_payment_delivery_execution"]["automated_refund_program"]["enabled"]
        )
        self.assertFalse(payload["payment_delivery_live_pilot"]["payment_provider_result_readback"]["provider_call_executed"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["delivery_provider_result_readback"]["provider_call_executed"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["real_charge_attempted"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["real_delivery_fulfillment_attempted"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["real_refund_attempted"])
        self.assertFalse(payload["payment_delivery_live_pilot"]["automated_refund_program"]["enabled"])
        self.assertFalse(
            payload["payment_sandbox_provider_records"]["charge_status_callback_sandbox_record"][
                "payment_capture_enabled"
            ]
        )
        self.assertFalse(
            payload["delivery_sandbox_provider_records"]["delivery_provider_sandbox_record"][
                "real_delivery_fulfillment_attempted"
            ]
        )
        self.assertFalse(
            payload["order_payment_delivery_execution_summary"]["real_payment_gateway_enabled"]
        )


if __name__ == "__main__":
    unittest.main()
