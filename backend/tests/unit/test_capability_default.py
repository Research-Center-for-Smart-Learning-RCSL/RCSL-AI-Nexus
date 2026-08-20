"""A key may name what serves a capability it was not issued for.

The setting exists because this platform's `model` field takes a capability
rather than a model name, and clients send model names anyway — Codex's own
picker overrides a configured `model` line and sends one of its built-in
slugs. The refusal that produces is *worth having*: it is the only channel that
tells an integrator their client overrode them, and three integrations have
found out that way. So the substitution is per key and off unless somebody
turns it on, and these tests are mostly about the "off" half staying off.
"""

from __future__ import annotations

from contextlib import aclosing

import pytest

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.exceptions import CapabilityNotIssuedError
from app.interfaces.http.sse import CAPABILITY_DEFAULTED_HEADER, capability_defaulted_header
from tests.unit.streaming_contract_fixtures import MESSAGES, FakeRuntime, build


def key_actor(
    allowed: frozenset[str] = frozenset({"code"}),
    default: str | None = None,
) -> Actor:
    """An API-key actor, which is the only kind this setting reaches.

    A person on an admin entrance carries `allowed_capabilities=None`, is
    already unrestricted, and never meets the substitution at all.
    """
    return Actor(
        id="owner-1",
        display="68953ceba2169efd",
        role=Role.SERVICE,
        source="api_key",
        scopes=frozenset({Scope.CHAT_USE}),
        api_key_id="68953ceba2169efd",
        allowed_capabilities=allowed,
        default_capability=default,
    )


# --- the rule itself -----------------------------------------------------


def test_a_capability_the_key_holds_is_served_as_asked() -> None:
    """The default is not consulted when nothing is wrong. A version that
    resolved through it unconditionally would work identically here and would
    have moved the decision for every request in the deployment."""
    assert key_actor(default="code").capability_for("code") == "code"


def test_without_a_default_an_unissued_capability_is_still_refused() -> None:
    """The behaviour every key has unless its issuer changed it, and the one
    this whole design exists to keep: `None` is a refusal, not a fallback."""
    assert key_actor().capability_for("gpt-5.6-luna") is None


def test_a_default_answers_for_a_capability_the_key_was_not_issued() -> None:
    assert key_actor(default="code").capability_for("gpt-5.6-luna") == "code"


def test_a_default_outside_the_key_s_own_capabilities_decides_nothing() -> None:
    """The substitution can shorten the path to what a key already reaches and
    can never add to it.

    `ManageApiKeys` refuses to store this pair, so reaching it means a row that
    arrived some other way — which is the case the re-check exists for. Were it
    trusted, one direct database write against a `code` key would reach
    `assist`, the capability that serves the management assistant and is
    deliberately not issuable at all.
    """
    smuggled = key_actor(allowed=frozenset({"code"}), default="assist")

    assert smuggled.capability_for("assist") is None
    assert smuggled.capability_for("gpt-5.6-luna") is None


def test_an_admin_entrance_person_is_unaffected() -> None:
    """`allowed_capabilities=None` is unrestricted, so `may_use` answers first
    and the default never runs."""
    person = Actor(
        id="u1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
    )

    assert person.capability_for("anything at all") == "anything at all"


# --- what the caller is told ---------------------------------------------


def test_the_header_is_absent_when_nothing_was_substituted() -> None:
    """Its presence has to mean something, so it is emitted only when the
    substitution actually fires — not on every request from a key that happens
    to have a default configured."""
    assert capability_defaulted_header(key_actor(default="code"), "code") == {}


def test_the_header_is_absent_on_a_refusal() -> None:
    """A refusal is the error handler's business and carries its own body. A
    header here would describe a request that was never served."""
    assert capability_defaulted_header(key_actor(), "gpt-5.6-luna") == {}


def test_the_header_names_what_actually_served_the_request() -> None:
    header = capability_defaulted_header(key_actor(default="code"), "gpt-5.6-luna")

    assert header == {CAPABILITY_DEFAULTED_HEADER: "code"}


# --- and what the gateway then does --------------------------------------


async def test_the_substituted_capability_is_the_one_billed() -> None:
    """Everything downstream reads the served capability, not the sent one.

    `usage_records.capability` is the assertion because it is the one an
    operator reads back: a row saying `gpt-5.6-luna` would attribute the
    hardware's work to a capability this deployment does not have, and the
    usage screen groups by that column.
    """
    use_case, usage, _ = build(FakeRuntime(chunks=2))

    async with aclosing(
        use_case.execute(key_actor(default="code"), "gpt-5.6-luna", MESSAGES)
    ) as stream:
        async for _ in stream:
            pass

    assert usage.records[0].capability == "code"


async def test_the_usage_row_keeps_what_the_caller_actually_asked_for() -> None:
    """The durable half, and the reason the setting is defensible at all.

    With a default configured there is no refusal any more, so nothing else
    outlives the request: the header is read by the client or by nobody, and
    the log line goes with the container. This column is what turns "is this
    key being defaulted, and what is its client sending?" into a query.
    """
    use_case, usage, _ = build(FakeRuntime(chunks=2))

    async with aclosing(
        use_case.execute(key_actor(default="code"), "gpt-5.6-luna", MESSAGES)
    ) as stream:
        async for _ in stream:
            pass

    assert usage.records[0].requested_capability == "gpt-5.6-luna"


async def test_an_ordinary_request_records_no_requested_capability() -> None:
    """Null means "asked for what it got", not "unknown".

    Writing the capability into both columns on every row would make the
    distinguishing query `capability <> requested_capability` instead of
    `requested_capability IS NOT NULL` — and would silently reinterpret every
    row written before the column existed, which hold null and were never
    substituted.
    """
    use_case, usage, _ = build(FakeRuntime(chunks=2))

    async with aclosing(use_case.execute(key_actor(default="code"), "code", MESSAGES)) as stream:
        async for _ in stream:
            pass

    assert usage.records[0].capability == "code"
    assert usage.records[0].requested_capability is None


async def test_a_key_without_a_default_still_gets_the_refusal_that_names_the_list() -> None:
    """The regression that matters most. This refusal is what an integrator
    reads to discover that `model` takes a capability."""
    use_case, usage, _ = build(FakeRuntime(chunks=2))

    with pytest.raises(CapabilityNotIssuedError) as refusal:
        async with aclosing(use_case.execute(key_actor(), "gpt-5.6-luna", MESSAGES)) as stream:
            async for _ in stream:
                pass

    assert refusal.value.capability == "gpt-5.6-luna"
    assert usage.records == [], "a refused request bills nothing"
