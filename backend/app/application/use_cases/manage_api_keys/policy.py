"""Policy value objects and validation helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions import (
    InvalidCidrError,
)


class Unchanged:
    """The third state a PATCH field needs, and the reason it needs one.

    `default_capability` is the first editable setting whose *null* is a
    meaningful value — "refuse, as every key did before this field existed" —
    so the convention every other field here uses, where `None` means "the
    caller did not mention this", would make the setting impossible to clear
    once set. An explicit sentinel keeps absent and null apart all the way from
    `model_fields_set` on the request to the column.
    """


UNCHANGED = Unchanged()


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    key: ApiKey
    plaintext: str
    """The only copy that will ever exist."""


def _parse_cidrs(values: Sequence[str]) -> tuple[IPv4Network | IPv6Network, ...]:
    networks: list[IPv4Network | IPv6Network] = []
    for value in values:
        candidate = value.strip()
        if not candidate:
            continue
        try:
            # `strict=False` so `10.0.0.7/24` is accepted as the network it
            # obviously means, rather than rejected for having host bits set.
            networks.append(ip_network(candidate, strict=False))
        except ValueError as exc:
            raise InvalidCidrError(detail=f"unparsable range {candidate!r}") from exc
    return tuple(networks)
