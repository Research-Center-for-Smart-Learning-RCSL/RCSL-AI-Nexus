#!/bin/sh
# Forward from the tailnet address to 127.0.0.1 for the three services
# whose published ports the nginx proxy reaches. Under Docker Desktop these
# bound directly to the tailnet IP; under Colima the Docker daemon runs in
# a VM that has no host interfaces, so containers bind to loopback and this
# script bridges the gap.
#
# Waits for the tailnet address to appear on an interface, then launches
# three socat instances. If one exits it is restarted; if the script is
# killed all three are cleaned up.

set -eu

# The node's own tailnet address, asked of Tailscale rather than written here:
# the repository is public. `.env`'s TAILNET_IP is not it under Colima, where
# containers bind loopback and that variable is 127.0.0.1. An explicit
# TAILNET_IP in the job's environment still wins.
TAILNET_IP="${TAILNET_IP:-}"
TAILSCALE="/opt/homebrew/bin/tailscale"
SOCAT="/opt/homebrew/bin/socat"

# gateway :8000, admin-public :8002, frontend-public :3001
FORWARDS="8000:8000 8002:8002 3001:3001"

log() { printf '%s socat-forwards: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

# Wait for the tailnet address, same as the reconciler. At boot `tailscale ip`
# fails until tailscaled is up, and the address reaches an interface later
# still, so both are inside the same 120-second wait.
waited=0
while :; do
    ip="$TAILNET_IP"
    [ -n "$ip" ] || ip="$("$TAILSCALE" ip -4 2>/dev/null | head -1)" || ip=""
    if [ -n "$ip" ] && /sbin/ifconfig 2>/dev/null | grep -q "inet ${ip} "; then
        TAILNET_IP="$ip"
        break
    fi
    if [ "$waited" -ge 120 ]; then
        log "FATAL: tailnet address ${ip:-unknown} not on any interface after 120s"
        exit 1
    fi
    sleep 2
    waited=$((waited + 2))
done
log "tailnet address ${TAILNET_IP} is up"

PIDS=""

cleanup() {
    log "shutting down"
    for pid in $PIDS; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    exit 0
}
trap cleanup INT TERM

for spec in $FORWARDS; do
    src_port="${spec%%:*}"
    dst_port="${spec##*:}"
    $SOCAT TCP4-LISTEN:"${src_port}",bind="${TAILNET_IP}",fork,reuseaddr \
           TCP4:127.0.0.1:"${dst_port}" &
    pid=$!
    PIDS="$PIDS $pid"
    log "forwarding ${TAILNET_IP}:${src_port} -> 127.0.0.1:${dst_port} (pid ${pid})"
done

# Keep running; if any socat exits, restart it.
while true; do
    new_pids=""
    i=0
    for spec in $FORWARDS; do
        i=$((i + 1))
        pid=$(echo "$PIDS" | awk "{print \$$i}")
        if ! kill -0 "$pid" 2>/dev/null; then
            src_port="${spec%%:*}"
            dst_port="${spec##*:}"
            log "restarting forward ${TAILNET_IP}:${src_port} -> 127.0.0.1:${dst_port}"
            $SOCAT TCP4-LISTEN:"${src_port}",bind="${TAILNET_IP}",fork,reuseaddr \
                   TCP4:127.0.0.1:"${dst_port}" &
            pid=$!
        fi
        new_pids="$new_pids $pid"
    done
    PIDS="$new_pids"
    sleep 5
done
