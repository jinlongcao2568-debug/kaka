# Stage: api
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

from api.deps import get_settings
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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AX9S Internal Preview API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.storage_bootstrap = settings.storage_bootstrap_payload()
    app.state.disabled_stage_transports = {
        "stage1": register_stage1_routes(),
        "stage2": register_stage2_routes(),
        "stage3": register_stage3_routes(),
        "stage4": register_stage4_routes(),
        "stage5": register_stage5_routes(),
    }
    mounted_routes = (
        register_stage6_routes()
        + register_stage7_routes()
        + register_stage8_routes()
        + register_stage9_routes()
    )
    _mount_routes(app, mounted_routes)
    app.state.mounted_transport_operations = [route["operationId"] for route in mounted_routes]
    return app


__all__ = ["create_app"]
