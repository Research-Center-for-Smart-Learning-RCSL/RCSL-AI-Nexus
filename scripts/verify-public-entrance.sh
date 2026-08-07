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

PASS=0
FAIL=0
SKIP=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; printf '        %s\n' "$2"; FAIL=$((FAIL + 1)); }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; printf '        %s\n' "$2"; SKIP=$((SKIP + 1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# A function because section 4 can end the run early, and the counts have to be
# reported the same way from both places.
summary() {
  printf '\n\033[1m%s passed, %s failed, %s skipped\033[0m\n' "$PASS" "$FAIL" "$SKIP"
  [ "$FAIL" -eq 0 ] || exit 1
  exit 0
}

# Status code only. --max-time so a hung proxy fails the check rather than the
# person running it.
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" 2>/dev/null; }
body() { curl -s --max-time 15 "$@" 2>/dev/null; }

# Why the entrance is not answering, as one word.
#
# The first version of this script read %{ssl_verify_result} and called anything
# non-zero an invalid certificate. That value is 1 whenever the handshake did
# not complete, so four unrelated states produced one message — and the hint it
# printed alongside ("a *.rcsl.online wildcard does not cover a two-label name")
# named a certificate-scope problem as the cause. On 2026-08-04 the actual cause
# was that both proxy hosts had been removed from NPM, and the script sent the
# reader to look at certificates. This is the same defect as the one section 4
# documents: one probe, several causes, and a confident message for the wrong
# one. Certificate scope is a real failure and its note belongs in `cert`, where
# the handshake got far enough for the certificate to be the thing at fault.
#
# curl's exit code carries the distinction the status code cannot: 000 is every
# one of these. `unrecognized name` is TLS alert 112, sent when no server block
# matches the SNI -- the name is not configured, which is not a TLS fault at all.
entrance_state() {
  local h="$1"
  local out
  local rc
  out="$(curl -sv -o /dev/null --max-time 15 "https://$h/" 2>&1)"
  rc=$?
  case "$rc" in
    0)  echo ok ;;
    6)  echo dns ;;
    7)  echo refused ;;
    28) echo timeout ;;
    35) if printf '%s' "$out" | grep -qi 'unrecognized name'; then
          echo unconfigured
        else
          echo handshake
        fi ;;
    51|60) echo cert ;;
    *)  echo "curl$rc" ;;
  esac
}

# Corroborates `unconfigured` from the other side. NPM answers port 80 for a
# name it does not know with its own stock welcome page, so seeing it means the
# proxy is running and this hostname has no host entry -- as opposed to nginx
# being down, which cannot answer anything. Distinguishing those two decides
# whether the administrator restores a host or starts a service.
serves_npm_default_site() {
  body "http://$1/" | grep -q 'successfully started the Nginx Proxy Manager'
}

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

# --- 2. TLS, and whether the entrance answers at all -------------------------
head_ "2. TLS and the entrance answering at all"

# Recorded so sections 3-5 can skip rather than report a second failure with a
# third explanation. Every check below sends an HTTPS request to one of these
# two names; if the name does not answer, none of them is testing what it says.
ADMIN_STATE="$(entrance_state "$ADMIN_HOST")"
API_STATE="$(entrance_state "$API_HOST")"

for h in "$ADMIN_HOST" "$API_HOST"; do
  if [ "$h" = "$ADMIN_HOST" ]; then ST="$ADMIN_STATE"; else ST="$API_STATE"; fi
  case "$ST" in
    ok)
      pass "$h presents a valid certificate" ;;
    unconfigured)
      if serves_npm_default_site "$h"; then
        fail "$h is configured on the proxy" \
          "the proxy is running and has no host entry for this name: TLS alert 112 (unrecognized name) on 443, and port 80 answers with NPM's stock welcome page. The certificate is not the problem and may well still be present under SSL Certificates. Restore the proxy host (deployment.md section 5), and re-read the placement warning there before saving: the four proxy_set_header directives must end up inside the location block that serves the request."
      else
        fail "$h is configured on the proxy" \
          "TLS alert 112 (unrecognized name): no server block matches this name, so nginx refused before any certificate was chosen. Either the host entry is gone or it is bound to a different name."
      fi ;;
    cert)
      fail "$h presents a valid certificate" \
        "the handshake reached the certificate and it was rejected. Both names this script checks are single-label, so a *.rcsl.online wildcard does cover them — which makes scope the unlikely cause here, and expiry or an incomplete chain the likely one." ;;
    handshake)
      fail "$h completes a TLS handshake" \
        "the connection was accepted and the handshake failed before the certificate. Protocol or cipher mismatch, or something on 443 that is not a TLS server." ;;
    refused)
      fail "$h answers on 443" \
        "connection refused. nginx is not listening -- a stopped service, not a configuration error. Nothing below can run until it is back." ;;
    timeout)
      fail "$h answers on 443" \
        "no answer within 15s. A firewall dropping the packets looks exactly like this; a refusal does not." ;;
    dns)
      fail "$h resolves" \
        "the name does not resolve. Nothing here reaches the proxy at all." ;;
    *)
      fail "$h answers on 443" "curl exited ${ST#curl}, which this script does not classify." ;;
  esac
done

# --- 3. Reaching our backends, not the proxy's own pages ---------------------
head_ "3. Requests reach this deployment"

# An empty body is not evidence about what serves a path. When the entrance is
# down these read "got: " three times, which says nothing and still counts as
# three distinct failures next to section 2's one real one.
DOWN="the entrance is not answering (see check 2), so this cannot be tested"

if [ "$API_STATE" != "ok" ]; then
  skip "$API_HOST/healthz is served by the gateway" "$DOWN"
  skip "$API_HOST/ returns the application's 404, not the proxy's" "$DOWN"
else
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
fi

if [ "$ADMIN_STATE" != "ok" ]; then
  skip "$ADMIN_HOST/login is served by the management UI" "$DOWN"
else
  L="$(body "https://$ADMIN_HOST/login")"
  case "$L" in
    *'<!DOCTYPE html>'*) pass "$ADMIN_HOST/login is served by the management UI" ;;
    *) fail "$ADMIN_HOST/login is served by the management UI" "got: ${L:0:120}" ;;
  esac
fi

# --- 4. The two header controls ---------------------------------------------
head_ "4. Perimeter headers (the two that fail silently)"

# **This section probed ADMIN_HOST alone until 2026-08-07, and the omission
# cost exactly what it was written to prevent.** The script reported 9 passed,
# 0 failed on that day, and an agent client pointed at the inference host got
# `400 untrusted_proxy` on its first request: that host's server block never
# had the four `proxy_set_header` directives, and nothing here had ever asked
# it. A perimeter control verified on one of two hosts is verified on neither,
# because the reason to check is that the two are configured separately.
#
# Section 5 stays on ADMIN_HOST: `Tailscale-User-Login` means nothing to the
# gateway, which resolves identity from an API key and has no tailnet path.
if [ "$ADMIN_STATE" != "ok" ] && [ "$API_STATE" != "ok" ]; then
  skip "nginx sets X-Nexus-Proxy" "$DOWN"
  skip "nginx overwrites X-Forwarded-For (forged address discarded)" "$DOWN"
  head_ "5. Forged tailnet identity (security.md section 14)"
  skip "forged Tailscale-User-Login is refused" "$DOWN"
  summary
fi

# The paired probe, run per host.
#
# **The two entrances cannot be probed the same way, and assuming they could
# produced a false pass on the first attempt at this.** On the management host
# `GeoFilterMiddleware` calls `resolve_client_ip` at the ASGI stack level, so an
# unauthenticated `/admin/me` reaches the perimeter check and a missing header
# is a 400. The gateway has no stack-level middleware at all — it applies the
# geo filter *inline inside key authentication* — and `api_key_auth.py` orders
# its checks so that a missing, malformed, unknown or inactive key answers 401
# at lines 101-116, long before `resolve_client_ip` at line 126.
#
# So on the inference host every credential-free probe answers 401 whatever the
# proxy does, and reading that as "not 400, therefore the header is set" is a
# pass that means nothing. It reported one on 2026-08-07 while a real client was
# being refused `untrusted_proxy` on its first request.
#
# Hence `auth`: the inference check needs a valid key and is skipped, loudly,
# without one. A skip that names the reason is worth more than a green tick
# that cannot fail.
check_proxy_headers() {
  local host="$1" probe_path="$2" state="$3" label="$4" auth="${5:-}"

  if [ "$state" != "ok" ]; then
    skip "$label: nginx sets X-Nexus-Proxy" "$DOWN"
    skip "$label: nginx overwrites X-Forwarded-For" "$DOWN"
    return
  fi

  local -a cred=()
  if [ -n "$auth" ]; then
    cred=(-H "Authorization: Bearer $auth")
  elif [ "$probe_path" = "/v1/models" ]; then
    skip "$label: nginx sets X-Nexus-Proxy" \
      "needs a valid API key. The gateway answers 401 to anything unauthenticated before it ever looks at the proxy headers (api_key_auth.py, key checks at 101-116 against resolve_client_ip at 126), so a credential-free probe here cannot distinguish a configured host from an unconfigured one. Set NEXUS_API_KEY to a key scoped to any capability and re-run."
    skip "$label: nginx overwrites X-Forwarded-For" "same reason"
    return
  fi

  local wrong right
  wrong="$(status ${cred[@]+"${cred[@]}"} -H 'X-Nexus-Proxy: deliberately-wrong-value' "https://$host$probe_path")"
  if [ -n "$SECRET" ]; then
    right="$(status ${cred[@]+"${cred[@]}"} -H "X-Nexus-Proxy: $SECRET" "https://$host$probe_path")"
  else
    right=""
  fi

  if [ -z "$wrong" ] || [ "$wrong" = "000" ]; then
    fail "$label: nginx sets X-Nexus-Proxy" \
      "no status from the probe (got '"'"'$wrong'"'"'). An empty result is a broken check, not a healthy host."
  elif [ "$wrong" != "400" ]; then
    pass "$label: nginx sets X-Nexus-Proxy and overwrites the caller's (got $wrong)"
  elif [ -z "$right" ]; then
    fail "$label: nginx sets X-Nexus-Proxy" \
      "a wrong value survived to the application (400). Without $SECRET_FILE this cannot say whether nginx sets nothing or sets a different value."
  elif [ "$right" = "400" ]; then
    fail "$label: nginx sets the CORRECT X-Nexus-Proxy" \
      "state C: nginx is setting this header, but not to the value this deployment expects — the real secret is refused too. Check the value in the proxy configuration against secrets/proxy_shared_secret; a placeholder left in place looks exactly like a correct configuration in a screenshot."
  else
    fail "$label: nginx sets X-Nexus-Proxy" \
      "state A: nginx sets no value at all — the caller's own header reaches the application untouched, whatever it says. Every request through this entrance is refused (400), and a caller who learns the secret can supply it themselves. If the configuration looks correct, the usual cause is placement: a single proxy_set_header inside a location block DISCARDS every proxy_set_header inherited from the server block, so directives added at server level vanish. Confirm with 'nginx -T' (the effective config) rather than the file or the UI."
  fi

  # A forged foreign address must be discarded. The real secret goes with it so
  # this reports on X-Forwarded-For rather than failing at the previous gate.
  if [ -z "$SECRET" ]; then
    skip "$label: nginx overwrites X-Forwarded-For" "no $SECRET_FILE on this host"
    return
  fi
  local forged
  forged="$(status ${cred[@]+"${cred[@]}"} -H "X-Nexus-Proxy: $SECRET" -H 'X-Forwarded-For: 8.8.8.8' "https://$host$probe_path")"
  if [ "$forged" = "403" ]; then
    fail "$label: nginx overwrites X-Forwarded-For (forged address discarded)" \
      "a forged US address was believed (403 country_not_allowed). nginx is appending or not setting it. Use 'proxy_set_header X-Forwarded-For \$remote_addr', never \$proxy_add_x_forwarded_for: the application reads the first value, so an appended header lets the caller choose its own source address and bypass both the country filter and every per-key CIDR allowlist."
  elif [ -z "$forged" ] || [ "$forged" = "000" ]; then
    fail "$label: nginx overwrites X-Forwarded-For (forged address discarded)" "no response"
  else
    pass "$label: nginx overwrites X-Forwarded-For (forged address discarded, got $forged)"
  fi
}

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
#
# `/v1/models` is the gateway's probe rather than `/healthz`, which is exempt
# from the perimeter so a prober can reach it — a check aimed at an exempt path
# would pass on a host with no directives at all.
check_proxy_headers "$ADMIN_HOST" "/admin/me" "$ADMIN_STATE" "management"
check_proxy_headers "$API_HOST" "/v1/models" "$API_STATE" "inference" "${NEXUS_API_KEY:-}"

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
summary
