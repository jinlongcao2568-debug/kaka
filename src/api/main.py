# Stage: api
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from api.deps import get_database_session, get_settings
from api.routes.stage1 import register_stage1_routes
from api.routes.stage2 import register_stage2_routes
from api.routes.stage3 import register_stage3_routes
from api.routes.stage4 import register_stage4_routes
from api.routes.stage5 import register_stage5_routes
from api.routes.stage6 import register_stage6_routes
from api.routes.stage7 import register_stage7_routes
from api.routes.stage8 import register_stage8_routes
from api.routes.stage9 import register_stage9_routes


RouteHandler = Callable[[Any], Any]
MOUNTED_OPERATION_READBACK_KEYS = (
    "operationId",
    "method",
    "path",
    "surface_mode",
    "internal_only",
    "live_execution_enabled",
    "candidate_only",
    "external_delivery_enabled",
    "requires_review",
)


def _coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


async def _request_payload(request: Request) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    body = await request.body()
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"invalid json body: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")
        payload.update(parsed)

    payload.update({key: _coerce_scalar(value) for key, value in request.query_params.items()})
    payload.update({key: value for key, value in request.path_params.items()})
    return payload


def _endpoint_for(route: dict[str, Any]) -> Callable[[Request], Any]:
    handler: RouteHandler = route["handler"]

    async def endpoint(request: Request) -> Any:
        payload = await _request_payload(request)
        try:
            return handler(payload)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    endpoint.__name__ = route["operationId"]
    endpoint.__doc__ = f"Transport wrapper for {route['operationId']}."
    return endpoint


def _mount_routes(app: FastAPI, routes: list[dict[str, Any]]) -> None:
    for route in routes:
        app.add_api_route(
            route["path"],
            _endpoint_for(route),
            methods=[route["method"]],
            name=route["operationId"],
            operation_id=route["operationId"],
        )


def _stage_transport_readback(stage_transports: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        stage_name: [dict(transport_state) for transport_state in transport_states]
        for stage_name, transport_states in stage_transports.items()
    }


def _mounted_operation_readback(stage_scope: int, route: dict[str, Any]) -> dict[str, Any]:
    operation = {
        key: route[key]
        for key in MOUNTED_OPERATION_READBACK_KEYS
        if key in route
    }
    operation["stage_scope"] = stage_scope
    operation["blocked_by_default"] = bool(route.get("blocked_by_default", False))
    return operation


def _mounted_operations_readback(
    mounted_stage_routes: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for stage_name, routes in mounted_stage_routes.items():
        stage_scope = int(stage_name.removeprefix("stage"))
        operations.extend(_mounted_operation_readback(stage_scope, route) for route in routes)
    return operations


def _operation_ids_by_stage(mounted_stage_routes: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        stage_name: [route["operationId"] for route in routes]
        for stage_name, routes in mounted_stage_routes.items()
    }


def _build_transport_bootstrap(
    disabled_stage_transports: dict[str, list[dict[str, Any]]],
    mounted_stage_routes: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    operation_ids_by_stage = _operation_ids_by_stage(mounted_stage_routes)
    return {
        "internal_only": True,
        "live_execution_enabled": False,
        "stage1_to_stage5_transport_state": _stage_transport_readback(disabled_stage_transports),
        "stage6_to_stage9_mounted_operations": _mounted_operations_readback(mounted_stage_routes),
        "entry_strategy": {
            "stage1_to_stage5": {
                "current_entry": "controlled-unavailable readback only",
                "http_entry_enabled": False,
                "real_transport_enabled": False,
                "source": "stage1-stage5 transport registrars",
            },
            "stage6": {
                "current_entry": "repository-backed preview / workbench mounted transport",
                "http_entry_enabled": True,
                "mounted_operations": operation_ids_by_stage["stage6"],
            },
            "stage7_to_stage9": {
                "current_entry": "internal governed preview / draft workbench mounted transport",
                "http_entry_enabled": True,
                "mounted_operations_by_stage": {
                    stage_name: operation_ids_by_stage[stage_name]
                    for stage_name in ("stage7", "stage8", "stage9")
                },
            },
            "stage1_to_stage6_full_chain_entry": {
                "current_entry": "bootstrap/readback strategy only",
                "executes_stage1_to_stage5_transport": False,
                "executes_real_orchestrator": False,
                "mounted_entry_stage": 6,
            },
        },
        "redlines": {
            "new_http_endpoint_added": False,
            "stage1_to_stage5_real_transport_enabled": False,
            "external_software_release_enabled": False,
            "external_leadpack_delivery_requires_approval_and_audit": True,
            "stage8_real_execution_enabled": False,
            "stage9_real_payment_delivery_refund_enabled": False,
        },
    }


def create_app() -> FastAPI:
    settings = get_settings()
    storage_session = get_database_session()
    app = FastAPI(
        title="AX9S Internal Preview API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.storage_session = storage_session
    app.state.storage_bootstrap = settings.storage_bootstrap_payload()
    app.state.disabled_stage_transports = {
        "stage1": register_stage1_routes(),
        "stage2": register_stage2_routes(),
        "stage3": register_stage3_routes(),
        "stage4": register_stage4_routes(),
        "stage5": register_stage5_routes(),
    }
    mounted_stage_routes = {
        "stage6": register_stage6_routes(),
        "stage7": register_stage7_routes(),
        "stage8": register_stage8_routes(),
        "stage9": register_stage9_routes(),
    }
    mounted_routes = [
        route
        for stage_routes in mounted_stage_routes.values()
        for route in stage_routes
    ]
    _mount_routes(app, mounted_routes)
    app.state.mounted_transport_operations = [route["operationId"] for route in mounted_routes]
    app.state.transport_bootstrap = _build_transport_bootstrap(
        app.state.disabled_stage_transports,
        mounted_stage_routes,
    )
    return app


__all__ = ["create_app"]
