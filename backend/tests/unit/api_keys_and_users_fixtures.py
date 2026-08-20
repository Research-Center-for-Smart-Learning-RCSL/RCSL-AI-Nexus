"""Key issuance and account administration.

The guards here are the ones whose absence is unrecoverable or invisible: a
key that is dead on arrival, a key edited by someone who does not own it, and
the removal of the last administrator, which leaves an instance nobody can
manage and no bootstrap to fall back on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_api_keys import ManageApiKeys
from app.application.use_cases.manage_users import ManageUsers
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.user import User
from app.domain.services.api_key_service import ApiKeyService
from app.shared.clock import FixedClock
from tests.unit.fakes import (
    FakeApiKeys,
    FakeAudit,
    FakeInvitations,
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
