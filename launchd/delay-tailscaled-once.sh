#!/bin/bash
# Fault injection, for the one acceptance outcome that cannot be produced on demand.
#
# THIS IS A TEST TOOL. It is not part of the running platform and must not be
# left installed. It holds this machine off the tailnet for ninety seconds at
# boot, on purpose.
#
# Why it exists. runbook §1.1 lists six outcomes for a boot, and the valuable one
# — `OK: all bindings restored`, the binding repair path actually walking at boot
# — has been blank for seven boots. It needs a boot on which Docker Desktop binds
# its port forwards *before* `tailscaled` has put the tailnet address on utun0,
# and that is a race nobody controls. The runbook's lever for it was "reboot twice
# and watch the second", because a boot that loads the netmap disk cache does not
# rewrite it and hands the next boot the slow path. Seven boots of measurement
# show the lever cannot win:
#
#   Docker binds 10.3 to 14 seconds after tailscaled starts (six observations).
#   Cache-miss boots put the address up at 9 seconds (three observations, no
#   spread at all). The 17-second address that produced the one real failure, on
#   2026-07-26 16:45, has not recurred in six boots.
#
# So the budget is about 1.3 seconds and it has never gone negative on demand.
# Rebooting repeatedly is not a test, it is waiting for weather. This makes the
# weather instead: hold the address back long enough that Docker cannot win, and
# the reconciler has to do the thing it was written for.
#
# It has been run once, on 2026-07-26 at 21:02, and it worked on the first pull.
# Docker bound at 21:02:56, seventy-eight seconds before the address existed, and
# failed on exactly the three services that name it; the reconciler logged
# `OK: all bindings restored` at 21:05:31 and the full check passed afterwards.
# Runbook §1.1a carries the record, including the two costs only a boot reveals:
# the reconciler's named-set precondition took 27 seconds against a stable 16 on
# healthy boots, and its binding scan took 40 against under one.
#
# What it proves that a hand test cannot. Stopping a container and running the
# reconciler by hand is already recorded in the runbook, and it is a different
# claim. At boot everything moves at once — Docker Desktop restoring containers,
# the daemon becoming responsive, the address arriving, the reconciler's three
# preconditions resolving against all of it. The hand test cannot produce that,
# which is why §1.1 still counts those two outcomes as blank.
#
# THE RISK, STATED PLAINLY. While the hold is on, this machine is off the tailnet:
# no Tailscale SSH, no `tailscale serve`, no way in from anywhere. The Mac Studio
# has no out-of-band management (runbook, "why a person has to be present"), so
# **run this only with physical access to the machine**. The release below runs
# from a trap and covers a normal exit, SIGTERM, SIGINT and SIGHUP. It cannot
# cover SIGKILL. If this process is SIGKILLed mid-hold, tailscaled stays down
# until something starts it, and the recovery is one command at the machine:
#
#   sudo launchctl bootstrap system /Library/LaunchDaemons/homebrew.mxcl.tailscale.plist
#
# A plain reboot also fixes it, because the first thing this script does is delete
# its own plist. Whatever else happens, it affects exactly one boot.
#
# It does not touch tailscale's preferences. `bootout` and `bootstrap` restart the
# daemon and it comes back with the prefs on disk — the same thing a reboot does.
# `tailscale down` / `tailscale up` was the other candidate and was rejected: `up`
# can reset prefs that were not named on the command line, and the prefs here
# include Tailscale SSH, which is the remote access path.
#
# Written for the bash 3.2 that macOS ships.

set -uo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

LABEL="online.rcsl.delay-tailscaled-once"
SELF_PLIST="/Library/LaunchDaemons/$LABEL.plist"

TS_LABEL="homebrew.mxcl.tailscale"
TS_PLIST="/Library/LaunchDaemons/$TS_LABEL.plist"
TS_TARGET="system/$TS_LABEL"

# Ninety seconds. Docker Desktop's first `exposer.Add` has landed 10.3 to 14
# seconds after tailscaled starts on every boot where it bound at all, so this is
# roughly six times the margin it needs to lose by. It is also well inside the
# reconciler's ten-minute deadline, which starts at its own launch a few seconds
# into the boot: after the release the address takes about ten seconds to appear,
# leaving the reconciler around eight minutes it will not need.
HOLD=90

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

# Delete the plist before anything else. This is what bounds the blast radius to
# one boot, so it happens before the first thing that can fail.
if rm -f "$SELF_PLIST" 2>/dev/null; then
  log "removed $SELF_PLIST — this affects this boot only"
else
  log "WARNING: could not remove $SELF_PLIST; remove it by hand or every boot will do this"
fi

if [ ! -f "$TS_PLIST" ]; then
  log "FATAL: $TS_PLIST does not exist; refusing to stop something I cannot start again"
  exit 1
fi

# Read from the same .env the reconciler and compose read, so the address this
# reports on cannot drift from the one they use. Read before the trap is armed:
# the release path below refers to it, and a trap that fires on an unset variable
# under `set -u` would be a recovery path that fails while recovering.
TAILNET_IP="$(sed -n 's/^TAILNET_IP=//p' /Users/rcslmac1/dev/RCSL-AI-Nexus/.env 2>/dev/null | head -1 | tr -d '"'\''[:space:]')"
if [ -z "$TAILNET_IP" ]; then
  log "FATAL: TAILNET_IP is not set; not injecting a fault I cannot describe"
  exit 1
fi

RELEASED=0
release() {
  [ "$RELEASED" -eq 1 ] && return
  RELEASED=1
  log "releasing tailscaled"
  launchctl bootstrap system "$TS_PLIST" 2>&1 | sed 's/^/  /'
  # Report the address coming back rather than assuming it. This is the line that
  # says the machine is reachable again.
  #
  # Elapsed seconds, measured — not the loop counter. The first version logged
  # `i * 5`, which charges the sleep that comes *after* each check to the check
  # itself and so overstates by a whole poll interval before granularity is even
  # considered. On the 2026-07-26 21:02 injection it printed "within 10s" for an
  # address the reconciler had independently seen at +1s: 5 seconds of off-by-one
  # on top of 5 seconds of polling. That is this repository's recurring defect
  # landing on the one line whose entire job is to be a number, in the tool whose
  # entire job is measurement. Polling is every second for the same reason.
  local start=$SECONDS
  while [ $((SECONDS - start)) -lt 60 ]; do
    if ifconfig 2>/dev/null | grep -qw "$TAILNET_IP"; then
      log "tailnet address $TAILNET_IP is back $((SECONDS - start))s after the release"
      return
    fi
    sleep 1
  done
  log "WARNING: $TAILNET_IP did not come back within 60s of the release"
  log "recover at the machine: sudo launchctl bootstrap system $TS_PLIST"
}
trap release EXIT INT TERM HUP

log "holding tailscaled down for ${HOLD}s so Docker binds before $TAILNET_IP exists"

# A loop, not a single bootout. launchd may not have brought tailscaled up yet
# when this first runs — both are RunAtLoad daemons and their order is not
# defined — and a bootout against a job that is not loaded does nothing. Knocking
# it down every two seconds covers that race and also covers KeepAlive, which is
# true on the tailscale job.
END=$((SECONDS + HOLD))
while [ "$SECONDS" -lt "$END" ]; do
  launchctl bootout "$TS_TARGET" >/dev/null 2>&1
  sleep 2
done

log "hold over"
release
trap - EXIT INT TERM HUP

log "done — now read /opt/homebrew/var/log/nexus-reconcile.log"
log "expecting: 'recreating: ...' then 'OK: all bindings restored'"
exit 0
