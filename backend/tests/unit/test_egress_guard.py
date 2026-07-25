"""The SSRF egress guard for node addresses.

The whole value of §7.2 is that these cases are rejected before an address is
stored: a node address the platform will later make outbound requests to must be
inside the tailnet, and everything an attacker would point it at (loopback, the
LAN, the cloud metadata endpoint) is outside.
"""

from __future__ import annotations

import pytest

from app.adapters.http.egress_guard import assert_allowed_node_address, resolve_node_ips
from app.domain.exceptions import InvalidNodeAddressError


def test_a_tailnet_ipv4_literal_is_allowed() -> None:
    assert_allowed_node_address("100.101.102.103")  # does not raise
    ips = resolve_node_ips("100.64.0.1")
    assert str(ips[0]) == "100.64.0.1"


def test_a_tailnet_ipv6_literal_is_allowed() -> None:
    assert_allowed_node_address("fd7a:115c:a1e0::1")
    assert_allowed_node_address("[fd7a:115c:a1e0::1]")  # bracketed form


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "169.254.169.254",  # cloud metadata, the classic SSRF target
        "192.168.1.10",  # RFC 1918 LAN
        "10.0.0.5",  # RFC 1918 LAN
        "172.16.0.1",  # RFC 1918 LAN
        "8.8.8.8",  # public internet
        "100.63.255.255",  # one below the tailnet range
        "100.128.0.0",  # one above the tailnet range
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
    ],
)
def test_an_address_outside_the_tailnet_is_refused(address: str) -> None:
    with pytest.raises(InvalidNodeAddressError):
        assert_allowed_node_address(address)


def test_an_empty_address_is_refused() -> None:
    with pytest.raises(InvalidNodeAddressError):
        assert_allowed_node_address("   ")


def test_a_hostname_is_rejected_when_it_resolves_off_tailnet(monkeypatch) -> None:
    """A name resolving even partly outside the tailnet must not pass. The DNS is
    stubbed so the test does not depend on a resolver."""

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(None, None, None, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("app.adapters.http.egress_guard.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(InvalidNodeAddressError):
        assert_allowed_node_address("evil.example")


def test_a_hostname_that_resolves_into_the_tailnet_is_allowed(monkeypatch) -> None:
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(None, None, None, "", ("100.90.80.70", 0))]

    monkeypatch.setattr("app.adapters.http.egress_guard.socket.getaddrinfo", fake_getaddrinfo)
    ips = resolve_node_ips("mac-studio.tailnet.ts.net")
    assert str(ips[0]) == "100.90.80.70"


def test_a_hostname_with_one_bad_answer_among_good_ones_is_refused(monkeypatch) -> None:
    """DNS rebinding defence: a name that returns a tailnet address and a public
    one must be rejected, not accepted on the strength of the good record."""

    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (None, None, None, "", ("100.90.80.70", 0)),
            (None, None, None, "", ("8.8.8.8", 0)),
        ]

    monkeypatch.setattr("app.adapters.http.egress_guard.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(InvalidNodeAddressError):
        assert_allowed_node_address("rebind.example")
