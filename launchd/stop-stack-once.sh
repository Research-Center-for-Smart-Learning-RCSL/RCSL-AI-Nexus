#!/bin/bash
# Fault injection, for the second of the two repair paths that a boot has to walk.
#
# THIS IS A TEST TOOL. It deliberately takes the platform down and leaves it
# down across a reboot, so that something else has to bring it back.
#
# Why it exists. Runbook §1.1 lists six outcomes for a boot. §1.1a filled the
# `OK: all bindings restored` row on 2026-07-26 by holding `tailscaled` down at
# boot. The other valuable row — `docker did not restore the stack; bringing it
# up` → `stack up: all expected services running` — is still blank, and §1.1a
# cannot fill it: it withholds the tailnet address, not Docker Desktop's ability
# to restore containers. Only the 19:09 boot has ever produced that state, and
# that one was repaired by hand before the reconciler could do it.
#
# How this produces it. Every long-lived service in docker-compose.yml carries
# `restart: unless-stopped`, and the "unless" is the whole mechanism: a container
# that was explicitly stopped stays stopped when the daemon comes back. So
# stopping the stack and rebooting puts Docker Desktop in front of nine
# containers it will deliberately not restore, and the reconciler meets exactly
# the state the 19:09 boot left it: `docker compose ps --services --status
# running` empty, everything present, nothing running.
#
# What it proves that a hand test cannot. Running the reconciler by hand against
# a stopped stack is already recorded in the runbook and it is a different claim.
# At boot everything moves at once — Docker Desktop starting, the daemon becoming
# responsive, `tailscaled` bringing the address up, the reconciler's three
# preconditions resolving against all of it. §1.1a measured what that costs: the
# same code that settles in 16 seconds on a healthy boot took 27, and a binding
# scan that finishes inside a second took 40. A hand test cannot reproduce that.
#
# What it does not prove. That Docker Desktop's restore *fails* on its own. That
# happened once, on the 19:10 boot after the macOS 26.5.2 update, and why is
# still unproven. This injection reproduces the state, not the cause — the same
# limit §1.1a has, and the runbook says so in both places.
#
# THE RISK, AND WHY IT IS MUCH SMALLER THAN §1.1a. The platform is down from the
# moment this runs until the reconciler finishes after the next boot, so nothing
# is served in that window. But the *host* stays on the tailnet throughout: SSH
# works, `tailscale serve` works, and if the reconciler does not do its job the
# recovery is one command from anywhere:
#
#   cd ~/dev/RCSL-AI-Nexus && docker compose up -d
#
# So unlike §1.1a this does not require a person at the machine. It requires
# somebody willing to have the platform offline for a few minutes.
#
# It is self-limiting when it passes, for a different reason than §1.1a: that one
# deletes its own plist, this one is undone by the very thing it is testing. When
# it fails, it stays failed until a person acts — which is the honest shape of a
# recovery test and is why the recovery command is printed below rather than
# left to be remembered.
#
# There is no plist for this and there should not be. §1.1a needed one because
# its fault had to be injected *during* boot; this fault is set before the
# reboot and simply persists, so a boot-time job would be a moving part with
# nothing to do.
#
# Written for the bash 3.2 that macOS ships: no mapfile, no associative arrays.

set -uo pipefail

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
export DOCKER_HOST="unix:///Users/rcslmac1/.docker/run/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

RECONCILE_LOG="/opt/homebrew/var/log/nexus-reconcile.log"
RECONCILE_PLIST="/Library/LaunchDaemons/online.rcsl.reconcile-port-bindings.plist"
DELAY_PLIST="/Library/LaunchDaemons/online.rcsl.delay-tailscaled-once.plist"

# Derived from the compose file, with the literal below as the fallback — the
# same shape as reconcile-port-bindings.sh and check-platform-health.sh, and
# for the same reason they stopped keeping theirs by hand.
#
# **Keeping it by hand did not work here either, and this file was the last to
# find out.** The other two were corrected on 2026-08-04 when `parser` and
# `qdrant` turned out to have been missing from every copy since the day they
# were added; this one kept the nine-service list until 2026-08-18, while its
# own comment claimed all three were in step. What that cost is exactly the
# check this script exists to make: the precondition below asserts the platform
# is healthy before it injects a fault, and a platform with `qdrant` or
# `parser` already down would have passed it — so a recovery test could start
# from a broken stack and report success, which is the one outcome that makes
# the test worse than not running it.
EXPECTED_SERVICES="postgres redis prometheus grafana gateway admin-public admin-tailnet frontend-public frontend-tailnet parser qdrant"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

refuse() {
  log "REFUSING: $1"
  log "nothing was changed; the platform is as it was"
  exit 1
}

cd "$REPO" || refuse "cannot cd to $REPO"

# After the cd, because `docker compose config` reads the compose file from the
# working directory. `migrate` is excluded: it is the one-shot that exits 0, so
# a running check would fail on it forever.
DERIVED_SERVICES="$(docker compose config --services 2>/dev/null | grep -vx 'migrate' | tr '\n' ' ')"
if [ -n "$DERIVED_SERVICES" ]; then
  EXPECTED_SERVICES="${DERIVED_SERVICES% }"
else
  log "WARNING: could not derive the service list from docker compose config; using the built-in list"
fi
log "expecting: $EXPECTED_SERVICES"

# --- refuse to run alongside the other injector ------------------------------
#
# Both at once would take the host off the tailnet *and* leave the stack down,
# which is the one combination where the cheap recovery path for each is blocked
# by the other.

if [ -f "$DELAY_PLIST" ]; then
  refuse "$DELAY_PLIST is installed. That is §1.1a's injector, and running both
  on one boot means the host is off the tailnet with the stack down — neither
  fault's recovery path is reachable. Remove it first: sudo rm $DELAY_PLIST"
fi

# --- refuse unless the platform is healthy right now -------------------------
#
# A recovery test that starts from a broken platform proves nothing: when it
# comes back wrong there is no way to tell what this injection caused from what
# was already true. §1.1 makes the same argument for not running round two
# before round one has passed.

docker info >/dev/null 2>&1 || refuse "the docker daemon does not answer; there is nothing here to stop"

RUNNING="$(docker compose ps --services --status running 2>/dev/null)"
MISSING=""
for svc in $EXPECTED_SERVICES; do
  printf '%s\n' "$RUNNING" | grep -qx "$svc" || MISSING="$MISSING $svc"
done
[ -n "$MISSING" ] && refuse "not running right now:$MISSING. Bring the platform
  fully up before injecting a fault into it (docker compose up -d), or the result
  of the next boot cannot be attributed."

# `--status running` for the same reason the health check uses it: plain
# `docker compose ps` excludes only *stopped* containers, so a paused one would
# read as running here and this would inject a fault into a platform that was
# already degraded.

UNBOUND=""
for cid in $(docker compose ps -q 2>/dev/null); do
  req="$(docker inspect "$cid" --format '{{json .HostConfig.PortBindings}}' 2>/dev/null)"
  case "$req" in ""|"{}"|"null") continue ;; esac
  act="$(docker inspect "$cid" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null)"
  case "$act" in
    *'[]'*)
      svc="$(docker inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.service"}}' 2>/dev/null)"
      UNBOUND="$UNBOUND ${svc:-$cid}"
      ;;
  esac
done
[ -n "$UNBOUND" ] && refuse "requested a host port and did not get one:$UNBOUND.
  The platform is already in the state §1.1a tests for; repair that first."

# --- refuse unless the reconciler actually ran on this boot ------------------
#
# This is the check that matters most, and it is deliberately not "the plist
# exists". A plist on disk is a necessary condition and proves nothing about
# whether launchd loaded it; rebooting with the stack down and nothing scheduled
# to bring it up is the one way this injection turns into an outage rather than
# a test. The log answers the question that is actually being asked — did this
# daemon run on the current boot — and the answer is evidence rather than
# configuration.

[ -f "$RECONCILE_PLIST" ] || refuse "$RECONCILE_PLIST is missing. Nothing would
  bring the stack up after the reboot. Install it (runbook §7) before injecting."

BOOT_SEC="$(sysctl -n kern.boottime 2>/dev/null | sed -n 's/^{ sec = \([0-9]*\).*/\1/p')"
[ -n "$BOOT_SEC" ] || refuse "cannot read kern.boottime, so cannot tell whether
  the reconciler ran on this boot"

LAST_START="$(grep -a 'reconcile starting' "$RECONCILE_LOG" 2>/dev/null | tail -1 | awk '{print $1}')"
[ -n "$LAST_START" ] || refuse "$RECONCILE_LOG has no 'reconcile starting' line.
  The daemon has never run; do not reboot with the stack down."

LAST_SEC="$(date -j -f '%Y-%m-%dT%H:%M:%S%z' "$LAST_START" +%s 2>/dev/null)"
[ -n "$LAST_SEC" ] || refuse "cannot parse the timestamp '$LAST_START' from $RECONCILE_LOG"

if [ "$LAST_SEC" -lt "$BOOT_SEC" ]; then
  refuse "the newest 'reconcile starting' in $RECONCILE_LOG is $LAST_START, which
  is older than this boot ($(date -r "$BOOT_SEC" '+%Y-%m-%dT%H:%M:%S%z')). The
  daemon did not run on this boot, so there is no evidence it will run on the
  next one. Check: sudo launchctl print system/online.rcsl.reconcile-port-bindings"
fi

log "preconditions pass"
log "  nine expected services running, six requested bindings actual"
log "  reconciler ran $((LAST_SEC - BOOT_SEC))s into this boot ($LAST_START)"

# --- record the pre-state ----------------------------------------------------
#
# Written before the fault, because after it there is nothing left to inspect
# and "what was it before" is the first question any failure raises.

log "pre-state, requested bindings:"
for cid in $(docker compose ps -q 2>/dev/null); do
  req="$(docker inspect "$cid" --format '{{json .HostConfig.PortBindings}}' 2>/dev/null)"
  case "$req" in ""|"{}"|"null") continue ;; esac
  svc="$(docker inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.service"}}' 2>/dev/null)"
  log "  $svc $req"
done

# --- inject ------------------------------------------------------------------

log "stopping the stack — the platform is down from here until the next boot recovers it"
if ! docker compose stop 2>&1 | sed 's/^/  /'; then
  log "ERROR: docker compose stop returned non-zero; check what state the stack is in"
fi

# Read the result back rather than trusting the command. A partially stopped
# stack is the worst outcome available here: Docker would restore the ones still
# running, the reconciler would find a set that is neither empty nor complete,
# and whatever the next boot printed would be about a fault nobody designed.
STILL_RUNNING="$(docker compose ps --services --status running 2>/dev/null)"
if [ -n "$STILL_RUNNING" ]; then
  log "WARNING: still running after stop: $(printf '%s' "$STILL_RUNNING" | tr '\n' ' ')"
  log "do NOT reboot on this. Stop them by hand, or bring everything back up with"
  log "  docker compose up -d"
  log "and start over — a half-stopped stack tests a fault that was not designed."
  exit 1
fi

log "all expected services stopped"
log ""
log "now reboot, and do not touch it:"
log "  sudo reboot"
log ""
log "after the boot, read:"
log "  tail -40 $RECONCILE_LOG"
log "expecting, in this order:"
log "  not running: <the nine>"
log "  docker did not restore the stack; bringing it up"
log "  stack up: all expected services running"
log "  all published bindings intact"
log ""
log "if that does not happen, the platform stays down and the host stays reachable."
log "recover from anywhere with:"
log "  cd $REPO && docker compose up -d"

exit 0
