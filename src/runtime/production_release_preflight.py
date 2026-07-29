from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from runtime.production_release_orchestrator import (
    PRODUCTION_RELEASE_STATE_ACTIVE,
    ProductionReleaseConfig,
    build_production_release_readiness,
    production_alert_dispatch_readiness,
)
from shared.settings import Settings
from storage.db import DatabaseSession


PRODUCTION_RELEASE_PREFLIGHT_ID = "runtime.production_release_preflight.v1"


def run_production_release_preflight(
    *,
    require_active: bool = False,
) -> dict[str, Any]:
    repo_root = str(Path(__file__).resolve().parents[2])
    settings = Settings.from_env(
        repo_root=repo_root,
        environment=str(os.getenv("KAKA_ENVIRONMENT") or "INTERNAL_ONLY"),
    )
    session = DatabaseSession(settings=settings)
    try:
        config = ProductionReleaseConfig.from_env(settings=settings)
        readiness = build_production_release_readiness(
            config=config,
            settings=settings,
            provider_summary=settings.provider_adapter_readiness_summary(),
            session=session,
            alert_readiness=production_alert_dispatch_readiness(),
        )
    finally:
        session.close()
    passed = bool(
        readiness.get("release_active")
        if require_active
        else readiness.get("technical_ready")
    )
    return {
        "preflight_id": PRODUCTION_RELEASE_PREFLIGHT_ID,
        "state": "PASSED" if passed else "BLOCKED",
        "require_active": require_active,
        "release_id": readiness.get("release_id"),
        "release_version": readiness.get("release_version"),
        "tenant_id": readiness.get("tenant_id"),
        "release_state": readiness.get("state"),
        "technical_ready": bool(readiness.get("technical_ready")),
        "release_active": bool(readiness.get("release_active")),
        "readiness_hash": readiness.get("readiness_hash"),
        "technical_blocking_reasons": list(
            readiness.get("technical_blocking_reasons") or []
        ),
        "blocking_reasons": list(readiness.get("blocking_reasons") or []),
        "provider_readiness": dict(readiness.get("provider_readiness") or {}),
        "alert_dispatch_readiness": dict(
            readiness.get("alert_dispatch_readiness") or {}
        ),
        "recovery_evidence_readiness": dict(
            readiness.get("recovery_evidence_readiness") or {}
        ),
        "payment_provider_probe_readiness": dict(
            readiness.get("payment_provider_probe_readiness") or {}
        ),
        "storage_schema_revision": readiness.get("storage_schema_revision"),
        "required_storage_schema_revision": readiness.get(
            "required_storage_schema_revision"
        ),
        "automated_refund_enabled": False,
        "contains_secret_material": False,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    resolved = path.resolve()
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("preflight output path must be absolute and not a symlink")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate customer-visible production release gates"
    )
    parser.add_argument("--require-active", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_production_release_preflight(
            require_active=args.require_active,
        )
        if args.output_json:
            _atomic_write_json(args.output_json, result)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "preflight_id": PRODUCTION_RELEASE_PREFLIGHT_ID,
                    "state": "BLOCKED",
                    "error_category": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["state"] == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PRODUCTION_RELEASE_PREFLIGHT_ID",
    "run_production_release_preflight",
]
