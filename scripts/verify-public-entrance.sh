#!/bin/bash
# Acceptance checks for the public entrance, run from outside it.
#
# Why this exists. security.md section 14 says several of its items must be
# tested rather than assumed, and names two by hand: a forged
# `Tailscale-User-Login` and a forged `X-Forwarded-For`. Until 2026-08-03 there
# was nothing to run them against, because nginx did not exist yet. The day it
# did, both of the header items in the request to the proxy administrator were
# wrong — and the failure was invisible from the proxy's side, where every
# response looks like a working TLS terminator forwarding to a live backend.
#
# The checks that matter here are the two that **cannot be passed by
# accident**, and both work by sending something deliberately wrong:
#
#   - A wrong shared secret must be *overwritten* by nginx. If it survives to
#     the application, nginx is not setting the header at all, and the
#     application is trusting whatever the caller sent.
#   - A forged foreign `X-Forwarded-For` must be *discarded*. If it survives,
#     nginx is appending rather than overwriting, and every caller can choose
#     the source address the country filter and the per-key CIDR allowlists
#     will judge them by.
#
# Both were failing on 2026-08-03 and neither is visible in a 200. That is the
# argument for a script rather than a checklist item.
#
# Read-only: every request here is a GET that expects to be refused. Nothing is
# created, and no valid credential is used.
#
# Written for the bash 3.2 that macOS ships.

set -uo pipefail

ADMIN_HOST="${ADMIN_HOST:-llm.rcsl.online}"
API_HOST="${API_HOST:-llmapi.rcsl.online}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SECRET_FILE="$REPO/secrets/proxy_shared_secret"

# Ordered stages; each is sourced so exit codes and shared state remain unchanged.
. "$REPO/scripts/lib/public-entrance/assertions.sh"
. "$REPO/scripts/lib/public-entrance/entrance_checks.sh"
. "$REPO/scripts/lib/public-entrance/proxy_headers.sh"
. "$REPO/scripts/lib/public-entrance/summary.sh"
