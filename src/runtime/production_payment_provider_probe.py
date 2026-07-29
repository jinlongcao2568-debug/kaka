from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from shared.utils import utc_now_iso
from stage9_delivery.production_execution import StripeApiClient, StripeApiConfig


PRODUCTION_PAYMENT_PROVIDER_PROBE_ID = (
    "runtime.production_payment_provider_probe.v1"
)


def run_production_payment_provider_probe(
    *,
    client: StripeApiClient | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    expected_account_id = str(env.get("KAKA_STRIPE_ACCOUNT_ID") or "").strip()
    if not re.fullmatch(r"acct_[A-Za-z0-9]{8,64}", expected_account_id):
        raise ValueError("KAKA_STRIPE_ACCOUNT_ID is invalid")
    output_value = str(
        env.get("KAKA_PRODUCTION_PAYMENT_PROVIDER_PROBE_FILE") or ""
    ).strip()
    if not output_value:
        raise ValueError("KAKA_PRODUCTION_PAYMENT_PROVIDER_PROBE_FILE is required")
    output_path = Path(output_value)
    if not output_path.is_absolute() or output_path.is_symlink():
        raise ValueError("payment provider probe path must be absolute and not a symlink")
    key_value = str(
        env.get("KAKA_PROVIDER_LIVE_EVIDENCE_SIGNING_KEY_FILE") or ""
    ).strip()
    key_path = Path(key_value)
    if not key_value or not key_path.is_absolute() or key_path.is_symlink():
        raise ValueError("provider evidence signing key path is invalid")
    signing_key = key_path.read_bytes().strip()
    if len(signing_key) < 32 or len(signing_key) > 4096:
        raise ValueError("provider evidence signing key length is invalid")

    stripe = client or StripeApiClient(StripeApiConfig.from_env(env))
    account = stripe.retrieve_account()
    account_id = str(account.get("id") or "")
    if account_id != expected_account_id:
        raise PermissionError("Stripe live key does not belong to expected account")
    capability_fields = {
        "charges_enabled": account.get("charges_enabled") is True,
        "payouts_enabled": account.get("payouts_enabled") is True,
        "details_submitted": account.get("details_submitted") is True,
    }
    if not all(capability_fields.values()):
        raise PermissionError("Stripe account is not enabled for charges and payouts")

    payload = {
        "evidence_version": 1,
        "probe_id": PRODUCTION_PAYMENT_PROVIDER_PROBE_ID,
        "provider_id": "stripe_payment",
        "account_id": account_id,
        **capability_fields,
        "probed_at": utc_now_iso(),
        "contains_secret_material": False,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["signature_sha256"] = hmac.new(
        signing_key,
        canonical,
        hashlib.sha256,
    ).hexdigest()
    _atomic_write_json(output_path, payload)
    return {
        **payload,
        "state": "VALIDATED",
        "evidence_path": str(output_path),
        "evidence_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the expected Stripe live account and settlement readiness"
    )
    parser.parse_args(argv)
    try:
        result = run_production_payment_provider_probe()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "probe_id": PRODUCTION_PAYMENT_PROVIDER_PROBE_ID,
                    "state": "BLOCKED",
                    "error_category": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PRODUCTION_PAYMENT_PROVIDER_PROBE_ID",
    "run_production_payment_provider_probe",
]
