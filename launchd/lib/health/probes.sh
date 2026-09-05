# Sourced stage: probes.
probe() {
  # $1 url, $2 label, $3 expected code
  local code
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$1" 2>/dev/null)"
  if [ "$code" != "$3" ]; then
    fail "probe:$2" "$2 ($1) returned $code, expected $3."
  fi
}

if [ -n "$TAILNET_IP" ]; then
  probe "http://$TAILNET_IP:8000/readyz"  "gateway"          200
  probe "http://$TAILNET_IP:8002/readyz"  "admin-public"     200
  probe "http://$TAILNET_IP:3001/"        "frontend-public"  200
fi
probe "http://127.0.0.1:8001/readyz" "admin-tailnet"    200
probe "http://127.0.0.1:3000/"       "frontend-tailnet" 200
probe "http://127.0.0.1:3002/login"  "grafana"          200

# --- 7. Ollama is up and still only on loopback -----------------------------
#
# Two assertions, not one. That it answers is availability; that it does not
# answer on the tailnet address is security.md 7.1, and it is worth re-checking
# rather than assuming because the value that keeps it on loopback lives in a
# plist that an ollama upgrade could replace.

OLLAMA_LOOPBACK="$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:11434/api/tags 2>/dev/null)"
if [ "$OLLAMA_LOOPBACK" != "200" ]; then
  fail "ollama" "Ollama did not answer on 127.0.0.1:11434 (got $OLLAMA_LOOPBACK). Inference is down; the gateway's /readyz runtime check will follow."
fi
if [ -n "$TAILNET_IP" ]; then
  OLLAMA_TAILNET="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$TAILNET_IP:11434/api/tags" 2>/dev/null)"
  if [ "$OLLAMA_TAILNET" = "200" ]; then
    fail "ollama-exposed" "Ollama is answering on $TAILNET_IP:11434. It must bind loopback only (security.md 7.1) — OLLAMA_HOST has been lost, most likely by an upgrade replacing online.rcsl.ollama.plist."
  fi
fi

# --- 8. the host metrics daemon, and the host figures it serves -------------
#
# online.rcsl.host-metrics reports the Mac's memory and disk over loopback
# because a container on macOS cannot see either — it would describe the Linux
# VM. Nothing watched it until 2026-08-04, and its log is a wall of
# `OSError: [Errno 48] Address already in use`: KeepAlive restarts it faster than
# the old socket is released, so it recovers on its own and the front end's host
# panel goes blank for a few seconds. A permanent failure would look identical
# and nothing would say so.
#
# Reading it here does two jobs — it is the liveness check for that daemon, and
# it is where the disk and memory numbers come from. `df` on the host would be
# the obvious alternative and would be wrong: on macOS `/` is the read-only
# system volume and reports about 12 GiB used of 3.6 TiB forever, no matter how
# full the machine actually is. host-metrics.py already uses statfs, which
# answers for the whole APFS container.

HOST_JSON="$(curl -s -m 5 http://127.0.0.1:9101/host 2>/dev/null)"
if [ -z "$HOST_JSON" ]; then
  fail "host-metrics" "The host metrics daemon did not answer on 127.0.0.1:9101/host. The front end's host panel is blind, and the disk and memory checks below could not run. See $(dirname "$HEALTH_LOG")/nexus-host-metrics.log."
else
  HOST_PARSED="$(printf '%s' "$HOST_JSON" | /usr/bin/python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
disk = d.get("disk") or {}
mem = d.get("memory") or {}
# host-metrics.py returns null for any figure it could not read — vm_stat
# unparseable, `sysctl vm.swapusage` failing. Rendering null the default way
# puts the literal string "None" into an awk numeric comparison, where
# strnum rules compare it as a string: "None" >= "8" is true, so a broken swap
# reading would warn about swap, and "None" < "4" is false, so a broken memory
# reading would silently suppress a real low-memory warning. Empty is the only
# honest rendering of "not answered", and the callers already treat it as
# unknown.
def num(v):
    return "" if v is None else v

total, free = disk.get("total_gb"), disk.get("free_gb")
pct = "" if not total or free is None else round((total - free) * 100.0 / total, 1)
print(pct)
print(num(mem.get("available_gb")))
print(num(mem.get("swap_used_gb")))
' 2>/dev/null)"
  if [ -z "$HOST_PARSED" ]; then
    fail "host-metrics" "The host metrics daemon answered on 127.0.0.1:9101/host but the reply did not parse as the expected JSON. The shape it serves has changed, or something else is listening on that port."
  else
    DISK_PCT="$(printf '%s\n' "$HOST_PARSED" | sed -n '1p')"
    MEM_AVAIL="$(printf '%s\n' "$HOST_PARSED" | sed -n '2p')"
    SWAP_USED="$(printf '%s\n' "$HOST_PARSED" | sed -n '3p')"

    if [ -n "$DISK_PCT" ]; then
      if awk -v v="$DISK_PCT" -v t="$DISK_FAIL_PCT" 'BEGIN{exit !(v>=t)}'; then
        fail "disk" "The host volume is ${DISK_PCT}% full (threshold ${DISK_FAIL_PCT}%). Postgres goes read-only when it fills, so this is hours away from an outage, not a chore."
      elif awk -v v="$DISK_PCT" -v t="$DISK_WARN_PCT" 'BEGIN{exit !(v>=t)}'; then
        warn "host disk ${DISK_PCT}% full (warn at ${DISK_WARN_PCT}%, fail at ${DISK_FAIL_PCT}%)"
      fi
    fi
    if [ -n "$MEM_AVAIL" ] && awk -v v="$MEM_AVAIL" -v t="$MEM_AVAIL_WARN_GB" 'BEGIN{exit !(v<t)}'; then
      warn "only ${MEM_AVAIL} GB memory available (warn under ${MEM_AVAIL_WARN_GB} GB); a large model resident in Ollama is the usual cause"
    fi
    if [ -n "$SWAP_USED" ] && awk -v v="$SWAP_USED" -v t="$SWAP_WARN_GB" 'BEGIN{exit !(v>=t)}'; then
      warn "${SWAP_USED} GB of swap in use (warn at ${SWAP_WARN_GB} GB); inference latency degrades badly once the machine swaps"
    fi
  fi
fi

# --- 9. the disk the containers actually write to ---------------------------
#
# Not the same volume as check 8 and not derivable from it. Colima keeps a
# virtual disk with its own size, and Postgres filling that VM disk while the
# Mac has terabytes free is a real and unremarkable way for this to fail.

if [ "$DOCKER_UP" -eq 1 ] && running_p postgres; then
  DOCKER_DISK_PCT="$(run_timeout 20 docker compose exec -T postgres df -P /var/lib/postgresql/data 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')"
  case "$DOCKER_DISK_PCT" in
    ''|*[!0-9]*) DOCKER_DISK_PCT="" ;;
    *)
      if [ "$DOCKER_DISK_PCT" -ge "$DISK_FAIL_PCT" ]; then
        fail "docker-disk" "The Docker VM disk is ${DOCKER_DISK_PCT}% full (threshold ${DISK_FAIL_PCT}%). This is the volume Postgres, Qdrant and the document store write to; the Mac having free space is irrelevant to it."
      elif [ "$DOCKER_DISK_PCT" -ge "$DISK_WARN_PCT" ]; then
        warn "Docker VM disk ${DOCKER_DISK_PCT}% full (warn at ${DISK_WARN_PCT}%, fail at ${DISK_FAIL_PCT}%)"
      fi
      ;;
  esac
fi

# --- 10. reclaimable Docker space -------------------------------------------
#
# Housekeeping, and the reason it is tier 2: build cache is reclaimable by
# definition, so this is never an emergency until check 9 makes it one.

if [ "$DOCKER_UP" -eq 1 ]; then
  RECLAIM_GB="$(run_timeout 20 docker system df --format '{{json .}}' 2>/dev/null | /usr/bin/python3 -c '
import json, re, sys
units = {"B": 1e-9, "KB": 1e-6, "MB": 1e-3, "GB": 1.0, "TB": 1000.0}
total = 0.0
seen = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        row = json.loads(line)
    except Exception:
        continue
    m = re.match(r"([0-9.]+)\s*([KMGT]?B)", str(row.get("Reclaimable", "")))
    if m:
        seen = True
        total += float(m.group(1)) * units.get(m.group(2), 0.0)
print(round(total, 1) if seen else "")
' 2>/dev/null)"
  if [ -n "$RECLAIM_GB" ] && awk -v v="$RECLAIM_GB" -v t="$DOCKER_RECLAIM_WARN_GB" 'BEGIN{exit !(v>=t)}'; then
    warn "${RECLAIM_GB} GB of Docker space is reclaimable (warn at ${DOCKER_RECLAIM_WARN_GB} GB); mostly build cache, \`docker builder prune\` frees it"
  fi
fi

# --- 11. Prometheus is scraping, and what it scraped ------------------------
#
# The monitoring system is a thing that can fail, and until 2026-08-04 nothing
# asked whether it was working: it published no host port, had no alert rules,
# and Grafana had no contact point, so every metric it collected was visible
# only to somebody who opened a dashboard. `up == 0` is Prometheus's own answer
# to "am I able to scrape this target", which is a different question from check
# 4 (is the container running) and check 6 (does the entrance answer) — a target
# can be up and serving while its /metrics bearer token is wrong.
#
# Queried over `docker compose exec` rather than a published port, because
# Prometheus deliberately publishes none.
