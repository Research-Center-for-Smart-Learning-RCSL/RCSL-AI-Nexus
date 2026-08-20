# Sourced stage: repair.
BROKEN="$(broken_services)"

if [ -z "$BROKEN" ]; then
  log "all published bindings intact"
  if [ "$INCOMPLETE" -eq 1 ]; then
    log "but the platform is incomplete; see the missing services above"
    exit 1
  fi
  exit 0
fi

# Unquoted on purpose: word-splitting turns the newline-separated list into
# separate arguments. Compose service names cannot contain whitespace.
log "recreating: $(printf '%s' "$BROKEN" | tr '\n' ' ')"
if ! docker compose up -d --force-recreate $BROKEN 2>&1; then
  log "ERROR: force-recreate returned non-zero"
fi

# Verify rather than assume, and only once. A service still unbound after a
# recreate has a cause a retry cannot fix — an internal-only network, a port
# already taken — and looping would churn every boot while burying that in
# noise.
sleep 5
STILL="$(broken_services)"

if [ -z "$STILL" ]; then
  log "OK: all bindings restored"
  if [ "$INCOMPLETE" -eq 1 ]; then
    log "but the platform is incomplete; see the missing services above"
    exit 1
  fi
  exit 0
fi

log "STILL UNBOUND after recreate: $(printf '%s' "$STILL" | tr '\n' ' ')"
log "this has a cause a recreate cannot fix; investigate rather than retry"
exit 1
