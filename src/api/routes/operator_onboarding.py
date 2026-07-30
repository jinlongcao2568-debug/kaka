# Stage: api_operator_product_onboarding
# Consumes formal objects: product onboarding profile versions and active pointer
# Dependent handoff: internal private-pilot configuration only
# Dependent schema/contracts: contracts/governance/product_onboarding_config_contract.json

from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException

from api.projections import register_route_table
from shared.product_onboarding_config import (
    ProductOnboardingAccessError,
    ProductOnboardingConflictError,
    ProductOnboardingInputError,
    list_product_onboarding_configs,
    mutate_product_onboarding_config,
    run_product_onboarding_offline_test,
)


OPERATOR_ONBOARDING_ROUTE_METADATA = {
    "surface_mode": "internal-private-single-tenant-configuration",
    "internal_only": True,
    "private_single_tenant_only": True,
    "customer_self_service": False,
    "live_execution_enabled": False,
    "external_release_enabled": False,
    "provider_call_enabled": False,
    "real_external_fetch_enabled": False,
    "source_allowlist_override_enabled": False,
    "approval_bypass_enabled": False,
}


def _raise_product_onboarding_error(exc: ValueError) -> None:
    if isinstance(exc, ProductOnboardingAccessError):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INTERNAL_PRODUCT_CONFIG_PERMISSION_DENIED",
                "message": str(exc),
            },
        ) from exc
    if isinstance(exc, ProductOnboardingConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PRODUCT_ONBOARDING_CONFIG_STATE_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    raise HTTPException(
        status_code=400,
        detail={
            "code": "INVALID_PRODUCT_ONBOARDING_CONFIG",
            "message": str(exc),
        },
    ) from exc


def list_operator_product_onboarding_configs(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return list_product_onboarding_configs(payload)
    except (
        ProductOnboardingAccessError,
        ProductOnboardingConflictError,
        ProductOnboardingInputError,
    ) as exc:
        _raise_product_onboarding_error(exc)
    raise AssertionError("unreachable")


def mutate_operator_product_onboarding_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return mutate_product_onboarding_config(payload)
    except (
        ProductOnboardingAccessError,
        ProductOnboardingConflictError,
        ProductOnboardingInputError,
    ) as exc:
        _raise_product_onboarding_error(exc)
    raise AssertionError("unreachable")


def run_operator_product_onboarding_config_test(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return run_product_onboarding_offline_test(payload)
    except (
        ProductOnboardingAccessError,
        ProductOnboardingConflictError,
        ProductOnboardingInputError,
    ) as exc:
        _raise_product_onboarding_error(exc)
    raise AssertionError("unreachable")


OPERATOR_ONBOARDING_ROUTES = [
    {
        "operationId": "listProductOnboardingConfigs",
        "method": "GET",
        "path": "/operator-console/onboarding/configs",
        "handler": list_operator_product_onboarding_configs,
        **OPERATOR_ONBOARDING_ROUTE_METADATA,
    },
    {
        "operationId": "mutateProductOnboardingConfig",
        "method": "POST",
        "path": "/operator-console/onboarding/configs",
        "handler": mutate_operator_product_onboarding_config,
        "explicit_operator_action": True,
        "raw_json_required": False,
        **OPERATOR_ONBOARDING_ROUTE_METADATA,
    },
    {
        "operationId": "runProductOnboardingConfigTest",
        "method": "POST",
        "path": "/operator-console/onboarding/config-test-runs",
        "handler": run_operator_product_onboarding_config_test,
        "explicit_operator_action": True,
        "raw_json_required": False,
        "offline_validation_only": True,
        **OPERATOR_ONBOARDING_ROUTE_METADATA,
    },
]


def register_operator_onboarding_routes(router: object | None = None) -> list[dict[str, Any]]:
    return register_route_table(router, OPERATOR_ONBOARDING_ROUTES)


__all__ = [
    "OPERATOR_ONBOARDING_ROUTES",
    "list_operator_product_onboarding_configs",
    "mutate_operator_product_onboarding_config",
    "register_operator_onboarding_routes",
    "run_operator_product_onboarding_config_test",
]
