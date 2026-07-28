from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Iterator, Mapping
from uuid import uuid4


OPERATIONAL_EVENT_SCHEMA_VERSION = 1
SUPPORTED_COMPONENTS = frozenset(
    {"api", "fetch", "queue", "parse", "database", "delivery", "alert_dispatch"}
)
SUPPORTED_OUTCOMES = frozenset(
    {"started", "success", "degraded", "blocked", "retry", "cancelled", "error"}
)
SUPPORTED_SEVERITIES = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SENSITIVE_KEY_TOKENS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
)
_PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_PROCESS_LOCK = Lock()


class OperationalObservabilityConfigError(ValueError):
    pass


class OperationalEventSink:
    def __init__(
        self,
        *,
        service_name: str,
        event_path: str | Path | None,
        enabled: bool = True,
        emit_stdout: bool = True,
        max_file_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        normalized_service = str(service_name or "").strip().lower()
        if not _SAFE_NAME.fullmatch(normalized_service):
            raise OperationalObservabilityConfigError(
                "observability service_name must be a safe 1-96 character identifier"
            )
        self.service_name = normalized_service
        self.event_path = Path(event_path).resolve() if event_path else None
        self.enabled = bool(enabled)
        self.emit_stdout = bool(emit_stdout)
        self.max_file_bytes = max(1024, int(max_file_bytes))
        if self.enabled and not self.emit_stdout and self.event_path is None:
            raise OperationalObservabilityConfigError(
                "enabled observability requires stdout or a persistent event path"
            )

    @classmethod
    def from_env(cls, *, default_service_name: str) -> "OperationalEventSink":
        enabled = _env_bool("KAKA_OBSERVABILITY_ENABLED", default=False)
        event_path = str(os.getenv("KAKA_OBSERVABILITY_EVENT_PATH") or "").strip() or None
        if enabled and _env_bool("KAKA_PRIVATE_EDGE_REQUIRED", default=False) and event_path is None:
            raise OperationalObservabilityConfigError(
                "private-edge observability requires KAKA_OBSERVABILITY_EVENT_PATH"
            )
        return cls(
            service_name=str(
                os.getenv("KAKA_OBSERVABILITY_SERVICE_NAME") or default_service_name
            ),
            event_path=event_path,
            enabled=enabled,
            emit_stdout=_env_bool("KAKA_OBSERVABILITY_STDOUT_ENABLED", default=True),
            max_file_bytes=_env_int(
                "KAKA_OBSERVABILITY_MAX_FILE_BYTES",
                default=64 * 1024 * 1024,
                minimum=1024,
                maximum=1024 * 1024 * 1024,
            ),
        )

    def readiness(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "service_name": self.service_name,
            "structured_stdout_enabled": self.emit_stdout,
            "persistent_event_ledger_enabled": self.event_path is not None,
            "event_path_configured": self.event_path is not None,
            "max_file_bytes": self.max_file_bytes,
            "schema_version": OPERATIONAL_EVENT_SCHEMA_VERSION,
            "actual_runtime_events": True,
            "simulated_readback_only": False,
        }

    def record(
        self,
        *,
        component: str,
        operation: str,
        outcome: str,
        severity: str = "INFO",
        duration_ms: float | int | None = None,
        trace_id: str | None = None,
        error_category: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_component = str(component or "").strip().lower()
        normalized_operation = str(operation or "").strip().lower()
        normalized_outcome = str(outcome or "").strip().lower()
        normalized_severity = str(severity or "INFO").strip().upper()
        if normalized_component not in SUPPORTED_COMPONENTS:
            raise ValueError(f"unsupported operational component: {component!r}")
        if not _SAFE_NAME.fullmatch(normalized_operation):
            raise ValueError("operational operation must be a safe identifier")
        if normalized_outcome not in SUPPORTED_OUTCOMES:
            raise ValueError(f"unsupported operational outcome: {outcome!r}")
        if normalized_severity not in SUPPORTED_SEVERITIES:
            raise ValueError(f"unsupported operational severity: {severity!r}")

        event = {
            "schema_version": OPERATIONAL_EVENT_SCHEMA_VERSION,
            "event_id": f"OPSEVT-{uuid4().hex}",
            "occurred_at": occurred_at or _utc_now_iso(),
            "observed_unix_seconds": round(time(), 6),
            "service": self.service_name,
            "component": normalized_component,
            "operation": normalized_operation,
            "outcome": normalized_outcome,
            "severity": normalized_severity,
            "duration_ms": (
                max(0.0, round(float(duration_ms), 3))
                if duration_ms is not None
                else None
            ),
            "trace_id": _safe_optional_identifier(trace_id),
            "error_category": _safe_optional_identifier(error_category),
            "attributes": _sanitize_attributes(attributes or {}),
            "alert_eligible": normalized_severity in {"ERROR", "CRITICAL"},
            "contains_secret_material": False,
        }
        if not self.enabled:
            return {**event, "recorded": False, "recording_state": "DISABLED"}

        encoded = (
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded) > 32 * 1024:
            raise ValueError("operational event exceeds 32 KiB safety limit")
        if self.emit_stdout:
            sys.stderr.write(encoded.decode("utf-8"))
            sys.stderr.flush()
        if self.event_path is not None:
            self._append(encoded)
        return {**event, "recorded": True, "recording_state": "RECORDED"}

    def _append(self, encoded: bytes) -> None:
        assert self.event_path is not None
        path = self.event_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f"{path.name}.lock")
        with _PROCESS_LOCK, _exclusive_file_lock(lock_path):
            current_size = path.stat().st_size if path.exists() else 0
            if current_size + len(encoded) > self.max_file_bytes:
                rotated = path.with_name(f"{path.name}.1")
                if rotated.exists():
                    rotated.unlink()
                if path.exists():
                    os.replace(path, rotated)
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())


def load_operational_events(
    event_path: str | Path | None,
    *,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    if not event_path:
        return []
    path = Path(event_path)
    if not path.is_file():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=max(1, min(int(limit), 100_000)))
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            value = line.strip()
            if not value:
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"operational event ledger contains invalid JSON at line {line_number}"
                ) from exc
            if not isinstance(payload, Mapping):
                raise ValueError(
                    f"operational event ledger line {line_number} is not an object"
                )
            rows.append(dict(payload))
    return list(rows)


def operational_metrics_snapshot(
    event_path: str | Path | None,
    *,
    limit: int = 10_000,
) -> dict[str, Any]:
    events = load_operational_events(event_path, limit=limit)
    event_counts: Counter[tuple[str, str, str, str]] = Counter()
    error_counts: Counter[tuple[str, str, str]] = Counter()
    last_timestamp: dict[tuple[str, str], float] = {}
    for event in events:
        service = str(event.get("service") or "unknown")
        component = str(event.get("component") or "unknown")
        operation = str(event.get("operation") or "unknown")
        outcome = str(event.get("outcome") or "unknown")
        event_counts[(service, component, operation, outcome)] += 1
        timestamp = float(event.get("observed_unix_seconds") or 0.0)
        last_timestamp[(service, component)] = max(
            timestamp,
            last_timestamp.get((service, component), 0.0),
        )
        if str(event.get("severity") or "").upper() in {"ERROR", "CRITICAL"}:
            error_category = str(event.get("error_category") or "uncategorized")
            error_counts[(service, component, error_category)] += 1
    return {
        "schema_version": 1,
        "event_count": len(events),
        "event_counts": [
            {
                "service": key[0],
                "component": key[1],
                "operation": key[2],
                "outcome": key[3],
                "count": count,
            }
            for key, count in sorted(event_counts.items())
        ],
        "error_counts": [
            {
                "service": key[0],
                "component": key[1],
                "error_category": key[2],
                "count": count,
            }
            for key, count in sorted(error_counts.items())
        ],
        "last_event_unix_seconds": [
            {"service": key[0], "component": key[1], "value": value}
            for key, value in sorted(last_timestamp.items())
        ],
        "source": "actual_operational_event_ledger",
        "simulated_readback_only": False,
    }


def render_prometheus_metrics(snapshot: Mapping[str, Any]) -> str:
    lines = [
        "# HELP kaka_operational_events_total Actual Kaka operational events.",
        "# TYPE kaka_operational_events_total counter",
    ]
    for row in list(snapshot.get("event_counts") or []):
        labels = _labels(
            service=row.get("service"),
            component=row.get("component"),
            operation=row.get("operation"),
            outcome=row.get("outcome"),
        )
        lines.append(f"kaka_operational_events_total{{{labels}}} {int(row.get('count') or 0)}")
    lines.extend(
        [
            "# HELP kaka_operational_errors_total Actual Kaka error events.",
            "# TYPE kaka_operational_errors_total counter",
        ]
    )
    for row in list(snapshot.get("error_counts") or []):
        labels = _labels(
            service=row.get("service"),
            component=row.get("component"),
            error_category=row.get("error_category"),
        )
        lines.append(f"kaka_operational_errors_total{{{labels}}} {int(row.get('count') or 0)}")
    lines.extend(
        [
            "# HELP kaka_operational_last_event_timestamp_seconds Last actual event time.",
            "# TYPE kaka_operational_last_event_timestamp_seconds gauge",
        ]
    )
    for row in list(snapshot.get("last_event_unix_seconds") or []):
        labels = _labels(service=row.get("service"), component=row.get("component"))
        lines.append(
            f"kaka_operational_last_event_timestamp_seconds{{{labels}}} "
            f"{float(row.get('value') or 0.0):.6f}"
        )
    lines.append("")
    return "\n".join(lines)


@lru_cache(maxsize=16)
def get_operational_event_sink(service_name: str) -> OperationalEventSink:
    return OperationalEventSink.from_env(default_service_name=service_name)


def record_operational_event_safely(
    sink: OperationalEventSink,
    **event: Any,
) -> dict[str, Any]:
    """Record one event without allowing telemetry I/O to alter the business outcome."""
    try:
        return sink.record(**event)
    except Exception as exc:
        diagnostic = {
            "event": "operational_observability_write_failed",
            "service": sink.service_name,
            "component": str(event.get("component") or "unknown")[:96],
            "operation": str(event.get("operation") or "unknown")[:96],
            "error_category": type(exc).__name__,
        }
        try:
            sys.stderr.write(
                json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
        return {
            **diagnostic,
            "recorded": False,
            "recording_state": "WRITE_FAILED",
        }


def reset_operational_event_sinks() -> None:
    get_operational_event_sink.cache_clear()


@contextmanager
def _exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _sanitize_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for index, (raw_key, raw_value) in enumerate(attributes.items()):
        if index >= 32:
            break
        key = str(raw_key or "").strip().lower()
        if not _SAFE_NAME.fullmatch(key):
            continue
        if any(token in key for token in _SENSITIVE_KEY_TOKENS):
            sanitized[key] = "[REDACTED]"
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            sanitized[key] = raw_value
        else:
            sanitized[key] = str(raw_value)[:512]
    return sanitized


def _safe_optional_identifier(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", normalized)[:160]


def _labels(**values: Any) -> str:
    return ",".join(
        f'{key}="{_escape_prometheus_label(value)}"'
        for key, value in sorted(values.items())
    )


def _escape_prometheus_label(value: Any) -> str:
    return str(value or "unknown").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise OperationalObservabilityConfigError(f"{name} must be a boolean")


def _env_int(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise OperationalObservabilityConfigError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise OperationalObservabilityConfigError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "OPERATIONAL_EVENT_SCHEMA_VERSION",
    "OperationalEventSink",
    "OperationalObservabilityConfigError",
    "get_operational_event_sink",
    "record_operational_event_safely",
    "load_operational_events",
    "operational_metrics_snapshot",
    "render_prometheus_metrics",
    "reset_operational_event_sinks",
    "_PROMETHEUS_CONTENT_TYPE",
]
