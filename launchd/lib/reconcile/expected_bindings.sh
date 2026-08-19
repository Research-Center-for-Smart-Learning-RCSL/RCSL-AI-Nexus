# Sourced stage: expected bindings.
missing_services() {
  local running svc
  running="$(docker compose ps --services --status running 2>/dev/null)"
  for svc in $EXPECTED_SERVICES; do
    printf '%s\n' "$running" | grep -qx "$svc" || printf '%s\n' "$svc"
  done
}

STABLE=""
FIRST=1
SETTLE=0
while :; do
  MISSING="$(missing_services)"
  if [ "$FIRST" -eq 0 ] && [ "$MISSING" = "$STABLE" ]; then
    SETTLE=$((SETTLE + 1))
    # Three consecutive matching samples, five seconds apart. While Docker
    # Desktop is restoring, the missing set shrinks and never matches, so this
    # cannot mistake a restore in progress for a restore that will not happen.
    [ "$SETTLE" -ge 3 ] && break
  else
    SETTLE=0
  fi
  STABLE="$MISSING"
  FIRST=0
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    log "WARNING: the running set never settled; acting on the last sample"
    break
  fi
  sleep 5
done

if [ -z "$MISSING" ]; then
  log "all expected services running"
else
  # Unquoted on purpose: word-splitting turns the newline-separated list into
  # separate arguments. Compose service names cannot contain whitespace.
  log "not running: $(printf '%s' "$MISSING" | tr '\n' ' ')"
  log "docker did not restore the stack; bringing it up"
  if ! docker compose up -d $MISSING 2>&1; then
    log "ERROR: compose up returned non-zero"
  fi

  # `up -d` returns once the containers are started, but a service that starts
  # and then dies would leave the same hole this branch exists to fill, so the
  # result is read back rather than assumed.
  #
  # It gets its own budget rather than the remaining share of the original one,
  # which can be nothing. DEADLINE is absolute, and one of the two ways into this
  # branch is the settle loop timing out — the 19:10 boot's exact path. Reached
  # that way there is no time left, so the first sample, taken in the moment
  # between `up -d` returning and the containers being reported running, would
  # print FATAL: "these services will not start", about a stack that is starting.
  # A repair whose failure report is a race is not a repair anyone can act on.
  DEADLINE=$((SECONDS + 120))
  while :; do
    MISSING="$(missing_services)"
    [ -z "$MISSING" ] && break
    if [ "$SECONDS" -ge "$DEADLINE" ]; then
      log "FATAL: still not running after up -d: $(printf '%s' "$MISSING" | tr '\n' ' ')"
      log "the bindings below, if any, are checked against an incomplete platform"
      break
    fi
    sleep 5
  done
  [ -z "$MISSING" ] && log "stack up: all expected services running"
fi

# Carried to the end so that a platform which is missing a service cannot leave
# here reporting success just because the services that did come up have their
# bindings. That combination — a true statement about part of the platform
# standing in for a statement about the platform — is the failure this whole
# script was rewritten for, and it is a shape the binding check can reproduce
# on its own.
