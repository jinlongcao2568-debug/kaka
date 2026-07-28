from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from api.main import create_app
from shared.product_onboarding_config import (
    AUDIT_OBJECT_TYPE,
    ProductOnboardingAccessError,
    ProductOnboardingConflictError,
    ProductOnboardingInputError,
    list_product_onboarding_configs,
    mutate_product_onboarding_config,
    run_product_onboarding_offline_test,
)
from shared.settings import Settings
from storage.db import DatabaseSession
from storage_test_support import IsolatedStorageTestMixin


def _actor(tenant: str = "customer-a", role: str = "owner") -> dict:
    return {
        "authenticated": True,
        "principal_id": f"{role}-principal",
        "role": role,
        "permissions": ["internal_product_config"] if role in {"owner", "admin"} else [],
        "deployment_tenant_id": tenant,
    }


def _draft(**overrides: object) -> dict:
    payload: dict = {
        "action": "UPSERT_DRAFT",
        "profile_id": "default-pilot",
        "profile_name": "广东私有试点默认配置",
        "region_codes": ["CN-GD"],
        "industry_code": "CONSTRUCTION_PUBLIC_EVIDENCE",
        "evidence_template_id": "SKU_B_PUBLIC_SOURCE_FOUR_FIELD_RISK_REVIEW",
        "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
        "budgets": {
            "discovery_candidate_limit": 10,
            "detail_capture_limit": 3,
            "attachment_capture_limit": 6,
            "job_time_budget_seconds": 600,
        },
        "_internal_auth_context": _actor(),
    }
    payload.update(overrides)
    return payload


class ProductOnboardingConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.session = DatabaseSession(
            settings=Settings(
                storage_path_optional=str(Path(self.tmp.name) / "onboarding.json"),
                storage_scope="process",
                storage_runtime_mode="explicit-path",
            )
        )

    def tearDown(self) -> None:
        self.session.close()
        self.tmp.cleanup()

    def test_versioned_test_activate_update_and_rollback_flow(self) -> None:
        draft = mutate_product_onboarding_config(_draft(), session=self.session)
        self.assertEqual(draft["operation_state"], "DRAFT_CREATED")
        self.assertEqual(draft["profile"]["version"], 1)
        self.assertEqual(draft["profile"]["state"], "DRAFT_VALIDATED")
        self.assertIsNone(draft["active_profile"])

        with self.assertRaisesRegex(ProductOnboardingConflictError, "passing offline test"):
            mutate_product_onboarding_config(
                {
                    "action": "ACTIVATE",
                    "profile_id": "default-pilot",
                    "expected_version": 1,
                    "_internal_auth_context": _actor(),
                },
                session=self.session,
            )

        test_run = run_product_onboarding_offline_test(
            {
                "profile_id": "default-pilot",
                "version": 1,
                "mode": "OFFLINE_VALIDATION",
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        self.assertEqual(test_run["test_state"], "PASSED")
        self.assertFalse(test_run["test_run"]["task_created"])
        self.assertFalse(test_run["test_run"]["fetch_executed"])
        self.assertFalse(test_run["execution_projection"]["live_source_enabled"])
        self.assertFalse(test_run["execution_projection"]["approval_bypass_enabled"])

        activated_v2 = mutate_product_onboarding_config(
            {
                "action": "ACTIVATE",
                "profile_id": "default-pilot",
                "expected_version": 1,
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        self.assertEqual(activated_v2["profile"]["version"], 2)
        self.assertEqual(activated_v2["profile"]["state"], "ACTIVE")
        self.assertEqual(activated_v2["active_profile"]["active_version"], 2)

        changed = _draft(
            expected_version=2,
            budgets={
                "discovery_candidate_limit": 12,
                "detail_capture_limit": 4,
                "attachment_capture_limit": 8,
                "job_time_budget_seconds": 900,
            },
        )
        draft_v3 = mutate_product_onboarding_config(changed, session=self.session)
        self.assertEqual(draft_v3["profile"]["version"], 3)
        self.assertEqual(draft_v3["active_profile"]["active_version"], 2)
        run_product_onboarding_offline_test(
            {
                "profile_id": "default-pilot",
                "version": 3,
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        activated_v4 = mutate_product_onboarding_config(
            {
                "action": "ACTIVATE",
                "profile_id": "default-pilot",
                "expected_version": 3,
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        self.assertEqual(activated_v4["profile"]["version"], 4)

        rollback_v5 = mutate_product_onboarding_config(
            {
                "action": "ROLLBACK",
                "profile_id": "default-pilot",
                "expected_version": 4,
                "target_version": 2,
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        self.assertEqual(rollback_v5["profile"]["version"], 5)
        self.assertEqual(rollback_v5["profile"]["state"], "ACTIVE_ROLLBACK")
        self.assertEqual(rollback_v5["profile"]["rollback_target_version"], 2)
        self.assertEqual(
            rollback_v5["profile"]["config"]["budgets"]["discovery_candidate_limit"],
            10,
        )

        readback = list_product_onboarding_configs(
            {
                "profile_id": "default-pilot",
                "include_history": True,
                "_internal_auth_context": _actor(),
            },
            session=self.session,
        )
        self.assertEqual(readback["count"], 1)
        self.assertEqual(readback["active_profile"]["active_version"], 5)
        self.assertEqual(
            [item["version"] for item in readback["profiles"][0]["history"]],
            [5, 4, 3, 2, 1],
        )
        audit_payload = " ".join(
            json.dumps(record.payload, ensure_ascii=False)
            for record in self.session.list_records(AUDIT_OBJECT_TYPE)
        )
        self.assertNotIn("广东私有试点默认配置", audit_payload)
        self.assertIn('"raw_config_persisted_in_audit": false', audit_payload)

    def test_unregistered_scope_budget_secret_and_live_override_are_rejected(self) -> None:
        invalid_payloads = [
            _draft(region_codes=["CN-SH"]),
            _draft(source_profile_ids=["SICHUAN-GGZY-TRANSACTION-INFO"]),
            _draft(
                budgets={
                    "discovery_candidate_limit": 31,
                    "detail_capture_limit": 3,
                    "attachment_capture_limit": 6,
                    "job_time_budget_seconds": 600,
                }
            ),
            _draft(industry_code="ALL_INDUSTRIES"),
            _draft(profile_name="api_key=must-not-store"),
            _draft(live_source_enabled=True),
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ProductOnboardingInputError):
                    mutate_product_onboarding_config(payload, session=self.session)
        self.assertEqual(
            list_product_onboarding_configs(
                {"_internal_auth_context": _actor()}, session=self.session
            )["count"],
            0,
        )

    def test_version_conflict_tenant_isolation_and_role_permission(self) -> None:
        mutate_product_onboarding_config(_draft(), session=self.session)
        with self.assertRaisesRegex(ProductOnboardingConflictError, "version conflict"):
            mutate_product_onboarding_config(
                _draft(expected_version=9), session=self.session
            )
        tenant_b = list_product_onboarding_configs(
            {"_internal_auth_context": _actor("customer-b")}, session=self.session
        )
        self.assertEqual(tenant_b["count"], 0)
        with self.assertRaises(ProductOnboardingAccessError):
            list_product_onboarding_configs(
                {"_internal_auth_context": _actor(role="operator")},
                session=self.session,
            )


class ProductOnboardingConfigApiTests(unittest.TestCase, IsolatedStorageTestMixin):
    def setUp(self) -> None:
        self.setUp_storage_test_env(storage_filename="product-onboarding-api.json")
        self.client = TestClient(create_app())
        self.owner_headers = {
            "X-Kaka-Test-Operator-Auth": "approved",
            "X-Kaka-Test-Principal-Id": "product-owner",
            "X-Kaka-Test-Role": "owner",
        }

    def tearDown(self) -> None:
        self.client.close()
        self.tearDown_storage_test_env()

    def test_owner_api_requires_offline_test_before_activation(self) -> None:
        empty = self.client.get(
            "/operator-console/onboarding/configs?include_history=true",
            headers=self.owner_headers,
        )
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["count"], 0)
        payload = _draft()
        payload.pop("_internal_auth_context")
        created = self.client.post(
            "/operator-console/onboarding/configs",
            headers=self.owner_headers,
            json=payload,
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["profile"]["version"], 1)
        blocked = self.client.post(
            "/operator-console/onboarding/configs",
            headers=self.owner_headers,
            json={
                "action": "ACTIVATE",
                "profile_id": "default-pilot",
                "expected_version": 1,
            },
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(
            blocked.json()["detail"]["code"],
            "PRODUCT_ONBOARDING_CONFIG_STATE_CONFLICT",
        )
        tested = self.client.post(
            "/operator-console/onboarding/config-test-runs",
            headers=self.owner_headers,
            json={
                "profile_id": "default-pilot",
                "version": 1,
                "mode": "OFFLINE_VALIDATION",
            },
        )
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(tested.json()["test_state"], "PASSED")
        self.assertFalse(tested.json()["test_run"]["fetch_executed"])
        activated = self.client.post(
            "/operator-console/onboarding/configs",
            headers=self.owner_headers,
            json={
                "action": "ACTIVATE",
                "profile_id": "default-pilot",
                "expected_version": 1,
            },
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json()["active_profile"]["active_version"], 2)

    def test_operator_and_unregistered_source_are_rejected(self) -> None:
        operator_headers = {
            "X-Kaka-Test-Operator-Auth": "approved",
            "X-Kaka-Test-Principal-Id": "ordinary-operator",
            "X-Kaka-Test-Role": "operator",
        }
        denied = self.client.get(
            "/operator-console/onboarding/configs",
            headers=operator_headers,
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        payload = _draft(source_profile_ids=["CUSTOM-UNREGISTERED-SOURCE"])
        payload.pop("_internal_auth_context")
        invalid = self.client.post(
            "/operator-console/onboarding/configs",
            headers=self.owner_headers,
            json=payload,
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(
            invalid.json()["detail"]["code"],
            "INVALID_PRODUCT_ONBOARDING_CONFIG",
        )


if __name__ == "__main__":
    unittest.main()
