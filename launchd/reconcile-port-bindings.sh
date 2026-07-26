#!/bin/bash
# Make the platform be running and reachable after a boot.
#
# Two different things go wrong at boot, and this handles both. They are not
# variants of each other: one leaves the containers up and unreachable, the
# other leaves no containers at all.
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
# The second failure. Docker Desktop does not always restore the containers at
# all. On the 2026-07-26 19:10 boot — the macOS 26.5.2 update reboot — it
# restored nothing: all nine had stopped cleanly at the 19:04 shutdown, the
# engine was running again at 19:10:37, and no container was ever started.
# `restart: unless-stopped` is a promise the Docker daemon makes, and it was kept
# on the two boots before that one and broken on this one; nothing else on this
# machine ever ran `docker compose up`, so there was no second line of defence.
# Precondition 3 below is now that line.
#
# Whether the update reboot is what made the difference is unproven — the two
# boots that restored were plain reboots, which is one correlation — so nothing
# here is conditioned on it. This runs at every boot and asks only whether the
# services are running.
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

# The long-lived services: every compose service except `migrate`, which is a
# one-shot job and is correctly `Exited (0)` after a boot. Named rather than
# enumerated, for the reason precondition 3 explains: a list built from what is
# running cannot contain a service that is not running, which is the exact case
# this script now has to detect. check-platform-health.sh carries the same list
# for the same reason; a service added to docker-compose.yml has to be added to
# both or neither will notice it is gone.
EXPECTED_SERVICES="postgres redis prometheus grafana gateway admin-public admin-tailnet frontend-public frontend-tailnet"

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
INCOMPLETE=0
[ -n "$MISSING" ] && INCOMPLETE=1

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
