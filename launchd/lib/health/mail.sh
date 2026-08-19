# Sourced stage: mail.
ACCOUNT="$(tr -d '[:space:]' < "$ACCOUNT_FILE")"

# All whitespace, not just newlines. A Google app password is sixteen letters
# with no spaces in it; the console displays it as four groups of four purely
# for reading, and pasting what is shown gets the spaces too. Stripping a
# password would normally be wrong — here the space is known not to be part of
# the value, and the failure it causes otherwise is a bare authentication
# rejection that says nothing about why.
PASSWORD="$(tr -d '[:space:]' < "$PASSWORD_FILE")"

# One envelope recipient per address, and a To: header listing all of them. The
# header is display only — delivery is decided entirely by --mail-rcpt, so a
# missing address here would silently not be mailed while the header claimed it
# was. Both are built from the single ALERT_TO list for that reason. Indexed
# arrays are bash 3.2; only associative ones are not.
TO_HEADER=""
RCPT_ARGS=()
for addr in $ALERT_TO; do
  if [ -z "$TO_HEADER" ]; then TO_HEADER="$addr"; else TO_HEADER="$TO_HEADER, $addr"; fi
  RCPT_ARGS+=(--mail-rcpt "$addr")
done

RECONCILE_TAIL="$(tail -5 "$RECONCILE_LOG" 2>/dev/null)"

send_mail() {
  # $1 subject, $2 file holding the body. Headers are added here so no caller
  # can forget one.
  local subject="$1" body="$2" msg
  if [ "$DRY_RUN" != "0" ]; then
    printf '\n===== [dry-run] would send =====\nTo: %s\nSubject: %s\n\n' "$TO_HEADER" "$subject"
    cat "$body"
    printf '===== end =====\n'
    return 0
  fi
  msg="$(mktemp -t nexus-health)" || { log "ERROR: mktemp failed"; return 1; }
  {
    printf 'From: %s\n' "$ACCOUNT"
    printf 'To: %s\n' "$TO_HEADER"
    printf 'Subject: %s\n' "$subject"
    printf 'Date: %s\n' "$(date -R)"
    printf 'Content-Type: text/plain; charset=utf-8\n'
    printf '\n'
    cat "$body"
  } > "$msg"

  if curl --silent --show-error --ssl-reqd --max-time 60 \
       --url "$SMTP_URL" \
       --user "$ACCOUNT:$PASSWORD" \
       --mail-from "$ACCOUNT" \
       "${RCPT_ARGS[@]}" \
       --upload-file "$msg" 2>&1; then
    rm -f "$msg"
    return 0
  fi
  rm -f "$msg"
  return 1
}

BODY="$(mktemp -t nexus-health-body)" || { log "ERROR: mktemp failed"; exit 1; }
trap 'rm -f "$BODY"' EXIT

RC=0

# --- the event mail ---------------------------------------------------------

if [ "$SEND_EVENT" -eq 1 ]; then
  log "$EVENT_KIND: $SIGNATURE"
  {
    printf 'host      %s\n' "$HOST"
    printf 'time      %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'uptime    %ss\n' "$UP"
    printf 'state     %s\n' "$SIGNATURE"
    printf 'previous  %s\n' "${PREV_SIGNATURE:-<none, first run>}"
    printf '\n'
    if [ -n "$DETAIL" ]; then
      printf 'What is wrong\n-------------\n%s\n' "$DETAIL"
    else
      printf 'All checks pass: expected services running and healthy, every\n'
      printf 'requested host binding actually bound and only on %s,\n' "$ALLOWED_HOST_IPS"
      printf 'no container restarted, all six entrances answering, Ollama on\n'
      printf 'loopback only, host metrics served, disk and scrape targets fine.\n\n'
    fi
    printf 'Last lines of nexus-reconcile.log\n---------------------------------\n%s\n\n' "${RECONCILE_TAIL:-<no log>}"
    printf 'Where to look\n-------------\n'
    printf '  docs/runbooks/first-deploy.md 1.1  the acceptance run and the four reconcile outcomes\n'
    printf '  docs/runbooks/first-deploy.md 7    the requested-versus-actual port table\n'
    printf '  docs/architecture/deployment.md 9  why a failed bind does not restart anything\n'
  } > "$BODY"

  if send_mail "$EVENT_SUBJECT" "$BODY"; then
    log "$(sent_word) $EVENT_KIND to $ALERT_TO"
  else
    log "ERROR: could not send the $EVENT_KIND mail; the state below was not delivered"
    log "state was: $SIGNATURE"
    [ -n "$DETAIL" ] && printf '%s' "$DETAIL"
    RC=1
  fi
fi

# --- the daily digest -------------------------------------------------------

if [ "$SEND_DIGEST" -eq 1 ]; then
  WARN_COUNT="$(printf '%s' "$WARNINGS" | grep -c '^' 2>/dev/null)"
  [ -n "$WARNINGS" ] || WARN_COUNT=0

  if [ "$SIGNATURE" != "OK" ]; then
    DIGEST_SUBJECT="[nexus] daily on $HOST: FAILING ($(printf '%s' "$FAILURES" | tr '\n' ' '))"
  elif [ "$WARN_COUNT" -gt 0 ]; then
    DIGEST_SUBJECT="[nexus] daily on $HOST: OK, $WARN_COUNT warning(s)"
  else
    DIGEST_SUBJECT="[nexus] daily on $HOST: all clear"
  fi

  log "digest: $SIGNATURE, $WARN_COUNT warning(s)"

  {
    printf 'host      %s\n' "$HOST"
    printf 'time      %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'uptime    %sh\n' "$((UP / 3600))"
    printf 'state     %s\n' "$SIGNATURE"
    printf '\n'

    if [ -n "$DETAIL" ]; then
      printf 'Failing now\n-----------\n%s\n' "$DETAIL"
    fi

    printf 'Warnings\n--------\n'
    if [ -n "$WARNINGS" ]; then
      printf '%s' "$WARNINGS"
    else
      printf '  none\n'
    fi
    printf '\n'

    # "Figures" and not "Checked and fine". These lines print unconditionally,
    # so when one of them is also the subject of a warning above, calling the
    # section "fine" makes the mail contradict itself — a digest saying the
    # GeoLite2 database is stale and then that it is fine teaches the reader to
    # trust neither half. They are readings; the warnings are the judgement.
    printf 'Figures\n-------\n'
    printf '  - host disk %s%%, Docker VM disk %s%%, %s GB memory available, %s GB swap\n' \
      "${DISK_PCT:-?}" "${DOCKER_DISK_PCT:-?}" "${MEM_AVAIL:-?}" "${SWAP_USED:-?}"
    printf '  - GeoLite2 database %s days old\n' "${GEOIP_AGE_DAYS:-?}"
    # Printed whether or not it is also a warning above, like every other line
    # in this section: a figure the reader can watch trend is worth more than a
    # line that only appears on the days something is wrong.
    printf '  - last successful backup %s hours ago (%s)\n' "${BACKUP_AGE_H:-?}" "${BACKUP_FIGURES:-no figures}"
    [ -n "$RECLAIM_GB" ] && printf '  - %s GB of Docker space reclaimable\n' "$RECLAIM_GB"
    [ -n "$NOTES" ] && printf '%s' "$NOTES"
    printf '\n'

    printf 'Last 24 hours\n-------------\n'
    if [ "$PROM_OK" -eq 1 ]; then
      D_REQ="$(prom_get value 'sum(increase(nexus_http_requests_total[24h])) or vector(0)')"
      D_ERR="$(prom_get value 'sum(increase(nexus_http_requests_total{status=~"5.."}[24h])) or vector(0)')"
      D_P95="$(prom_get value 'histogram_quantile(0.95, sum by (le) (rate(nexus_http_request_duration_seconds_bucket[24h])))')"
      D_TOK="$(prom_get value 'sum(increase(nexus_inference_tokens_total[24h])) or vector(0)')"
      D_CAP="$(prom_get pairs 'sum by (capability) (increase(nexus_inference_requests_total[24h]))' capability)"
      printf '  requests        %s\n' "$(fmt_int "${D_REQ:-}")"
      printf '  of those 5xx    %s\n' "$(fmt_int "${D_ERR:-}")"
      printf '  p95 latency     %s s\n' "$(fmt_sec "${D_P95:-}")"
      printf '  tokens produced %s\n' "$(fmt_int "${D_TOK:-}")"
      if [ -n "$D_CAP" ]; then
        printf '  completions by capability\n'
        printf '%s\n' "$D_CAP" | while read -r cap val; do
          printf '    %-24s %s\n' "$cap" "$(fmt_int "$val")"
        done
      else
        printf '  completions     none\n'
      fi
    else
      printf '  Prometheus was not reachable, so there are no application figures.\n'
    fi
    printf '\n'

    printf 'State changes in the last 24 hours\n----------------------------------\n'
    EVENTS="$(/usr/bin/python3 - "$HEALTH_LOG" <<'PY' 2>/dev/null
import datetime, sys
try:
    with open(sys.argv[1]) as fh:
        lines = fh.readlines()
except Exception:
    sys.exit(0)
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
out = []
for line in lines:
    stamp, _, rest = line.partition(" ")
    if not rest.strip():
        continue
    try:
        when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        continue
    # State changes and errors only. `log` also writes a "mailed <kind> to ..."
    # line for every mail, and those doubled the list while the [-20:] cap threw
    # away the oldest real transitions — the delivery receipts crowding out the
    # events they were receipts for.
    if not rest.startswith(("failing:", "recovered:", "baseline:", "ERROR")):
        continue
    if when >= cutoff:
        # Date as well as time: the window is 24 hours, so it spans two dates,
        # and a bare "22:44" above a "21:02" reads as out of order.
        out.append("  %s %s" % (when.strftime("%m-%d %H:%M"), rest.rstrip()))
print("\n".join(out[-20:]))
PY
)"
    if [ -n "$EVENTS" ]; then
      printf '%s\n' "$EVENTS"
    else
      printf '  none\n'
    fi
    printf '\n'

    printf 'Last lines of nexus-reconcile.log\n---------------------------------\n%s\n\n' "${RECONCILE_TAIL:-<no log>}"
    printf 'This mail arrives daily from %02d:00. If a day passes without one,\n' "$DIGEST_HOUR"
    printf 'the machine or this daemon is the thing to look at first.\n'
  } > "$BODY"

  if send_mail "$DIGEST_SUBJECT" "$BODY"; then
    log "$(sent_word) digest to $ALERT_TO"
    # Only now is the day spent. A failure leaves the previous date in place, so
    # the next run five minutes later tries again.
    write_state "$SIGNATURE" "$DIGEST_DATE" "$RESTART_SNAPSHOT"
  else
    log "ERROR: could not send the digest; it will be retried on the next run"
    RC=1
  fi
fi

exit $RC
