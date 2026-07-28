from __future__ import annotations

import argparse
import json
import os
import re
import select
import socket
import socketserver
from dataclasses import dataclass
from threading import BoundedSemaphore
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from stage2_ingestion.real_public_url_fetcher import (
    _connect_to_pinned_public_addresses,
    _validate_public_network_url,
    registered_public_source_hosts,
)


PUBLIC_EGRESS_PROXY_ID = "runtime.public_egress_proxy.v1"
_HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_MAX_REQUEST_LINE_BYTES = 8 * 1024
_MAX_HEADER_BYTES = 64 * 1024
_MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


class PublicEgressProxyDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicEgressProxyPolicy:
    allowed_hosts: frozenset[str]
    connect_timeout_seconds: float = 10.0
    tunnel_idle_timeout_seconds: float = 60.0
    max_concurrent_connections: int = 32

    @classmethod
    def from_env(cls) -> "PublicEgressProxyPolicy":
        hosts = set(registered_public_source_hosts())
        for item in str(os.environ.get("KAKA_EGRESS_ADDITIONAL_ALLOWED_HOSTS") or "").split(","):
            host = item.strip().rstrip(".").lower()
            if not host:
                continue
            if host == "*" or host.startswith("*.") or not _HOST_PATTERN.fullmatch(host):
                raise ValueError(f"invalid explicit egress allowlist host: {host!r}")
            hosts.add(host)
        if not hosts:
            raise ValueError("public egress proxy requires at least one registered host")
        return cls(
            allowed_hosts=frozenset(hosts),
            connect_timeout_seconds=_bounded_float_env(
                "KAKA_EGRESS_CONNECT_TIMEOUT_SECONDS", 10.0, minimum=1.0, maximum=30.0
            ),
            tunnel_idle_timeout_seconds=_bounded_float_env(
                "KAKA_EGRESS_TUNNEL_IDLE_TIMEOUT_SECONDS", 60.0, minimum=5.0, maximum=600.0
            ),
            max_concurrent_connections=_bounded_int_env(
                "KAKA_EGRESS_MAX_CONCURRENT_CONNECTIONS", 32, minimum=1, maximum=128
            ),
        )

    def require_allowed(self, host: str, port: int) -> str:
        normalized = str(host or "").strip().rstrip(".").lower()
        if normalized not in self.allowed_hosts:
            raise PublicEgressProxyDenied("destination_host_not_registered")
        if port not in {80, 443}:
            raise PublicEgressProxyDenied("destination_port_not_allowed")
        return normalized

    def open_upstream(self, host: str, port: int) -> socket.socket:
        normalized = self.require_allowed(host, port)
        scheme = "https" if port == 443 else "http"
        addresses = _validate_public_network_url(
            f"{scheme}://{normalized}/",
            resolve_dns=True,
        )
        return _connect_to_pinned_public_addresses(
            addresses,
            port,
            self.connect_timeout_seconds,
        )


def _bounded_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.environ.get(name) or default))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _parse_authority(value: str, *, default_port: int | None = None) -> tuple[str, int]:
    parsed = urlsplit(f"//{value}")
    if (
        parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise PublicEgressProxyDenied("invalid_destination_authority")
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise PublicEgressProxyDenied("invalid_destination_port") from exc
    if port is None:
        raise PublicEgressProxyDenied("destination_port_required")
    return parsed.hostname.rstrip(".").lower(), int(port)


class _PublicEgressProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, server_address: tuple[str, int], policy: PublicEgressProxyPolicy) -> None:
        self.policy = policy
        self.connection_slots = BoundedSemaphore(policy.max_concurrent_connections)
        super().__init__(server_address, _PublicEgressProxyHandler)


class _PublicEgressProxyHandler(socketserver.StreamRequestHandler):
    server: _PublicEgressProxyServer

    def handle(self) -> None:
        if not self.server.connection_slots.acquire(blocking=False):
            self._send_error(503, "egress concurrency limit reached")
            return
        try:
            self._handle_request()
        finally:
            self.server.connection_slots.release()

    def _handle_request(self) -> None:
        line = self.rfile.readline(_MAX_REQUEST_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > _MAX_REQUEST_LINE_BYTES or not line.endswith(b"\n"):
            self._send_error(431, "request line too large")
            return
        try:
            method, target, version = line.decode("iso-8859-1").strip().split(" ", 2)
        except ValueError:
            self._send_error(400, "malformed proxy request line")
            return
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            self._send_error(505, "unsupported HTTP version")
            return
        try:
            headers = self._read_headers()
            if method.upper() == "CONNECT":
                self._handle_connect(target)
            else:
                self._handle_http(method.upper(), target, headers)
        except PublicEgressProxyDenied as exc:
            self._send_error(403, str(exc))
        except (OSError, RuntimeError, ValueError) as exc:
            self._send_error(502, f"controlled egress failed:{type(exc).__name__}")

    def _read_headers(self) -> list[tuple[str, str]]:
        headers: list[tuple[str, str]] = []
        total = 0
        while True:
            line = self.rfile.readline(_MAX_HEADER_BYTES + 1)
            total += len(line)
            if total > _MAX_HEADER_BYTES or not line:
                raise PublicEgressProxyDenied("proxy_request_headers_too_large_or_incomplete")
            if line in {b"\r\n", b"\n"}:
                return headers
            if b":" not in line:
                raise PublicEgressProxyDenied("malformed_proxy_request_header")
            name, value = line.decode("iso-8859-1").split(":", 1)
            normalized_name = name.strip()
            if not normalized_name or any(ch in normalized_name for ch in "\r\n\t "):
                raise PublicEgressProxyDenied("invalid_proxy_request_header_name")
            normalized_value = value.strip()
            if "\r" in normalized_value or "\n" in normalized_value:
                raise PublicEgressProxyDenied("invalid_proxy_request_header_value")
            headers.append((normalized_name, normalized_value))

    def _handle_connect(self, target: str) -> None:
        host, port = _parse_authority(target, default_port=443)
        if port != 443:
            raise PublicEgressProxyDenied("connect_port_not_allowed")
        upstream = self.server.policy.open_upstream(host, port)
        try:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\nConnection: close\r\n\r\n")
            self.wfile.flush()
            self._relay_tunnel(upstream)
        finally:
            upstream.close()

    def _relay_tunnel(self, upstream: socket.socket) -> None:
        client = self.connection
        idle_timeout = self.server.policy.tunnel_idle_timeout_seconds
        client.settimeout(idle_timeout)
        upstream.settimeout(idle_timeout)
        client_to_upstream = 0
        upstream_to_client = 0
        while True:
            readable, _, _ = select.select([client, upstream], [], [], idle_timeout)
            if not readable:
                return
            for source in readable:
                destination = upstream if source is client else client
                chunk = source.recv(64 * 1024)
                if not chunk:
                    return
                if source is client:
                    client_to_upstream += len(chunk)
                    if client_to_upstream > _MAX_REQUEST_BODY_BYTES:
                        return
                else:
                    upstream_to_client += len(chunk)
                    if upstream_to_client > _MAX_RESPONSE_BYTES:
                        return
                destination.sendall(chunk)

    def _handle_http(
        self,
        method: str,
        target: str,
        headers: list[tuple[str, str]],
    ) -> None:
        if method not in {"GET", "HEAD", "POST", "OPTIONS"}:
            raise PublicEgressProxyDenied("http_method_not_allowed")
        parsed = urlsplit(target)
        if parsed.scheme.lower() != "http" or not parsed.hostname:
            raise PublicEgressProxyDenied("absolute_http_proxy_target_required")
        if parsed.username is not None or parsed.password is not None:
            raise PublicEgressProxyDenied("destination_userinfo_not_allowed")
        try:
            port = parsed.port or 80
        except ValueError as exc:
            raise PublicEgressProxyDenied("invalid_destination_port") from exc
        host = self.server.policy.require_allowed(parsed.hostname, port)
        header_map = {name.lower(): value for name, value in headers}
        if header_map.get("transfer-encoding"):
            raise PublicEgressProxyDenied("chunked_proxy_request_not_supported")
        try:
            content_length = int(header_map.get("content-length") or 0)
        except ValueError as exc:
            raise PublicEgressProxyDenied("invalid_proxy_content_length") from exc
        if content_length < 0 or content_length > _MAX_REQUEST_BODY_BYTES:
            raise PublicEgressProxyDenied("proxy_request_body_too_large")
        body = self.rfile.read(content_length) if content_length else b""
        if len(body) != content_length:
            raise PublicEgressProxyDenied("incomplete_proxy_request_body")
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        forwarded_headers = [
            (name, value)
            for name, value in headers
            if name.lower() not in _HOP_BY_HOP_HEADERS and name.lower() != "host"
        ]
        forwarded_headers.extend([("Host", host), ("Connection", "close")])
        upstream = self.server.policy.open_upstream(host, port)
        try:
            request_head = [f"{method} {path} HTTP/1.1", *[f"{name}: {value}" for name, value in forwarded_headers], "", ""]
            upstream.sendall("\r\n".join(request_head).encode("iso-8859-1") + body)
            total = 0
            while True:
                chunk = upstream.recv(64 * 1024)
                if not chunk:
                    return
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    return
                self.connection.sendall(chunk)
        finally:
            upstream.close()

    def _send_error(self, status: int, message: str) -> None:
        reason = {
            400: "Bad Request",
            403: "Forbidden",
            431: "Request Header Fields Too Large",
            502: "Bad Gateway",
            503: "Service Unavailable",
            505: "HTTP Version Not Supported",
        }.get(status, "Error")
        payload = (message + "\n").encode("utf-8")
        try:
            self.wfile.write(
                (
                    f"HTTP/1.1 {status} {reason}\r\n"
                    "Content-Type: text/plain; charset=utf-8\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                + payload
            )
            self.wfile.flush()
        except OSError:
            pass


def build_readiness(policy: PublicEgressProxyPolicy) -> dict[str, Any]:
    return {
        "proxy_id": PUBLIC_EGRESS_PROXY_ID,
        "allowed_host_count": len(policy.allowed_hosts),
        "wildcard_allowed": False,
        "allowed_ports": [80, 443],
        "dns_result_must_be_global": True,
        "connects_to_validated_numeric_ip": True,
        "host_header_from_validated_target": True,
        "client_body_limit_bytes": _MAX_REQUEST_BODY_BYTES,
        "response_limit_bytes": _MAX_RESPONSE_BYTES,
        "max_concurrent_connections": policy.max_concurrent_connections,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the private-pilot allowlisted public egress proxy.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    policy = PublicEgressProxyPolicy.from_env()
    readiness = build_readiness(policy)
    if args.check_config:
        print(json.dumps(readiness, ensure_ascii=False, sort_keys=True))
        return 0
    if args.port < 1 or args.port > 65535:
        raise ValueError("proxy port must be between 1 and 65535")
    print(json.dumps({**readiness, "listen_host": args.host, "listen_port": args.port}, ensure_ascii=False))
    with _PublicEgressProxyServer((args.host, args.port), policy) as server:
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
