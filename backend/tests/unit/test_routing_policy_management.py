from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_routing_policies import ManageRoutingPolicies
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.exceptions import (
    ModelNotFoundError,
    NotAuthorizedError,
    RoutingPolicyStateConflictError,
)
from tests.unit.api_keys_and_users_fixtures import (
    ADMIN,
    MEMBER,
    _model,
)
from tests.unit.fakes import (
    FakeAudit,
    FakeModels,
    FakePolicies,
)

pytest_plugins = ("tests.unit.api_keys_and_users_fixtures",)


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

    with pytest.raises(RoutingPolicyStateConflictError):
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

    with pytest.raises(RoutingPolicyStateConflictError):
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
