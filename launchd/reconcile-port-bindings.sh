#!/bin/bash
# Re-establish the published port bindings that Docker Desktop drops at boot.
#
# Why this exists. Docker Desktop restores containers before `tailscaled` has
# put the tailnet address on utun0, so the port forwards that name that address
# fail with `bind: can't assign requested address`. The backend logs one warning
# and does not retry. The containers stay up and healthy, `restart:
# unless-stopped` never fires because nothing exited, and the platform is
# unreachable from the tailnet with nothing anywhere saying so. Observed on the
# 2026-07-26 reboot: gateway, admin-public and frontend-public all lost their
# bindings 21 seconds after boot, while SSH and the `tailscale serve` entrance
# kept working, so every way an operator would casually check looked healthy.
#
# Why it recreates rather than restarts. The forward is created when the
# container is created, not when it starts. `docker compose up -d` is a no-op
# against a container already running with a matching config, and `docker
# compose restart` reuses the container and leaves the backend's forwarding
# table untouched. Both were tried on this machine and neither restored a
# binding; only `--force-recreate` did.
#
# It waits for its preconditions rather than racing them.
#
# Written for the bash 3.2 that macOS ships: no mapfile, no associative arrays.

set -uo pipefail

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
export DOCKER_HOST="unix:///Users/rcslmac1/.docker/run/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Bounded: Docker Desktop's own startup is the slow part. Give up rather than
# hang forever, so a failure appears in the log as a failure.
DEADLINE=$((SECONDS + 600))

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

log "reconcile starting"

cd "$REPO" || { log "FATAL: cannot cd to $REPO"; exit 1; }

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

# Precondition 2: the docker daemon answers. Docker Desktop needs the logged-in
# session that automatic login provides; if that link of the chain broke, this
# is where it surfaces, instead of failing obscurely further on.
while ! docker info >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    log "FATAL: timed out waiting for the docker daemon"
    exit 1
  fi
  sleep 5
done
log "docker daemon responding"

# Precondition 3: Docker Desktop has finished restoring containers.
#
# The daemon answers well before the last container is back, and at boot it
# restores them one at a time. Checking then would enumerate only the containers
# that had already returned, find their bindings intact, and exit reporting
# success while the ones still to come — possibly the broken ones — were never
# looked at. That is the same shape of error as trusting `up -d` to rebuild a
# forward: a check whose timing lets it produce only one answer.
#
# So wait for the count to stop moving rather than for a fixed delay, which
# would be another guess.
STABLE_COUNT=-1
SETTLE=0
while :; do
  COUNT="$(docker compose ps -q 2>/dev/null | grep -c .)"
  if [ "$COUNT" -gt 0 ] && [ "$COUNT" -eq "$STABLE_COUNT" ]; then
    SETTLE=$((SETTLE + 1))
    # Two consecutive matching samples, ten seconds apart.
    [ "$SETTLE" -ge 2 ] && break
  else
    SETTLE=0
  fi
  STABLE_COUNT="$COUNT"
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    log "WARNING: container count never settled (last: $COUNT); checking anyway"
    break
  fi
  sleep 5
done
log "container set settled at $STABLE_COUNT running"

# A container is broken when it asked for a host binding and did not get one:
# HostConfig.PortBindings is non-empty while the matching NetworkSettings.Ports
# entry is an empty list. That signature is exactly the dropped forward, and it
# separates those containers from the ones that never published a port at all
# (whose Ports entries are null, not []).
#
# Prints one compose service name per line on stdout; commentary goes to stderr
# so the caller can capture the list cleanly.
broken_services() {
  local cid req act svc name
  for cid in $(docker compose ps -q 2>/dev/null); do
    req="$(docker inspect "$cid" --format '{{json .HostConfig.PortBindings}}' 2>/dev/null)"
    if [ -z "$req" ] || [ "$req" = "{}" ] || [ "$req" = "null" ]; then
      continue
    fi
    act="$(docker inspect "$cid" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null)"
    case "$act" in
      *'[]'*)
        svc="$(docker inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.service"}}' 2>/dev/null)"
        name="$(docker inspect "$cid" --format '{{.Name}}' 2>/dev/null)"
        log "  dropped binding: ${name:-$cid} requested $req" >&2
        [ -n "$svc" ] && printf '%s\n' "$svc"
        ;;
    esac
  done
}

BROKEN="$(broken_services)"

if [ -z "$BROKEN" ]; then
  log "all published bindings intact; nothing to do"
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
  exit 0
fi

log "STILL UNBOUND after recreate: $(printf '%s' "$STILL" | tr '\n' ' ')"
log "this has a cause a recreate cannot fix; investigate rather than retry"
exit 1
