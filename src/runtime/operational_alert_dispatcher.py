from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import signal
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from runtime.operational_observability import (
    get_operational_event_sink,
    load_operational_events,
    record_operational_event_safely,
)


ALERT_DISPATCHER_ID = "runtime.operational_alert_dispatcher.v1"
ALERT_STATE_SCHEMA_VERSION = 1
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_POLL_SECONDS = 15.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_TRACKED_EVENT_IDS = 250_000
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class OperationalAlertConfigError(ValueError):
    pass


class OperationalAlertDispatchError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class OperationalAlertConfig:
    event_path: Path
    state_path: Path
    dead_letter_path: Path
    webhook_url: str
    allowed_hosts: frozenset[str]
    signing_secret_file: Path
    proxy_url: str | None = None
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    batch_size: int = 50
    allow_http_loopback: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_attempts > 20:
            raise OperationalAlertConfigError("alert max_attempts must be between 1 and 20")
        if self.request_timeout_seconds <= 0 or self.request_timeout_seconds > 60:
            raise OperationalAlertConfigError(
                "alert request_timeout_seconds must be greater than 0 and at most 60"
            )
        if self.batch_size < 1 or self.batch_size > 500:
            raise OperationalAlertConfigError("alert batch_size must be between 1 and 500")
        host = _validate_webhook_url(
            self.webhook_url,
            allow_http_loopback=self.allow_http_loopback,
        )
        normalized_allowed_hosts = frozenset(_normalized_host(item) for item in self.allowed_hosts)
        if not normalized_allowed_hosts or host not in normalized_allowed_hosts:
            raise OperationalAlertConfigError(
                "alert webhook host must exactly match KAKA_ALERT_ALLOWED_HOSTS"
            )
        if not self.signing_secret_file.is_file():
            raise OperationalAlertConfigError("alert signing secret file is missing")
        secret = self.signing_secret_file.read_bytes().strip()
        if len(secret) < 16 or len(secret) > 4096:
            raise OperationalAlertConfigError(
                "alert signing secret file must contain between 16 and 4096 bytes"
            )
        if secret == b"replace-with-random-32-byte-secret":
            raise OperationalAlertConfigError("example alert signing secret cannot be used")
        if self.proxy_url:
            parsed_proxy = urlsplit(self.proxy_url)
            if (
                parsed_proxy.scheme not in {"http", "https"}
                or not parsed_proxy.hostname
                or parsed_proxy.username
                or parsed_proxy.password
            ):
                raise OperationalAlertConfigError("controlled alert proxy URL is invalid")
        elif not (self.allow_http_loopback and host in _LOOPBACK_HOSTS):
            raise OperationalAlertConfigError(
                "non-loopback alert dispatch requires a controlled egress proxy"
            )

    @classmethod
    def from_env(cls) -> "OperationalAlertConfig":
        event_path = _required_env("KAKA_OBSERVABILITY_EVENT_PATH")
        webhook_url = _required_env("KAKA_ALERT_WEBHOOK_URL")
        allowed_hosts = frozenset(
            item.strip().lower().rstrip(".")
            for item in _required_env("KAKA_ALERT_ALLOWED_HOSTS").split(",")
            if item.strip()
        )
        secret_file = _required_env("KAKA_ALERT_SIGNING_SECRET_FILE")
        event = Path(event_path).resolve()
        state_path = Path(
            str(os.getenv("KAKA_ALERT_STATE_PATH") or "").strip()
            or event.with_name("operational-alert-state-v1.json")
        ).resolve()
        dead_letter_path = Path(
            str(os.getenv("KAKA_ALERT_DEAD_LETTER_PATH") or "").strip()
            or event.with_name("operational-alert-dead-letter-v1.jsonl")
        ).resolve()
        private_edge = _env_bool("KAKA_PRIVATE_EDGE_REQUIRED", default=False)
        proxy_url = str(os.getenv("KAKA_CONTROLLED_EGRESS_PROXY_URL") or "").strip() or None
        if private_edge and not proxy_url:
            raise OperationalAlertConfigError(
                "private-edge alert dispatch requires KAKA_CONTROLLED_EGRESS_PROXY_URL"
            )
        return cls(
            event_path=event,
            state_path=state_path,
            dead_letter_path=dead_letter_path,
            webhook_url=webhook_url,
            allowed_hosts=allowed_hosts,
            signing_secret_file=Path(secret_file).resolve(),
            proxy_url=proxy_url,
            max_attempts=_env_int(
                "KAKA_ALERT_MAX_ATTEMPTS", default=DEFAULT_MAX_ATTEMPTS, minimum=1, maximum=20
            ),
            request_timeout_seconds=_env_float(
                "KAKA_ALERT_REQUEST_TIMEOUT_SECONDS",
                default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
                minimum=0.1,
                maximum=60.0,
            ),
            batch_size=_env_int("KAKA_ALERT_BATCH_SIZE", default=50, minimum=1, maximum=500),
            allow_http_loopback=False,
        )

    def readiness(self) -> dict[str, Any]:
        return {
            "dispatcher_id": ALERT_DISPATCHER_ID,
            "ready": True,
            "event_path_configured": True,
            "persistent_state_configured": True,
            "dead_letter_path_configured": True,
            "webhook_host": _normalized_host(urlsplit(self.webhook_url).hostname or ""),
            "webhook_scheme": urlsplit(self.webhook_url).scheme.lower(),
            "exact_host_allowlist_enforced": True,
            "hmac_sha256_signing_enabled": True,
            "controlled_proxy_configured": self.proxy_url is not None,
            "max_attempts": self.max_attempts,
            "batch_size": self.batch_size,
            "actual_external_dispatch_configured": True,
            "simulated_readback_only": False,
        }


class OperationalAlertDispatcher:
    def __init__(self, config: OperationalAlertConfig) -> None:
        self.config = config
        self._sink = get_operational_event_sink("alert-dispatcher")

    def dispatch_once(self, *, now_unix_seconds: float | None = None) -> dict[str, Any]:
        observed_at = float(now_unix_seconds if now_unix_seconds is not None else time.time())
        lock_path = self.config.state_path.with_name(f"{self.config.state_path.name}.lock")
        with _exclusive_file_lock(lock_path):
            state = _load_state(self.config.state_path)
            candidates = self._candidate_events(state)
            attempted = delivered = retry_scheduled = dead_lettered = 0
            for event_payload in candidates[: self.config.batch_size]:
                event_id = str(event_payload["event_id"])
                attempt_state = dict(state["attempts"].get(event_id) or {})
                if float(attempt_state.get("next_attempt_unix_seconds") or 0.0) > observed_at:
                    continue
                attempted += 1
                try:
                    status_code = self._send(event_payload)
                except OperationalAlertDispatchError as exc:
                    attempt_count = int(attempt_state.get("attempt_count") or 0) + 1
                    if attempt_count >= self.config.max_attempts:
                        _append_dead_letter(
                            self.config.dead_letter_path,
                            event_payload,
                            attempt_count=attempt_count,
                            error_category=exc.category,
                        )
                        state["dead_letter_event_ids"].append(event_id)
                        state["attempts"].pop(event_id, None)
                        dead_lettered += 1
                        self._record_dispatch_event(
                            event_payload,
                            outcome="error",
                            severity="ERROR",
                            error_category="max_attempts_exhausted",
                            attributes={"attempt_count": attempt_count},
                        )
                    else:
                        next_attempt = observed_at + _retry_delay_seconds(attempt_count)
                        state["attempts"][event_id] = {
                            "attempt_count": attempt_count,
                            "next_attempt_unix_seconds": next_attempt,
                            "last_error_category": exc.category,
                        }
                        retry_scheduled += 1
                        self._record_dispatch_event(
                            event_payload,
                            outcome="retry",
                            severity="WARNING",
                            error_category=exc.category,
                            attributes={
                                "attempt_count": attempt_count,
                                "next_attempt_unix_seconds": next_attempt,
                            },
                        )
                else:
                    state["delivered_event_ids"].append(event_id)
                    state["attempts"].pop(event_id, None)
                    delivered += 1
                    self._record_dispatch_event(
                        event_payload,
                        outcome="success",
                        severity="INFO",
                        attributes={"status_code": status_code},
                    )
                _trim_state(state)
                _save_state(self.config.state_path, state)

            if attempted == 0:
                _save_state(self.config.state_path, state)
            return {
                "dispatcher_id": ALERT_DISPATCHER_ID,
                "state": "DISPATCH_COMPLETED",
                "candidate_count": len(candidates),
                "attempted_count": attempted,
                "delivered_count": delivered,
                "retry_scheduled_count": retry_scheduled,
                "dead_lettered_count": dead_lettered,
                "tracked_delivered_count": len(state["delivered_event_ids"]),
                "tracked_dead_letter_count": len(state["dead_letter_event_ids"]),
                "pending_retry_count": len(state["attempts"]),
                "completed_at_unix_seconds": time.time(),
                **self.config.readiness(),
            }

    def _candidate_events(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        delivered = set(str(item) for item in list(state.get("delivered_event_ids") or []))
        dead_lettered = set(str(item) for item in list(state.get("dead_letter_event_ids") or []))
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        rotated_path = self.config.event_path.with_name(f"{self.config.event_path.name}.1")
        for source_path in (rotated_path, self.config.event_path):
            for item in load_operational_events(source_path, limit=100_000):
                event_id = str(item.get("event_id") or "")
                if not event_id or event_id in seen or event_id in delivered or event_id in dead_lettered:
                    continue
                seen.add(event_id)
                if not bool(item.get("alert_eligible")):
                    continue
                if str(item.get("severity") or "").upper() not in {"ERROR", "CRITICAL"}:
                    continue
                if str(item.get("component") or "").lower() == "alert_dispatch":
                    continue
                candidates.append(dict(item))
        return candidates

    def _send(self, event_payload: Mapping[str, Any]) -> int:
        secret = self.config.signing_secret_file.read_bytes().strip()
        body = json.dumps(
            _webhook_payload(event_payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
        event_id = str(event_payload.get("event_id") or "")
        request = Request(
            self.config.webhook_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Kaka-Operational-Alert-Dispatcher/1.0",
                "X-Kaka-Alert-ID": event_id,
                "X-Kaka-Signature": f"sha256={signature}",
            },
        )
        proxies = (
            {"http": self.config.proxy_url, "https": self.config.proxy_url}
            if self.config.proxy_url
            else {}
        )
        opener = build_opener(ProxyHandler(proxies))
        try:
            with opener.open(request, timeout=self.config.request_timeout_seconds) as response:
                status_code = int(getattr(response, "status", 0))
                response.read(4097)
        except HTTPError as exc:
            raise OperationalAlertDispatchError(f"HTTP_{int(exc.code)}") from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", None)
            category = type(reason).__name__ if reason is not None else type(exc).__name__
            raise OperationalAlertDispatchError(category) from exc
        except OSError as exc:
            raise OperationalAlertDispatchError(type(exc).__name__) from exc
        if status_code < 200 or status_code >= 300:
            raise OperationalAlertDispatchError(f"HTTP_{status_code}")
        return status_code

    def _record_dispatch_event(
        self,
        source_event: Mapping[str, Any],
        *,
        outcome: str,
        severity: str,
        error_category: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        record_operational_event_safely(
            self._sink,
            component="alert_dispatch",
            operation="webhook_delivery",
            outcome=outcome,
            severity=severity,
            trace_id=str(source_event.get("event_id") or "") or None,
            error_category=error_category,
            attributes={
                "source_service": source_event.get("service"),
                "source_component": source_event.get("component"),
                "source_operation": source_event.get("operation"),
                **dict(attributes or {}),
            },
        )


def _webhook_payload(event_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "alert_id": event_payload.get("event_id"),
        "occurred_at": event_payload.get("occurred_at"),
        "service": event_payload.get("service"),
        "component": event_payload.get("component"),
        "operation": event_payload.get("operation"),
        "outcome": event_payload.get("outcome"),
        "severity": event_payload.get("severity"),
        "error_category": event_payload.get("error_category"),
        "trace_id": event_payload.get("trace_id"),
        "attributes": dict(event_payload.get("attributes") or {}),
        "source": "actual_operational_event_ledger",
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": ALERT_STATE_SCHEMA_VERSION,
            "delivered_event_ids": [],
            "dead_letter_event_ids": [],
            "attempts": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationalAlertConfigError("alert dispatcher state is unreadable or invalid") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != ALERT_STATE_SCHEMA_VERSION:
        raise OperationalAlertConfigError("alert dispatcher state schema is invalid")
    delivered = payload.get("delivered_event_ids")
    dead = payload.get("dead_letter_event_ids")
    attempts = payload.get("attempts")
    if not isinstance(delivered, list) or not isinstance(dead, list) or not isinstance(attempts, Mapping):
        raise OperationalAlertConfigError("alert dispatcher state fields are invalid")
    return {
        "schema_version": ALERT_STATE_SCHEMA_VERSION,
        "delivered_event_ids": [str(item) for item in delivered],
        "dead_letter_event_ids": [str(item) for item in dead],
        "attempts": {str(key): dict(value) for key, value in attempts.items() if isinstance(value, Mapping)},
    }


def _save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_dead_letter(
    path: Path,
    event_payload: Mapping[str, Any],
    *,
    attempt_count: int,
    error_category: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "dead_lettered_at_unix_seconds": time.time(),
        "event_id": event_payload.get("event_id"),
        "source_service": event_payload.get("service"),
        "source_component": event_payload.get("component"),
        "source_operation": event_payload.get("operation"),
        "attempt_count": attempt_count,
        "error_category": error_category,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _trim_state(state: dict[str, Any]) -> None:
    for key in ("delivered_event_ids", "dead_letter_event_ids"):
        values = list(dict.fromkeys(str(item) for item in list(state.get(key) or [])))
        state[key] = values[-_MAX_TRACKED_EVENT_IDS:]


def _retry_delay_seconds(attempt_count: int) -> float:
    return float(min(300, 2 ** max(0, attempt_count - 1)))


class _exclusive_file_lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_exclusive_file_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        assert self.handle is not None
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _validate_webhook_url(url: str, *, allow_http_loopback: bool) -> str:
    try:
        parsed = urlsplit(str(url or "").strip())
        host = _normalized_host(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise OperationalAlertConfigError("alert webhook URL is invalid") from exc
    if not host or parsed.username or parsed.password or parsed.fragment:
        raise OperationalAlertConfigError("alert webhook URL boundary is invalid")
    if parsed.scheme != "https" and not (
        allow_http_loopback and parsed.scheme == "http" and host in _LOOPBACK_HOSTS
    ):
        raise OperationalAlertConfigError("alert webhook URL must use HTTPS")
    if port is not None and (port < 1 or port > 65535):
        raise OperationalAlertConfigError("alert webhook URL port is invalid")
    return host


def _normalized_host(value: str) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise OperationalAlertConfigError(f"{name} is required")
    return value


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise OperationalAlertConfigError(f"{name} must be a boolean")


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise OperationalAlertConfigError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise OperationalAlertConfigError(f"{name} is outside the supported range")
    return value


def _env_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise OperationalAlertConfigError(f"{name} must be numeric") from exc
    if value < minimum or value > maximum:
        raise OperationalAlertConfigError(f"{name} is outside the supported range")
    return value


def _write_status(path: str | None, payload: Mapping[str, Any]) -> None:
    if not path:
        return
    _save_state(Path(path).resolve(), dict(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch actual Kaka operational alerts")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--status-json")
    args = parser.parse_args(argv)
    if args.poll_seconds < 1 or args.poll_seconds > 300:
        parser.error("--poll-seconds must be between 1 and 300")
    try:
        dispatcher = OperationalAlertDispatcher(OperationalAlertConfig.from_env())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "dispatcher_id": ALERT_DISPATCHER_ID,
                    "state": "CONFIGURATION_BLOCKED",
                    "error_category": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2

    if not args.serve:
        result = dispatcher.dispatch_once()
        _write_status(args.status_json, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    stop_event = threading.Event()

    def _request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not stop_event.is_set():
        try:
            result = dispatcher.dispatch_once()
        except Exception as exc:
            result = {
                "dispatcher_id": ALERT_DISPATCHER_ID,
                "state": "DISPATCH_LOOP_ERROR",
                "error_category": type(exc).__name__,
                **dispatcher.config.readiness(),
            }
        _write_status(args.status_json, result)
        if not stop_event.wait(args.poll_seconds):
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALERT_DISPATCHER_ID",
    "OperationalAlertConfig",
    "OperationalAlertConfigError",
    "OperationalAlertDispatcher",
    "main",
]
