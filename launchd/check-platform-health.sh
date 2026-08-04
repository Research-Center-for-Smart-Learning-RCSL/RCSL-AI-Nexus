#!/bin/bash
# Watch for the platform being up but not serving, and mail when that changes.
#
# Why this exists. On 2026-07-26 the first reboot left nine containers running,
# the gateway reporting `healthy`, and four of six published ports unbound. The
# platform was unreachable from the tailnet and nothing anywhere said so: SSH
# worked, `tailscale serve` worked, `docker compose ps` looked perfect. It was
# found because a person sat and read four logs. `reconcile-port-bindings.sh`
# now repairs that at boot, but a repair that fails, or a daemon that never runs,
# would land in exactly the same silence. This closes that: the state is checked
# on an interval and a change is mailed out.
#
# What it can and cannot see. It runs on the machine it watches, so it reports
# "up but not serving" — the observed failure — and cannot report "the machine is
# off". The daily heartbeat below is what covers that: if the mail stops arriving,
# something is wrong even though no alert was sent. Silence is only evidence when
# something is expected to break it.
#
# Every check is written so it can produce more than one answer. The service
# check compares against an expected list rather than enumerating what happens to
# be running, because a container that is simply gone would otherwise not appear
# in the enumeration and the sweep would report success. That is the same error
# the reconciler's third precondition exists for, and the same one that made
# `tailscale status --json` answer "no SSH host keys" to a question it did not
# have a field for.
#
# Written for the bash 3.2 that macOS ships: no mapfile, no associative arrays.

set -uo pipefail

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
export DOCKER_HOST="unix:///Users/rcslmac1/.docker/run/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Where the alerts go. Not a secret; kept here so it is reviewable in git rather
# than sitting in an untracked file nobody reads. Space-separated: each address
# gets its own envelope recipient, and the To: header is built from the same list
# below so what the mail says and what the envelope does cannot drift apart.
ALERT_TO="leolove3very@gmail.com shaniawang06@gmail.com"

# The sending account and its app password. Two files, following the one-file-per
# -credential convention in secrets/README.md. Gmail requires the envelope sender
# to be the account that authenticates, so both come from the same pair.
ACCOUNT_FILE="$REPO/secrets/alert_smtp_account"
PASSWORD_FILE="$REPO/secrets/alert_smtp_password"
SMTP_URL="smtps://smtp.gmail.com:465"

# The state file is also the liveness record: its mtime is the last run. The log
# carries only events, so an empty log means "nothing happened", and "did this
# ever run" is answered here instead. A log that is quiet for both reasons would
# be the ambiguity this whole script exists to remove.
STATE_FILE="/opt/homebrew/var/nexus-health.state"

# Long-lived services, which is every compose service except `migrate`. `migrate`
# is a one-shot job and is correctly `Exited (0)` after a boot; treating it as
# expected-running would alert on every reboot forever.
#
# `parser` and `qdrant` were missing from this list until 2026-08-04, so either
# could have stopped without the sweep noticing — the list is compared against,
# and a service absent from it is a service nothing asks about. That is the
# enumeration error the header above argues against, in the list the argument
# is about. Anything added to docker-compose.yml belongs here on the same day.
EXPECTED_SERVICES="postgres redis prometheus grafana gateway admin-public admin-tailnet frontend-public frontend-tailnet parser qdrant"

# Boot grace. The reconciler owns the first minutes: it waits for the tailnet
# address, the daemon, and the container set to settle, which can legitimately
# take a couple of minutes. Alerting inside that window would mail out a failure
# that is about to be repaired, and the first thing anyone would learn is to
# ignore the alerts.
#
# 240 rather than 300, and the difference is the whole point. The plist fires
# this every 300 seconds, so a grace of 300 puts the first post-boot run exactly
# on the boundary: whether it evaluates or is skipped comes down to how many
# seconds launchd took to load the job. Either answer is defensible; a coin flip
# between them is not, because it decides whether the first real check of a boot
# happens at five minutes or at ten. 240 is below the interval by a clear margin,
# so the boot-time run (RunAtLoad, added with this) is suppressed and every
# scheduled run after it evaluates.
#
# This value had never once been read. `sysctl -n kern.boottime` prints
# `{ sec = 1785068938, usec = 428375 } ...` and the expression that parsed it was
# `s/.*sec = \([0-9]*\).*/\1/`, whose leading `.*` is greedy and therefore matched
# through to `usec`. BOOT_SEC was the microseconds field, uptime came out as the
# whole Unix epoch, and the comparison below could only ever say "not in grace" —
# the same defect this repository keeps finding, in the check whose entire job was
# to have two answers. It also put a nine-digit `uptime` line in every alert mail
# sent before 2026-07-26 20:45. The anchor is what fixes it: the field wanted is
# the one at the start of the line.
BOOT_GRACE=240

HEARTBEAT_INTERVAL=86400

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

FAILURES=""
DETAIL=""

fail() {
  # $1 short id used for the change signature, $2 human line for the mail body.
  FAILURES="$FAILURES$1
"
  DETAIL="$DETAIL$2
"
}

# --- the previous state -----------------------------------------------------
#
# Read here, above the grace check, because that check exits early and still has
# to leave the state file rewritten. The file's mtime is the only record that
# this ran at all, and the runbook's acceptance criterion reads it as one: "mtime
# is under five minutes old". A path that exits without touching it makes that
# criterion false while nothing is wrong.

PREV_SIGNATURE=""
PREV_HEARTBEAT=0
if [ -f "$STATE_FILE" ]; then
  PREV_SIGNATURE="$(sed -n '1p' "$STATE_FILE")"
  PREV_HEARTBEAT="$(sed -n '2p' "$STATE_FILE")"
  case "$PREV_HEARTBEAT" in ''|*[!0-9]*) PREV_HEARTBEAT=0 ;; esac
fi

# --- boot grace -------------------------------------------------------------
#
# The anchored `^{ sec = ` is load-bearing; see BOOT_GRACE above for what the
# unanchored version did.

BOOT_SEC="$(sysctl -n kern.boottime 2>/dev/null | sed -n 's/^{ sec = \([0-9]*\).*/\1/p')"
NOW="$(date +%s)"
if [ -n "$BOOT_SEC" ]; then
  UP=$((NOW - BOOT_SEC))
  if [ "$UP" -lt "$BOOT_GRACE" ]; then
    # Rewrite the previous state verbatim rather than exiting silently. The
    # signature is unchanged because nothing was checked, so this claims nothing
    # and cannot mail; the only thing it changes is the mtime, which is exactly
    # the claim being made — "this ran, and deliberately asserted nothing".
    #
    # Before this, the first five and a half minutes of every boot had no run at
    # all: the plist was RunAtLoad=false with a 300-second interval, so the
    # earliest write was the first scheduled fire. The runbook tells the operator
    # to wait two or three minutes after a reboot and then check that the mtime is
    # under five minutes old, and in that window the newest mtime available was
    # from before the boot — between three and eight minutes old depending only on
    # where the reboot fell in the previous interval. The criterion passed or
    # failed by timing, on a healthy machine. Observed on the 2026-07-26 20:24 and
    # 20:29 reboots, which were 4m37s apart: no run happened across either of
    # them, and the 20:26 check passed with thirteen seconds to spare.
    #
    # If the file did not exist, this writes an empty signature line, which is the
    # same "no previous state" sentinel an absent file produces — so the first
    # real run still mails `baseline` and not a false `recovered`.
    mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
    printf '%s\n%s\n' "$PREV_SIGNATURE" "$PREV_HEARTBEAT" > "$STATE_FILE"
    exit 0
  fi
else
  UP=-1
fi

# --- 1. configuration -------------------------------------------------------

cd "$REPO" 2>/dev/null || { log "FATAL: cannot cd to $REPO"; exit 1; }

TAILNET_IP="$(sed -n 's/^TAILNET_IP=//p' .env 2>/dev/null | head -1 | tr -d '"'\''[:space:]')"
if [ -z "$TAILNET_IP" ]; then
  fail "config" "TAILNET_IP is not set in $REPO/.env, so nothing below could be checked against the right address."
fi

# --- 2. the tailnet address is on an interface ------------------------------

if [ -n "$TAILNET_IP" ] && ! ifconfig 2>/dev/null | grep -qw "$TAILNET_IP"; then
  fail "tailnet" "$TAILNET_IP is not on any interface. tailscaled is down or has not brought utun0 up; every tailnet-facing binding depends on this."
fi

# --- 3. the docker daemon answers -------------------------------------------

DOCKER_UP=1
if ! docker info >/dev/null 2>&1; then
  DOCKER_UP=0
  fail "docker" "The docker daemon does not answer. Docker Desktop needs the logged-in session that automatic login provides, so this is also where a broken automatic login surfaces."
fi

# --- 4. every expected service is running -----------------------------------
#
# Compared against the list above rather than against whatever `ps` returns, so
# a container that is entirely gone is a failure and not an absence.
#
# `--status running` is load-bearing. `docker compose ps` without it excludes
# only *stopped* containers — `--all` is documented as adding those — so paused,
# restarting and created ones are listed, and this check would have counted them
# as running. Not hypothetical on this machine: Docker Desktop's Resource Saver
# pauses containers, and the 2026-07-26 19:04 shutdown path issued an `/unpause`,
# so it had done it. `postgres`, `redis` and `prometheus` have no probe in check
# 6, which makes this their only coverage: paused, they would have been silent
# here and silent everywhere. The reconciler already asked the question this way;
# the two now agree.

if [ "$DOCKER_UP" -eq 1 ]; then
  RUNNING="$(docker compose ps --services --status running 2>/dev/null)"
  MISSING=""
  for svc in $EXPECTED_SERVICES; do
    if ! printf '%s\n' "$RUNNING" | grep -qx "$svc"; then
      MISSING="$MISSING $svc"
    fi
  done
  if [ -n "$MISSING" ]; then
    fail "services" "Not running:$MISSING. Expected all of: $EXPECTED_SERVICES (migrate is excluded; it is a one-shot job and Exited (0) is correct)."
  fi
fi

# --- 5. requested bindings are actual bindings ------------------------------
#
# The 2026-07-26 failure exactly: HostConfig.PortBindings asks for a host port
# and NetworkSettings.Ports has an empty list for it. A service that publishes
# nothing has null there, not [], so the two cases do not blur.

if [ "$DOCKER_UP" -eq 1 ]; then
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
  if [ -n "$UNBOUND" ]; then
    fail "bindings" "Requested a host port and did not get one:$UNBOUND. This is the state where containers are Up and healthy and the platform is unreachable. The reconciler should have repaired it at boot; check /opt/homebrew/var/log/nexus-reconcile.log."
  fi
fi

# --- 6. the entrances answer over their published ports ---------------------
#
# The only checks here that cross a published binding, which is why they are not
# redundant with 5: they are what an actual caller experiences. Kept to the
# unauthenticated endpoints, so no credential is needed to run this.

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

# --- decide, and mail only on a change --------------------------------------

if [ -z "$FAILURES" ]; then
  SIGNATURE="OK"
else
  SIGNATURE="$(printf '%s' "$FAILURES" | sort | tr '\n' ',')"
fi

# PREV_SIGNATURE and PREV_HEARTBEAT were read above the grace check, which needs
# them to rewrite the file on its way out.

HOST="$(hostname -s)"
SEND=0
SUBJECT=""
KIND=""

if [ "$SIGNATURE" != "$PREV_SIGNATURE" ]; then
  SEND=1
  if [ -z "$PREV_SIGNATURE" ] && [ "$SIGNATURE" = "OK" ]; then
    # First run ever. Reporting this as a recovery would claim a failure that
    # never happened; it is a baseline, and it doubles as proof the mail path
    # works, which is the one part of this that cannot be tested by watching.
    KIND="baseline"
    SUBJECT="[nexus] monitoring started on $HOST, all checks pass"
  elif [ "$SIGNATURE" = "OK" ]; then
    KIND="recovered"
    SUBJECT="[nexus] RECOVERED on $HOST"
  else
    KIND="failing"
    SUBJECT="[nexus] FAILING on $HOST: $(printf '%s' "$FAILURES" | tr '\n' ' ')"
  fi
elif [ "$SIGNATURE" = "OK" ] && [ $((NOW - PREV_HEARTBEAT)) -ge "$HEARTBEAT_INTERVAL" ]; then
  SEND=1
  KIND="heartbeat"
  SUBJECT="[nexus] OK on $HOST"
fi

# Any mail resets the heartbeat clock, not just a heartbeat mail. Otherwise a
# recovery would be followed immediately by a redundant "OK" the moment the old
# timestamp aged out, which is the shape that teaches people to filter the alerts.
HEARTBEAT="$PREV_HEARTBEAT"
if [ "$SEND" -eq 1 ] || [ "$PREV_HEARTBEAT" -eq 0 ]; then
  HEARTBEAT="$NOW"
fi

# Written before the mail is attempted, so a broken mail path cannot turn one
# state change into an alert on every interval.
mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
printf '%s\n%s\n' "$SIGNATURE" "$HEARTBEAT" > "$STATE_FILE"

if [ "$SEND" -eq 0 ]; then
  exit 0
fi

log "$KIND: $SIGNATURE"

# --- send -------------------------------------------------------------------

if [ ! -r "$ACCOUNT_FILE" ] || [ ! -r "$PASSWORD_FILE" ]; then
  log "ERROR: cannot mail — $ACCOUNT_FILE or $PASSWORD_FILE is missing or unreadable"
  log "state was: $SIGNATURE"
  [ -n "$DETAIL" ] && printf '%s' "$DETAIL"
  exit 1
fi

ACCOUNT="$(tr -d '[:space:]' < "$ACCOUNT_FILE")"

# All whitespace, not just newlines. A Google app password is sixteen letters
# with no spaces in it; the console displays it as four groups of four purely
# for reading, and pasting what is shown gets the spaces too. Stripping a
# password would normally be wrong — here the space is known not to be part of
# the value, and the failure it causes otherwise is a bare authentication
# rejection that says nothing about why.
PASSWORD="$(tr -d '[:space:]' < "$PASSWORD_FILE")"

RECONCILE_TAIL="$(tail -5 /opt/homebrew/var/log/nexus-reconcile.log 2>/dev/null)"

# One envelope recipient per address, and a To: header listing all of them. The
# header is display only — delivery is decided entirely by --mail-rcpt, so a
# missing address here would silently not be mailed while the header claimed it
# was. Both are built from the single ALERT_TO list for that reason. Indexed
# arrays are bash 3.2; only associative ones are not.
TO_HEADER=""
RCPT_ARGS=()
for addr in $ALERT_TO; do
  if [ -z "$TO_HEADER" ]; then TO_HEADER="$addr"; else TO_HEADER="$TO_HEADER, $addr"; fi
  RCPT_ARGS+=(--mail-rcpt "$addr")
done

MSG="$(mktemp -t nexus-health)" || { log "ERROR: mktemp failed"; exit 1; }
trap 'rm -f "$MSG"' EXIT

{
  printf 'From: %s\n' "$ACCOUNT"
  printf 'To: %s\n' "$TO_HEADER"
  printf 'Subject: %s\n' "$SUBJECT"
  printf 'Date: %s\n' "$(date -R)"
  printf 'Content-Type: text/plain; charset=utf-8\n'
  printf '\n'
  printf 'host      %s\n' "$HOST"
  printf 'time      %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf 'uptime    %ss\n' "$UP"
  printf 'state     %s\n' "$SIGNATURE"
  printf 'previous  %s\n' "${PREV_SIGNATURE:-<none, first run>}"
  printf '\n'
  if [ -n "$DETAIL" ]; then
    printf 'What is wrong\n-------------\n%s\n' "$DETAIL"
  else
    printf 'All checks pass: expected services running, every requested host\n'
    printf 'binding actually bound, all six entrances answering, Ollama on\n'
    printf 'loopback only.\n\n'
  fi
  printf 'Last lines of nexus-reconcile.log\n---------------------------------\n%s\n\n' "${RECONCILE_TAIL:-<no log>}"
  printf 'Where to look\n-------------\n'
  printf '  docs/runbooks/first-deploy.md 1.1  the acceptance run and the four reconcile outcomes\n'
  printf '  docs/runbooks/first-deploy.md 7    the requested-versus-actual port table\n'
  printf '  docs/architecture/deployment.md 9  why a failed bind does not restart anything\n'
} > "$MSG"

if curl --silent --show-error --ssl-reqd --max-time 60 \
     --url "$SMTP_URL" \
     --user "$ACCOUNT:$PASSWORD" \
     --mail-from "$ACCOUNT" \
     "${RCPT_ARGS[@]}" \
     --upload-file "$MSG" 2>&1; then
  log "mailed $KIND to $ALERT_TO"
else
  log "ERROR: could not send mail; the state below was not delivered"
  log "state was: $SIGNATURE"
  [ -n "$DETAIL" ] && printf '%s' "$DETAIL"
  exit 1
fi

exit 0
