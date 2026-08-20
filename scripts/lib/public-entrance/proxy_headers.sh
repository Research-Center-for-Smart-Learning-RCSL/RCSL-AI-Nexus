# Sourced stage: proxy headers.
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
