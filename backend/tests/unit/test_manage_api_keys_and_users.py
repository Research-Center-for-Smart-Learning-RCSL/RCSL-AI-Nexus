"""Key issuance and account administration.

The guards here are the ones whose absence is unrecoverable or invisible: a
key that is dead on arrival, a key edited by someone who does not own it, and
the removal of the last administrator, which leaves an instance nobody can
manage and no bootstrap to fall back on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_api_keys import ManageApiKeys
from app.application.use_cases.manage_routing_policies import ManageRoutingPolicies
from app.application.use_cases.manage_users import ManageUsers
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCidrError,
    LastAdministratorError,
    ModelNotFoundError,
    ModelStateConflictError,
    NotAuthorizedError,
    UserNotFoundError,
)
from app.domain.services.api_key_service import ApiKeyService
from app.domain.services.debug_window import MAX_DEBUG_WINDOW_MINUTES
from app.shared.clock import FixedClock
from tests.unit.fakes import (
    FakeApiKeys,
    FakeAudit,
    FakeInvitations,
    FakeModels,
    FakePolicies,
    FakeSessions,
    FakeUsage,
    FakeUsers,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
NEXT_YEAR = NOW + timedelta(days=365)

ADMIN = Actor(
    id="admin-1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
)
MEMBER = Actor(
    id="u2",
    display="member",
    role=Role.USER,
    source="local",
    scopes=RoleAuthorization().scopes_for("user"),
)


def make_user(user_id: str, role: Role = Role.USER, **overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": user_id,
        "login": f"{user_id}@example.org",
        "display_name": user_id,
        "role": role,
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


# --- API keys ------------------------------------------------------------


class KeyHarness:
    def __init__(self, users: list[User] | None = None) -> None:
        self.keys = FakeApiKeys()
        self.users = FakeUsers(users or [make_user("admin-1", Role.ADMIN), make_user("u2")])
        self.usage = FakeUsage()
        self.audit = FakeAudit()

        self.use_case = ManageApiKeys(
            keys=self.keys,
            users=self.users,
            usage=self.usage,
            service=ApiKeyService(peppers=(b"test-pepper",)),
            authz=RoleAuthorization(),
            audit=self.audit,
            clock=FixedClock(NOW),
        )

    async def issue(self, actor: Actor = ADMIN, **overrides: object):
        kwargs: dict[str, object] = {
            "name": "ci",
            "owner_id": "u2",
            "scopes": ["chat"],
            "expires_at": NEXT_YEAR,
            "rate_limit_rpm": 60,
            "quota_tokens_per_day": 100_000,
            "allowed_cidrs": [],
        }
        kwargs.update(overrides)
        return await self.use_case.create(actor, **kwargs)  # type: ignore[arg-type]


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

    with pytest.raises(ModelStateConflictError):
        await harness.issue(expires_at=NOW - timedelta(days=1))


async def test_an_unknown_capability_is_refused() -> None:
    """Otherwise the typo becomes a key that verifies and can do nothing."""
    harness = KeyHarness()

    with pytest.raises(ModelStateConflictError):
        await harness.issue(scopes=["chatt"])


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

    with pytest.raises(ModelStateConflictError):
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


# --- users ---------------------------------------------------------------


class UserHarness:
    def __init__(self, users: list[User]) -> None:
        self.users = FakeUsers(users)
        self.keys = FakeApiKeys()
        self.invitations = FakeInvitations()
        self.sessions = FakeSessions()
        self.audit = FakeAudit()

        self.use_case = ManageUsers(
            users=self.users,
            keys=self.keys,
            invitations=self.invitations,
            sessions=self.sessions,
            authz=RoleAuthorization(),
            audit=self.audit,
            clock=FixedClock(NOW),
        )


async def test_the_last_administrator_cannot_be_deleted() -> None:
    """Removing them leaves an instance nobody can manage, and the bootstrap
    setting does not come back: it is inert once any user row exists."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    other_admin = Actor(
        id="u2", display="u2", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
    )

    with pytest.raises(LastAdministratorError):
        await harness.use_case.delete(other_admin, "admin-1")


async def test_the_last_administrator_cannot_be_demoted() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    other_admin = Actor(
        id="u2", display="u2", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
    )

    with pytest.raises(LastAdministratorError):
        await harness.use_case.update(other_admin, "admin-1", role=Role.USER)


async def test_an_administrator_cannot_delete_themselves() -> None:
    """The frontend had this check and it never fired, because it compared a
    UUID against a login."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("a2", Role.ADMIN)])

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.delete(ADMIN, "admin-1")


async def test_an_administrator_cannot_demote_themselves() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("a2", Role.ADMIN)])

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.update(ADMIN, "admin-1", role=Role.USER)


async def test_changing_a_role_ends_that_users_sessions() -> None:
    """Scopes are derived from the role at request time, so a live session
    would otherwise keep what it was granted at login until it expired."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    await harness.use_case.update(ADMIN, "u2", role=Role.ADMIN)

    assert harness.sessions.invalidated_all == ["u2"]


async def test_renaming_does_not_end_sessions() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    await harness.use_case.update(ADMIN, "u2", display_name="Renamed")

    assert harness.sessions.invalidated_all == []


async def test_disabling_ends_sessions_immediately() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    await harness.use_case.set_disabled(ADMIN, "u2", disabled=True)

    assert harness.sessions.invalidated_all == ["u2"]
    assert harness.users.rows["u2"].disabled_at == NOW


async def test_deleting_a_user_removes_the_rows_that_reference_them() -> None:
    """`api_keys`, `invitations` and `recovery_codes` carry a foreign key, so
    they go first or the delete is impossible. Their keys stopping is the
    correct consequence."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    harness.keys.rows["k1"] = _key_for("u2")

    await harness.use_case.delete(ADMIN, "u2")

    assert "u2" not in harness.users.rows
    assert harness.keys.rows == {}
    assert "user.deleted" in harness.audit.actions()


async def test_deleting_an_unknown_user_is_a_404() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN)])

    with pytest.raises(UserNotFoundError):
        await harness.use_case.delete(ADMIN, "nobody")


# --- the debug window, on both credentials -------------------------------
#
# One control on two credentials, so the ceiling is shared
# (`domain/services/debug_window.py`) and tested on both. The user half exists
# for the case the key half cannot reach: the management UI authenticates by
# session and carries no API key, so an administrator debugging their own
# admin session had no credential to open a window on until 2026-08-05 —
# while `identity.py` had been reading the column and granting on it all
# along.


async def test_opening_a_users_debug_window_stores_its_expiry_and_audits_it() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    user = await harness.use_case.set_debug_window(ADMIN, "u2", minutes=60)

    assert user.debug_logging_until == NOW + timedelta(minutes=60)
    assert harness.users.rows["u2"].debug_logging_until == NOW + timedelta(minutes=60)
    assert "user.debug_window_set" in harness.audit.actions()


async def test_zero_minutes_closes_a_users_debug_window() -> None:
    """Opening and closing are the same verb, so the audit log carries both."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    await harness.use_case.set_debug_window(ADMIN, "u2", minutes=60)

    user = await harness.use_case.set_debug_window(ADMIN, "u2", minutes=0)

    assert user.debug_logging_until is None
    assert harness.users.rows["u2"].debug_logging_until is None


async def test_a_users_debug_window_cannot_exceed_the_shared_ceiling() -> None:
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.set_debug_window(ADMIN, "u2", minutes=MAX_DEBUG_WINDOW_MINUTES + 1)

    assert harness.users.rows["u2"].debug_logging_until is None


async def test_a_keys_debug_window_cannot_exceed_the_shared_ceiling() -> None:
    """The same bound from the other side. It moved out of this use case into
    a shared rule, so it is asserted on both rather than trusted to stay."""
    harness = KeyHarness()
    issued = await harness.issue()

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.set_debug_window(
            ADMIN, issued.key.key_id, minutes=MAX_DEBUG_WINDOW_MINUTES + 1
        )

    assert harness.keys.rows[issued.key.key_id].debug_logging_until is None


async def test_a_disabled_account_cannot_have_its_debug_window_opened() -> None:
    """The guard is the conditional UPDATE, not a check before it: a disable
    landing in between would otherwise leave the window open on an account
    nobody can sign in as, and report success."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])
    await harness.use_case.set_disabled(ADMIN, "u2", disabled=True)

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.set_debug_window(ADMIN, "u2", minutes=60)

    assert harness.users.rows["u2"].debug_logging_until is None
    assert "user.debug_window_set" not in harness.audit.actions()


async def test_setting_a_debug_window_needs_user_write() -> None:
    """It widens what the platform discloses about a *different* account, so
    it sits behind the same scope as editing one — not behind self-service."""
    harness = UserHarness([make_user("admin-1", Role.ADMIN), make_user("u2")])

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.set_debug_window(MEMBER, "u2", minutes=60)

    assert harness.users.rows["u2"].debug_logging_until is None


# --- routing policies ----------------------------------------------------


async def test_a_policy_naming_an_unregistered_alias_is_refused() -> None:
    """At inference time this fails as "no available model", which is
    indistinguishable from every node being busy. The operator writing the
    policy is the one who can fix a typo."""
    use_case = ManageRoutingPolicies(
        policies=FakePolicies(),
        models=FakeModels(),
        authz=RoleAuthorization(),
        audit=FakeAudit(),
    )

    with pytest.raises(ModelNotFoundError):
        await use_case.save(ADMIN, "chat", [RoutingCandidate("missing", 1)])


async def test_candidates_are_stored_in_priority_order() -> None:
    """So the stored order is the evaluation order, and nobody has to know
    whether routing sorts before it reads."""
    models = FakeModels([_model("a"), _model("b")])
    policies = FakePolicies()
    use_case = ManageRoutingPolicies(
        policies=policies, models=models, authz=RoleAuthorization(), audit=FakeAudit()
    )

    saved = await use_case.save(ADMIN, "chat", [RoutingCandidate("b", 5), RoutingCandidate("a", 1)])

    assert [c.model_alias for c in saved.candidates] == ["a", "b"]


async def test_a_policy_for_an_unknown_capability_is_refused() -> None:
    """The two write paths disagreed about what a capability name is. A policy
    for `chatt` stored and audited cleanly while `ManageApiKeys` refused a key
    for `chatt` as unknown, so nothing could ever route to it — and it was
    advertised as servable by `GET /v1/models` to every caller."""
    use_case = ManageRoutingPolicies(
        policies=FakePolicies(),
        models=FakeModels([_model("a")]),
        authz=RoleAuthorization(),
        audit=FakeAudit(),
    )

    with pytest.raises(ModelStateConflictError):
        await use_case.save(ADMIN, "chatt", [RoutingCandidate("a", 1)])


async def test_an_empty_policy_is_refused() -> None:
    """A capability with no candidates routes nowhere, which is the same as
    not having the policy at all but harder to notice."""
    use_case = ManageRoutingPolicies(
        policies=FakePolicies(),
        models=FakeModels(),
        authz=RoleAuthorization(),
        audit=FakeAudit(),
    )

    with pytest.raises(ModelStateConflictError):
        await use_case.save(ADMIN, "chat", [])


async def test_a_member_cannot_edit_routing() -> None:
    use_case = ManageRoutingPolicies(
        policies=FakePolicies([RoutingPolicy("chat", (RoutingCandidate("a", 1),))]),
        models=FakeModels([_model("a")]),
        authz=RoleAuthorization(),
        audit=FakeAudit(),
    )

    with pytest.raises(NotAuthorizedError):
        await use_case.save(MEMBER, "chat", [RoutingCandidate("a", 1)])


def _model(alias: str) -> Model:
    return Model(
        id=alias,
        alias=alias,
        ref=f"library/{alias}:1",
        runtime=RuntimeKind.OLLAMA,
        node_id="node-1",
        state=ModelState.LOADED,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=1.0, context_length=1024),
    )


def _key_for(owner_id: str):
    from app.domain.entities.api_key import ApiKey

    return ApiKey(
        id="k1",
        key_id="0123456789abcdef",
        digest="deadbeef",
        name="theirs",
        owner_id=owner_id,
        expires_at=NEXT_YEAR,
    )
