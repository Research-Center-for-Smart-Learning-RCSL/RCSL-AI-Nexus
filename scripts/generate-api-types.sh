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
SPEC="$(mktemp -t nexus-openapi).json"
trap 'rm -f "$SPEC"' EXIT

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
