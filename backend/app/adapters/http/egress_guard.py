"""Egress guard for node addresses (SSRF).

A node's `address` is a value the platform makes outbound HTTP requests to: the
health probe now, and routing to a second node once there is one. That is the
textbook SSRF entry point recorded in the threat model, where a registration
address pointing at an internal service turns node management into internal
probing (docs/architecture/security.md section 7.2).

A compute node is always on the tailnet, so the allowlist is exactly the tailnet
range. That single rule is enough: loopback, link-local, RFC 1918 LAN addresses,
and the cloud metadata endpoint (169.254.169.254) all fall outside it, so none
has to be enumerated.

Validation happens when an address is stored, not only when it is used, so a
value that could never be reached safely is refused at the write endpoint rather
than surfacing later as a failed probe. The address is resolved here and every
result must be in range, so a hostname that resolves partly outside the tailnet
is rejected rather than trusted on the strength of one good record.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from app.domain.exceptions import InvalidNodeAddressError

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

TAILNET_RANGES: tuple[IpNetwork, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),  # Tailscale IPv4, the CGNAT range
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),  # Tailscale IPv6 ULA
)


def _in_tailnet(ip: IpAddress) -> bool:
    return any(ip in net for net in TAILNET_RANGES)


def resolve_node_ips(address: str) -> list[IpAddress]:
    """Resolve an address to every IP it maps to, raising unless all are tailnet.

    A literal IP resolves to itself with no DNS lookup, which also closes the
    rebinding gap for the common case: the value stored is the value connected
    to. A hostname is resolved and every answer is checked, so a name pointing
    even partly outside the tailnet does not pass.

    Returns the resolved addresses so a caller that is about to connect can use
    the validated IP rather than resolving a second time.
    """
    address = address.strip()
    if not address:
        raise InvalidNodeAddressError(detail="empty node address")

    # A bracketed literal is how an IPv6 address is written with a port; accept
    # the inner form. An IP literal needs no DNS and cannot be rebound.
    literal = address[1:-1] if address.startswith("[") and address.endswith("]") else address
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        ip = None

    if ip is not None:
        if not _in_tailnet(ip):
            raise InvalidNodeAddressError(detail=f"{address} is not inside the tailnet range")
        return [ip]

    try:
        infos = socket.getaddrinfo(address, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise InvalidNodeAddressError(detail=f"{address} does not resolve: {exc}") from exc

    ips: list[IpAddress] = []
    seen: set[str] = set()
    for info in infos:
        raw = str(info[4][0])
        if raw in seen:
            continue
        seen.add(raw)
        ips.append(ipaddress.ip_address(raw))
    if not ips:
        raise InvalidNodeAddressError(detail=f"{address} does not resolve")

    off_tailnet = [ip for ip in ips if not _in_tailnet(ip)]
    if off_tailnet:
        raise InvalidNodeAddressError(
            detail=f"{address} resolves outside the tailnet: {off_tailnet[0]}"
        )
    return ips


def assert_allowed_node_address(address: str) -> None:
    """Raise `InvalidNodeAddressError` unless the address is on the tailnet.

    Called at every node write so an address the platform could never reach
    safely is never stored. The synchronous DNS in `resolve_node_ips` is why the
    adapter below runs this off the event loop; a literal IP, the ordinary case,
    does no lookup at all.
    """
    resolve_node_ips(address)


class TailnetEgressGuard:
    """`EgressGuardPort` over the tailnet allowlist.

    The guard resolves DNS synchronously, so it is run in a worker thread to keep
    the event loop free; for a literal IP that thread does no lookup and returns
    at once.
    """

    async def assert_node_address_allowed(self, address: str) -> None:
        await asyncio.to_thread(assert_allowed_node_address, address)
