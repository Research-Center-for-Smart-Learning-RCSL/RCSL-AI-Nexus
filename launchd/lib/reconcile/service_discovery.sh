# Sourced stage: service discovery.
log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

log "reconcile starting"

cd "$REPO" || { log "FATAL: cannot cd to $REPO"; exit 1; }

# After the cd, because `docker compose config` reads the compose file from the
# working directory. Before that it would have failed silently every time and
# left the literal standing, which is the shape of bug this derivation exists to
# remove rather than reproduce.
DERIVED_SERVICES="$(docker compose config --services 2>/dev/null | grep -vx 'migrate' | tr '\n' ' ')"
if [ -n "$DERIVED_SERVICES" ]; then
  EXPECTED_SERVICES="${DERIVED_SERVICES% }"
else
  log "WARNING: could not derive the service list from docker compose config; using the built-in list"
fi
log "expecting: $EXPECTED_SERVICES"

# TAILNET_IP is read from the same .env that docker-compose.yml interpolates,
# so the address this waits for cannot drift from the address it binds.
TAILNET_IP="$(sed -n 's/^TAILNET_IP=//p' .env 2>/dev/null | head -1 | tr -d '"'\''[:space:]')"
if [ -z "$TAILNET_IP" ]; then
  log "FATAL: TAILNET_IP is not set in $REPO/.env; nothing to wait for"
  exit 1
fi
log "waiting for tailnet address $TAILNET_IP and a responsive docker"

# Precondition 1: the address is actually assigned to an interface. `tailscale
# status` reporting it is not enough — the bind needs it on utun0, and that is
# what ifconfig answers.
while ! ifconfig 2>/dev/null | grep -qw "$TAILNET_IP"; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    log "FATAL: timed out waiting for $TAILNET_IP to appear on an interface"
    exit 1
  fi
  sleep 5
done
log "tailnet address present"

# Precondition 2: the docker daemon answers. Colima must be running (started by
# online.rcsl.colima.plist); if it has not come up yet, this is where it
# surfaces, instead of failing obscurely further on.
while ! docker info >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    log "FATAL: timed out waiting for the docker daemon"
    exit 1
  fi
  sleep 5
done
log "docker daemon responding"

# Precondition 3: the expected services are actually running.
#
# The daemon answers well before the last container is back, and at boot Docker
# Desktop restores them one at a time. Checking then would enumerate only the
# containers that had already returned, find their bindings intact, and exit
# reporting success while the ones still to come — possibly the broken ones —
# were never looked at. That is the same shape of error as trusting `up -d` to
# rebuild a forward: a check whose timing lets it produce only one answer.
#
# So wait for the set to stop moving rather than for a fixed delay, which would
# be another guess.
#
# It waits for a *named* set rather than for a count, because a count cannot
# distinguish "not restored yet" from "not coming back". `restart: unless-stopped`
# is Docker's promise, not this machine's, and on the 2026-07-26 19:10 boot it
# was not kept: nine containers stopped cleanly at 19:04:18, the engine was
# running again at 19:10:37, and nothing was ever restored — no `exposer.Add` in
# the backend log, no container started. The earlier version of this loop
# required a count greater than zero before it would settle, so it spun to its
# ten-minute deadline against an empty platform and then reported "all published
# bindings intact; nothing to do" and exited 0. It was structurally incapable of
# reporting the failure it was standing in the middle of: a sweep over running
# containers finds nothing wrong when there are no running containers.
#
# Nothing else on this machine owns "the stack must be up". It does now.
