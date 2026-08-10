#!/usr/bin/env python3
"""Emit the backend's audit action catalogue as a TypeScript module.

Run through `scripts/generate-api-types.sh`, beside the OpenAPI types and the
role map, for the same reason all three exist: the frontend needs to know
something the backend decides, and a copy maintained by hand drifts silently.

The copy this replaces was `features/logs/schema.ts`, and it had drifted by
eight names before 2026-08-08 -- both `debug_window_set` events, all three
`prompt_template.*` and both `retention.*` had shipped without being added to
it. The `/admin/logs` filter is an exact match rather than a search, so an
action missing from that list is one an operator can only filter for by already
knowing its exact spelling, which is the failure the list exists to remove.

Read from `AuditAction` rather than from the call sites, because `AuditPort`
takes that type: an action a use case can write is by construction a member
here, so the enum is the whole set rather than a summary of one.
"""

from __future__ import annotations

from app.domain.entities.audit import AuditAction

BANNER = '''/**
 * Generated from the backend audit action catalogue. Do not edit.
 *
 *     scripts/generate-api-types.sh
 *
 * Every action name the platform writes to the audit log, taken from
 * `domain/entities/audit.py`. `AuditPort.record` takes that enum, so an action
 * a use case can write is necessarily one of these.
 *
 * This file exists because the hand-kept version of it drifted by eight names
 * before 2026-08-08, and each missing name was an action the `/admin/logs`
 * filter could not offer -- the filter matches exactly, so a name absent here
 * is unreachable to anyone who does not already know how it is spelled. A
 * generated copy cannot drift: CI regenerates it and fails if the committed
 * result differs.
 */'''


def main() -> None:
    actions = sorted(action.value for action in AuditAction)

    out: list[str] = [BANNER, ""]

    out.append("export const AUDIT_ACTIONS = [")
    out.extend(f"  '{action}'," for action in actions)
    out.append("] as const;")
    out.append("")

    out.append("/**")
    out.append(" * An action name known at build time.")
    out.append(" *")
    out.append(" * Deliberately not the type of `AuditEntry.action`, which stays `string`:")
    out.append(" * that types what the server sends, and a log row written by a backend")
    out.append(" * newer than this bundle is still a row to render rather than a parse")
    out.append(" * failure. Use this one wherever an action is *authored*.")
    out.append(" */")
    out.append("export type KnownAuditAction = (typeof AUDIT_ACTIONS)[number];")

    print("\n".join(out))


if __name__ == "__main__":
    main()
