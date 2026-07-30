from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from runtime.production_release_orchestrator import (
    ProductionReleaseConfig,
    approve_production_release,
    build_production_release_readiness,
    production_alert_dispatch_readiness,
    request_production_release,
    suspend_production_release,
)
from shared.settings import Settings
from stage9_delivery.production_execution import (
    CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE,
    PAYMENT_PROVIDER_EVENT_OBJECT_TYPE,
    PRODUCTION_REFUND_REQUEST_OBJECT_TYPE,
    StripeApiClient,
    StripeApiConfig,
    approve_and_execute_production_refund,
    authorize_customer_session,
    create_production_payment,
    issue_customer_artifact_grant,
    process_stripe_webhook,
    read_customer_artifact,
    request_production_refund,
    revoke_customer_artifact_grant,
    validate_production_delivery_source,
)
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository
from api.routes.operator_frontend import build_approved_evidence_package_artifact


CUSTOMER_SESSION_COOKIE = "kaka_customer_access"


class ProductionReleaseRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=1000)
    evidence_refs: list[str] = Field(min_length=3, max_length=100)


class ProductionReleaseApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_readiness_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    approval_note: str = Field(min_length=10, max_length=1000)


class ProductionReleaseSuspensionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=1000)


class ProductionPaymentRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=3, max_length=128)
    amount_minor: int = Field(ge=100, le=100_000_000)
    currency: str = Field(pattern=r"^(cny|usd)$")
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]+$",
    )


class ProductionRefundRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: str = Field(min_length=3, max_length=128)
    amount_minor: int = Field(ge=1, le=100_000_000)
    reason: str = Field(min_length=10, max_length=500)


class ProductionCustomerDeliveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: str = Field(min_length=3, max_length=128)
    opportunity_id: str = Field(min_length=3, max_length=128)
    customer_subject: str = Field(min_length=3, max_length=320)
    expires_in_seconds: int = Field(default=86400, ge=300, le=2_592_000)
    max_downloads: int = Field(default=3, ge=1, le=20)


class ProductionGrantRevocationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=500)


class CustomerSessionRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=40, max_length=8192)
    access_code: str = Field(pattern=r"^\d{8}$")


def _auth_context(request: Request) -> dict[str, Any]:
    return dict(getattr(request.state, "internal_auth_context", {}) or {})


def _require_permission(request: Request, permission: str) -> dict[str, Any]:
    actor = _auth_context(request)
    if (
        not actor.get("authenticated")
        or permission not in set(actor.get("permissions") or [])
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INTERNAL_API_PERMISSION_DENIED",
                "required_permission": permission,
            },
        )
    return actor


def register_production_release_routes(
    app: FastAPI,
    *,
    settings: Settings,
    session: DatabaseSession,
    provider_summary: dict[str, Any],
) -> list[str]:
    config = ProductionReleaseConfig.from_env(settings=settings)
    app.state.production_release_config = config

    def production_object_repository() -> ObjectStorageRepository:
        return ObjectStorageRepository(session=session, settings=settings)

    def current_readiness() -> dict[str, Any]:
        return build_production_release_readiness(
            config=config,
            settings=settings,
            provider_summary=provider_summary,
            session=session,
            alert_readiness=production_alert_dispatch_readiness(),
        )

    @app.get(
        "/production/operations",
        operation_id="readProductionOperations",
    )
    async def read_production_operations(
        request: Request,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        _require_permission(request, "internal_api_access")
        readiness = current_readiness()
        payments = [
            _production_payment_readback(record.payload)
            for record in session.list_records("payment_record")
            if str(record.payload.get("governed_execution_mode") or "")
            == "PROD_LIVE_MODE"
        ][-limit:]
        refunds = [
            _production_refund_readback(record.payload)
            for record in session.list_records(
                PRODUCTION_REFUND_REQUEST_OBJECT_TYPE
            )
        ][-limit:]
        grants = [
            _production_grant_readback(record.payload)
            for record in session.list_records(
                CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE
            )
        ][-limit:]
        events = [
            _production_provider_event_readback(record.payload)
            for record in session.list_records(PAYMENT_PROVIDER_EVENT_OBJECT_TYPE)
        ][-limit:]
        return {
            "release": {
                "release_id": readiness.get("release_id"),
                "release_version": readiness.get("release_version"),
                "state": readiness.get("state"),
                "release_active": bool(readiness.get("release_active")),
                "readiness_hash": readiness.get("readiness_hash"),
            },
            "summary": {
                "payment_count": len(payments),
                "paid_and_reconciled_count": sum(
                    1
                    for item in payments
                    if item["payment_status"] == "PAID"
                    and item["reconciliation_state"] == "MATCHED"
                ),
                "payment_exception_count": sum(
                    1
                    for item in payments
                    if item["payment_status"] == "PAYMENT_EXCEPTION"
                    or item["reconciliation_state"]
                    in {"MISMATCH_REVIEW_REQUIRED", "PENDING_CALLBACK"}
                ),
                "refund_pending_count": sum(
                    1
                    for item in refunds
                    if item["state"] in {"PENDING_APPROVAL", "REFUND_SUBMITTED"}
                ),
                "active_delivery_grant_count": sum(
                    1 for item in grants if item["status"] == "ACTIVE"
                ),
                "provider_event_review_count": sum(
                    1
                    for item in events
                    if "REVIEW_REQUIRED" in item["state"]
                ),
            },
            "payments": payments,
            "refunds": refunds,
            "delivery_grants": grants,
            "provider_events": events,
            "raw_provider_payload_persisted": False,
            "customer_access_secret_persisted": False,
        }

    @app.get(
        "/production/readiness",
        operation_id="readProductionReleaseReadiness",
    )
    async def read_production_release_readiness(request: Request) -> dict[str, Any]:
        _require_permission(request, "internal_api_access")
        return current_readiness()

    @app.post(
        "/production/releases/requests",
        status_code=201,
        operation_id="requestProductionRelease",
    )
    async def create_production_release_request(
        request: Request,
        body: ProductionReleaseRequestBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_release_request")
        try:
            return request_production_release(
                config=config,
                settings=settings,
                provider_summary=provider_summary,
                session=session,
                actor=actor,
                reason=body.reason,
                evidence_refs=body.evidence_refs,
                alert_readiness=production_alert_dispatch_readiness(),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/releases/{request_id}/approve",
        operation_id="approveProductionRelease",
    )
    async def approve_production_release_request(
        request_id: str,
        request: Request,
        body: ProductionReleaseApprovalBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_release_approve")
        try:
            return approve_production_release(
                request_id=request_id,
                expected_readiness_hash=body.expected_readiness_hash,
                config=config,
                settings=settings,
                provider_summary=provider_summary,
                session=session,
                actor=actor,
                approval_note=body.approval_note,
                alert_readiness=production_alert_dispatch_readiness(),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/releases/{request_id}/suspend",
        operation_id="suspendProductionRelease",
    )
    async def suspend_production_release_request(
        request_id: str,
        request: Request,
        body: ProductionReleaseSuspensionBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_release_suspend")
        try:
            return suspend_production_release(
                request_id=request_id,
                session=session,
                actor=actor,
                reason=body.reason,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/payments",
        status_code=201,
        operation_id="createProductionPayment",
    )
    async def create_production_payment_request(
        request: Request,
        body: ProductionPaymentRequestBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_payment_execute")
        try:
            return await run_in_threadpool(
                create_production_payment,
                order_id=body.order_id,
                amount_minor=body.amount_minor,
                currency=body.currency,
                idempotency_key=body.idempotency_key,
                config=config,
                release_readiness=current_readiness(),
                session=session,
                actor=actor,
                client=StripeApiClient(StripeApiConfig.from_env()),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/refunds/requests",
        status_code=201,
        operation_id="requestProductionRefund",
    )
    async def create_production_refund_request(
        request: Request,
        body: ProductionRefundRequestBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_refund_request")
        try:
            return request_production_refund(
                payment_id=body.payment_id,
                amount_minor=body.amount_minor,
                reason=body.reason,
                config=config,
                release_readiness=current_readiness(),
                session=session,
                actor=actor,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/refunds/requests/{refund_request_id}/approve",
        operation_id="approveProductionRefund",
    )
    async def approve_production_refund_request(
        refund_request_id: str,
        request: Request,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_refund_approve")
        try:
            return await run_in_threadpool(
                approve_and_execute_production_refund,
                refund_request_id=refund_request_id,
                config=config,
                release_readiness=current_readiness(),
                session=session,
                actor=actor,
                client=StripeApiClient(StripeApiConfig.from_env()),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/deliveries/grants",
        status_code=201,
        operation_id="issueProductionCustomerDelivery",
    )
    async def issue_production_customer_delivery(
        request: Request,
        body: ProductionCustomerDeliveryBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_delivery_issue")
        try:
            def issue_delivery() -> dict[str, Any]:
                object_repository = production_object_repository()
                validate_production_delivery_source(
                    payment_id=body.payment_id,
                    opportunity_id=body.opportunity_id,
                    session=session,
                )
                approved_artifact = build_approved_evidence_package_artifact(
                    {
                        "opportunity_id": body.opportunity_id,
                        "_internal_auth_context": actor,
                    }
                )
                bundle = dict(approved_artifact["bundle"])
                artifact = object_repository.put_object(
                    bytes(bundle["bytes"]),
                    content_type=str(bundle["media_type"]),
                    object_key=f"customer-artifacts/{bundle['bundle_sha256']}.zip",
                )
                issued = issue_customer_artifact_grant(
                    payment_id=body.payment_id,
                    source_opportunity_id=body.opportunity_id,
                    artifact_object_key=artifact.object_key,
                    artifact_sha256=artifact.sha256,
                    customer_subject=body.customer_subject,
                    expires_in_seconds=body.expires_in_seconds,
                    max_downloads=body.max_downloads,
                    release_readiness=current_readiness(),
                    config=config,
                    session=session,
                    object_repository=object_repository,
                    actor=actor,
                )
                issued["source_opportunity_id"] = body.opportunity_id
                issued["approved_package_scope_sha256"] = approved_artifact[
                    "bundle_sha256"
                ]
                return issued

            return await run_in_threadpool(issue_delivery)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/deliveries/grants/{grant_id}/revoke",
        operation_id="revokeProductionCustomerDelivery",
    )
    async def revoke_production_customer_delivery(
        grant_id: str,
        request: Request,
        body: ProductionGrantRevocationBody,
    ) -> dict[str, Any]:
        actor = _require_permission(request, "production_delivery_issue")
        try:
            return revoke_customer_artifact_grant(
                grant_id=grant_id,
                session=session,
                actor=actor,
                reason=body.reason,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/production/webhooks/payments/stripe",
        include_in_schema=False,
    )
    async def receive_stripe_payment_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        signature = str(request.headers.get("stripe-signature") or "")
        try:
            result = process_stripe_webhook(
                body=body,
                signature_header=signature,
                config=config,
                session=session,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = JSONResponse(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/customer/access", include_in_schema=False)
    async def customer_access_page() -> HTMLResponse:
        nonce = secrets.token_urlsafe(24)
        content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>客户交付验证</title>
  <style nonce="{nonce}">
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f4f6f8; color: #17202a; }}
    main {{ width: min(520px, calc(100% - 48px)); margin: 15vh auto 0; }}
    h1 {{ font-size: 24px; margin: 0 0 12px; }}
    p {{ color: #52606d; line-height: 1.7; }}
    form {{ display: grid; gap: 12px; margin-top: 24px; }}
    label {{ font-size: 14px; font-weight: 700; }}
    input {{ height: 44px; padding: 0 12px; border: 1px solid #9aa5b1; border-radius: 4px; font-size: 18px; letter-spacing: 0; }}
    button {{ height: 44px; border: 0; border-radius: 4px; background: #176b4d; color: #fff; font-weight: 700; cursor: pointer; }}
    #status[data-error="true"] {{ color: #b42318; }}
  </style>
</head>
<body>
<main>
  <h1>客户交付验证</h1>
  <p id="status" role="status">请输入服务人员通过独立渠道提供的 8 位访问码。</p>
  <form id="access-form">
    <label for="access-code">访问码</label>
    <input id="access-code" name="access-code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{8}}" maxlength="8" required>
    <button type="submit">验证并下载</button>
  </form>
</main>
<script nonce="{nonce}">
const statusNode = document.getElementById("status");
const formNode = document.getElementById("access-form");
const token = window.location.hash.slice(1);
window.history.replaceState(null, "", "/customer/access");
if (!token) {{
  formNode.hidden = true;
  statusNode.dataset.error = "true";
  statusNode.textContent = "交付凭据缺失";
}}
formNode.addEventListener("submit", async (event) => {{
  event.preventDefault();
  try {{
    const accessCode = document.getElementById("access-code").value;
    const response = await fetch("/customer/session", {{
      method: "POST",
      credentials: "same-origin",
      headers: {{ "content-type": "application/json" }},
      body: JSON.stringify({{ token, access_code: accessCode }})
    }});
    const result = await response.json();
    if (!response.ok || !result.artifact_path) throw new Error("交付凭据无效或已失效");
    window.location.replace(result.artifact_path);
  }} catch (error) {{
    statusNode.dataset.error = "true";
    statusNode.textContent = error instanceof Error ? error.message : "验证失败";
  }}
}});
</script>
</body>
</html>"""
        response = HTMLResponse(content)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "base-uri 'none'; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            f"script-src 'nonce-{nonce}'; "
            f"style-src 'nonce-{nonce}'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def customer_payment_status_page(*, title: str, message: str) -> HTMLResponse:
        nonce = secrets.token_urlsafe(24)
        content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>{title}</title>
  <style nonce="{nonce}">
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f4f6f8; color: #17202a; }}
    main {{ width: min(560px, calc(100% - 48px)); margin: 15vh auto 0; }}
    h1 {{ font-size: 24px; margin: 0 0 12px; }}
    p {{ color: #52606d; line-height: 1.7; }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p>{message}</p>
</main>
</body>
</html>"""
        response = HTMLResponse(content)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            f"style-src 'nonce-{nonce}'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/customer/payment/complete", include_in_schema=False)
    async def customer_payment_complete_page() -> HTMLResponse:
        return customer_payment_status_page(
            title="支付结果正在确认",
            message="支付平台已返回。系统会以签名回调和金额对账结果为准，确认后再签发交付权限。",
        )

    @app.get("/customer/payment/cancelled", include_in_schema=False)
    async def customer_payment_cancelled_page() -> HTMLResponse:
        return customer_payment_status_page(
            title="支付未完成",
            message="本次结账未完成，系统不会据此签发交付权限。可关闭本页并联系服务人员。",
        )

    @app.post("/customer/session", include_in_schema=False)
    async def create_customer_session(
        body: CustomerSessionRequestBody,
    ) -> JSONResponse:
        try:
            authorization = authorize_customer_session(
                token=body.token,
                access_code=body.access_code,
                config=config,
                session=session,
            )
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        grant_id = str(authorization["grant_id"])
        max_age = max(
            int(authorization["expires_at_unix"]) - int(time.time()),
            0,
        )
        response = JSONResponse(
            {
                "authenticated": True,
                "grant_id": grant_id,
                "artifact_path": f"/customer/artifacts/{grant_id}",
                "expires_at_unix": authorization["expires_at_unix"],
                "second_factor_verified": True,
            }
        )
        response.set_cookie(
            key=CUSTOMER_SESSION_COOKIE,
            value=body.token,
            max_age=max_age,
            path="/customer",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/customer/artifacts/{grant_id}", include_in_schema=False)
    async def download_customer_artifact(
        grant_id: str,
        request: Request,
    ) -> Response:
        token = str(request.cookies.get(CUSTOMER_SESSION_COOKIE) or "")
        if not token:
            raise HTTPException(status_code=401, detail="customer session required")
        try:
            def read_artifact() -> dict[str, Any]:
                object_repository = production_object_repository()
                return read_customer_artifact(
                    grant_id=grant_id,
                    token=token,
                    config=config,
                    release_readiness=current_readiness(),
                    session=session,
                    object_repository=object_repository,
                )

            artifact = await run_in_threadpool(
                read_artifact,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            artifact["bytes"],
            media_type=str(artifact["content_type"]),
            headers={
                "Content-Disposition": f'attachment; filename="evidence-package-{grant_id}.zip"',
                "X-Kaka-Bundle-SHA256": str(artifact["artifact_sha256"]),
                "X-Kaka-Delivery-ID": str(artifact["delivery_id"]),
                "Cache-Control": "no-store",
            },
        )

    @app.delete("/customer/session", include_in_schema=False)
    async def delete_customer_session() -> JSONResponse:
        response = JSONResponse({"authenticated": False, "session_deleted": True})
        response.delete_cookie(
            key=CUSTOMER_SESSION_COOKIE,
            path="/customer",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return [
        "readProductionReleaseReadiness",
        "readProductionOperations",
        "requestProductionRelease",
        "approveProductionRelease",
        "suspendProductionRelease",
        "createProductionPayment",
        "requestProductionRefund",
        "approveProductionRefund",
        "issueProductionCustomerDelivery",
        "revokeProductionCustomerDelivery",
    ]


def _production_payment_readback(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("governed_metadata") or {})
    return {
        "payment_id": payload.get("payment_id"),
        "order_id": payload.get("order_id"),
        "project_id": payload.get("project_id"),
        "payment_status": payload.get("payment_status"),
        "refund_state": payload.get("refund_state"),
        "amount_minor": int(metadata.get("amount_minor") or 0),
        "currency": metadata.get("currency"),
        "reconciliation_state": metadata.get("reconciliation_state"),
        "provider_status": metadata.get("provider_status"),
        "provider_event_type": metadata.get("provider_event_type"),
        "last_provider_callback_at": metadata.get("last_provider_callback_at"),
        "release_id": metadata.get("release_id"),
    }


def _production_refund_readback(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "refund_request_id": payload.get("refund_request_id"),
        "payment_id": payload.get("payment_id"),
        "order_id": payload.get("order_id"),
        "amount_minor": int(payload.get("amount_minor") or 0),
        "currency": payload.get("currency"),
        "state": payload.get("state"),
        "requester_id": payload.get("requester_id"),
        "approver_id": payload.get("approver_id"),
        "requested_at": payload.get("requested_at"),
        "approved_at": payload.get("approved_at"),
        "provider_status": payload.get("provider_status"),
        "automated": False,
    }


def _production_grant_readback(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "grant_id": payload.get("grant_id"),
        "delivery_id": payload.get("delivery_id"),
        "payment_id": payload.get("payment_id"),
        "order_id": payload.get("order_id"),
        "project_id": payload.get("project_id"),
        "release_id": payload.get("release_id"),
        "status": payload.get("status"),
        "issued_at": payload.get("issued_at"),
        "expires_at": payload.get("expires_at"),
        "download_count": int(payload.get("download_count") or 0),
        "max_downloads": int(payload.get("max_downloads") or 0),
        "access_locked": bool(payload.get("access_locked_at")),
    }


def _production_provider_event_readback(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": payload.get("event_id"),
        "event_type": payload.get("event_type"),
        "payment_id": payload.get("payment_id"),
        "state": str(payload.get("state") or ""),
        "signature_verified": bool(payload.get("signature_verified")),
        "processed_at": payload.get("processed_at"),
        "raw_payload_persisted": False,
    }


__all__ = [
    "ProductionReleaseApprovalBody",
    "ProductionReleaseRequestBody",
    "ProductionReleaseSuspensionBody",
    "ProductionPaymentRequestBody",
    "ProductionRefundRequestBody",
    "ProductionCustomerDeliveryBody",
    "register_production_release_routes",
]
