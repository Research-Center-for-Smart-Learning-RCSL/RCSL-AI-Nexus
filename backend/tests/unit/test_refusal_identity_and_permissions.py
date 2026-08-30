from __future__ import annotations

import ast
from pathlib import Path

from app.adapters.authz.role_authorization import ADMIN_ONLY_SCOPES
from app.domain.entities.actor import Role, Scope
from app.domain.entities.retention import RETENTION_BOUNDS, RetentionDataset
from tests.unit.refusal_store_fixtures import (
    AUTHZ,
)

pytest_plugins = ("tests.unit.refusal_store_fixtures",)


def test_the_dataset_is_bounded_by_a_ceiling_as_well_as_a_floor() -> None:
    """A ceiling because a year of somebody's 413s is a description of how they
    work that nobody asked to have kept; a floor because the person who reads
    this table is the person who was refused, and a Friday refusal has to
    survive until Monday."""
    bounds = RETENTION_BOUNDS[RetentionDataset.REFUSALS]

    assert bounds.maximum_days is not None
    assert bounds.minimum_days >= 7
    assert bounds.minimum_days <= bounds.default_days <= bounds.maximum_days


def test_reading_your_own_refusals_is_not_an_administrative_privilege() -> None:
    """Two people lost an evening each to refusals they could not look up. A
    scope only an administrator holds would have left them exactly there."""
    assert Scope.REFUSAL_READ_OWN in AUTHZ.scopes_for("user")
    assert Scope.REFUSAL_READ_ALL not in AUTHZ.scopes_for("user")
    assert Scope.REFUSAL_READ_ALL in AUTHZ.scopes_for("operator")


def test_who_sees_whose_refusals_is_exactly_who_sees_whose_usage() -> None:
    """Pinned as a whole table, because "which roles" is the question this
    feature is most likely to be asked and least likely to be re-derived.

    The rule is not a new judgement: both datasets are metadata about requests
    rather than their content, and the roles that investigate load are the
    roles that investigate refusals. Stating it as an equality means a future
    change to one has to be a deliberate change to the other, or this fails.

    **`service` is the one deliberate difference, and it is a difference in
    kind.** An API key may read its own usage, and it may not read its own
    refusals — not because the holder should not see them, but because there is
    nowhere for that read to happen: the gateway mounts no route here and its
    database account has `SELECT` on this table revoked, following
    `prompt_logs`. A scope granted here would promise something no endpoint
    serves. The key's owner is an account, and they read their own refusals on
    the admin entrance like everybody else.
    """
    for role in Role:
        if role is Role.SERVICE:
            continue
        scopes = AUTHZ.scopes_for(role.value)
        assert (Scope.REFUSAL_READ_OWN in scopes) == (Scope.USAGE_READ_OWN in scopes), role
        assert (Scope.REFUSAL_READ_ALL in scopes) == (Scope.USAGE_READ_ALL in scopes), role

    service = AUTHZ.scopes_for(Role.SERVICE.value)
    assert Scope.REFUSAL_READ_OWN not in service
    assert Scope.REFUSAL_READ_ALL not in service

    assert Scope.REFUSAL_READ_ALL not in ADMIN_ONLY_SCOPES, (
        "deliberately not beside prompt_log:read — that one reads what somebody "
        "typed, and this one reads only what the platform told them"
    )


def test_every_identity_dependency_leaves_its_actor_on_the_request() -> None:
    """The defect a deployment found and no test would have.

    `actor_from_request` is how the exception handler says *who* was refused
    after the frame that identified them is gone, and its module docstring says
    each resolver leaves a copy there on its way past. The API-key resolver did
    not — and while its only consumer was `_audit_refusal`, which returns early
    on the gateway because that application has no `audit` on its state, the
    omission was unobservable. It became observable the moment refusals were
    stored: a deployed `413` on a real key, the exact refusal this table was
    built for, was answered correctly and written nowhere.

    Checked over the source rather than by exercising each dependency, because
    what makes this stick is that a *fourth* one added later cannot forget
    either — a test that drove the four that exist would pass on the day the
    fifth arrives.

    The rule is over the public functions returning `Actor`, which are exactly
    what a router may `Depends` on, and it follows calls within the package so
    a dependency may delegate: `authenticate_api_key` remembers by way of
    `_authenticate`, and the two identity resolvers by wrapping `_actor_for` in
    the call itself.
    """
    root = Path(__file__).resolve().parents[2] / "app" / "interfaces" / "http" / "middleware"
    definitions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef] = {}
    returns_actor: set[str] = set()
    for module in sorted(root.rglob("*.py")):
        # `encoding` is not optional, for the reason spelled out in
        # test_proxy_and_body_limits.py: without it these sources decode in the
        # process locale, and this test died on a `UnicodeDecodeError` rather than
        # on its invariant on every machine whose locale was not UTF-8.
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                definitions[node.name] = node
                if getattr(node.returns, "id", None) == "Actor":
                    returns_actor.add(node.name)

    def calls(name: str) -> set[str]:
        return {
            call.func.id
            for call in ast.walk(definitions[name])
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }

    remembers = {name for name in definitions if "remember_actor" in calls(name)}
    changed = True
    while changed:
        changed = False
        for name in definitions:
            if name not in remembers and calls(name) & remembers:
                remembers.add(name)
                changed = True

    dependencies = {name for name in returns_actor if not name.startswith("_")}
    assert len(dependencies) >= 3, f"expected the tailnet, session and API-key ones: {dependencies}"

    forgot = sorted(dependencies - remembers)
    assert forgot == [], f"identity dependencies that never remember their actor: {forgot}"


def test_the_api_key_resolver_remembers_before_the_checks_that_refuse() -> None:
    """Remembering at the `return` stored the 413s and dropped everything the
    checks above it raise: a rate limit, an exhausted quota, a blocked country,
    a source outside the key's allowlist. All four refuse a caller who is
    already fully identified — and a `429` nobody can look up is exactly the
    row `retry_after_seconds` was added for, since the header carrying it is
    gone by the time anybody reads back.

    Pinned as an ordering over the source, because that is what the defect was.
    """
    module = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "interfaces"
        / "http"
        / "middleware"
        / "api_key_auth"
        / "authentication.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    resolver = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_authenticate"
    )

    def line_of(name: str) -> int:
        return min(
            (
                call.lineno
                for call in ast.walk(resolver)
                if isinstance(call, ast.Call) and name in ast.dump(call.func)
            ),
            default=-1,
        )

    remembered = line_of("remember_actor")
    assert remembered > 0
    for check in (
        "assert_allowed",
        "_assert_source_allowed",
        "_assert_within_rate_limit",
        "_assert_within_quota",
    ):
        refuses_at = line_of(check)
        assert refuses_at > 0, f"{check} is no longer in this resolver"
        assert remembered < refuses_at, (
            f"{check} can refuse an identified caller before the request remembers who they are, "
            "so its refusal is stored nowhere"
        )
