from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from runtime.operational_alert_dispatcher import OperationalAlertConfig
from runtime.operational_observability import get_operational_event_sink
from shared.utils import utc_now_iso


PRODUCTION_ALERT_PROBE_ID = "runtime.production_alert_probe.v1"


def run_production_alert_probe(
    *,
    wait_seconds: float = 90.0,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    if wait_seconds < 5 or wait_seconds > 600:
        raise ValueError("wait_seconds must be between 5 and 600")
    if poll_seconds < 0.1 or poll_seconds > 10:
        raise ValueError("poll_seconds must be between 0.1 and 10")
    evidence_path_value = str(
        os.getenv("KAKA_PRODUCTION_ALERT_TEST_EVIDENCE_FILE") or ""
    ).strip()
    if not evidence_path_value:
        raise ValueError("KAKA_PRODUCTION_ALERT_TEST_EVIDENCE_FILE is required")
    evidence_path = Path(evidence_path_value)
    if not evidence_path.is_absolute() or evidence_path.is_symlink():
        raise ValueError("production alert evidence path must be absolute and not a symlink")

    alert_config = OperationalAlertConfig.from_env()
    event = get_operational_event_sink("production-alert-probe").record(
        component="api",
        operation="production_alert_probe",
        outcome="error",
        severity="CRITICAL",
        error_category="release_alert_probe",
        attributes={
            "probe_id": PRODUCTION_ALERT_PROBE_ID,
            "customer_impact": False,
            "synthetic": True,
        },
    )
    event_id = str(event.get("event_id") or "")
    if not event.get("recorded") or not event_id:
        raise RuntimeError("production alert probe event was not persisted")

    deadline = time.monotonic() + wait_seconds
    delivered = False
    while time.monotonic() < deadline:
        state = _read_alert_state(alert_config.state_path)
        delivered = event_id in {
            str(item) for item in list(state.get("delivered_event_ids") or [])
        }
        if delivered:
            break
        time.sleep(poll_seconds)
    if not delivered:
        raise TimeoutError("production alert probe was not delivered before the deadline")

    evidence = {
        "evidence_version": 1,
        "probe_id": PRODUCTION_ALERT_PROBE_ID,
        "event_id": event_id,
        "delivered": True,
        "delivered_verified_at": utc_now_iso(),
        "alert_state_path": str(alert_config.state_path),
        "contains_secret_material": False,
    }
    _atomic_write_json(evidence_path, evidence)
    return {
        **evidence,
        "evidence_path": str(evidence_path),
    }


def _read_alert_state(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    if path.stat().st_size <= 0 or path.stat().st_size > 8 * 1024 * 1024:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


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
        description="Emit and verify one actual production alert delivery probe"
    )
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        result = run_production_alert_probe(
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "probe_id": PRODUCTION_ALERT_PROBE_ID,
                    "state": "BLOCKED",
                    "error_category": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps({**result, "state": "DELIVERED"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PRODUCTION_ALERT_PROBE_ID",
    "run_production_alert_probe",
]
