#!/bin/bash
# Make the platform be running and reachable after a boot.
#
# Under Colima (2026-09-05+) the port binding race is gone — containers bind
# to 127.0.0.1, so binding never fails. The remaining job is the second
# failure below: Docker sometimes does not restore containers at all.
#
# History (Docker Desktop, pre-2026-09-05). Two different things went wrong at
# boot. The first — port binding race — is structurally eliminated by Colima.
# The second — unrestored containers — can still happen under any Docker daemon.
#
# First failure (historical). Docker Desktop restored containers before
# `tailscaled` had put the tailnet address on utun0, so the port forwards that
# named that address failed. Observed on 2026-07-26. Eliminated by moving all
# containers to 127.0.0.1 and using socat for the tailnet IP forwarding.
#
# Second failure (still relevant). The Docker daemon does not always restore
# containers. On the 2026-07-26 19:10 boot — the macOS 26.5.2 update reboot —
# it restored nothing: all nine had stopped cleanly at shutdown, the engine was
# running again, and no container was ever started. `restart: unless-stopped` is
# a promise the Docker daemon makes, and it was broken on that boot. Precondition
# 3 below is the second line of defence.
#
# This runs at every boot and asks only whether the services are running.
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
export DOCKER_HOST="unix:///Users/rcslmac1/.colima/default/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Bounded: Colima's VM startup is the slow part. Give up rather than hang
# forever, so a failure appears in the log as a failure.
DEADLINE=$((SECONDS + 600))

# The long-lived services: every compose service except `migrate`, which is a
# one-shot job and is correctly `Exited (0)` after a boot. Named rather than
# enumerated, for the reason precondition 3 explains: a list built from what is
# running cannot contain a service that is not running, which is the exact case
# this script now has to detect.
#
# Derived from the compose file, with the literal below as the fallback. Keeping
# it by hand did not work: `parser` and `qdrant` were missing from it from the
# day they were added to docker-compose.yml until 2026-08-04, and this list
# drives both the settle precondition and the `docker compose up -d` repair. On
# a boot where Docker restores nothing — the 2026-07-26 19:10 path, which is the
# whole reason the repair branch exists — those two would have been left down
# while this script logged `all expected services running` and exited 0. The
# component whose job is the repair was structurally blind to a third of what it
# was repairing, which is this document's recurring defect in the list the
# argument about that defect is about.
#
# check-platform-health.sh derives its copy the same way and for the same reason.
EXPECTED_SERVICES="postgres redis prometheus grafana gateway admin-public admin-tailnet frontend-public frontend-tailnet parser qdrant"

# Ordered stages; each is sourced so exit codes and shared state remain unchanged.
. "$REPO/launchd/lib/reconcile/service_discovery.sh"
. "$REPO/launchd/lib/reconcile/expected_bindings.sh"
. "$REPO/launchd/lib/reconcile/broken_services.sh"
. "$REPO/launchd/lib/reconcile/repair.sh"
