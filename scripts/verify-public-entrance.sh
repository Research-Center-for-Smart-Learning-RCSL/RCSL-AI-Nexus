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

ADMIN_HOST="${ADMIN_HOST:-ai.nexus.rcsl.online}"
API_HOST="${API_HOST:-api.nexus.rcsl.online}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SECRET_FILE="$REPO/secrets/proxy_shared_secret"

PASS=0
FAIL=0
SKIP=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; printf '        %s\n' "$2"; FAIL=$((FAIL + 1)); }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; printf '        %s\n' "$2"; SKIP=$((SKIP + 1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# Status code only. --max-time so a hung proxy fails the check rather than the
# person running it.
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" 2>/dev/null; }
body() { curl -s --max-time 15 "$@" 2>/dev/null; }

SECRET=""
if [ -s "$SECRET_FILE" ]; then
  SECRET="$(tr -d '[:space:]' < "$SECRET_FILE")"
fi

printf '\033[1mPublic entrance acceptance — %s / %s\033[0m\n' "$ADMIN_HOST" "$API_HOST"

# --- 1. The tailnet hop ------------------------------------------------------
head_ "1. Proxy on the tailnet, correctly tagged"

if ! command -v tailscale >/dev/null 2>&1; then
  skip "proxy carries tag:ntnu-proxy" "tailscale CLI not on this host; run from the AI server"
else
  PEER_TAGS="$(tailscale status --json 2>/dev/null \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
for p in (d.get("Peer") or {}).values():
    for t in (p.get("Tags") or []):
        print(p.get("HostName"), t)' 2>/dev/null | grep 'tag:ntnu-proxy')"
  if [ -n "$PEER_TAGS" ]; then
    pass "proxy carries tag:ntnu-proxy (${PEER_TAGS%% *})"
  else
    fail "proxy carries tag:ntnu-proxy" \
      "no tailnet peer has that tag. An untagged join matches no ACL rule, so it reaches nothing and nginx returns 502."
  fi
fi

# --- 2. TLS ------------------------------------------------------------------
head_ "2. TLS"

for h in "$ADMIN_HOST" "$API_HOST"; do
  V="$(curl -s -o /dev/null -w '%{ssl_verify_result}' --max-time 15 "https://$h/" 2>/dev/null)"
  if [ "$V" = "0" ]; then
    pass "$h presents a valid certificate"
  else
    fail "$h presents a valid certificate" \
      "ssl_verify_result=$V. Note a *.rcsl.online wildcard does NOT cover a two-label name like this one."
  fi
done

# --- 3. Reaching our backends, not the proxy's own pages ---------------------
head_ "3. Requests reach this deployment"

H="$(body "https://$API_HOST/healthz")"
case "$H" in
  *'"status"'*'"ok"'*) pass "$API_HOST/healthz is served by the gateway" ;;
  *) fail "$API_HOST/healthz is served by the gateway" "got: ${H:0:120}" ;;
esac

R="$(body "https://$API_HOST/")"
case "$R" in
  *'"detail"'*) pass "$API_HOST/ returns the application's 404, not the proxy's" ;;
  *) fail "$API_HOST/ returns the application's 404, not the proxy's" "got: ${R:0:120}" ;;
esac

L="$(body "https://$ADMIN_HOST/login")"
case "$L" in
  *'<!DOCTYPE html>'*) pass "$ADMIN_HOST/login is served by the management UI" ;;
  *) fail "$ADMIN_HOST/login is served by the management UI" "got: ${L:0:120}" ;;
esac

# --- 4. The two header controls ---------------------------------------------
head_ "4. Perimeter headers (the two that fail silently)"

# Three states are possible and one test cannot separate them, which is worth
# spelling out because the wrong diagnosis sends the administrator looking in
# the wrong place — and a proxy whose configuration *looks* right is exactly
# when that happens:
#
#   A  nginx sets no X-Nexus-Proxy at all
#   B  nginx sets the correct secret
#   C  nginx sets some other value (a placeholder, or the secret never arrived)
#
#   sending a wrong value   -> A: 400   B: passes   C: 400
#   sending the real value  -> A: passes   B: passes   C: 400
#
# So the pair separates all three, and neither probe does it alone. The first
# version of this script reported A on the strength of the wrong-value probe by
# itself, which would have been a confident and unfounded accusation in case C.
S4_WRONG="$(status -H 'X-Nexus-Proxy: deliberately-wrong-value' "https://$ADMIN_HOST/admin/me")"
if [ -n "$SECRET" ]; then
  S4_RIGHT="$(status -H "X-Nexus-Proxy: $SECRET" "https://$ADMIN_HOST/admin/me")"
else
  S4_RIGHT=""
fi

if [ "$S4_WRONG" = "000" ]; then
  fail "nginx sets X-Nexus-Proxy" "no response"
elif [ "$S4_WRONG" != "400" ]; then
  pass "nginx sets X-Nexus-Proxy and overwrites the caller's (got $S4_WRONG)"
elif [ -z "$S4_RIGHT" ]; then
  fail "nginx sets X-Nexus-Proxy" \
    "a wrong value survived to the application (400). Without $SECRET_FILE this cannot say whether nginx sets nothing or sets a different value."
elif [ "$S4_RIGHT" = "400" ]; then
  fail "nginx sets the CORRECT X-Nexus-Proxy" \
    "state C: nginx is setting this header, but not to the value this deployment expects — the real secret is refused too. Check the value in the proxy configuration against secrets/proxy_shared_secret; a placeholder left in place looks exactly like a correct configuration in a screenshot."
else
  fail "nginx sets X-Nexus-Proxy" \
    "state A: nginx sets no value at all — the caller's own header reaches the application untouched, whatever it says. Every request through the entrance is refused (400), and a caller who learns the secret can supply it themselves. If the configuration looks correct, the usual cause is placement: a single proxy_set_header inside a location block DISCARDS every proxy_set_header inherited from the server block, so directives added at server level vanish. Confirm with 'nginx -T' (the effective config) rather than the file or the UI."
fi

# A forged foreign address must be discarded. Sending the real secret too, so
# this check reports on X-Forwarded-For rather than failing at the previous
# gate; once nginx sets the header, nginx's value wins and this is inert.
if [ -n "$SECRET" ]; then
  S5="$(status -H "X-Nexus-Proxy: $SECRET" -H 'X-Forwarded-For: 8.8.8.8' "https://$ADMIN_HOST/admin/me")"
  if [ "$S5" = "403" ]; then
    fail "nginx overwrites X-Forwarded-For (forged address discarded)" \
      "a forged US address was believed (403 country_not_allowed). nginx is appending or not setting it. Use 'proxy_set_header X-Forwarded-For \$remote_addr', never \$proxy_add_x_forwarded_for: the application reads the first value, so an appended header lets the caller choose its own source address and bypass both the country filter and every per-key CIDR allowlist."
  elif [ "$S5" = "000" ]; then
    fail "nginx overwrites X-Forwarded-For (forged address discarded)" "no response"
  else
    pass "nginx overwrites X-Forwarded-For (forged address discarded, got $S5)"
  fi
else
  skip "nginx overwrites X-Forwarded-For" "no $SECRET_FILE on this host"
fi

# --- 5. security.md section 14: forged identity ------------------------------
head_ "5. Forged tailnet identity (security.md section 14)"

AUTH_HDR=""
[ -n "$SECRET" ] && AUTH_HDR="$SECRET"
if [ -n "$AUTH_HDR" ]; then
  S6="$(status -H "X-Nexus-Proxy: $AUTH_HDR" \
        -H 'Tailscale-User-Login: attacker@ntnu.edu.tw' \
        -H 'Tailscale-User-Name: attacker' \
        "https://$ADMIN_HOST/admin/me")"
else
  S6="$(status -H 'Tailscale-User-Login: attacker@ntnu.edu.tw' "https://$ADMIN_HOST/admin/me")"
fi

case "$S6" in
  200) fail "forged Tailscale-User-Login is refused" \
         "AUTHENTICATED AS A FORGED IDENTITY. The public entrance must strip these headers unconditionally (security.md section 4). Stop and treat this as an incident." ;;
  401) pass "forged Tailscale-User-Login is refused (401)" ;;
  400) skip "forged Tailscale-User-Login is refused" \
         "refused at the perimeter (400) before identity resolution, so this says nothing yet. Re-run once check 4 passes." ;;
  *)   fail "forged Tailscale-User-Login is refused" "unexpected status $S6" ;;
esac

# --- summary -----------------------------------------------------------------
printf '\n\033[1m%s passed, %s failed, %s skipped\033[0m\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ] || exit 1
