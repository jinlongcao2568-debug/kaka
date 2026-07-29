from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from shared.provider_adapter_config import PROVIDER_FAMILIES


PROVIDER_LIVE_EVIDENCE_GENERATOR_ID = "runtime.provider_live_evidence.v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")


def create_provider_live_evidence(
    *,
    family: str,
    provider_id: str,
    signing_key_file: Path,
    output_file: Path,
    expires_at: str,
    sandbox_execution_ref: str,
    callback_event_ref: str,
    approval_ref: str,
    audit_ref: str,
    operator_action_ref: str,
) -> dict[str, Any]:
    normalized_family = str(family or "").strip()
    normalized_provider = str(provider_id or "").strip()
    if normalized_family not in PROVIDER_FAMILIES:
        raise ValueError("provider evidence family is unsupported")
    if not _SAFE_ID.fullmatch(normalized_provider):
        raise ValueError("provider evidence provider_id is invalid")

    key_path = signing_key_file.resolve()
    output_path = output_file.resolve()
    if not signing_key_file.is_absolute() or signing_key_file.is_symlink():
        raise ValueError("signing key file must be an absolute non-symlink path")
    if not key_path.is_file():
        raise ValueError("signing key file is missing")
    signing_key = key_path.read_bytes().strip()
    if len(signing_key) < 32 or len(signing_key) > 4096:
        raise ValueError("signing key must contain between 32 and 4096 bytes")
    if not output_file.is_absolute() or output_file.is_symlink():
        raise ValueError("output file must be an absolute non-symlink path")
    if output_path.exists():
        raise FileExistsError("provider evidence output is immutable and already exists")

    expiry = _parse_expiry(expires_at)
    refs = {
        "sandbox_execution_ref": sandbox_execution_ref,
        "callback_event_ref": callback_event_ref,
        "approval_ref": approval_ref,
        "audit_ref": audit_ref,
        "operator_action_ref": operator_action_ref,
    }
    for name, value in refs.items():
        normalized = str(value or "").strip()
        if len(normalized) < 3 or len(normalized) > 512:
            raise ValueError(f"{name} must contain between 3 and 512 characters")
        refs[name] = normalized

    payload = {
        "evidence_version": 1,
        "family": normalized_family,
        "provider_id": normalized_provider,
        "sandbox_pass_state": "PASSED",
        "callback_validation_state": "VALIDATED",
        **refs,
        "expires_at": expiry.isoformat().replace("+00:00", "Z"),
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
        "generator_id": PROVIDER_LIVE_EVIDENCE_GENERATOR_ID,
        "state": "SIGNED",
        "family": normalized_family,
        "provider_id": normalized_provider,
        "expires_at": payload["expires_at"],
        "evidence_file": str(output_path),
        "evidence_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "signature_sha256": payload["signature_sha256"],
        "contains_secret_material": False,
    }


def _parse_expiry(value: str) -> datetime:
    try:
        expiry = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if expiry.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    expiry = expiry.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    seconds = (expiry - now).total_seconds()
    if seconds < 3600 or seconds > 90 * 24 * 3600:
        raise ValueError("expires_at must be between 1 hour and 90 days in the future")
    return expiry


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create one immutable signed provider-live evidence file"
    )
    parser.add_argument("--family", required=True, choices=PROVIDER_FAMILIES)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--signing-key-file", required=True, type=Path)
    parser.add_argument("--output-file", required=True, type=Path)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--sandbox-execution-ref", required=True)
    parser.add_argument("--callback-event-ref", required=True)
    parser.add_argument("--approval-ref", required=True)
    parser.add_argument("--audit-ref", required=True)
    parser.add_argument("--operator-action-ref", required=True)
    args = parser.parse_args(argv)
    try:
        result = create_provider_live_evidence(
            family=args.family,
            provider_id=args.provider_id,
            signing_key_file=args.signing_key_file,
            output_file=args.output_file,
            expires_at=args.expires_at,
            sandbox_execution_ref=args.sandbox_execution_ref,
            callback_event_ref=args.callback_event_ref,
            approval_ref=args.approval_ref,
            audit_ref=args.audit_ref,
            operator_action_ref=args.operator_action_ref,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "generator_id": PROVIDER_LIVE_EVIDENCE_GENERATOR_ID,
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
    "PROVIDER_LIVE_EVIDENCE_GENERATOR_ID",
    "create_provider_live_evidence",
]
