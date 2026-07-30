from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from runtime.production_release_orchestrator import (
    ProductionReleaseConfig,
    require_active_production_release_window,
)
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.object_storage import ObjectStorageIntegrityError, ObjectStorageMissingError
from storage.repositories.delivery_record_repo import DeliveryRecordRepository
from storage.repositories.object_storage_repo import ObjectStorageRepository
from storage.repositories.order_record_repo import OrderRecordRepository
from storage.repositories.payment_record_repo import PaymentRecordRepository


PAYMENT_PROVIDER_EVENT_OBJECT_TYPE = "payment_provider_event"
PRODUCTION_REFUND_REQUEST_OBJECT_TYPE = "production_refund_request"
CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE = "customer_artifact_access_grant"
STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300
MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024
MAX_CUSTOMER_DOWNLOADS = 20
_TOKEN_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,127}$")
_CURRENCIES = frozenset({"cny", "usd"})
_REFUND_APPROVER_ROLES = frozenset({"reviewer"})
_REFUND_REQUESTER_ROLES = frozenset({"owner", "admin"})
_DELIVERY_ROLES = frozenset({"owner", "admin"})


class _RejectProviderRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _utc_now(now: datetime | None = None) -> datetime:
    resolved = now or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        raise ValueError("now must include a timezone")
    return resolved.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str, *, field_name: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _load_secret_file(path_value: str | None, *, name: str) -> bytes:
    if not path_value:
        raise ValueError(f"{name} secret file is not configured")
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"{name} secret file is missing")
    secret = path.read_bytes().strip()
    if len(secret) < 32 or len(secret) > 4096:
        raise ValueError(f"{name} secret must contain 32-4096 bytes")
    return secret


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _actor(
    value: Mapping[str, Any],
    *,
    roles: frozenset[str],
) -> tuple[str, str]:
    if not value.get("authenticated"):
        raise PermissionError("authenticated actor required")
    principal_id = str(value.get("principal_id") or "").strip()
    role = str(value.get("role") or "").strip()
    if not principal_id or role not in roles:
        raise PermissionError("actor is not authorized for this production action")
    return principal_id, role


def _release_capability(
    readiness: Mapping[str, Any],
    flag: str,
) -> None:
    if not bool(readiness.get("release_active")):
        raise PermissionError("active approved production release window required")
    if not bool(readiness.get(flag)):
        raise PermissionError(f"production capability is not enabled: {flag}")


def _amount_band(amount_minor: int) -> str:
    if amount_minor < 100_000:
        return "LOW"
    if amount_minor < 1_000_000:
        return "MEDIUM"
    if amount_minor < 10_000_000:
        return "HIGH"
    return "VERY_HIGH"


@dataclass(frozen=True)
class StripeApiConfig:
    api_base_url: str
    allowed_hosts: frozenset[str]
    secret_key_file: str
    proxy_url: str | None
    timeout_seconds: float = 20.0
    allow_http_loopback: bool = False
    direct_https_approved: bool = False

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "StripeApiConfig":
        env = environ if environ is not None else os.environ
        base_url = str(
            env.get("KAKA_STRIPE_API_BASE_URL") or "https://api.stripe.com/v1"
        ).strip().rstrip("/")
        allowed_hosts = frozenset(
            item.strip().lower().rstrip(".")
            for item in str(
                env.get("KAKA_PAYMENT_PROVIDER_ALLOWED_HOSTS") or "api.stripe.com"
            ).split(",")
            if item.strip()
        )
        proxy_url = str(env.get("KAKA_CONTROLLED_EGRESS_PROXY_URL") or "").strip() or None
        try:
            timeout = float(env.get("KAKA_PAYMENT_PROVIDER_TIMEOUT_SECONDS") or "20")
        except ValueError as exc:
            raise ValueError("payment provider timeout must be numeric") from exc
        return cls(
            api_base_url=base_url,
            allowed_hosts=allowed_hosts,
            secret_key_file=str(env.get("KAKA_STRIPE_SECRET_KEY_FILE") or "").strip(),
            proxy_url=proxy_url,
            timeout_seconds=timeout,
            allow_http_loopback=str(
                env.get("KAKA_PAYMENT_PROVIDER_ALLOW_HTTP_LOOPBACK") or ""
            ).strip().lower()
            in {"1", "true", "yes"},
            direct_https_approved=str(
                env.get("KAKA_PAYMENT_PROVIDER_DIRECT_HTTPS_APPROVED") or ""
            ).strip().lower()
            in {"1", "true", "yes"},
        )

    def validate(self) -> dict[str, Any]:
        parsed = urlsplit(self.api_base_url)
        host = str(parsed.hostname or "").lower().rstrip(".")
        is_loopback = host in {"127.0.0.1", "localhost", "::1"}
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("payment provider API base URL contains forbidden components")
        if is_loopback:
            if not self.allow_http_loopback or parsed.scheme != "http":
                raise ValueError("loopback payment provider requires explicit HTTP test mode")
        elif parsed.scheme != "https":
            raise ValueError("payment provider API must use HTTPS")
        if host not in self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("payment provider host must exactly match allowlist")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("payment provider timeout must be between 0 and 60 seconds")
        if not is_loopback and not self.proxy_url and not self.direct_https_approved:
            raise ValueError("payment provider requires controlled proxy or explicit direct HTTPS approval")
        secret = _load_secret_file(
            self.secret_key_file,
            name="payment provider",
        ).decode("utf-8", errors="strict")
        if not is_loopback and not secret.startswith("sk_live_"):
            raise ValueError("production payment provider requires a Stripe live secret key")
        return {
            "ready": True,
            "api_host": host,
            "https_enforced": not is_loopback,
            "exact_host_allowlist_enforced": True,
            "controlled_proxy_configured": bool(self.proxy_url),
            "direct_https_approved": self.direct_https_approved,
            "secret_file_configured": True,
        }


class StripeApiClient:
    def __init__(self, config: StripeApiConfig) -> None:
        self.config = config
        self.config.validate()

    def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        order_id: str,
        payment_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            "/payment_intents",
            {
                "amount": str(amount_minor),
                "currency": currency,
                "metadata[order_id]": order_id,
                "metadata[payment_id]": payment_id,
                "automatic_payment_methods[enabled]": "true",
            },
            idempotency_key=idempotency_key,
        )

    def create_checkout_session(
        self,
        *,
        amount_minor: int,
        currency: str,
        order_id: str,
        payment_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            "/checkout/sessions",
            {
                "mode": "payment",
                "client_reference_id": payment_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "line_items[0][price_data][currency]": currency,
                "line_items[0][price_data][unit_amount]": str(amount_minor),
                "line_items[0][price_data][product_data][name]": "Kaka evidence package",
                "line_items[0][quantity]": "1",
                "metadata[order_id]": order_id,
                "metadata[payment_id]": payment_id,
                "payment_intent_data[metadata][order_id]": order_id,
                "payment_intent_data[metadata][payment_id]": payment_id,
            },
            idempotency_key=idempotency_key,
        )

    def create_refund(
        self,
        *,
        payment_intent_id: str,
        amount_minor: int,
        reason: str,
        refund_request_id: str,
        payment_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._post(
            "/refunds",
            {
                "payment_intent": payment_intent_id,
                "amount": str(amount_minor),
                "metadata[governed_reason]": reason[:500],
                "metadata[refund_request_id]": refund_request_id,
                "metadata[payment_id]": payment_id,
            },
            idempotency_key=idempotency_key,
        )

    def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
        if not _SAFE_ID.fullmatch(checkout_session_id):
            raise ValueError("checkout session id is invalid")
        return self._get(f"/checkout/sessions/{checkout_session_id}")

    def retrieve_account(self) -> dict[str, Any]:
        return self._get("/account")

    def _post(
        self,
        path: str,
        fields: Mapping[str, str],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        secret = _load_secret_file(
            self.config.secret_key_file,
            name="payment provider",
        ).decode("utf-8")
        data = urlencode(dict(fields)).encode("ascii")
        request = Request(
            f"{self.config.api_base_url}{path}",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Idempotency-Key": idempotency_key,
                "User-Agent": "Kaka-Production-Payment/1.0",
            },
        )
        proxies = (
            {"http": self.config.proxy_url, "https": self.config.proxy_url}
            if self.config.proxy_url
            else {}
        )
        opener = build_opener(
            ProxyHandler(proxies),
            _RejectProviderRedirects(),
        )
        try:
            with opener.open(request, timeout=self.config.timeout_seconds) as response:
                body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                status = int(getattr(response, "status", 0))
        except HTTPError as exc:
            exc.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            raise RuntimeError(f"payment_provider_http_{int(exc.code)}") from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RuntimeError(f"payment_provider_transport_{type(exc).__name__}") from exc
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise RuntimeError("payment_provider_response_too_large")
        if status < 200 or status >= 300:
            raise RuntimeError(f"payment_provider_http_{status}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("payment_provider_invalid_json") from exc
        if not isinstance(payload, dict) or not str(payload.get("id") or ""):
            raise RuntimeError("payment_provider_response_missing_id")
        return payload

    def _get(self, path: str) -> dict[str, Any]:
        secret = _load_secret_file(
            self.config.secret_key_file,
            name="payment provider",
        ).decode("utf-8")
        request = Request(
            f"{self.config.api_base_url}{path}",
            method="GET",
            headers={
                "Authorization": f"Bearer {secret}",
                "User-Agent": "Kaka-Production-Payment/1.0",
            },
        )
        proxies = (
            {"http": self.config.proxy_url, "https": self.config.proxy_url}
            if self.config.proxy_url
            else {}
        )
        opener = build_opener(
            ProxyHandler(proxies),
            _RejectProviderRedirects(),
        )
        try:
            with opener.open(request, timeout=self.config.timeout_seconds) as response:
                body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                status = int(getattr(response, "status", 0))
        except HTTPError as exc:
            exc.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            raise RuntimeError(f"payment_provider_http_{int(exc.code)}") from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RuntimeError(f"payment_provider_transport_{type(exc).__name__}") from exc
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise RuntimeError("payment_provider_response_too_large")
        if status < 200 or status >= 300:
            raise RuntimeError(f"payment_provider_http_{status}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("payment_provider_invalid_json") from exc
        if not isinstance(payload, dict) or not str(payload.get("id") or ""):
            raise RuntimeError("payment_provider_response_missing_id")
        return payload


def create_production_payment(
    *,
    order_id: str,
    amount_minor: int,
    currency: str,
    idempotency_key: str,
    config: ProductionReleaseConfig,
    release_readiness: Mapping[str, Any],
    session: DatabaseSession,
    actor: Mapping[str, Any],
    client: StripeApiClient,
) -> dict[str, Any]:
    actor_id, actor_role = _actor(actor, roles=_DELIVERY_ROLES)
    _release_capability(release_readiness, "payment_execution_enabled")
    if amount_minor < 100 or amount_minor > 100_000_000:
        raise ValueError("payment amount must be between 100 and 100000000 minor units")
    normalized_currency = currency.strip().lower()
    if normalized_currency not in _CURRENCIES:
        raise ValueError("payment currency is not supported")
    normalized_idempotency_key = idempotency_key.strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized_idempotency_key):
        raise ValueError("payment idempotency_key must be 16-128 safe characters")
    request_fingerprint = _sha256_bytes(
        _canonical_json(
            {
                "release_id": config.release_id,
                "order_id": order_id,
                "amount_minor": amount_minor,
                "currency": normalized_currency,
            }
        )
    )
    stable_key_hash = _sha256_bytes(
        f"{config.release_id}:{normalized_idempotency_key}".encode("utf-8")
    )
    payment_id = f"PAY-{stable_key_hash[:32]}"
    provider_idempotency_key = f"kaka-payment-{stable_key_hash}"
    with session.serialized_key(
        f"production-release:{config.release_id}"
    ), session.serialized_key(
        "production-payment-mutation-global"
    ), session.serialized_key(
        f"production-payment-order:{order_id}"
    ), session.bulk_write():
        require_active_production_release_window(
            config=config,
            session=session,
            release_readiness=release_readiness,
        )
        order = OrderRecordRepository(session=session).get_by_id(order_id)
        if order is None:
            raise ValueError("order record not found")
        order_payload = dict(order.payload)
        if str(order_payload.get("approval_state") or "") != "APPROVED":
            raise ValueError("order approval_state must be APPROVED")
        order_metadata = dict(order_payload.get("governed_metadata") or {})
        approved_amount = int(order_metadata.get("approved_amount_minor") or 0)
        approved_currency = str(
            order_metadata.get("approved_currency") or ""
        ).lower()
        if approved_amount != amount_minor or approved_currency != normalized_currency:
            raise ValueError("payment amount and currency must match the approved order")
        existing = PaymentRecordRepository(session=session).get_by_id(payment_id)
        if existing is not None:
            existing_metadata = dict(existing.payload.get("governed_metadata") or {})
            if (
                str(existing_metadata.get("request_fingerprint_sha256") or "")
                != request_fingerprint
            ):
                raise ValueError("payment idempotency_key was reused with different input")
            checkout_url: str | None = None
            if str(existing.payload.get("payment_status") or "") == "PENDING_PAYMENT":
                provider = client.retrieve_checkout_session(
                    str(existing_metadata.get("provider_checkout_session_id") or "")
                )
                candidate_url = str(provider.get("url") or "")
                if candidate_url.startswith("https://"):
                    checkout_url = candidate_url
            return {
                "payment_id": payment_id,
                "order_id": order_id,
                "provider_checkout_session_id": existing_metadata.get(
                    "provider_checkout_session_id"
                ),
                "payment_status": existing.payload.get("payment_status"),
                "provider_status": existing_metadata.get("provider_status"),
                "checkout_url": checkout_url,
                "amount_minor": int(existing_metadata.get("amount_minor") or 0),
                "currency": str(existing_metadata.get("currency") or ""),
                "idempotent_replay": True,
                "real_provider_call_executed": bool(checkout_url),
                "audit_ref": f"production_payment_replay:{payment_id}:{actor_id}",
            }
        else:
            active_for_order = [
                record
                for record in session.list_records("payment_record")
                if str(record.payload.get("order_id") or "") == order_id
                and str(record.payload.get("payment_status") or "")
                in {"PENDING_PAYMENT", "PAID", "REFUND_PENDING", "REFUNDED"}
            ]
            if active_for_order:
                raise ValueError("order already has an active production payment")
        provider = client.create_checkout_session(
            amount_minor=amount_minor,
            currency=normalized_currency,
            order_id=order_id,
            payment_id=payment_id,
            success_url=f"{config.public_base_url}/customer/payment/complete",
            cancel_url=f"{config.public_base_url}/customer/payment/cancelled",
            idempotency_key=provider_idempotency_key,
        )
        provider_checkout_session_id = str(provider.get("id") or "")
        checkout_url = str(provider.get("url") or "")
        if not provider_checkout_session_id or not checkout_url.startswith("https://"):
            raise RuntimeError("payment provider checkout response is incomplete")
        payload = {
        "payment_id": payment_id,
        "project_id": str(order_payload["project_id"]),
        "order_id": order_id,
        "payment_status": "PENDING_PAYMENT",
        "payment_proof_state": "NOT_PROVIDED",
        "payer_match_state": "UNKNOWN",
        "amount_match_state": "PENDING",
        "amount_band": _amount_band(amount_minor),
        "payment_exception_family_optional": "NO_EXCEPTION",
        "payment_exception_reason_optional": "NO_EXCEPTION",
        "payment_exception_reason_tags_optional": [],
        "amount_mismatch_state_optional": "NO_MISMATCH",
        "refund_state": "NOT_REQUESTED",
        "refund_amount_band_optional": "NOT_APPLICABLE",
        "paid_at_optional": "UNKNOWN",
        "written_back_at_optional": utc_now_iso(),
        "governed_execution_mode": "PROD_LIVE_MODE",
        "permission_decision_state": "ALLOW",
        "governance_decision_state": "PASS",
        "semantic_decision_state": "PASS",
        "governed_metadata": {
            "provider_id": "stripe_payment",
            "provider_checkout_session_id": provider_checkout_session_id,
            "provider_payment_intent_id": str(provider.get("payment_intent") or ""),
            "provider_status": str(provider.get("status") or ""),
            "amount_minor": amount_minor,
            "currency": normalized_currency,
            "reconciliation_state": "PENDING_CALLBACK",
            "idempotency_key_sha256": _sha256_bytes(
                normalized_idempotency_key.encode("utf-8")
            ),
            "request_fingerprint_sha256": request_fingerprint,
            "release_id": release_readiness.get("release_id"),
            "release_window_request_id": dict(
                release_readiness.get("active_release_window") or {}
            ).get("request_id"),
            "executed_by": actor_id,
            "executed_by_role": actor_role,
            "provider_response_redacted": True,
            "provider_secret_persisted": False,
            "opportunity_id": str(order_payload.get("opportunity_id") or ""),
        },
        }
        PaymentRecordRepository(session=session).save(payload)
    return {
        "payment_id": payment_id,
        "order_id": order_id,
        "provider_checkout_session_id": provider_checkout_session_id,
        "payment_status": payload["payment_status"],
        "provider_status": payload["governed_metadata"]["provider_status"],
        "checkout_url": checkout_url,
        "amount_minor": amount_minor,
        "currency": normalized_currency,
        "idempotent_replay": existing is not None,
        "real_provider_call_executed": True,
        "audit_ref": f"production_payment_create:{payment_id}:{actor_id}",
    }


def verify_stripe_webhook(
    *,
    body: bytes,
    signature_header: str,
    secret_file: str,
    now_unix_seconds: int | None = None,
    tolerance_seconds: int = STRIPE_SIGNATURE_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ValueError("payment webhook body too large")
    timestamp: int | None = None
    signatures: list[str] = []
    for component in signature_header.split(","):
        key, separator, value = component.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif key == "v1" and re.fullmatch(r"[a-f0-9]{64}", value):
            signatures.append(value)
    if timestamp is None or not signatures:
        raise PermissionError("payment webhook signature header is invalid")
    observed = int(now_unix_seconds if now_unix_seconds is not None else time.time())
    if abs(observed - timestamp) > tolerance_seconds:
        raise PermissionError("payment webhook signature timestamp is outside tolerance")
    secret = _load_secret_file(secret_file, name="payment webhook")
    signed_payload = str(timestamp).encode("ascii") + b"." + body
    expected = hmac.new(secret, signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, supplied) for supplied in signatures):
        raise PermissionError("payment webhook signature mismatch")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("payment webhook JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("payment webhook payload must be an object")
    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("type") or "")
    data_object = dict(dict(payload.get("data") or {}).get("object") or {})
    if not _SAFE_ID.fullmatch(event_id) or not event_type or not data_object:
        raise ValueError("payment webhook event is incomplete")
    return {
        "event_id": event_id,
        "event_type": event_type,
        "created": payload.get("created"),
        "livemode": payload.get("livemode"),
        "account": payload.get("account"),
        "data_object": data_object,
        "signature_verified": True,
        "body_sha256": _sha256_bytes(body),
    }


def process_stripe_webhook(
    *,
    body: bytes,
    signature_header: str,
    config: ProductionReleaseConfig,
    session: DatabaseSession,
    now_unix_seconds: int | None = None,
) -> dict[str, Any]:
    event = verify_stripe_webhook(
        body=body,
        signature_header=signature_header,
        secret_file=str(config.payment_webhook_secret_file or ""),
        now_unix_seconds=now_unix_seconds,
    )
    if event.get("livemode") is not True:
        raise PermissionError("production payment webhook requires livemode=true")
    existing = session.get_record(PAYMENT_PROVIDER_EVENT_OBJECT_TYPE, event["event_id"])
    if existing is not None and str(existing.payload.get("state") or "") not in {
        "UNMATCHED_PAYMENT_REVIEW_REQUIRED",
        "UNMATCHED_REFUND_REVIEW_REQUIRED",
    }:
        return {
            "event_id": event["event_id"],
            "state": "ALREADY_PROCESSED",
            "idempotent_replay": True,
            "payment_id": existing.object_refs.get("payment_id"),
        }
    with session.serialized_key(
        "production-payment-mutation-global"
    ), session.serialized_key(
        "production-payment-webhook-global"
    ), session.bulk_write():
        existing = session.get_record(
            PAYMENT_PROVIDER_EVENT_OBJECT_TYPE,
            event["event_id"],
        )
        if existing is not None and str(existing.payload.get("state") or "") not in {
            "UNMATCHED_PAYMENT_REVIEW_REQUIRED",
            "UNMATCHED_REFUND_REVIEW_REQUIRED",
        }:
            return {
                "event_id": event["event_id"],
                "state": "ALREADY_PROCESSED",
                "idempotent_replay": True,
                "payment_id": existing.object_refs.get("payment_id"),
            }
        provider_object = dict(event["data_object"])
        provider_ids = {
            str(provider_object.get("id") or ""),
            str(provider_object.get("payment_intent") or ""),
        }
        provider_ids.discard("")
        payment = _payment_by_provider_ids(session, provider_ids)
        if payment is None:
            _save_provider_event(
                session=session,
                event=event,
                payment_id=None,
                state="UNMATCHED_PAYMENT_REVIEW_REQUIRED",
            )
            return {
                "event_id": event["event_id"],
                "state": "UNMATCHED_PAYMENT_REVIEW_REQUIRED",
                "idempotent_replay": False,
                "payment_id": None,
            }
        payment_payload = dict(payment.payload)
        metadata = dict(payment_payload.get("governed_metadata") or {})
        provider_metadata = dict(provider_object.get("metadata") or {})
        expected_amount = int(metadata.get("amount_minor") or 0)
        expected_currency = str(metadata.get("currency") or "").lower()
        provider_currency = str(provider_object.get("currency") or "").lower()
        event_type = str(event["event_type"])
        provider_amount = int(
            provider_object.get("amount_total")
            or provider_object.get("amount_received")
            or provider_object.get("amount")
            or 0
        )
        amount_match = provider_amount == expected_amount
        currency_match = provider_currency == expected_currency
        order_match = str(provider_metadata.get("order_id") or "") == str(
            payment_payload.get("order_id")
        )
        payment_id_match = str(provider_metadata.get("payment_id") or "") == str(
            payment_payload.get("payment_id")
        )
        reconciled = amount_match and currency_match and order_match and payment_id_match
        current_status = str(payment_payload.get("payment_status") or "")

        if event_type in {"checkout.session.completed", "payment_intent.succeeded"}:
            provider_paid = (
                event_type == "payment_intent.succeeded"
                or str(provider_object.get("payment_status") or "") == "paid"
            )
            reconciled = reconciled and provider_paid
            if current_status in {"REFUND_PENDING", "REFUNDED"}:
                state = "STALE_EVENT_IGNORED"
            else:
                payment_payload["payment_status"] = (
                    "PAID" if reconciled else "PAYMENT_EXCEPTION"
                )
                payment_payload["payment_proof_state"] = "PROVIDED"
                payment_payload["payer_match_state"] = (
                    "MATCHED" if order_match and payment_id_match else "MISMATCH"
                )
                payment_payload["amount_match_state"] = (
                    "MATCHED" if amount_match and currency_match else "MISMATCH"
                )
                if not reconciled:
                    payment_payload[
                        "payment_exception_family_optional"
                    ] = "AMOUNT_OR_ORDER_MISMATCH"
                    payment_payload[
                        "payment_exception_reason_optional"
                    ] = "provider_callback_reconciliation_mismatch"
                    payment_payload["payment_exception_reason_tags_optional"] = [
                        "AMOUNT_MATCHED" if amount_match else "AMOUNT_MISMATCH",
                        "CURRENCY_MATCHED" if currency_match else "CURRENCY_MISMATCH",
                        "ORDER_MATCHED" if order_match else "ORDER_MISMATCH",
                        "PAYMENT_ID_MATCHED"
                        if payment_id_match
                        else "PAYMENT_ID_MISMATCH",
                    ]
                    payment_payload["amount_mismatch_state_optional"] = (
                        "MISMATCH"
                        if not amount_match or not currency_match
                        else "NO_MISMATCH"
                    )
                else:
                    payment_payload["paid_at_optional"] = _safe_provider_event_time(
                        event.get("created")
                    )
                    provider_intent_id = str(
                        provider_object.get("payment_intent")
                        or provider_object.get("id")
                        or ""
                    )
                    if event_type == "payment_intent.succeeded":
                        metadata["provider_payment_intent_id"] = provider_intent_id
                    elif provider_object.get("payment_intent"):
                        metadata["provider_payment_intent_id"] = provider_intent_id
                state = "RECONCILED" if reconciled else "MISMATCH_REVIEW_REQUIRED"
        elif event_type in {"payment_intent.payment_failed", "payment_intent.canceled"}:
            if current_status != "PENDING_PAYMENT":
                state = "STALE_EVENT_IGNORED"
            else:
                payment_payload["payment_status"] = "PAYMENT_EXCEPTION"
                payment_payload["payment_exception_family_optional"] = "PROVIDER_FAILURE"
                payment_payload["payment_exception_reason_optional"] = event_type
                state = "PROVIDER_FAILURE_RECORDED"
        elif event_type in {"refund.updated", "refund.created"}:
            refund_request = _refund_request_for_provider_event(
                session=session,
                provider_object=provider_object,
                payment_id=str(payment_payload["payment_id"]),
            )
            if refund_request is None:
                reconciled = False
                state = "UNMATCHED_REFUND_REVIEW_REQUIRED"
            else:
                refund_payload = dict(refund_request.payload)
                refund_amount = int(refund_payload.get("amount_minor") or 0)
                amount_match = provider_amount == refund_amount
                currency_match = provider_currency == str(
                    refund_payload.get("currency") or ""
                ).lower()
                refund_id_match = str(provider_object.get("id") or "") == str(
                    refund_payload.get("provider_refund_id") or ""
                )
                refund_request_match = str(
                    provider_metadata.get("refund_request_id") or ""
                ) == str(refund_payload.get("refund_request_id") or "")
                reconciled = (
                    amount_match
                    and currency_match
                    and refund_id_match
                    and refund_request_match
                    and payment_id_match
                )
                completed = str(provider_object.get("status") or "") == "succeeded"
                if reconciled:
                    refund_payload["state"] = (
                        "REFUNDED" if completed else "REFUND_SUBMITTED"
                    )
                    refund_payload["provider_status"] = str(
                        provider_object.get("status") or ""
                    )
                    refund_payload["last_provider_event_id"] = event["event_id"]
                    _save_runtime_record(
                        session=session,
                        object_type=PRODUCTION_REFUND_REQUEST_OBJECT_TYPE,
                        record_id=str(refund_payload["refund_request_id"]),
                        project_id=str(refund_payload["project_id"]),
                        payload=refund_payload,
                        object_refs=dict(refund_request.object_refs),
                        decision_states={"state": str(refund_payload["state"])},
                        audit_refs=dict(refund_request.audit_refs),
                    )
                    if completed:
                        full_refund = refund_amount == expected_amount
                        payment_payload["payment_status"] = (
                            "REFUNDED" if full_refund else "PAID"
                        )
                        payment_payload["refund_state"] = (
                            "REFUNDED" if full_refund else "PARTIALLY_REFUNDED"
                        )
                    else:
                        payment_payload["payment_status"] = "REFUND_PENDING"
                        payment_payload["refund_state"] = "REFUND_PENDING"
                    state = "REFUND_RECONCILED"
                else:
                    state = "MISMATCH_REVIEW_REQUIRED"
        else:
            state = "IGNORED_EVENT_TYPE"

        metadata.update(
            {
                "provider_event_id": event["event_id"],
                "provider_event_type": event_type,
                "provider_event_body_sha256": event["body_sha256"],
                "provider_amount_minor": provider_amount,
                "provider_currency": provider_currency,
                "order_match": order_match,
                "payment_id_match": payment_id_match,
                "webhook_signature_verified": True,
                "last_provider_callback_at": utc_now_iso(),
            }
        )
        if state not in {"IGNORED_EVENT_TYPE", "STALE_EVENT_IGNORED"}:
            metadata["reconciliation_state"] = (
                "MATCHED"
                if reconciled
                else "MISMATCH_REVIEW_REQUIRED"
            )
        payment_payload["governed_metadata"] = metadata
        payment_payload["written_back_at_optional"] = utc_now_iso()
        PaymentRecordRepository(session=session).save(payment_payload)
        _save_provider_event(
            session=session,
            event=event,
            payment_id=str(payment_payload["payment_id"]),
            state=state,
        )
        return {
            "event_id": event["event_id"],
            "state": state,
            "idempotent_replay": False,
            "payment_id": payment_payload["payment_id"],
            "payment_status": payment_payload["payment_status"],
            "amount_match": amount_match,
            "currency_match": currency_match,
            "order_match": order_match,
            "payment_id_match": payment_id_match,
            "signature_verified": True,
        }


def request_production_refund(
    *,
    payment_id: str,
    amount_minor: int,
    reason: str,
    config: ProductionReleaseConfig,
    release_readiness: Mapping[str, Any],
    session: DatabaseSession,
    actor: Mapping[str, Any],
) -> dict[str, Any]:
    requester_id, requester_role = _actor(actor, roles=_REFUND_REQUESTER_ROLES)
    _release_capability(release_readiness, "refund_execution_enabled")
    normalized_reason = reason.strip()
    if len(normalized_reason) < 10 or len(normalized_reason) > 500:
        raise ValueError("refund reason must be 10-500 characters")
    with session.serialized_key(
        f"production-release:{config.release_id}"
    ), session.serialized_key(
        "production-payment-mutation-global"
    ), session.serialized_key(
        "production-refund-global"
    ), session.bulk_write():
        require_active_production_release_window(
            config=config,
            session=session,
            release_readiness=release_readiness,
        )
        payment = PaymentRecordRepository(session=session).get_by_id(payment_id)
        if payment is None:
            raise ValueError("payment record not found")
        payload = dict(payment.payload)
        metadata = dict(payload.get("governed_metadata") or {})
        paid_amount = int(metadata.get("amount_minor") or 0)
        if str(payload.get("payment_status") or "") != "PAID":
            raise ValueError("only PAID payment can enter refund request")
        if str(metadata.get("reconciliation_state") or "") != "MATCHED":
            raise ValueError("payment reconciliation must be MATCHED")
        if amount_minor < 1 or amount_minor > paid_amount:
            raise ValueError("refund amount exceeds reconciled payment")
        active_grants = [
            record
            for record in session.list_records(
                CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE
            )
            if str(record.payload.get("payment_id") or "") == payment_id
            and str(record.payload.get("status") or "") == "ACTIVE"
        ]
        if active_grants:
            raise ValueError(
                "active customer delivery grants must be revoked before refund"
            )
        active_refunds = [
            record
            for record in session.list_records(PRODUCTION_REFUND_REQUEST_OBJECT_TYPE)
            if str(record.payload.get("payment_id") or "") == payment_id
            and str(record.payload.get("state") or "")
            in {"PENDING_APPROVAL", "REFUND_SUBMITTED", "REFUNDED"}
        ]
        if active_refunds:
            raise ValueError("payment already has an active or completed refund request")
        request_id = f"REF-{uuid4().hex}"
        refund = {
            "refund_request_id": request_id,
            "payment_id": payment_id,
            "order_id": payload["order_id"],
            "project_id": payload["project_id"],
            "amount_minor": amount_minor,
            "currency": metadata.get("currency"),
            "reason": normalized_reason,
            "state": "PENDING_APPROVAL",
            "requester_id": requester_id,
            "requester_role": requester_role,
            "approver_id": None,
            "approver_role": None,
            "requested_at": utc_now_iso(),
            "approved_at": None,
            "provider_refund_id": None,
            "release_id": release_readiness.get("release_id"),
            "automated": False,
            "audit_refs": [f"production_refund_request:{request_id}:{requester_id}"],
        }
        _save_runtime_record(
            session=session,
            object_type=PRODUCTION_REFUND_REQUEST_OBJECT_TYPE,
            record_id=request_id,
            project_id=str(payload["project_id"]),
            payload=refund,
            object_refs={
                "payment_id": payment_id,
                "order_id": str(payload["order_id"]),
            },
            decision_states={"state": "PENDING_APPROVAL"},
            audit_refs={"request": refund["audit_refs"][0]},
        )
        return refund


def approve_and_execute_production_refund(
    *,
    refund_request_id: str,
    config: ProductionReleaseConfig,
    release_readiness: Mapping[str, Any],
    session: DatabaseSession,
    actor: Mapping[str, Any],
    client: StripeApiClient,
) -> dict[str, Any]:
    approver_id, approver_role = _actor(actor, roles=_REFUND_APPROVER_ROLES)
    _release_capability(release_readiness, "refund_execution_enabled")
    with session.serialized_key(
        f"production-release:{config.release_id}"
    ), session.serialized_key(
        "production-payment-mutation-global"
    ), session.serialized_key(
        "production-refund-global"
    ), session.bulk_write():
        require_active_production_release_window(
            config=config,
            session=session,
            release_readiness=release_readiness,
        )
        return _approve_and_execute_production_refund_locked(
            refund_request_id=refund_request_id,
            session=session,
            approver_id=approver_id,
            approver_role=approver_role,
            client=client,
        )


def _approve_and_execute_production_refund_locked(
    *,
    refund_request_id: str,
    session: DatabaseSession,
    approver_id: str,
    approver_role: str,
    client: StripeApiClient,
) -> dict[str, Any]:
    record = session.get_record(
        PRODUCTION_REFUND_REQUEST_OBJECT_TYPE,
        refund_request_id,
    )
    if record is None:
        raise ValueError("refund request not found")
    refund = dict(record.payload)
    if str(refund.get("state") or "") != "PENDING_APPROVAL":
        raise ValueError("refund request is not pending approval")
    if str(refund.get("requester_id") or "") == approver_id:
        raise ValueError("refund approver must differ from requester")
    payment = PaymentRecordRepository(session=session).get_by_id(
        str(refund["payment_id"])
    )
    if payment is None:
        raise ValueError("payment record not found")
    payment_payload = dict(payment.payload)
    payment_metadata = dict(payment_payload.get("governed_metadata") or {})
    if str(payment_payload.get("payment_status") or "") != "PAID":
        raise ValueError("refund approval requires payment to remain PAID")
    if str(payment_metadata.get("reconciliation_state") or "") != "MATCHED":
        raise ValueError("refund approval requires MATCHED payment reconciliation")
    if int(refund.get("amount_minor") or 0) > int(
        payment_metadata.get("amount_minor") or 0
    ):
        raise ValueError("refund amount exceeds current reconciled payment")
    provider_payment_id = str(
        payment_metadata.get("provider_payment_intent_id") or ""
    )
    if not provider_payment_id:
        raise ValueError("provider payment intent id is missing")
    provider = client.create_refund(
        payment_intent_id=provider_payment_id,
        amount_minor=int(refund["amount_minor"]),
        reason=str(refund["reason"]),
        refund_request_id=refund_request_id,
        payment_id=str(refund["payment_id"]),
        idempotency_key=f"kaka-refund-{refund_request_id}",
    )
    refund.update(
        {
            "state": "REFUND_SUBMITTED",
            "approver_id": approver_id,
            "approver_role": approver_role,
            "approved_at": utc_now_iso(),
            "provider_refund_id": str(provider.get("id") or ""),
            "provider_status": str(provider.get("status") or ""),
            "audit_refs": [
                *list(refund.get("audit_refs") or []),
                f"production_refund_approval:{refund_request_id}:{approver_id}",
            ],
        }
    )
    _save_runtime_record(
        session=session,
        object_type=PRODUCTION_REFUND_REQUEST_OBJECT_TYPE,
        record_id=refund_request_id,
        project_id=str(refund["project_id"]),
        payload=refund,
        object_refs={
            "payment_id": str(refund["payment_id"]),
            "order_id": str(refund["order_id"]),
        },
        decision_states={"state": "REFUND_SUBMITTED"},
        audit_refs={
            "request": str(refund["audit_refs"][0]),
            "approval": str(refund["audit_refs"][-1]),
        },
    )
    payment_payload["payment_status"] = "REFUND_PENDING"
    payment_payload["refund_state"] = "REFUND_PENDING"
    payment_payload["refund_amount_band_optional"] = _amount_band(
        int(refund["amount_minor"])
    )
    payment_metadata.update(
        {
            "refund_request_id": refund_request_id,
            "provider_refund_id": refund["provider_refund_id"],
            "refund_amount_minor": refund["amount_minor"],
            "refund_approval_separation_satisfied": True,
            "automated_refund": False,
        }
    )
    payment_payload["governed_metadata"] = payment_metadata
    payment_payload["written_back_at_optional"] = utc_now_iso()
    PaymentRecordRepository(session=session).save(payment_payload)
    return {
        **refund,
        "real_provider_call_executed": True,
        "automated_refund": False,
    }


def validate_production_delivery_source(
    *,
    payment_id: str,
    opportunity_id: str,
    session: DatabaseSession,
) -> dict[str, Any]:
    payment = PaymentRecordRepository(session=session).get_by_id(payment_id)
    if payment is None:
        raise ValueError("payment record not found")
    payload = dict(payment.payload)
    metadata = dict(payload.get("governed_metadata") or {})
    if str(payload.get("payment_status") or "") != "PAID":
        raise ValueError("customer delivery requires PAID payment")
    if str(metadata.get("reconciliation_state") or "") != "MATCHED":
        raise ValueError("customer delivery requires MATCHED payment reconciliation")
    if str(metadata.get("opportunity_id") or "") != opportunity_id:
        raise ValueError("delivery opportunity does not match the paid order")
    return {
        "payment_id": payment_id,
        "order_id": payload.get("order_id"),
        "project_id": payload.get("project_id"),
        "opportunity_id": opportunity_id,
        "source_bound": True,
    }


def issue_customer_artifact_grant(
    *,
    payment_id: str,
    source_opportunity_id: str,
    artifact_object_key: str,
    artifact_sha256: str,
    customer_subject: str,
    expires_in_seconds: int,
    max_downloads: int,
    release_readiness: Mapping[str, Any],
    config: ProductionReleaseConfig,
    session: DatabaseSession,
    object_repository: ObjectStorageRepository,
    actor: Mapping[str, Any],
) -> dict[str, Any]:
    actor_id, actor_role = _actor(actor, roles=_DELIVERY_ROLES)
    _release_capability(release_readiness, "delivery_execution_enabled")
    _release_capability(release_readiness, "customer_visible_allowed")
    if expires_in_seconds < 300 or expires_in_seconds > 30 * 24 * 60 * 60:
        raise ValueError("customer access expiry must be between 300 and 2592000 seconds")
    if max_downloads < 1 or max_downloads > MAX_CUSTOMER_DOWNLOADS:
        raise ValueError(f"max_downloads must be between 1 and {MAX_CUSTOMER_DOWNLOADS}")
    with session.serialized_key(
        f"production-release:{config.release_id}"
    ), session.serialized_key(
        "production-payment-mutation-global"
    ), session.serialized_key(
        "production-delivery-issuance-global"
    ), session.bulk_write():
        require_active_production_release_window(
            config=config,
            session=session,
            release_readiness=release_readiness,
        )
        return _issue_customer_artifact_grant_locked(
            payment_id=payment_id,
            source_opportunity_id=source_opportunity_id,
            artifact_object_key=artifact_object_key,
            artifact_sha256=artifact_sha256,
            customer_subject=customer_subject,
            expires_in_seconds=expires_in_seconds,
            max_downloads=max_downloads,
            release_readiness=release_readiness,
            config=config,
            session=session,
            object_repository=object_repository,
            actor_id=actor_id,
            actor_role=actor_role,
        )


def _issue_customer_artifact_grant_locked(
    *,
    payment_id: str,
    source_opportunity_id: str,
    artifact_object_key: str,
    artifact_sha256: str,
    customer_subject: str,
    expires_in_seconds: int,
    max_downloads: int,
    release_readiness: Mapping[str, Any],
    config: ProductionReleaseConfig,
    session: DatabaseSession,
    object_repository: ObjectStorageRepository,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    payment = PaymentRecordRepository(session=session).get_by_id(payment_id)
    if payment is None:
        raise ValueError("payment record not found")
    payment_payload = dict(payment.payload)
    payment_metadata = dict(payment_payload.get("governed_metadata") or {})
    if str(payment_metadata.get("opportunity_id") or "") != source_opportunity_id:
        raise ValueError("delivery opportunity does not match the paid order")
    if str(payment_payload.get("payment_status") or "") != "PAID":
        raise ValueError("customer delivery requires PAID payment")
    if str(payment_metadata.get("reconciliation_state") or "") != "MATCHED":
        raise ValueError("customer delivery requires MATCHED payment reconciliation")
    active_refunds = [
        record
        for record in session.list_records(PRODUCTION_REFUND_REQUEST_OBJECT_TYPE)
        if str(record.payload.get("payment_id") or "") == payment_id
        and str(record.payload.get("state") or "")
        in {"PENDING_APPROVAL", "REFUND_SUBMITTED", "REFUNDED"}
    ]
    if active_refunds:
        raise ValueError("customer delivery is blocked by an active refund request")
    metadata = object_repository.get_object_metadata(artifact_object_key)
    if metadata is None:
        raise ValueError("artifact object metadata is missing")
    if metadata.sha256 != artifact_sha256:
        raise ValueError("artifact object sha256 does not match approved package")
    try:
        object_repository.read_object(artifact_object_key)
    except (ObjectStorageMissingError, ObjectStorageIntegrityError) as exc:
        raise ValueError("artifact object is not replayable") from exc
    now = _utc_now()
    expires_at = now + timedelta(seconds=expires_in_seconds)
    grant_id = f"CAG-{uuid4().hex}"
    nonce = secrets.token_urlsafe(24)
    subject_hash = _sha256_bytes(customer_subject.strip().lower().encode("utf-8"))
    release_subjects = {
        str(record.payload.get("customer_subject_sha256") or "")
        for record in session.list_records(CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE)
        if str(record.payload.get("release_id") or "") == config.release_id
        and str(record.payload.get("status") or "") in {"ACTIVE", "DELIVERED"}
    }
    release_subjects.discard("")
    if (
        subject_hash not in release_subjects
        and len(release_subjects) >= config.canary_customer_limit
    ):
        raise ValueError("production release customer limit reached")
    token_payload = {
        "v": _TOKEN_VERSION,
        "grant_id": grant_id,
        "tenant_id": config.tenant_id,
        "release_id": config.release_id,
        "exp": int(expires_at.timestamp()),
        "nonce": nonce,
    }
    token = _sign_customer_token(
        token_payload,
        secret_file=str(config.customer_portal_signing_key_file or ""),
    )
    access_code = f"{secrets.randbelow(100_000_000):08d}"
    delivery_id = f"DEL-{uuid4().hex}"
    grant = {
        "grant_id": grant_id,
        "delivery_id": delivery_id,
        "payment_id": payment_id,
        "order_id": payment_payload["order_id"],
        "project_id": payment_payload["project_id"],
        "tenant_id": config.tenant_id,
        "release_id": config.release_id,
        "release_window_request_id": dict(
            release_readiness.get("active_release_window") or {}
        ).get("request_id"),
        "artifact_object_key": artifact_object_key,
        "artifact_sha256": artifact_sha256,
        "content_type": metadata.content_type,
        "byte_size": metadata.byte_size,
        "customer_subject_sha256": subject_hash,
        "token_sha256": _sha256_bytes(token.encode("ascii")),
        "access_code_hmac_sha256": _customer_access_code_digest(
            access_code,
            grant_id=grant_id,
            secret_file=str(config.customer_portal_signing_key_file or ""),
        ),
        "failed_access_attempts": 0,
        "access_locked_at": None,
        "status": "ACTIVE",
        "issued_at": _iso(now),
        "expires_at": _iso(expires_at),
        "max_downloads": max_downloads,
        "download_count": 0,
        "first_download_at": None,
        "last_download_at": None,
        "revoked_at": None,
        "issued_by": actor_id,
        "issued_by_role": actor_role,
        "audit_refs": [f"customer_artifact_grant:{grant_id}:{actor_id}"],
    }
    _save_runtime_record(
        session=session,
        object_type=CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE,
        record_id=grant_id,
        project_id=str(payment_payload["project_id"]),
        payload=grant,
        object_refs={
            "delivery_id": delivery_id,
            "payment_id": payment_id,
            "order_id": str(payment_payload["order_id"]),
            "artifact_object_key": artifact_object_key,
        },
        decision_states={"status": "ACTIVE"},
        audit_refs={"issuance": grant["audit_refs"][0]},
    )
    delivery_payload = {
        "delivery_id": delivery_id,
        "project_id": str(payment_payload["project_id"]),
        "order_id": str(payment_payload["order_id"]),
        "payment_id_optional": payment_id,
        "delivery_form": "CLIENT_DELIVERY",
        "package_template_code": "EVIDENCE_PACK",
        "delivery_status": "READY_FOR_RELEASE",
        "delivered_at_optional": "UNKNOWN",
        "customer_ack_state_optional": "ACK_PENDING",
        "delivery_exception_family_optional": "NO_EXCEPTION",
        "delivery_exception_reason_optional": "NO_EXCEPTION",
        "delivery_exception_reason_tags_optional": [],
        "partial_delivery_state_optional": "NOT_PARTIAL",
        "resend_required_optional": False,
        "redeliver_required_optional": False,
        "archival_status": "ARCHIVED",
        "retention_until": _iso(expires_at),
        "retrieval_status": "READY",
        "written_back_at_optional": utc_now_iso(),
        "governed_execution_mode": "PROD_LIVE_MODE",
        "permission_decision_state": "ALLOW",
        "governance_decision_state": "PASS",
        "semantic_decision_state": "PASS",
        "governed_metadata": {
            "grant_id": grant_id,
            "artifact_object_key": artifact_object_key,
            "artifact_sha256": artifact_sha256,
            "customer_subject_sha256": subject_hash,
            "release_id": config.release_id,
            "release_window_request_id": grant["release_window_request_id"],
            "customer_self_service_download_enabled": True,
            "download_limit": max_downloads,
            "delivery_boundary_checked": True,
            "internal_fields_exposed": False,
            "issued_by": actor_id,
        },
    }
    DeliveryRecordRepository(session=session).save(delivery_payload)
    return {
        "grant_id": grant_id,
        "delivery_id": delivery_id,
        "expires_at": grant["expires_at"],
        "max_downloads": max_downloads,
        "customer_access_url": (
            f"{config.public_base_url}/customer/access#{token}"
        ),
        "token": token,
        "access_code": access_code,
        "artifact_sha256": artifact_sha256,
        "customer_visible_delivery_enabled": True,
        "audit_ref": grant["audit_refs"][0],
    }


def read_customer_artifact(
    *,
    grant_id: str,
    token: str,
    config: ProductionReleaseConfig,
    release_readiness: Mapping[str, Any],
    session: DatabaseSession,
    object_repository: ObjectStorageRepository,
    now: datetime | None = None,
) -> dict[str, Any]:
    _release_capability(release_readiness, "customer_visible_allowed")
    token_payload = _verify_customer_token(
        token,
        secret_file=str(config.customer_portal_signing_key_file or ""),
        now=now,
    )
    if str(token_payload.get("grant_id") or "") != grant_id:
        raise PermissionError("customer access token grant mismatch")
    if str(token_payload.get("tenant_id") or "") != config.tenant_id:
        raise PermissionError("customer access token tenant mismatch")
    if str(token_payload.get("release_id") or "") != config.release_id:
        raise PermissionError("customer access token release mismatch")
    with session.serialized_key(
        f"production-release:{config.release_id}"
    ), session.serialized_key(
        f"production-customer-grant:{grant_id}"
    ), session.bulk_write():
        require_active_production_release_window(
            config=config,
            session=session,
            release_readiness=release_readiness,
            now=now,
        )
        return _read_customer_artifact_locked(
            grant_id=grant_id,
            token=token,
            session=session,
            object_repository=object_repository,
            now=now,
        )


def _read_customer_artifact_locked(
    *,
    grant_id: str,
    token: str,
    session: DatabaseSession,
    object_repository: ObjectStorageRepository,
    now: datetime | None,
) -> dict[str, Any]:
    record = session.get_record(CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE, grant_id)
    if record is None:
        raise PermissionError("customer artifact grant not found")
    grant = dict(record.payload)
    if str(grant.get("status") or "") != "ACTIVE":
        raise PermissionError("customer artifact grant is not active")
    if str(grant.get("token_sha256") or "") != _sha256_bytes(token.encode("ascii")):
        raise PermissionError("customer access token does not match active grant")
    observed = _utc_now(now)
    if observed >= _parse_iso(str(grant["expires_at"]), field_name="grant expires_at"):
        raise PermissionError("customer artifact grant expired")
    if int(grant.get("download_count") or 0) >= int(grant.get("max_downloads") or 0):
        raise PermissionError("customer artifact download limit reached")
    try:
        data = object_repository.read_object(str(grant["artifact_object_key"]))
    except (ObjectStorageMissingError, ObjectStorageIntegrityError) as exc:
        raise ValueError("customer artifact object failed integrity readback") from exc
    if _sha256_bytes(data) != str(grant["artifact_sha256"]):
        raise ValueError("customer artifact package hash mismatch")
    grant["download_count"] = int(grant.get("download_count") or 0) + 1
    grant["first_download_at"] = grant.get("first_download_at") or _iso(observed)
    grant["last_download_at"] = _iso(observed)
    grant["audit_refs"] = [
        *list(grant.get("audit_refs") or []),
        f"customer_artifact_download:{grant_id}:{grant['download_count']}",
    ]
    _save_runtime_record(
        session=session,
        object_type=CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE,
        record_id=grant_id,
        project_id=str(grant["project_id"]),
        payload=grant,
        object_refs={
            "delivery_id": str(grant["delivery_id"]),
            "payment_id": str(grant["payment_id"]),
            "order_id": str(grant["order_id"]),
            "artifact_object_key": str(grant["artifact_object_key"]),
        },
        decision_states={"status": "ACTIVE"},
        audit_refs={"download": str(grant["audit_refs"][-1])},
    )
    delivery = DeliveryRecordRepository(session=session).get_by_id(
        str(grant["delivery_id"])
    )
    if delivery is not None:
        delivery_payload = dict(delivery.payload)
        delivery_payload["delivery_status"] = "DELIVERED"
        delivery_payload["delivered_at_optional"] = _iso(observed)
        delivery_payload["retrieval_status"] = "RETRIEVED"
        delivery_payload["written_back_at_optional"] = utc_now_iso()
        DeliveryRecordRepository(session=session).save(delivery_payload)
    return {
        "bytes": data,
        "content_type": str(grant["content_type"]),
        "artifact_sha256": str(grant["artifact_sha256"]),
        "grant_id": grant_id,
        "delivery_id": grant["delivery_id"],
        "download_count": grant["download_count"],
        "downloads_remaining": int(grant["max_downloads"]) - int(grant["download_count"]),
        "audit_ref": grant["audit_refs"][-1],
    }


def revoke_customer_artifact_grant(
    *,
    grant_id: str,
    session: DatabaseSession,
    actor: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    actor_id, actor_role = _actor(actor, roles=_DELIVERY_ROLES)
    with session.serialized_key(
        f"production-customer-grant:{grant_id}"
    ), session.bulk_write():
        return _revoke_customer_artifact_grant_locked(
            grant_id=grant_id,
            session=session,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
        )


def _revoke_customer_artifact_grant_locked(
    *,
    grant_id: str,
    session: DatabaseSession,
    actor_id: str,
    actor_role: str,
    reason: str,
) -> dict[str, Any]:
    record = session.get_record(CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE, grant_id)
    if record is None:
        raise ValueError("customer artifact grant not found")
    normalized_reason = reason.strip()
    if len(normalized_reason) < 10 or len(normalized_reason) > 500:
        raise ValueError("grant revocation reason must be 10-500 characters")
    grant = dict(record.payload)
    grant.update(
        {
            "status": "REVOKED",
            "revoked_at": utc_now_iso(),
            "revoked_by": actor_id,
            "revoked_by_role": actor_role,
            "revocation_reason": normalized_reason,
            "audit_refs": [
                *list(grant.get("audit_refs") or []),
                f"customer_artifact_grant_revoked:{grant_id}:{actor_id}",
            ],
        }
    )
    _save_runtime_record(
        session=session,
        object_type=CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE,
        record_id=grant_id,
        project_id=str(grant["project_id"]),
        payload=grant,
        object_refs={
            "delivery_id": str(grant["delivery_id"]),
            "payment_id": str(grant["payment_id"]),
            "order_id": str(grant["order_id"]),
            "artifact_object_key": str(grant["artifact_object_key"]),
        },
        decision_states={"status": "REVOKED"},
        audit_refs={"revocation": str(grant["audit_refs"][-1])},
    )
    return grant


def _sign_customer_token(
    payload: Mapping[str, Any],
    *,
    secret_file: str,
) -> str:
    body = base64.urlsafe_b64encode(_canonical_json(payload)).rstrip(b"=")
    secret = _load_secret_file(secret_file, name="customer portal signing")
    signature = hmac.new(secret, body, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{body.decode('ascii')}.{encoded_signature.decode('ascii')}"


def _verify_customer_token(
    token: str,
    *,
    secret_file: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    body_text, separator, signature_text = token.partition(".")
    if (
        not separator
        or len(body_text) > 4096
        or not re.fullmatch(r"[A-Za-z0-9_-]+", body_text)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", signature_text)
    ):
        raise PermissionError("customer access token is malformed")
    body = body_text.encode("ascii")
    secret = _load_secret_file(secret_file, name="customer portal signing")
    expected = hmac.new(secret, body, hashlib.sha256).digest()
    try:
        supplied = base64.urlsafe_b64decode(
            signature_text + "=" * (-len(signature_text) % 4)
        )
    except (ValueError, TypeError) as exc:
        raise PermissionError("customer access token signature is malformed") from exc
    if not hmac.compare_digest(expected, supplied):
        raise PermissionError("customer access token signature mismatch")
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(body_text + "=" * (-len(body_text) % 4))
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise PermissionError("customer access token payload is invalid") from exc
    if not isinstance(payload, dict) or int(payload.get("v") or 0) != _TOKEN_VERSION:
        raise PermissionError("customer access token version is invalid")
    if int(payload.get("exp") or 0) <= int(_utc_now(now).timestamp()):
        raise PermissionError("customer access token expired")
    return payload


def verify_customer_access_token(
    token: str,
    *,
    config: ProductionReleaseConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    return _verify_customer_token(
        token,
        secret_file=str(config.customer_portal_signing_key_file or ""),
        now=now,
    )


def authorize_customer_session(
    *,
    token: str,
    access_code: str,
    config: ProductionReleaseConfig,
    session: DatabaseSession,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", access_code):
        raise PermissionError("customer access code is invalid")
    claims = verify_customer_access_token(token, config=config, now=now)
    grant_id = str(claims.get("grant_id") or "")
    if (
        str(claims.get("tenant_id") or "") != config.tenant_id
        or str(claims.get("release_id") or "") != config.release_id
    ):
        raise PermissionError("customer access token scope mismatch")
    with session.serialized_key(
        f"production-customer-grant:{grant_id}"
    ), session.bulk_write():
        record = session.get_record(CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE, grant_id)
        if record is None:
            raise PermissionError("customer artifact grant not found")
        grant = dict(record.payload)
        if (
            str(grant.get("status") or "") != "ACTIVE"
            or str(grant.get("token_sha256") or "")
            != _sha256_bytes(token.encode("ascii"))
        ):
            raise PermissionError("customer artifact grant is not active")
        if int(grant.get("failed_access_attempts") or 0) >= 5:
            raise PermissionError("customer artifact grant access is locked")
        expected = str(grant.get("access_code_hmac_sha256") or "")
        supplied = _customer_access_code_digest(
            access_code,
            grant_id=grant_id,
            secret_file=str(config.customer_portal_signing_key_file or ""),
        )
        if not expected or not hmac.compare_digest(expected, supplied):
            grant["failed_access_attempts"] = int(
                grant.get("failed_access_attempts") or 0
            ) + 1
            if grant["failed_access_attempts"] >= 5:
                grant["access_locked_at"] = utc_now_iso()
            _save_runtime_record(
                session=session,
                object_type=CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE,
                record_id=grant_id,
                project_id=str(grant["project_id"]),
                payload=grant,
                object_refs=dict(record.object_refs),
                decision_states={"status": str(grant["status"])},
                audit_refs=dict(record.audit_refs),
            )
            raise PermissionError("customer access code is invalid")
        grant["failed_access_attempts"] = 0
        grant["last_authenticated_at"] = utc_now_iso()
        _save_runtime_record(
            session=session,
            object_type=CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE,
            record_id=grant_id,
            project_id=str(grant["project_id"]),
            payload=grant,
            object_refs=dict(record.object_refs),
            decision_states={"status": str(grant["status"])},
            audit_refs=dict(record.audit_refs),
        )
        return {
            "grant_id": grant_id,
            "expires_at_unix": int(claims["exp"]),
            "authenticated": True,
            "second_factor_verified": True,
        }


def _customer_access_code_digest(
    access_code: str,
    *,
    grant_id: str,
    secret_file: str,
) -> str:
    secret = _load_secret_file(secret_file, name="customer portal signing")
    return hmac.new(
        secret,
        f"{grant_id}:{access_code}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _safe_provider_event_time(value: Any) -> str:
    try:
        timestamp = int(value)
        parsed = datetime.fromtimestamp(timestamp, timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError("payment provider event created timestamp is invalid") from exc
    now = datetime.now(timezone.utc)
    if parsed > now + timedelta(minutes=5) or parsed < datetime(2000, 1, 1, tzinfo=timezone.utc):
        raise ValueError("payment provider event created timestamp is outside accepted range")
    return _iso(parsed)


def _payment_by_provider_ids(
    session: DatabaseSession,
    provider_ids: set[str],
) -> PersistedRecord | None:
    if not provider_ids:
        return None
    for row in session.list_records("payment_record"):
        metadata = dict(row.payload.get("governed_metadata") or {})
        recorded_ids = {
            str(metadata.get("provider_payment_intent_id") or ""),
            str(metadata.get("provider_checkout_session_id") or ""),
        }
        recorded_ids.discard("")
        if recorded_ids.intersection(provider_ids):
            return row
    return None


def _refund_request_for_provider_event(
    *,
    session: DatabaseSession,
    provider_object: Mapping[str, Any],
    payment_id: str,
) -> PersistedRecord | None:
    provider_metadata = dict(provider_object.get("metadata") or {})
    request_id = str(provider_metadata.get("refund_request_id") or "")
    provider_refund_id = str(provider_object.get("id") or "")
    if request_id:
        record = session.get_record(PRODUCTION_REFUND_REQUEST_OBJECT_TYPE, request_id)
        if (
            record is not None
            and str(record.payload.get("payment_id") or "") == payment_id
        ):
            return record
    for record in session.list_records(PRODUCTION_REFUND_REQUEST_OBJECT_TYPE):
        if (
            str(record.payload.get("payment_id") or "") == payment_id
            and str(record.payload.get("provider_refund_id") or "") == provider_refund_id
        ):
            return record
    return None


def _save_provider_event(
    *,
    session: DatabaseSession,
    event: Mapping[str, Any],
    payment_id: str | None,
    state: str,
) -> None:
    _save_runtime_record(
        session=session,
        object_type=PAYMENT_PROVIDER_EVENT_OBJECT_TYPE,
        record_id=str(event["event_id"]),
        project_id=None,
        payload={
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "payment_id": payment_id,
            "state": state,
            "signature_verified": True,
            "body_sha256": event["body_sha256"],
            "processed_at": utc_now_iso(),
            "raw_payload_persisted": False,
        },
        object_refs={"payment_id": payment_id or ""},
        decision_states={"state": state},
        audit_refs={"webhook": f"payment_provider_event:{event['event_id']}"},
    )


def _save_runtime_record(
    *,
    session: DatabaseSession,
    object_type: str,
    record_id: str,
    project_id: str | None,
    payload: Mapping[str, Any],
    object_refs: Mapping[str, str],
    decision_states: Mapping[str, str],
    audit_refs: Mapping[str, str],
) -> PersistedRecord:
    return session.upsert_record(
        PersistedRecord(
            object_type=object_type,
            record_id=record_id,
            stage_scope=9,
            project_id=project_id,
            object_refs={
                str(key): str(value)
                for key, value in object_refs.items()
                if value not in (None, "")
            },
            decision_states=dict(decision_states),
            trace_refs={},
            audit_refs=dict(audit_refs),
            governed_state=dict(decision_states),
            writeback_state={"updated_at": utc_now_iso()},
            payload=dict(payload),
            persisted_at=build_persisted_at(),
        )
    )


__all__ = [
    "CUSTOMER_ARTIFACT_GRANT_OBJECT_TYPE",
    "PAYMENT_PROVIDER_EVENT_OBJECT_TYPE",
    "PRODUCTION_REFUND_REQUEST_OBJECT_TYPE",
    "StripeApiClient",
    "StripeApiConfig",
    "approve_and_execute_production_refund",
    "authorize_customer_session",
    "create_production_payment",
    "issue_customer_artifact_grant",
    "process_stripe_webhook",
    "read_customer_artifact",
    "request_production_refund",
    "revoke_customer_artifact_grant",
    "validate_production_delivery_source",
    "verify_stripe_webhook",
    "verify_customer_access_token",
]
