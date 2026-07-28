from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


def controlled_egress_proxy_url(*, required: bool = False) -> str | None:
    value = str(os.environ.get("KAKA_CONTROLLED_EGRESS_PROXY_URL") or "").strip()
    private_pilot = (
        str(os.environ.get("KAKA_DEPLOYMENT_TENANCY_MODE") or "").strip().upper()
        == "PRIVATE_SINGLE_TENANT"
    )
    if not value:
        if required or private_pilot:
            raise RuntimeError("controlled_egress_proxy_required_for_unpinned_transport")
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise RuntimeError("controlled_egress_proxy_must_be_an_http_url")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("controlled_egress_proxy_credentials_not_allowed_in_url")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RuntimeError("controlled_egress_proxy_url_must_not_have_path_query_or_fragment")
    host = parsed.hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host != "egress-proxy":
            raise RuntimeError("controlled_egress_proxy_host_not_allowed")
    else:
        if not address.is_private or address.is_unspecified or address.is_multicast:
            raise RuntimeError("controlled_egress_proxy_address_must_be_private")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"controlled_egress_proxy_port_invalid:{exc}") from exc
    if port is None or port < 1 or port > 65535:
        raise RuntimeError("controlled_egress_proxy_explicit_port_required")
    return value


def playwright_proxy_settings(*, required: bool = False) -> dict[str, str] | None:
    value = controlled_egress_proxy_url(required=required)
    return {"server": value} if value else None
