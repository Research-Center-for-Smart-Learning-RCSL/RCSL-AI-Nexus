"""Resolving the real caller address behind the reverse proxy.

The obvious implementation does not work here, and getting it wrong disables
both the country filter and the per-key CIDR allowlist at once.

Peer-address comparison fails under Docker: traffic arriving through a
published port is NAT'd, so the container sees the bridge gateway
(192.168.65.x or 172.x.0.1), never the proxy's tailnet address. A check
written that way rejects every request.

Trust comes instead from socket binding plus the tailnet ACL: the gateway
publishes only on the tailnet address, and the ACL admits only the proxy tag,
so anything arriving has come through openresty. The shared secret header is
an independent second check, since the ACL is otherwise the only control.

See docs/architecture/deployment.md section 7.
"""

from __future__ import annotations

from hmac import compare_digest
from ipaddress import IPv4Address, IPv6Address, ip_address

from fastapi import Request

from app.domain.exceptions import UntrustedProxyError
from app.infrastructure.config import get_settings

PROXY_SECRET_HEADER = "x-nexus-proxy"  # noqa: S105  (a header name, not a credential)
FORWARDED_FOR_HEADER = "x-forwarded-for"


def resolve_client_ip(request: Request) -> IPv4Address | IPv6Address:
    settings = get_settings()

    if settings.auth_mode == "dev":
        # No proxy in front of a developer machine. Falling back to the peer
        # address keeps the stack runnable locally; config.py refuses to start
        # in this mode under ENV=production, so it cannot reach a deployment.
        return _peer_address_or_loopback(request)

    presented = request.headers.get(PROXY_SECRET_HEADER, "")
    if not compare_digest(presented, settings.proxy_shared_secret):
        raise UntrustedProxyError(detail="proxy secret missing or wrong")

    forwarded = request.headers.get(FORWARDED_FOR_HEADER)
    if not forwarded:
        # Never silently fall back to the peer address: that would be the
        # proxy's, and every caller would appear to share one origin, quietly
        # neutering the per-key allowlist.
        raise UntrustedProxyError(detail="X-Forwarded-For absent behind the proxy")

    # The first value, because nginx is configured to overwrite the header with
    # $remote_addr rather than append with $proxy_add_x_forwarded_for. If that
    # configuration is ever changed to the conventional form, this must read
    # the last value instead. The coupling is recorded in deployment.md too.
    first = forwarded.split(",")[0].strip()
    try:
        return ip_address(first)
    except ValueError as exc:
        raise UntrustedProxyError(detail=f"unparsable forwarded address {first!r}") from exc


LOOPBACK = ip_address("127.0.0.1")


def _peer_address_or_loopback(request: Request) -> IPv4Address | IPv6Address:
    """Development only.

    Not every transport presents a real peer address: ASGI test clients use a
    placeholder string, and a unix socket has none at all. Neither is an error
    worth failing a local request over, and there is no security decision to
    make here because the caller is the developer. Production never reaches
    this branch, since `auth_mode` is `dev` only outside production and
    config.py refuses to start if the two are combined.
    """
    client = request.client
    if client is None:
        return LOOPBACK
    try:
        return ip_address(client.host)
    except ValueError:
        return LOOPBACK
