from __future__ import annotations

import os
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import runtime.public_egress_proxy as proxy_module
from runtime.public_egress_proxy import (
    PublicEgressProxyDenied,
    PublicEgressProxyPolicy,
    _PublicEgressProxyServer,
    _parse_authority,
    build_readiness,
)
from shared.controlled_egress import controlled_egress_proxy_url, playwright_proxy_settings


class PublicEgressProxyTests(unittest.TestCase):
    def test_private_pilot_browser_transport_requires_controlled_proxy(self) -> None:
        with patch.dict(
            os.environ,
            {"KAKA_DEPLOYMENT_TENANCY_MODE": "PRIVATE_SINGLE_TENANT"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "controlled_egress_proxy_required"):
                controlled_egress_proxy_url()

        with patch.dict(
            os.environ,
            {
                "KAKA_DEPLOYMENT_TENANCY_MODE": "PRIVATE_SINGLE_TENANT",
                "KAKA_CONTROLLED_EGRESS_PROXY_URL": "http://egress-proxy:18080",
            },
            clear=True,
        ):
            self.assertEqual(
                playwright_proxy_settings(),
                {"server": "http://egress-proxy:18080"},
            )

        with patch.dict(
            os.environ,
            {"KAKA_CONTROLLED_EGRESS_PROXY_URL": "http://public-proxy.example:8080"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "proxy_host_not_allowed"):
                controlled_egress_proxy_url()

    def test_registry_allowlist_is_explicit_and_has_no_wildcards(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            policy = PublicEgressProxyPolicy.from_env()

        self.assertGreaterEqual(len(policy.allowed_hosts), 18)
        self.assertIn("www.ggzy.gov.cn", policy.allowed_hosts)
        self.assertNotIn("*", policy.allowed_hosts)
        self.assertFalse(any(host.startswith("*.") for host in policy.allowed_hosts))
        readiness = build_readiness(policy)
        self.assertTrue(readiness["dns_result_must_be_global"])
        self.assertTrue(readiness["connects_to_validated_numeric_ip"])
        self.assertFalse(readiness["wildcard_allowed"])

    def test_wildcard_or_implicit_subdomain_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"KAKA_EGRESS_ADDITIONAL_ALLOWED_HOSTS": "*.example.com"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "invalid explicit egress allowlist host"):
                PublicEgressProxyPolicy.from_env()

        policy = PublicEgressProxyPolicy(frozenset({"example.com"}))
        self.assertEqual(policy.require_allowed("example.com", 443), "example.com")
        with self.assertRaisesRegex(PublicEgressProxyDenied, "destination_host_not_registered"):
            policy.require_allowed("sub.example.com", 443)
        with self.assertRaisesRegex(PublicEgressProxyDenied, "destination_port_not_allowed"):
            policy.require_allowed("example.com", 8080)

    def test_policy_rejects_any_private_dns_answer_before_connect(self) -> None:
        policy = PublicEgressProxyPolicy(frozenset({"example.com"}))
        dns_result = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 443),
            )
            for address in ("93.184.216.34", "169.254.169.254")
        ]
        with patch.object(
            proxy_module.socket,
            "getaddrinfo",
            return_value=dns_result,
        ), patch.object(
            proxy_module,
            "_connect_to_pinned_public_addresses",
        ) as connector:
            with self.assertRaisesRegex(RuntimeError, "non_public_url_address"):
                policy.open_upstream("example.com", 443)
        connector.assert_not_called()

    def test_policy_passes_only_validated_numeric_addresses_to_connector(self) -> None:
        policy = PublicEgressProxyPolicy(frozenset({"example.com"}))
        dns_result = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", 443),
            )
        ]
        sentinel = object()
        with patch.object(
            proxy_module.socket,
            "getaddrinfo",
            return_value=dns_result,
        ), patch.object(
            proxy_module,
            "_connect_to_pinned_public_addresses",
            return_value=sentinel,
        ) as connector:
            self.assertIs(policy.open_upstream("example.com", 443), sentinel)

        self.assertEqual(connector.call_args.args[0], ("93.184.216.34",))
        self.assertEqual(connector.call_args.args[1], 443)

    def test_connect_authority_rejects_userinfo_path_and_nonstandard_port(self) -> None:
        self.assertEqual(_parse_authority("example.com:443"), ("example.com", 443))
        for value in ("user@example.com:443", "example.com:443/path", "example.com:bad"):
            with self.subTest(value=value):
                with self.assertRaises(PublicEgressProxyDenied):
                    _parse_authority(value)

    def test_live_proxy_socket_rejects_unregistered_destination_without_network(self) -> None:
        policy = PublicEgressProxyPolicy(frozenset({"example.com"}))
        server = _PublicEgressProxyServer(("127.0.0.1", 0), policy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                client.sendall(
                    b"CONNECT 169.254.169.254:443 HTTP/1.1\r\n"
                    b"Host: 169.254.169.254:443\r\n\r\n"
                )
                response = client.recv(4096)
            self.assertIn(b"403 Forbidden", response)
            self.assertIn(b"destination_host_not_registered", response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_live_connect_tunnel_relays_only_after_policy_open(self) -> None:
        proxy_side, upstream_side = socket.socketpair()

        class FakePolicy:
            max_concurrent_connections = 2
            tunnel_idle_timeout_seconds = 2.0

            def open_upstream(self, host: str, port: int) -> socket.socket:
                self.last_target = (host, port)
                return proxy_side

        policy = FakePolicy()
        server = _PublicEgressProxyServer(("127.0.0.1", 0), policy)  # type: ignore[arg-type]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                client.sendall(
                    b"CONNECT example.com:443 HTTP/1.1\r\n"
                    b"Host: example.com:443\r\n\r\n"
                )
                self.assertIn(b"200 Connection Established", client.recv(4096))
                client.sendall(b"client-tls-bytes")
                self.assertEqual(upstream_side.recv(4096), b"client-tls-bytes")
                upstream_side.sendall(b"server-tls-bytes")
                self.assertEqual(client.recv(4096), b"server-tls-bytes")
            self.assertEqual(policy.last_target, ("example.com", 443))
        finally:
            upstream_side.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_live_http_proxy_rewrites_target_and_strips_proxy_credentials(self) -> None:
        proxy_side, upstream_side = socket.socketpair()
        captured: list[bytes] = []

        class FakePolicy:
            max_concurrent_connections = 2
            tunnel_idle_timeout_seconds = 2.0

            def require_allowed(self, host: str, port: int) -> str:
                if (host, port) != ("example.com", 80):
                    raise PublicEgressProxyDenied("unexpected target")
                return host

            def open_upstream(self, host: str, port: int) -> socket.socket:
                self.last_target = (host, port)
                return proxy_side

        def serve_upstream() -> None:
            request = upstream_side.recv(4096)
            captured.append(request)
            upstream_side.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            )
            upstream_side.close()

        policy = FakePolicy()
        server = _PublicEgressProxyServer(("127.0.0.1", 0), policy)  # type: ignore[arg-type]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        upstream_thread = threading.Thread(target=serve_upstream, daemon=True)
        thread.start()
        upstream_thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                client.sendall(
                    b"GET http://example.com/public?q=1 HTTP/1.1\r\n"
                    b"Host: attacker.invalid\r\n"
                    b"Proxy-Authorization: Basic secret\r\n\r\n"
                )
                response = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response += chunk
            self.assertIn(b"200 OK", response)
            self.assertTrue(response.endswith(b"ok"))
            forwarded = captured[0]
            self.assertIn(b"GET /public?q=1 HTTP/1.1", forwarded)
            self.assertIn(b"Host: example.com", forwarded)
            self.assertNotIn(b"attacker.invalid", forwarded)
            self.assertNotIn(b"Proxy-Authorization", forwarded)
            self.assertEqual(policy.last_target, ("example.com", 80))
        finally:
            upstream_side.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            upstream_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
