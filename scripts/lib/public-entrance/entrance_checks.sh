# Sourced stage: entrance checks.
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
