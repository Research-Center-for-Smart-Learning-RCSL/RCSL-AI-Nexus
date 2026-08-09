#!/usr/bin/env python3
"""Emit the backend's role map as a TypeScript module.

Run through `scripts/generate-api-types.sh`, beside the OpenAPI types and for
the same reason: the frontend needs to know something the backend decides, and
a copy maintained by hand drifts silently. `app-shell.test.tsx` held such a copy
and disagreed with `role_authorization.py` twice in one day, each time leaving
its assertions describing a navigation no real role is shown.

A separate file rather than a heredoc inside the shell script, because the
emitter is Python producing TypeScript from inside a shell string, and three
levels of quoting is how a generator acquires a bug of its own.

Read through the public `scopes_for` rather than the private `_BY_ROLE`, so what
lands here is the map the application applies rather than the table it is built
from.
"""

from __future__ import annotations

from app.adapters.authz.role_authorization import ADMIN_ONLY_SCOPES, RoleAuthorization
from app.domain.entities.actor import Role, Scope

BANNER = '''/**
 * Generated from the backend role map. Do not edit.
 *
 *     scripts/generate-api-types.sh
 *
 * What each role holds, taken from `adapters/authz/role_authorization.py`
 * through its public `scopes_for`.
 *
 * This file exists because a hand-written copy of that map drifted twice in one
 * day, and each time the tests kept passing while asserting a navigation no
 * real role is shown. A generated copy cannot drift: CI regenerates it and
 * fails if the committed result differs.
 *
 * **Consuming this in a test does not weaken the test.** What a role holds is
 * now followed rather than restated; what a role can *see* is still asserted
 * explicitly, so a scope change that alters the navigation fails loudly, with
 * the expected list of links beside it.
 */'''


def quoted(values: list[str], indent: int) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}'{value}'," for value in values)


def main() -> None:
    authz = RoleAuthorization()
    scopes = sorted(scope.value for scope in Scope)
    roles = {
        role.value: sorted(scope.value for scope in authz.scopes_for(role.value))
        for role in Role
    }
    admin_only = sorted(scope.value for scope in ADMIN_ONLY_SCOPES)

    out: list[str] = [BANNER, ""]

    out.append("/** Every scope the backend defines. */")
    out.append("export const SCOPE_NAMES = [")
    out.append(quoted(scopes, 2))
    out.append("] as const;")
    out.append("")

    out.append("/**")
    out.append(" * A scope name known at build time.")
    out.append(" *")
    out.append(" * Distinct from `ScopeName`, which stays `string` because it types what the")
    out.append(" * server sends and this application must not claim to know that")
    out.append(" * exhaustively. Use this one wherever a scope is *authored* — a nav entry's")
    out.append(" * `requires`, a cross-reference — so a typo is a compile error rather than")
    out.append(" * an entry that silently never renders.")
    out.append(" */")
    out.append("export type KnownScope = (typeof SCOPE_NAMES)[number];")
    out.append("")

    out.append("/** Roles as the backend spells them, including the non-human `service`. */")
    out.append("export type GeneratedRole =")
    out.append("\n".join(f"  | '{role}'" for role in roles) + ";")
    out.append("")

    out.append("export const ROLE_SCOPES: Record<GeneratedRole, readonly KnownScope[]> = {")
    for role, held in roles.items():
        out.append(f"  '{role}': [")
        out.append(quoted(held, 4))
        out.append("  ],")
    out.append("};")
    out.append("")

    out.append("/** Held by `admin` and no other role. */")
    out.append("export const ADMIN_ONLY_SCOPES = [")
    out.append(quoted(admin_only, 2))
    out.append("] as const;")

    print("\n".join(out))


if __name__ == "__main__":
    main()
