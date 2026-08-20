# Sourced stage: metrics.
PROM_OK=0
[ "$DOCKER_UP" -eq 1 ] && running_p prometheus && PROM_OK=1

prom_get() {
  # $1 mode: `value` for the first sample, `pairs` for "<label> <value>" lines.
  # $2 promql. $3 label name, for pairs.
  #
  # Returns non-zero when Prometheus could not be asked or did not answer
  # successfully, and zero with empty output when the query matched nothing.
  # Those are different answers and the callers rely on the difference.
  [ "$PROM_OK" -eq 1 ] || return 1
  local enc raw
  enc="$(/usr/bin/python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$2" 2>/dev/null)" || return 1
  raw="$(run_timeout 20 docker compose exec -T prometheus wget -qO- "http://localhost:9090/api/v1/query?query=$enc" 2>/dev/null)" || return 1
  [ -n "$raw" ] || return 1
  printf '%s' "$raw" | /usr/bin/python3 -c '
import json, sys
mode = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else ""
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if d.get("status") != "success":
    sys.exit(1)
result = d.get("data", {}).get("result", [])
if mode == "value":
    print(result[0]["value"][1] if result else "")
else:
    for s in result:
        print("%s %s" % (s["metric"].get(label, "?"), s["value"][1]))
' "$1" "${3:-}"
}

if [ "$PROM_OK" -eq 1 ]; then
  DOWN_TARGETS="$(prom_get pairs 'up == 0' job)"
  if [ $? -ne 0 ]; then
    fail "prometheus" "Prometheus is running but did not answer a query. Every metric behind it — the dashboards, and the application checks below — is unavailable."
  elif [ -n "$DOWN_TARGETS" ]; then
    fail "scrape" "Prometheus cannot scrape: $(printf '%s' "$DOWN_TARGETS" | awk '{print $1}' | tr '\n' ' '). The container can be running and the entrance answering while this fails, which is what makes it its own check — a wrong metrics_scrape_token looks exactly like this."
  fi

  # 5xx rate over the last five minutes, guarded by a sample floor: at low
  # traffic one failed request is 100% and would mail every time somebody's
  # browser gave up.
  ERR5="$(prom_get value 'sum(increase(nexus_http_requests_total{status=~"5.."}[5m])) or vector(0)')"
  TOT5="$(prom_get value 'sum(increase(nexus_http_requests_total[5m])) or vector(0)')"
  if [ -n "$ERR5" ] && [ -n "$TOT5" ]; then
    if awk -v e="$ERR5" -v t="$TOT5" -v r="$HTTP_5XX_RATIO" -v m="$HTTP_5XX_MIN_SAMPLE" \
       'BEGIN{exit !(t>=m && e/t>=r)}'; then
      fail "http-5xx" "$(fmt_int "$ERR5") of $(fmt_int "$TOT5") requests in the last five minutes returned 5xx (threshold $(awk -v r="$HTTP_5XX_RATIO" 'BEGIN{printf "%d", r*100}')%). Every entrance can be answering /readyz while the requests that matter fail."
    fi
  fi
fi

# --- 12. the GeoLite2 database is not stale ---------------------------------
#
# refresh-geolite2 runs weekly and, in the runbook's own words, "失敗不會有人通知
# 你". Its own staleness check only speaks when it runs, which is precisely the
# thing that is not happening when it has failed. One stat answers it from
# outside, which is the only place the answer is trustworthy.

GEOIP_FILE="$REPO/data/GeoLite2-Country.mmdb"
if [ ! -f "$GEOIP_FILE" ]; then
  warn "the GeoLite2 database is missing from $GEOIP_FILE; the geo filter has nothing to read"
else
  GEOIP_MTIME="$(stat -f %m "$GEOIP_FILE" 2>/dev/null)"
  case "$GEOIP_MTIME" in
    ''|*[!0-9]*) warn "could not read the mtime of $GEOIP_FILE, so its freshness is unknown" ;;
    *)
      GEOIP_AGE_DAYS=$(( (NOW - GEOIP_MTIME) / 86400 ))
      if [ "$GEOIP_AGE_DAYS" -gt "$GEOIP_MAX_AGE_DAYS" ]; then
        warn "the GeoLite2 database is ${GEOIP_AGE_DAYS} days old (warn over ${GEOIP_MAX_AGE_DAYS}); it refreshes weekly, so this is at least two failed runs — see /opt/homebrew/var/log/nexus-geolite2.log"
      fi
      ;;
  esac
fi

# --- 13. the tailscale node key ---------------------------------------------
#
# Three answers, and the third is the point. `tailscale status --json` omits
# `KeyExpiry` from `Self` entirely when key expiry is disabled for the node —
# peers that do expire carry the field, this machine does not. A check that read
# the field and treated absence as "fine" would be a permanent silent pass, and
# would keep passing if the JSON shape ever changed or the command broke. So:
# absent field is only an answer once `Self` itself has been found.

TS_STATE=""
TS_DAYS=""
TS_PARSED="$(tailscale status --json 2>/dev/null | /usr/bin/python3 -c '
import datetime, json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("unreadable"); sys.exit(0)
self_node = d.get("Self")
if not isinstance(self_node, dict):
    print("no-self"); sys.exit(0)
expiry = self_node.get("KeyExpiry")
if not expiry:
    print("disabled"); sys.exit(0)
try:
    when = datetime.datetime.strptime(expiry[:19], "%Y-%m-%dT%H:%M:%S")
except Exception:
    print("unreadable"); sys.exit(0)
print("expires")
print(int((when - datetime.datetime.utcnow()).total_seconds() // 86400))
' 2>/dev/null)"
TS_STATE="$(printf '%s\n' "$TS_PARSED" | sed -n '1p')"
TS_DAYS="$(printf '%s\n' "$TS_PARSED" | sed -n '2p')"
case "$TS_STATE" in
  disabled)
    note "tailscale node key: expiry is disabled for this machine, so it cannot lapse" ;;
  expires)
    if [ -n "$TS_DAYS" ] && [ "$TS_DAYS" -le "$TS_KEY_WARN_DAYS" ]; then
      warn "the tailscale node key expires in ${TS_DAYS} days; when it lapses the tailnet address disappears and every tailnet-facing binding with it"
    else
      note "tailscale node key: ${TS_DAYS} days remaining" ;
    fi ;;
  no-self|unreadable|*)
    warn "could not read the tailscale node key expiry (\`tailscale status --json\` gave '${TS_STATE:-nothing}'). This is unknown, not fine — the field is absent both when expiry is disabled and when the command has stopped answering the way it used to." ;;
esac

# --- 14. what the database says about itself --------------------------------
#
# Four questions, one connection, all of them tier 2 because each has weeks of
# lead time. No credential: `psql` over `docker compose exec` authenticates
# locally inside the container, which is the same reason the rest of this script
# needs none.
#
# The retention question is asked as an outcome rather than as a liveness check.
# `run_retention_sweep` is an asyncio loop inside the admin process; there is no
# port to probe and no metric to read, and a loop that has died looks exactly
# like one that has nothing to delete. "Is the oldest row older than the policy
# allows" is answerable from outside and is the thing anybody actually cares
# about, and when no policy is stored it says that instead of inventing a pass.

if [ "$DOCKER_UP" -eq 1 ] && running_p postgres; then
  DB_OUT="$(run_timeout 25 docker compose exec -T postgres psql -U nexus -d nexus -tAc "
select 'keys_expiring='||count(*) from api_keys
  where revoked_at is null and expires_at is not null
    and expires_at < now() + (interval '1 day' * $KEY_EXPIRY_WARN_DAYS)
union all select 'keys_debug='||count(*) from api_keys where debug_logging_until > now()
union all select 'users_debug='||count(*) from users where debug_logging_until > now()
union all select 'policies='||count(*) from retention_policies
union all select 'audit_days='||coalesce(round(extract(epoch from (now()-min(at)))/86400)::int::text,'-1') from audit_log
union all select 'usage_days='||coalesce(round(extract(epoch from (now()-min(at)))/86400)::int::text,'-1') from usage_records
union all select 'audit_policy='||coalesce((select days::text from retention_policies where dataset='audit_log'),'$DEFAULT_RETENTION_DAYS')
union all select 'usage_policy='||coalesce((select days::text from retention_policies where dataset='usage_records'),'$DEFAULT_RETENTION_DAYS')
" 2>/dev/null)"

  if [ -z "$DB_OUT" ]; then
    warn "could not query Postgres for key expiry and retention state; the container is running, so this is psql or the database itself"
  else
    KEYS_EXPIRING=""; KEYS_DEBUG=""; USERS_DEBUG=""; POLICIES=""
    AUDIT_DAYS=""; USAGE_DAYS=""; AUDIT_POLICY=""; USAGE_POLICY=""
    while IFS= read -r row; do
      case "$row" in
        keys_expiring=*) KEYS_EXPIRING="${row#*=}" ;;
        keys_debug=*)    KEYS_DEBUG="${row#*=}" ;;
        users_debug=*)   USERS_DEBUG="${row#*=}" ;;
        policies=*)      POLICIES="${row#*=}" ;;
        audit_days=*)    AUDIT_DAYS="${row#*=}" ;;
        usage_days=*)    USAGE_DAYS="${row#*=}" ;;
        audit_policy=*)  AUDIT_POLICY="${row#*=}" ;;
        usage_policy=*)  USAGE_POLICY="${row#*=}" ;;
      esac
    done <<EOF
$DB_OUT
EOF

    [ "${KEYS_EXPIRING:-0}" -gt 0 ] 2>/dev/null && \
      warn "${KEYS_EXPIRING} API key(s) expire within ${KEY_EXPIRY_WARN_DAYS} days; the first thing a caller will know about it is a 401"
    [ "${KEYS_DEBUG:-0}" -gt 0 ] 2>/dev/null && \
      warn "${KEYS_DEBUG} API key(s) still have debug logging switched on; it expires by itself, but until it does their request contents are being recorded"
    [ "${USERS_DEBUG:-0}" -gt 0 ] 2>/dev/null && \
      warn "${USERS_DEBUG} user(s) still have debug logging switched on"

    # An absent row is not an absent policy. `ManageRetention._days_for` falls
    # back to DEFAULT_RETENTION_DAYS, and RetentionPolicyRow's docstring says the
    # absence of a row *is* the default — which is why no migration seeds one, and
    # why `policies=0` is the normal shipped state rather than a fault. The SQL
    # above therefore resolves the effective number of days per dataset, and the
    # staleness check below runs against it unconditionally.
    #
    # This was wrong in the first version of this check, and wrong twice over: it
    # warned every single day that "the sweep deletes nothing", which was false,
    # and it put the real check — the only thing that can detect a dead
    # `run_retention_sweep` loop — in the branch that never runs by default.
    if [ "${POLICIES:-0}" = "0" ]; then
      note "retention: no policy row stored, so both datasets use the built-in default of ${DEFAULT_RETENTION_DAYS} days"
    fi

    # Two days of slack: the sweep runs daily, so a row one day past the window
    # is on time rather than late.
    if [ "${AUDIT_POLICY:--1}" -gt 0 ] 2>/dev/null && [ "${AUDIT_DAYS:--1}" -gt $((AUDIT_POLICY + 2)) ] 2>/dev/null; then
      warn "audit_log holds rows ${AUDIT_DAYS} days old against an effective ${AUDIT_POLICY}-day window; the retention sweep is not doing what the policy says"
    fi
    if [ "${USAGE_POLICY:--1}" -gt 0 ] 2>/dev/null && [ "${USAGE_DAYS:--1}" -gt $((USAGE_POLICY + 2)) ] 2>/dev/null; then
      warn "usage_records holds rows ${USAGE_DAYS} days old against an effective ${USAGE_POLICY}-day window; the retention sweep is not doing what the policy says"
    fi
  fi
fi

# --- 15. the encrypted backup -----------------------------------------------
#
# Asked as an outcome, not as a liveness check, for the same reason the
# retention question above is: `online.rcsl.backup` is a launchd job in the
# system domain, so this script — running unprivileged — cannot ask launchctl
# whether it is loaded, and a job that is loaded but silently failing looks
# exactly like one that is not installed. What is answerable from here is the
# only thing anybody actually cares about: when did a backup last SUCCEED.
#
# backup.sh writes /opt/homebrew/var/nexus-backup.state on every path it can
# exit through, including the watchdog kill, and keeps the last success and the
# last outcome on separate lines. That separation is what lets this check
# distinguish one transient failure on top of a fresh backup — the external disk
# unmounted overnight — from a run that has been failing since Tuesday.
#
# Tier 1 for the two states that will not fix themselves, and the split is
# deliberate. The header of this file argues that a check with lead time belongs
# in the digest, because a subject line that reads FAILING for a fortnight stops
# meaning anything. A backup that has never run, or has not succeeded in three
# days, has no lead time in that sense: nothing is going to repair it, and the
# cost is not paid gradually — it is paid in full, once, on the day somebody
# needs it. Between one and three days is genuinely degrading and waits for the
# digest, which is where a single failed night belongs.
