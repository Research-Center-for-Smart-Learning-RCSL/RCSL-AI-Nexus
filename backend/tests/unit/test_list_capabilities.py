"""What a caller may ask for, and who is allowed to find out.

The two things worth pinning are that the answer is narrowed to the caller's
own key rather than describing the deployment, and that a member can read it
at all: they are the people integrating against a key, and gating it on
`routing:read` would have made it administrator-only.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.list_capabilities import ListCapabilities
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.exceptions import NotAuthorizedError
from tests.unit.fakes import FakePolicies

POLICIES = [
    RoutingPolicy("chat", (RoutingCandidate("a", 1),)),
    RoutingPolicy("code", (RoutingCandidate("a", 1),)),
]


def build() -> ListCapabilities:
    return ListCapabilities(policies=FakePolicies(POLICIES), authz=RoleAuthorization())


def service_actor(*capabilities: str) -> Actor:
    return Actor(
        id="u1",
        display="0123456789abcdef",
        role=Role.SERVICE,
        source="api_key",
        scopes=frozenset({Scope.CHAT_USE}),
        allowed_capabilities=frozenset(capabilities),
    )


async def test_a_key_sees_only_what_it_was_issued_for() -> None:
    listed = await build().execute(service_actor("chat"))

    assert listed == ["chat"]


async def test_a_capability_without_a_policy_is_absent() -> None:
    """It can be issued on a key, and it would answer `no_available_model`
    until a policy names it. Listing it would send an integrator to an
    endpoint that cannot serve them."""
    listed = await build().execute(service_actor("chat", "vision"))

    assert listed == ["chat"]


async def test_a_key_with_no_capabilities_sees_nothing() -> None:
    assert await build().execute(service_actor()) == []


async def test_a_member_reads_the_whole_servable_set() -> None:
    """A person is not restricted by capability; `allowed_capabilities` is
    None for them and their role decides what they can reach."""
    member = Actor(
        id="u2",
        display="member",
        role=Role.USER,
        source="local",
        scopes=RoleAuthorization().scopes_for("user"),
    )

    assert await build().execute(member) == ["chat", "code"]


async def test_a_caller_without_chat_use_is_refused() -> None:
    """The scope required is the one for reaching inference, so the audience
    is exactly those who can use what the list describes."""
    powerless = Actor(
        id="u3",
        display="0123456789abcdef",
        role=Role.SERVICE,
        source="api_key",
        scopes=frozenset(),
        allowed_capabilities=frozenset({"chat"}),
    )

    with pytest.raises(NotAuthorizedError):
        await build().execute(powerless)
