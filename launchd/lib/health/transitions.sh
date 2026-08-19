# Sourced stage: transitions.
HOST="$(hostname -s)"

SEND_EVENT=0
EVENT_KIND=""
EVENT_SUBJECT=""
if [ "$SIGNATURE" != "$PREV_SIGNATURE" ]; then
  SEND_EVENT=1
  if [ -z "$PREV_SIGNATURE" ] && [ "$SIGNATURE" = "OK" ]; then
    # First run ever. Reporting this as a recovery would claim a failure that
    # never happened; it is a baseline, and it doubles as proof the mail path
    # works, which is the one part of this that cannot be tested by watching.
    EVENT_KIND="baseline"
    EVENT_SUBJECT="[nexus] monitoring started on $HOST, all checks pass"
  elif [ "$SIGNATURE" = "OK" ]; then
    EVENT_KIND="recovered"
    EVENT_SUBJECT="[nexus] RECOVERED on $HOST"
  else
    EVENT_KIND="failing"
    EVENT_SUBJECT="[nexus] FAILING on $HOST: $(printf '%s' "$FAILURES" | tr '\n' ' ')"
  fi
fi

# The digest is due once per calendar day, from DIGEST_HOUR onwards. Both mails
# can fall in the same run; they are allowed to, because they answer different
# questions and merging them would mean the urgent one waits for the daily one
# or the daily one loses its summary.
SEND_DIGEST=0
DIGEST_DATE="$PREV_DIGEST_DATE"
if [ "$TODAY" != "$PREV_DIGEST_DATE" ] && [ "$HOUR" -ge "$DIGEST_HOUR" ]; then
  SEND_DIGEST=1
  DIGEST_DATE="$TODAY"
fi
# A dry run always renders the digest, whatever the calendar says. Otherwise the
# one mail that is hard to eyeball — the one with every tier-2 check in it — can
# only be inspected on the day it happens not to have been sent yet.
[ "$DRY_RUN" != "0" ] && SEND_DIGEST=1

# Written before any mail is attempted, so a broken mail path cannot turn one
# state change into an alert on every interval.
#
# The digest date is deliberately *not* advanced here — it is written again
# after the digest actually goes out. The reasoning above is about the
# signature: re-alerting every five minutes is worse than losing one alert. It
# does not carry over to the digest, where burning the date on a transient SMTP
# failure at 08:00 means no digest at all that day, and the design's own
# contract says a day with no digest means the machine is gone. A network blip
# would manufacture that signal, with an ERROR line in a log this file says
# nobody reads as the only trace.
write_state "$SIGNATURE" "$PREV_DIGEST_DATE" "$RESTART_SNAPSHOT"

if [ "$SEND_EVENT" -eq 0 ] && [ "$SEND_DIGEST" -eq 0 ]; then
  exit 0
fi

# --- send -------------------------------------------------------------------

if [ ! -r "$ACCOUNT_FILE" ] || [ ! -r "$PASSWORD_FILE" ]; then
  log "ERROR: cannot mail — $ACCOUNT_FILE or $PASSWORD_FILE is missing or unreadable"
  log "state was: $SIGNATURE"
  [ -n "$DETAIL" ] && printf '%s' "$DETAIL"
  exit 1
fi
