#!/usr/bin/env bash
# Regenerate the frontend's view of the admin API.
#
# The gateway serves no schema on purpose (security.md 4.4 disables
# /openapi.json there, and /api-docs is what was written in exchange), so the
# admin entrance is the only source. Its app is built here rather than scraped
# from a running container: FastAPI can produce the document offline, so this
# needs no deployment, no database and no credentials, which is what lets CI
# check that the committed output is current.
#
# The output is committed, and that is forced rather than preferred: the
# frontend image builds from ./frontend alone, with no Python and no backend
# source, so a type derived from the backend cannot be produced there and a
# fresh clone would fail `pnpm build`. Committing also makes the diff the place
# a contract change is reviewed.
set -euo pipefail

cd "$(dirname "$0")/.."
# A directory, and a template carrying X's, because both halves of the obvious
# one-liner were wrong. `mktemp -t nexus-openapi` is BSD-only: GNU coreutils
# refuses a template with no X's ("too few X's in template"), so under
# `set -euo pipefail` this script died on its first working line everywhere
# except macOS -- including the CI step added to run it. And appending `.json`
# to the result named a *different* path from the one mktemp created, so the
# trap removed the suffixed file and left the real one behind: five empty files
# had accumulated here before this was found.
WORK="$(mktemp -d -t nexus-openapi-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
SPEC="$WORK/admin-openapi.json"

OUT=frontend/src/lib/generated/admin-api.ts

# AUTH_MODE is set because Settings validates it at import; nothing here reaches
# an entrance, so any legal value produces the same document.
( cd backend && AUTH_MODE=tailnet uv run python -c "
import json, sys
from app.infrastructure.main_admin_tailnet import create_app
json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
" ) > "$SPEC"

mkdir -p "$(dirname "$OUT")"
( cd frontend && pnpm exec openapi-typescript "$SPEC" -o "../$OUT" )

# The banner has to survive regeneration, so it is prepended on every run
# rather than edited into the file, where the next run would drop it.
cat > "$OUT.tmp" <<'BANNER'
/**
 * Generated from the admin API OpenAPI document. Do not edit.
 *
 *     scripts/generate-api-types.sh
 *
 * Types only: nothing here validates at runtime, which is why the hand-written
 * zod schemas under `features/*` still exist and still parse every response.
 * What this adds is that the two cannot silently drift. `lib/api-contract.ts`
 * checks each schema against the types here, so a field the backend renames or
 * retypes fails `tsc` instead of failing in a browser.
 */

BANNER
cat "$OUT" >> "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

echo "wrote $OUT"

# --- the role map -------------------------------------------------------------
#
# A second output from the same source, for the same reason. `app-shell.test.tsx`
# held a hand-copied version of `role_authorization.py` and drifted from it twice
# in one day: `prompt:read` is in `_BASE_SCOPES` and reaches every human role
# while the copy listed it for none, so every navigation assertion in that file
# described a sidebar no real role has ever been shown, and the two entries
# gated on it were covered by nothing. Correcting the copy is not a fix, because
# the next scope added recreates it.

ROLES_OUT=frontend/src/lib/generated/role-scopes.ts

# `PYTHONPATH=.` because running a *file* puts that file's directory on the
# path rather than the working directory, so `app` would not be importable from
# a script living in scripts/. The OpenAPI step above sidesteps this by using
# `-c`, where the working directory is what lands on the path.
( cd backend && AUTH_MODE=tailnet PYTHONPATH=. uv run python ../scripts/emit_role_scopes.py ) > "$ROLES_OUT"

echo "wrote $ROLES_OUT"

# --- the audit action catalogue -----------------------------------------------
#
# A third output, and the same defect a third time: `features/logs/schema.ts`
# held a hand-kept list of every action the backend writes, for the filter's
# suggestions, and it had drifted by eight names before 2026-08-08. The filter
# matches exactly, so each missing name was an action nobody could filter for
# without already knowing its spelling.

AUDIT_OUT=frontend/src/lib/generated/audit-actions.ts

( cd backend && AUTH_MODE=tailnet PYTHONPATH=. uv run python ../scripts/emit_audit_actions.py ) > "$AUDIT_OUT"

echo "wrote $AUDIT_OUT"
