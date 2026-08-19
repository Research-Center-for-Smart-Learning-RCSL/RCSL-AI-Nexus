# Sourced stage: state.
PREV_SIGNATURE=""
PREV_DIGEST_DATE=""
PREV_RESTARTS=""
if [ -f "$STATE_FILE" ]; then
  PREV_SIGNATURE="$(sed -n '1p' "$STATE_FILE")"
  PREV_DIGEST_DATE="$(sed -n '2p' "$STATE_FILE")"
  PREV_RESTARTS="$(sed -n '3p' "$STATE_FILE")"
  # Anything that is not a date is "no digest has been sent", which includes the
  # rolling heartbeat's timestamp from before 2026-08-04.
  case "$PREV_DIGEST_DATE" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) PREV_DIGEST_DATE="" ;;
  esac
fi

write_state() {
  # $1 signature, $2 digest date, $3 restart snapshot. Every exit path calls
  # this, and it always writes three lines: a path that wrote two would truncate
  # the restart snapshot, the baseline would be lost, and the restart check
  # would go quiet without saying so.
  if [ "$DRY_RUN" != "0" ]; then
    printf '[dry-run] would write state: %s | %s | %s\n' "$1" "$2" "$3"
    return 0
  fi
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  printf '%s\n%s\n%s\n' "$1" "$2" "$3" > "$STATE_FILE"
}

# --- boot grace -------------------------------------------------------------
#
# The anchored `^{ sec = ` is load-bearing; see BOOT_GRACE above for what the
# unanchored version did.
