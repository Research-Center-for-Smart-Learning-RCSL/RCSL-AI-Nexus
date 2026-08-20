from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.exceptions import (
    ApiKeyStateConflictError,
    InvalidCidrError,
    NotAuthorizedError,
    UserNotFoundError,
)
from tests.unit.api_keys_and_users_fixtures import (
    ADMIN,
    MEMBER,
    NOW,
    KeyHarness,
)

pytest_plugins = ("tests.unit.api_keys_and_users_fixtures",)


async def test_the_plaintext_is_returned_once_and_never_stored() -> None:
    harness = KeyHarness()
    issued = await harness.issue()

    assert issued.plaintext.startswith("nx_live_")
    stored = harness.keys.rows[issued.key.key_id]
    assert issued.plaintext not in stored.digest
    # The lookup handle is independent of the secret, so it is safe in a log.
    assert stored.key_id in issued.plaintext


async def test_an_expiry_in_the_past_is_refused() -> None:
    """The column is NOT NULL, but a date already gone produces a key that is
    dead on arrival and reads as a platform fault."""
    harness = KeyHarness()

    with pytest.raises(ApiKeyStateConflictError):
        await harness.issue(expires_at=NOW - timedelta(days=1))


async def test_an_unknown_capability_is_refused() -> None:
    """Otherwise the typo becomes a key that verifies and can do nothing."""
    harness = KeyHarness()

    with pytest.raises(ApiKeyStateConflictError):
        await harness.issue(scopes=["chatt"])


async def test_a_key_is_issued_without_a_default_capability() -> None:
    """The setting is opt-in, and this is what "opt" means: a key issued by the
    ordinary form refuses a capability it was not issued for, which is the
    refusal that tells an integrator their client sent a model name."""
    harness = KeyHarness()

    issued = await harness.issue()

    assert issued.key.default_capability is None


async def test_a_default_capability_outside_the_key_s_own_list_is_refused() -> None:
    """A substitution, never a widening.

    Stored, it would let a key issued for `chat` alone serve `code` to anything
    that asked — which is the field quietly becoming a second capability list,
    and a worse one, since the form that grants capabilities would not show it.
    """
    harness = KeyHarness()

    with pytest.raises(ApiKeyStateConflictError):
        await harness.issue(scopes=["chat"], default_capability="code")


async def test_a_default_capability_within_the_key_s_own_list_is_stored() -> None:
    harness = KeyHarness()

    issued = await harness.issue(scopes=["chat", "code"], default_capability="code")

    assert issued.key.default_capability == "code"
    assert harness.keys.rows[issued.key.key_id].default_capability == "code"


async def test_narrowing_the_capabilities_out_from_under_a_default_is_refused() -> None:
    """One request, both halves, or neither.

    Silently clearing the default instead would leave the key working
    differently from the settings the operator was last shown, and nothing
    would say when it changed.
    """
    harness = KeyHarness()
    issued = await harness.issue(scopes=["chat", "code"], default_capability="code")

    with pytest.raises(ApiKeyStateConflictError):
        await harness.use_case.update(ADMIN, issued.key.key_id, scopes=["chat"])

    assert harness.keys.rows[issued.key.key_id].default_capability == "code"


async def test_an_edit_that_does_not_mention_the_default_leaves_it_alone() -> None:
    harness = KeyHarness()
    issued = await harness.issue(scopes=["chat", "code"], default_capability="code")

    await harness.use_case.update(ADMIN, issued.key.key_id, rate_limit_rpm=30)

    assert harness.keys.rows[issued.key.key_id].default_capability == "code"


async def test_an_explicit_null_clears_the_default() -> None:
    """The reason the sentinel exists. Every other field on this verb reads
    `None` as "not mentioned"; this one has a meaningful null, so a default
    that could be set and never withdrawn would be a one-way door."""
    harness = KeyHarness()
    issued = await harness.issue(scopes=["chat", "code"], default_capability="code")

    await harness.use_case.update(ADMIN, issued.key.key_id, default_capability=None)

    assert harness.keys.rows[issued.key.key_id].default_capability is None


async def test_an_unparsable_cidr_is_refused() -> None:
    harness = KeyHarness()

    with pytest.raises(InvalidCidrError):
        await harness.issue(allowed_cidrs=["10.0.0.0/wide"])


async def test_a_range_with_host_bits_is_accepted_as_the_network_it_means() -> None:
    harness = KeyHarness()
    issued = await harness.issue(allowed_cidrs=["10.0.0.7/24"])

    assert [str(n) for n in issued.key.allowed_cidrs] == ["10.0.0.0/24"]


async def test_issuing_for_an_unknown_owner_is_a_404_not_a_500() -> None:
    """The column is a foreign key, so this fails at commit either way. Caught
    here it comes back with a reason."""
    harness = KeyHarness()

    with pytest.raises(UserNotFoundError):
        await harness.issue(owner_id="nobody")


async def test_a_member_cannot_issue_a_key_for_someone_else() -> None:
    harness = KeyHarness()

    with pytest.raises(NotAuthorizedError):
        await harness.issue(actor=MEMBER, owner_id="admin-1")


async def test_a_member_can_issue_their_own() -> None:
    harness = KeyHarness()
    issued = await harness.issue(actor=MEMBER, owner_id="u2")

    assert issued.key.owner_id == "u2"


async def test_a_member_sees_only_their_own_keys() -> None:
    harness = KeyHarness()
    await harness.issue(owner_id="u2")
    await harness.issue(owner_id="admin-1", name="theirs")

    visible, _ = await harness.use_case.list_visible(MEMBER)
    assert {k.owner_id for k in visible} == {"u2"}

    all_keys, _ = await harness.use_case.list_visible(ADMIN)
    assert {k.owner_id for k in all_keys} == {"u2", "admin-1"}


async def test_permission_is_checked_against_the_keys_owner_not_the_request() -> None:
    """A caller must not be able to aim an edit at somebody else's key by
    naming their own id."""
    harness = KeyHarness()
    theirs = await harness.issue(owner_id="admin-1")

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.update(MEMBER, theirs.key.key_id, name="mine now")


async def test_a_revoked_key_cannot_be_edited() -> None:
    """Editing one produces something that looks active in a list and is not."""
    harness = KeyHarness()
    issued = await harness.issue()
    await harness.use_case.revoke(ADMIN, issued.key.key_id)

    with pytest.raises(ApiKeyStateConflictError):
        await harness.use_case.update(ADMIN, issued.key.key_id, name="again")


async def test_revoking_twice_keeps_the_first_timestamp() -> None:
    """ "When did this stop working" must not answer with the most recent
    attempt to revoke it."""
    harness = KeyHarness()
    issued = await harness.issue()

    await harness.use_case.revoke(ADMIN, issued.key.key_id)
    first = harness.keys.rows[issued.key.key_id].revoked_at
    await harness.use_case.revoke(ADMIN, issued.key.key_id)

    assert harness.keys.rows[issued.key.key_id].revoked_at == first


async def test_an_unknown_key_is_refused_the_same_way_as_someone_elses() -> None:
    """So the endpoint does not confirm which key ids exist."""
    harness = KeyHarness()

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.revoke(MEMBER, "0123456789abcdef")
