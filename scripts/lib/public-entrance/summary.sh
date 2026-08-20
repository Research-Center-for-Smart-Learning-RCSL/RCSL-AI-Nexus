# Sourced stage: summary.
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
