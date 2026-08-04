#!/bin/bash
# Watch the platform, mail when something breaks, and mail a summary once a day.
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
# off". The daily digest below is what covers that: if the mail stops arriving,
# something is wrong even though no alert was sent. Silence is only evidence when
# something is expected to break it. That remains the weakest joint here, because
# it needs a person to notice an absence; an external dead man's switch is the
# real fix and is deliberately not built yet.
#
# **Two tiers, and the split is the design.** Tier 1 is "broken now": it goes into
# the signature, and any change to that signature mails immediately. Tier 2 is
# "will break, or is degrading": expiries, staleness, growth. Tier 2 never enters
# the signature and never sends its own mail — it is reported once a day in the
# digest. The reason is that a fourteen-day expiry warning in the signature keeps
# the subject line reading FAILING for fourteen days, and a subject that means
# nothing is worse than no subject at all. Anything with lead time waits for the
# digest; anything without it wakes somebody.
#
# Every check is written so it can produce more than one answer. The service
# check compares against an expected list rather than enumerating what happens to
# be running, because a container that is simply gone would otherwise not appear
# in the enumeration and the sweep would report success. That is the same error
# the reconciler's third precondition exists for, and the same one that made
# `tailscale status --json` answer "no SSH host keys" to a question it did not
# have a field for. That failure repeated itself while this file was being
# extended: `Self` carries no `KeyExpiry` field at all when key expiry is
# disabled, so a check reading it would have been a permanent silent pass. See
# check 13 for the three answers it gives instead.
#
# Written for the bash 3.2 that macOS ships: no mapfile, no associative arrays.
# `/usr/bin/python3` is used for JSON and dates only, stdlib-only and never a
# virtualenv, for the reason online.rcsl.host-metrics.plist gives: a launchd job
# that depends on a project venv breaks the first time the project is rebuilt.

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
#
# Three lines, and every path that writes it writes all three:
#   1  the tier-1 signature
#   2  the date of the last digest, YYYY-MM-DD
#   3  restart counts at the last run, "service:count service:count"
#
# Line 2 held a Unix timestamp before 2026-08-04, when the digest was a rolling
# 24-hour heartbeat. A leftover timestamp does not parse as a date and is read as
# "no digest yet", which sends one at the next run — that is the intended
# upgrade path and it doubles as proof the new mail reaches both recipients.
STATE_FILE="/opt/homebrew/var/nexus-health.state"

HEALTH_LOG="/opt/homebrew/var/log/nexus-health.log"
RECONCILE_LOG="/opt/homebrew/var/log/nexus-reconcile.log"

# `NEXUS_HEALTH_DRY_RUN=1 bash check-platform-health.sh` runs every check and
# prints the mail it would have sent instead of sending it, and writes no state.
# Both halves matter: a dry run that wrote state would consume the digest date
# and the real run would then skip the day it was meant to verify. This exists
# because the alternative way to test a mailer is to mail somebody.
DRY_RUN="${NEXUS_HEALTH_DRY_RUN:-0}"

# The digest goes out at 08:00 local time, not 24 hours after the last one. The
# rolling version drifted — any mail reset its clock — so its arrival time
# wandered through the day and "today's mail has not come yet" was never a
# statement anyone could make. A fixed hour makes an absence legible, which is
# the only thing that makes a digest worth sending at all. The machine is on
# Asia/Taipei, so this is 08:00 UTC+8.
DIGEST_HOUR=8

# Long-lived services, which is every compose service except `migrate`. `migrate`
# is a one-shot job and is correctly `Exited (0)` after a boot; treating it as
# expected-running would alert on every reboot forever.
#
# Derived from the compose file at run time, with this list as the fallback for
# when that derivation fails. It was a hand-maintained literal until 2026-08-04
# and `parser` and `qdrant` were missing from it, so either could have stopped
# without the sweep noticing — the list is compared against, and a service absent
# from it is a service nothing asks about. That is the enumeration error the
# header argues against, in the list the argument is about. Deriving it means
# adding a service to docker-compose.yml is enough; nobody has to remember.
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
# so the boot-time run (RunAtLoad) is suppressed and every scheduled run after it
# evaluates.
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

# --- thresholds -------------------------------------------------------------
#
# Tier 1 numbers are where the platform is already failing or is hours away from
# it. Tier 2 numbers are where somebody should put it on a list. Two disk
# numbers rather than one for exactly that reason: 85% is a chore, 95% is an
# outage, because Postgres goes read-only when the volume fills.

GEOIP_MAX_AGE_DAYS=10        # refreshed weekly, so 10 days is two missed runs
DISK_WARN_PCT=85
DISK_FAIL_PCT=95
MEM_AVAIL_WARN_GB=4
SWAP_WARN_GB=8
DOCKER_RECLAIM_WARN_GB=30
KEY_EXPIRY_WARN_DAYS=30
# Mirrors DEFAULT_RETENTION_DAYS in backend/app/domain/entities/retention.py.
# Duplicated because this runs outside the application, and named here so the
# duplication is visible rather than buried in a SQL literal. An absent policy
# row *means* this number — `ManageRetention._days_for` returns it — so reading
# "no row" as "nothing is being deleted" is wrong in both directions: it invents
# a problem that does not exist and it skips the check for the one that does.
DEFAULT_RETENTION_DAYS=360
TS_KEY_WARN_DAYS=21
HTTP_5XX_RATIO=0.05
HTTP_5XX_MIN_SAMPLE=20       # below this a single error is 100% and means nothing

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

FAILURES=""
DETAIL=""
WARNINGS=""
NOTES=""

# Every figure the digest prints is initialised here, whether or not the check
# that fills it runs. The digest body is one `{ ... }` block under `set -u`, so a
# single unset variable aborts it part-way through — and the state file has
# already recorded today as the digest date by then, so the mail is not retried
# and never arrives. `RECLAIM_GB` was assigned only inside the Docker-is-up
# branch and read unconditionally, which meant "Docker Desktop is down at 08:00"
# produced exactly the missing-digest condition this file tells the reader means
# the machine itself is dead.
DISK_PCT=""
MEM_AVAIL=""
SWAP_USED=""
DOCKER_DISK_PCT=""
RECLAIM_GB=""
GEOIP_AGE_DAYS=""

fail() {
  # $1 short id used for the change signature, $2 human line for the mail body.
  FAILURES="$FAILURES$1
"
  DETAIL="$DETAIL$2
"
}

warn() {
  # Tier 2. Never reaches the signature, so it cannot mail on its own; it is
  # read once a day by the digest.
  WARNINGS="$WARNINGS  - $1
"
}

note() {
  # True, checked, and not a problem. Worth printing because "this was looked at
  # and was fine" and "this was never looked at" are different states, and the
  # digest is the only place that difference is visible.
  NOTES="$NOTES  - $1
"
}

fmt_num() { awk -v v="$1" 'BEGIN{ if (v=="" || v=="NaN") print "-"; else printf "%.1f", v }'; }
fmt_int() { awk -v v="$1" 'BEGIN{ if (v=="" || v=="NaN") print "-"; else printf "%d", int(v+0.5) }'; }
# Three decimals, because these are seconds and a healthy p95 here is single
# -digit milliseconds: one decimal prints every good day as `0.0` and every bad
# one as `0.1`, which is a figure nobody can read a trend from.
fmt_sec() { awk -v v="$1" 'BEGIN{ if (v=="" || v=="NaN") print "-"; else printf "%.3f", v }'; }
# `mailed` in the log has to mean mailed.
sent_word() { if [ "$DRY_RUN" != "0" ]; then printf 'rendered (dry run, not sent)'; else printf 'mailed'; fi; }

# Every external command gets a deadline. curl has carried `-m` since the first
# version of this file; the docker calls did not, and that asymmetry is a way
# for the monitor to die of the thing it is watching for. `docker compose exec
# -T postgres psql` blocks forever against a Postgres that is alive enough to
# stay `running` but not to answer — a full data volume being the canonical
# case, which is precisely what check 9 exists to report. launchd will not start
# a second instance of a `StartInterval` job while the first is still running,
# so one such hang stops every future check, freezes the state file's mtime, and
# sends no mail at all: total silence, produced by the failure most in need of a
# mail.
#
# macOS ships no timeout(1) and gtimeout is a homebrew package this cannot
# depend on, so the deadline comes from the subprocess timeout in python3. Exit
# 124 on expiry, matching the convention timeout(1) uses. stderr is inherited
# rather than discarded, so a caller that needs to read it — check 5 does — can,
# and every other call site redirects it as it would any other command.
run_timeout() {
  local secs="$1"; shift
  /usr/bin/python3 -c '
import subprocess, sys
try:
    p = subprocess.run(sys.argv[2:], timeout=float(sys.argv[1]),
                       stdout=subprocess.PIPE)
except subprocess.TimeoutExpired:
    sys.exit(124)
except Exception:
    sys.exit(125)
sys.stdout.write(p.stdout.decode("utf-8", "replace"))
sys.exit(p.returncode)
' "$secs" "$@"
}

# --- the previous state -----------------------------------------------------
#
# Read here, above the grace check, because that check exits early and still has
# to leave the state file rewritten. The file's mtime is the only record that
# this ran at all, and the runbook's acceptance criterion reads it as one: "mtime
# is under five minutes old". A path that exits without touching it makes that
# criterion false while nothing is wrong.

PREV_SIGNATURE=""
PREV_DIGEST_DATE=""
PREV_RESTARTS=""
if [ -f "$STATE_FILE" ]; then
  PREV_SIGNATURE="$(sed -n '1p' "$STATE_FILE")"
  PREV_DIGEST_DATE="$(sed -n '2p' "$STATE_FILE")"
  PREV_RESTARTS="$(sed -n '3p' "$STATE_FILE")"
  # Anything that is not a date is "no digest has been sent", which includes the
  # rolling heartbeat's timestamp from before 2026-08-04.
  case "$PREV_DIGEST_DATE" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) PREV_DIGEST_DATE="" ;;
  esac
fi

write_state() {
  # $1 signature, $2 digest date, $3 restart snapshot. Every exit path calls
  # this, and it always writes three lines: a path that wrote two would truncate
  # the restart snapshot, the baseline would be lost, and the restart check
  # would go quiet without saying so.
  if [ "$DRY_RUN" != "0" ]; then
    printf '[dry-run] would write state: %s | %s | %s\n' "$1" "$2" "$3"
    return 0
  fi
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  printf '%s\n%s\n%s\n' "$1" "$2" "$3" > "$STATE_FILE"
}

# --- boot grace -------------------------------------------------------------
#
# The anchored `^{ sec = ` is load-bearing; see BOOT_GRACE above for what the
# unanchored version did.

BOOT_SEC="$(sysctl -n kern.boottime 2>/dev/null | sed -n 's/^{ sec = \([0-9]*\).*/\1/p')"
NOW="$(date +%s)"
TODAY="$(date '+%Y-%m-%d')"
HOUR="$(date '+%H')"
HOUR="${HOUR#0}"
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
    write_state "$PREV_SIGNATURE" "$PREV_DIGEST_DATE" "$PREV_RESTARTS"
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

# The only host addresses any container is allowed to publish on. Check 5b
# compares against this, so it has to be built from what the deployment is
# entitled to and not from what it happens to be doing.
ALLOWED_HOST_IPS="127.0.0.1"
[ -n "$TAILNET_IP" ] && ALLOWED_HOST_IPS="$ALLOWED_HOST_IPS $TAILNET_IP"

# --- 2. the tailnet address is on an interface ------------------------------

if [ -n "$TAILNET_IP" ] && ! ifconfig 2>/dev/null | grep -qw "$TAILNET_IP"; then
  fail "tailnet" "$TAILNET_IP is not on any interface. tailscaled is down or has not brought utun0 up; every tailnet-facing binding depends on this."
fi

# --- 3. the docker daemon answers -------------------------------------------

DOCKER_UP=1
if ! run_timeout 15 docker info >/dev/null 2>&1; then
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

RUNNING=""
if [ "$DOCKER_UP" -eq 1 ]; then
  DERIVED="$(run_timeout 20 docker compose config --services 2>/dev/null | grep -vx 'migrate' | tr '\n' ' ')"
  [ -n "$DERIVED" ] && EXPECTED_SERVICES="$DERIVED"

  RUNNING="$(run_timeout 20 docker compose ps --services --status running 2>/dev/null)"
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

running_p() { printf '%s\n' "$RUNNING" | grep -qx "$1"; }

# --- 5. one pass over every container ---------------------------------------
#
# Bindings, health and restart count in a single `docker inspect`, because three
# separate passes would be three times the subprocesses for the same data and
# would let the three answers come from three different moments.
#
# 5a  requested bindings are actual bindings. The 2026-07-26 failure exactly:
#     HostConfig.PortBindings asks for a host port and NetworkSettings.Ports has
#     an empty list for it. A service that publishes nothing has null there, not
#     [], so the two cases do not blur.
#
# 5b  and nothing is published anywhere it should not be. 5a asks whether what
#     was requested happened; this asks whether what was requested was allowed.
#     Check 7 has always made that argument about Ollama — that a value keeping
#     a service on loopback lives somewhere an upgrade can replace — and the
#     compose file makes it too, in the `${TAILNET_IP:?...}` default that exists
#     precisely because an empty value would publish on 0.0.0.0. Nothing checked
#     it afterwards. An unset HostIp is rendered as 0.0.0.0 below rather than as
#     an empty field, because an empty field would vanish into the separator and
#     the exposure would be invisible in the exact case that matters most.
#
# 5c  container health, for the services that define a healthcheck. Running and
#     healthy are different questions and compose already answers the second
#     one; nothing read the answer until 2026-08-04. Containers without a
#     healthcheck report `none`, which is not a failure — it is the absence of an
#     opinion, and it must not be read as a passing one.
#
#     For the three backend services it is a *liveness* answer only: their probe
#     is /healthz, which by design checks nothing, so `healthy` there survives
#     Postgres being down. That is not a gap here — check 6 asks the readiness
#     question over /readyz, and the two are deliberately separate signals — but
#     it does mean this check alone can never report a dependency outage, and
#     neither can the `docker compose ps` the runbook opens with.
#
# 5d  restart counts against the previous run. A container in a crash loop is
#     intermittently `running`, so check 4 samples it every five minutes and sees
#     whatever it happens to see; the count only moves in one direction and is
#     the direct evidence.

UNHEALTHY=""
UNBOUND=""
EXPOSED=""
RESTARTED=""
RESTART_SNAPSHOT="$PREV_RESTARTS"

prev_restart() {
  printf '%s\n' $PREV_RESTARTS | sed -n "s/^$1://p" | head -1
}

if [ "$DOCKER_UP" -eq 1 ]; then
  CIDS="$(run_timeout 20 docker compose ps -q 2>/dev/null)"
  if [ -n "$CIDS" ]; then
    # `{{with index .State "Health"}}` and not `{{if .State.Health}}`. The second
    # spelling does not return empty for a container without a healthcheck — it
    # aborts that container's line with `map has no entry for key "Health"`, and
    # `docker inspect` writes the error to stderr and simply omits the row. The
    # five services with no healthcheck therefore produced no output at all, and
    # were silently excluded from the restart, binding and exposure checks in the
    # same stroke: a check that read `none` for them would have been fine, but
    # this read nothing for them and said nothing about it. Caught in the first
    # dry run, which is the entire reason the dry run exists.
    INSPECT_FMT='{{index .Config.Labels "com.docker.compose.service"}}|{{with index .State "Health"}}{{.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{json .HostConfig.PortBindings}}|{{json .NetworkSettings.Ports}}|{{range $p, $c := .HostConfig.PortBindings}}{{range $c}}{{if .HostIp}}{{.HostIp}}{{else}}0.0.0.0{{end}} {{end}}{{end}}'
    INSPECT_ERR="$(mktemp -t nexus-health-inspect)" || INSPECT_ERR=/dev/null
    INSPECT_OUT="$(run_timeout 30 docker inspect $CIDS --format "$INSPECT_FMT" 2>"$INSPECT_ERR")"

    NEW_SNAPSHOT=""
    while IFS='|' read -r svc health rc req act hostips; do
      [ -n "${svc:-}" ] || continue

      case "${health:-none}" in
        healthy|none|starting) ;;
        *) UNHEALTHY="$UNHEALTHY $svc=$health" ;;
      esac

      case "${rc:-}" in
        ''|*[!0-9]*) ;;
        *)
          NEW_SNAPSHOT="$NEW_SNAPSHOT$svc:$rc "
          old="$(prev_restart "$svc")"
          case "$old" in
            ''|*[!0-9]*) ;;
            *) [ "$rc" -gt "$old" ] && RESTARTED="$RESTARTED $svc($old->$rc)" ;;
          esac
          ;;
      esac

      case "${req:-}" in
        ""|"{}"|"null") continue ;;
      esac

      case "${act:-}" in
        *'[]'*) UNBOUND="$UNBOUND $svc" ;;
      esac

      for ip in ${hostips:-}; do
        case " $ALLOWED_HOST_IPS " in
          *" $ip "*) ;;
          *) EXPOSED="$EXPOSED $svc@$ip" ;;
        esac
      done
    done <<EOF
$INSPECT_OUT
EOF

    [ -n "$NEW_SNAPSHOT" ] && RESTART_SNAPSHOT="${NEW_SNAPSHOT% }"

    # `docker inspect` reports a per-container template failure on stderr and
    # then omits that container's row, so a broken template is invisible in the
    # output alone — which is exactly how the `.State.Health` spelling above hid
    # five containers.
    #
    # The test is the stderr text and not a row count, and the difference
    # matters. Rows also go missing for an entirely ordinary reason: `CIDS` is
    # captured first, and any container removed between that and the inspect is
    # reported as `No such object`. That is what a `docker compose up -d`
    # recreate looks like from here, and it happens on this machine — a count
    # test would mail FAILING and then RECOVERED for a routine redeploy, which is
    # how an alert becomes something people filter. A template error means the
    # check is broken; a vanished container means the platform is moving.
    CID_COUNT="$(printf '%s\n' "$CIDS" | grep -c '[^[:space:]]')"
    ROW_COUNT="$(printf '%s\n' "$INSPECT_OUT" | grep -c '[^[:space:]]')"
    if grep -qi 'template' "$INSPECT_ERR" 2>/dev/null; then
      fail "inspect" "docker inspect could not render its template ($ROW_COUNT rows for $CID_COUNT containers): $(head -1 "$INSPECT_ERR" 2>/dev/null). The health, restart, binding and exposure checks did not cover every container."
    fi
    [ "$INSPECT_ERR" != "/dev/null" ] && rm -f "$INSPECT_ERR"
  fi

  if [ -n "$UNBOUND" ]; then
    fail "bindings" "Requested a host port and did not get one:$UNBOUND. This is the state where containers are Up and healthy and the platform is unreachable. The reconciler should have repaired it at boot; check $RECONCILE_LOG."
  fi
  if [ -n "$EXPOSED" ]; then
    fail "exposed" "Published on an address that is not $ALLOWED_HOST_IPS:$EXPOSED. 0.0.0.0 here means the whole LAN reaches a service the tailnet ACL is supposed to be the only route to; an empty TAILNET_IP in .env is the way this happens."
  fi
  if [ -n "$UNHEALTHY" ]; then
    fail "health" "Container healthcheck failing:$UNHEALTHY. The container is running, so check 4 passes; this is the dependency underneath it."
  fi
  if [ -n "$RESTARTED" ]; then
    fail "restarts" "Restart count went up since the last run:$RESTARTED. A crash loop is intermittently 'running', so the count is the evidence rather than the state."
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
# Not the same volume as check 8 and not derivable from it. Docker Desktop keeps
# a virtual disk with its own size, and Postgres filling that VM disk while the
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

PROM_OK=0
[ "$DOCKER_UP" -eq 1 ] && running_p prometheus && PROM_OK=1

prom_get() {
  # $1 mode: `value` for the first sample, `pairs` for "<label> <value>" lines.
  # $2 promql. $3 label name, for pairs.
  #
  # Returns non-zero when Prometheus could not be asked or did not answer
  # successfully, and zero with empty output when the query matched nothing.
  # Those are different answers and the callers rely on the difference.
  [ "$PROM_OK" -eq 1 ] || return 1
  local enc raw
  enc="$(/usr/bin/python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$2" 2>/dev/null)" || return 1
  raw="$(run_timeout 20 docker compose exec -T prometheus wget -qO- "http://localhost:9090/api/v1/query?query=$enc" 2>/dev/null)" || return 1
  [ -n "$raw" ] || return 1
  printf '%s' "$raw" | /usr/bin/python3 -c '
import json, sys
mode = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else ""
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if d.get("status") != "success":
    sys.exit(1)
result = d.get("data", {}).get("result", [])
if mode == "value":
    print(result[0]["value"][1] if result else "")
else:
    for s in result:
        print("%s %s" % (s["metric"].get(label, "?"), s["value"][1]))
' "$1" "${3:-}"
}

if [ "$PROM_OK" -eq 1 ]; then
  DOWN_TARGETS="$(prom_get pairs 'up == 0' job)"
  if [ $? -ne 0 ]; then
    fail "prometheus" "Prometheus is running but did not answer a query. Every metric behind it — the dashboards, and the application checks below — is unavailable."
  elif [ -n "$DOWN_TARGETS" ]; then
    fail "scrape" "Prometheus cannot scrape: $(printf '%s' "$DOWN_TARGETS" | awk '{print $1}' | tr '\n' ' '). The container can be running and the entrance answering while this fails, which is what makes it its own check — a wrong metrics_scrape_token looks exactly like this."
  fi

  # 5xx rate over the last five minutes, guarded by a sample floor: at low
  # traffic one failed request is 100% and would mail every time somebody's
  # browser gave up.
  ERR5="$(prom_get value 'sum(increase(nexus_http_requests_total{status=~"5.."}[5m])) or vector(0)')"
  TOT5="$(prom_get value 'sum(increase(nexus_http_requests_total[5m])) or vector(0)')"
  if [ -n "$ERR5" ] && [ -n "$TOT5" ]; then
    if awk -v e="$ERR5" -v t="$TOT5" -v r="$HTTP_5XX_RATIO" -v m="$HTTP_5XX_MIN_SAMPLE" \
       'BEGIN{exit !(t>=m && e/t>=r)}'; then
      fail "http-5xx" "$(fmt_int "$ERR5") of $(fmt_int "$TOT5") requests in the last five minutes returned 5xx (threshold $(awk -v r="$HTTP_5XX_RATIO" 'BEGIN{printf "%d", r*100}')%). Every entrance can be answering /readyz while the requests that matter fail."
    fi
  fi
fi

# --- 12. the GeoLite2 database is not stale ---------------------------------
#
# refresh-geolite2 runs weekly and, in the runbook's own words, "失敗不會有人通知
# 你". Its own staleness check only speaks when it runs, which is precisely the
# thing that is not happening when it has failed. One stat answers it from
# outside, which is the only place the answer is trustworthy.

GEOIP_FILE="$REPO/data/GeoLite2-Country.mmdb"
if [ ! -f "$GEOIP_FILE" ]; then
  warn "the GeoLite2 database is missing from $GEOIP_FILE; the geo filter has nothing to read"
else
  GEOIP_MTIME="$(stat -f %m "$GEOIP_FILE" 2>/dev/null)"
  case "$GEOIP_MTIME" in
    ''|*[!0-9]*) warn "could not read the mtime of $GEOIP_FILE, so its freshness is unknown" ;;
    *)
      GEOIP_AGE_DAYS=$(( (NOW - GEOIP_MTIME) / 86400 ))
      if [ "$GEOIP_AGE_DAYS" -gt "$GEOIP_MAX_AGE_DAYS" ]; then
        warn "the GeoLite2 database is ${GEOIP_AGE_DAYS} days old (warn over ${GEOIP_MAX_AGE_DAYS}); it refreshes weekly, so this is at least two failed runs — see /opt/homebrew/var/log/nexus-geolite2.log"
      fi
      ;;
  esac
fi

# --- 13. the tailscale node key ---------------------------------------------
#
# Three answers, and the third is the point. `tailscale status --json` omits
# `KeyExpiry` from `Self` entirely when key expiry is disabled for the node —
# peers that do expire carry the field, this machine does not. A check that read
# the field and treated absence as "fine" would be a permanent silent pass, and
# would keep passing if the JSON shape ever changed or the command broke. So:
# absent field is only an answer once `Self` itself has been found.

TS_STATE=""
TS_DAYS=""
TS_PARSED="$(tailscale status --json 2>/dev/null | /usr/bin/python3 -c '
import datetime, json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("unreadable"); sys.exit(0)
self_node = d.get("Self")
if not isinstance(self_node, dict):
    print("no-self"); sys.exit(0)
expiry = self_node.get("KeyExpiry")
if not expiry:
    print("disabled"); sys.exit(0)
try:
    when = datetime.datetime.strptime(expiry[:19], "%Y-%m-%dT%H:%M:%S")
except Exception:
    print("unreadable"); sys.exit(0)
print("expires")
print(int((when - datetime.datetime.utcnow()).total_seconds() // 86400))
' 2>/dev/null)"
TS_STATE="$(printf '%s\n' "$TS_PARSED" | sed -n '1p')"
TS_DAYS="$(printf '%s\n' "$TS_PARSED" | sed -n '2p')"
case "$TS_STATE" in
  disabled)
    note "tailscale node key: expiry is disabled for this machine, so it cannot lapse" ;;
  expires)
    if [ -n "$TS_DAYS" ] && [ "$TS_DAYS" -le "$TS_KEY_WARN_DAYS" ]; then
      warn "the tailscale node key expires in ${TS_DAYS} days; when it lapses the tailnet address disappears and every tailnet-facing binding with it"
    else
      note "tailscale node key: ${TS_DAYS} days remaining" ;
    fi ;;
  no-self|unreadable|*)
    warn "could not read the tailscale node key expiry (\`tailscale status --json\` gave '${TS_STATE:-nothing}'). This is unknown, not fine — the field is absent both when expiry is disabled and when the command has stopped answering the way it used to." ;;
esac

# --- 14. what the database says about itself --------------------------------
#
# Four questions, one connection, all of them tier 2 because each has weeks of
# lead time. No credential: `psql` over `docker compose exec` authenticates
# locally inside the container, which is the same reason the rest of this script
# needs none.
#
# The retention question is asked as an outcome rather than as a liveness check.
# `run_retention_sweep` is an asyncio loop inside the admin process; there is no
# port to probe and no metric to read, and a loop that has died looks exactly
# like one that has nothing to delete. "Is the oldest row older than the policy
# allows" is answerable from outside and is the thing anybody actually cares
# about, and when no policy is stored it says that instead of inventing a pass.

if [ "$DOCKER_UP" -eq 1 ] && running_p postgres; then
  DB_OUT="$(run_timeout 25 docker compose exec -T postgres psql -U nexus -d nexus -tAc "
select 'keys_expiring='||count(*) from api_keys
  where revoked_at is null and expires_at is not null
    and expires_at < now() + (interval '1 day' * $KEY_EXPIRY_WARN_DAYS)
union all select 'keys_debug='||count(*) from api_keys where debug_logging_until > now()
union all select 'users_debug='||count(*) from users where debug_logging_until > now()
union all select 'policies='||count(*) from retention_policies
union all select 'audit_days='||coalesce(round(extract(epoch from (now()-min(at)))/86400)::int::text,'-1') from audit_log
union all select 'usage_days='||coalesce(round(extract(epoch from (now()-min(at)))/86400)::int::text,'-1') from usage_records
union all select 'audit_policy='||coalesce((select days::text from retention_policies where dataset='audit_log'),'$DEFAULT_RETENTION_DAYS')
union all select 'usage_policy='||coalesce((select days::text from retention_policies where dataset='usage_records'),'$DEFAULT_RETENTION_DAYS')
" 2>/dev/null)"

  if [ -z "$DB_OUT" ]; then
    warn "could not query Postgres for key expiry and retention state; the container is running, so this is psql or the database itself"
  else
    KEYS_EXPIRING=""; KEYS_DEBUG=""; USERS_DEBUG=""; POLICIES=""
    AUDIT_DAYS=""; USAGE_DAYS=""; AUDIT_POLICY=""; USAGE_POLICY=""
    while IFS= read -r row; do
      case "$row" in
        keys_expiring=*) KEYS_EXPIRING="${row#*=}" ;;
        keys_debug=*)    KEYS_DEBUG="${row#*=}" ;;
        users_debug=*)   USERS_DEBUG="${row#*=}" ;;
        policies=*)      POLICIES="${row#*=}" ;;
        audit_days=*)    AUDIT_DAYS="${row#*=}" ;;
        usage_days=*)    USAGE_DAYS="${row#*=}" ;;
        audit_policy=*)  AUDIT_POLICY="${row#*=}" ;;
        usage_policy=*)  USAGE_POLICY="${row#*=}" ;;
      esac
    done <<EOF
$DB_OUT
EOF

    [ "${KEYS_EXPIRING:-0}" -gt 0 ] 2>/dev/null && \
      warn "${KEYS_EXPIRING} API key(s) expire within ${KEY_EXPIRY_WARN_DAYS} days; the first thing a caller will know about it is a 401"
    [ "${KEYS_DEBUG:-0}" -gt 0 ] 2>/dev/null && \
      warn "${KEYS_DEBUG} API key(s) still have debug logging switched on; it expires by itself, but until it does their request contents are being recorded"
    [ "${USERS_DEBUG:-0}" -gt 0 ] 2>/dev/null && \
      warn "${USERS_DEBUG} user(s) still have debug logging switched on"

    # An absent row is not an absent policy. `ManageRetention._days_for` falls
    # back to DEFAULT_RETENTION_DAYS, and RetentionPolicyRow's docstring says the
    # absence of a row *is* the default — which is why no migration seeds one, and
    # why `policies=0` is the normal shipped state rather than a fault. The SQL
    # above therefore resolves the effective number of days per dataset, and the
    # staleness check below runs against it unconditionally.
    #
    # This was wrong in the first version of this check, and wrong twice over: it
    # warned every single day that "the sweep deletes nothing", which was false,
    # and it put the real check — the only thing that can detect a dead
    # `run_retention_sweep` loop — in the branch that never runs by default.
    if [ "${POLICIES:-0}" = "0" ]; then
      note "retention: no policy row stored, so both datasets use the built-in default of ${DEFAULT_RETENTION_DAYS} days"
    fi

    # Two days of slack: the sweep runs daily, so a row one day past the window
    # is on time rather than late.
    if [ "${AUDIT_POLICY:--1}" -gt 0 ] 2>/dev/null && [ "${AUDIT_DAYS:--1}" -gt $((AUDIT_POLICY + 2)) ] 2>/dev/null; then
      warn "audit_log holds rows ${AUDIT_DAYS} days old against an effective ${AUDIT_POLICY}-day window; the retention sweep is not doing what the policy says"
    fi
    if [ "${USAGE_POLICY:--1}" -gt 0 ] 2>/dev/null && [ "${USAGE_DAYS:--1}" -gt $((USAGE_POLICY + 2)) ] 2>/dev/null; then
      warn "usage_records holds rows ${USAGE_DAYS} days old against an effective ${USAGE_POLICY}-day window; the retention sweep is not doing what the policy says"
    fi
  fi
fi

# --- decide -----------------------------------------------------------------
#
# Only tier 1 reaches the signature. WARNINGS and NOTES are deliberately not in
# it: a signature that moved when a warning appeared would mail immediately, and
# the whole reason those checks are tier 2 is that they have lead time.

if [ -z "$FAILURES" ]; then
  SIGNATURE="OK"
else
  SIGNATURE="$(printf '%s' "$FAILURES" | sort | tr '\n' ',')"
fi

HOST="$(hostname -s)"

SEND_EVENT=0
EVENT_KIND=""
EVENT_SUBJECT=""
if [ "$SIGNATURE" != "$PREV_SIGNATURE" ]; then
  SEND_EVENT=1
  if [ -z "$PREV_SIGNATURE" ] && [ "$SIGNATURE" = "OK" ]; then
    # First run ever. Reporting this as a recovery would claim a failure that
    # never happened; it is a baseline, and it doubles as proof the mail path
    # works, which is the one part of this that cannot be tested by watching.
    EVENT_KIND="baseline"
    EVENT_SUBJECT="[nexus] monitoring started on $HOST, all checks pass"
  elif [ "$SIGNATURE" = "OK" ]; then
    EVENT_KIND="recovered"
    EVENT_SUBJECT="[nexus] RECOVERED on $HOST"
  else
    EVENT_KIND="failing"
    EVENT_SUBJECT="[nexus] FAILING on $HOST: $(printf '%s' "$FAILURES" | tr '\n' ' ')"
  fi
fi

# The digest is due once per calendar day, from DIGEST_HOUR onwards. Both mails
# can fall in the same run; they are allowed to, because they answer different
# questions and merging them would mean the urgent one waits for the daily one
# or the daily one loses its summary.
SEND_DIGEST=0
DIGEST_DATE="$PREV_DIGEST_DATE"
if [ "$TODAY" != "$PREV_DIGEST_DATE" ] && [ "$HOUR" -ge "$DIGEST_HOUR" ]; then
  SEND_DIGEST=1
  DIGEST_DATE="$TODAY"
fi
# A dry run always renders the digest, whatever the calendar says. Otherwise the
# one mail that is hard to eyeball — the one with every tier-2 check in it — can
# only be inspected on the day it happens not to have been sent yet.
[ "$DRY_RUN" != "0" ] && SEND_DIGEST=1

# Written before any mail is attempted, so a broken mail path cannot turn one
# state change into an alert on every interval.
#
# The digest date is deliberately *not* advanced here — it is written again
# after the digest actually goes out. The reasoning above is about the
# signature: re-alerting every five minutes is worse than losing one alert. It
# does not carry over to the digest, where burning the date on a transient SMTP
# failure at 08:00 means no digest at all that day, and the design's own
# contract says a day with no digest means the machine is gone. A network blip
# would manufacture that signal, with an ERROR line in a log this file says
# nobody reads as the only trace.
write_state "$SIGNATURE" "$PREV_DIGEST_DATE" "$RESTART_SNAPSHOT"

if [ "$SEND_EVENT" -eq 0 ] && [ "$SEND_DIGEST" -eq 0 ]; then
  exit 0
fi

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

RECONCILE_TAIL="$(tail -5 "$RECONCILE_LOG" 2>/dev/null)"

send_mail() {
  # $1 subject, $2 file holding the body. Headers are added here so no caller
  # can forget one.
  local subject="$1" body="$2" msg
  if [ "$DRY_RUN" != "0" ]; then
    printf '\n===== [dry-run] would send =====\nTo: %s\nSubject: %s\n\n' "$TO_HEADER" "$subject"
    cat "$body"
    printf '===== end =====\n'
    return 0
  fi
  msg="$(mktemp -t nexus-health)" || { log "ERROR: mktemp failed"; return 1; }
  {
    printf 'From: %s\n' "$ACCOUNT"
    printf 'To: %s\n' "$TO_HEADER"
    printf 'Subject: %s\n' "$subject"
    printf 'Date: %s\n' "$(date -R)"
    printf 'Content-Type: text/plain; charset=utf-8\n'
    printf '\n'
    cat "$body"
  } > "$msg"

  if curl --silent --show-error --ssl-reqd --max-time 60 \
       --url "$SMTP_URL" \
       --user "$ACCOUNT:$PASSWORD" \
       --mail-from "$ACCOUNT" \
       "${RCPT_ARGS[@]}" \
       --upload-file "$msg" 2>&1; then
    rm -f "$msg"
    return 0
  fi
  rm -f "$msg"
  return 1
}

BODY="$(mktemp -t nexus-health-body)" || { log "ERROR: mktemp failed"; exit 1; }
trap 'rm -f "$BODY"' EXIT

RC=0

# --- the event mail ---------------------------------------------------------

if [ "$SEND_EVENT" -eq 1 ]; then
  log "$EVENT_KIND: $SIGNATURE"
  {
    printf 'host      %s\n' "$HOST"
    printf 'time      %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'uptime    %ss\n' "$UP"
    printf 'state     %s\n' "$SIGNATURE"
    printf 'previous  %s\n' "${PREV_SIGNATURE:-<none, first run>}"
    printf '\n'
    if [ -n "$DETAIL" ]; then
      printf 'What is wrong\n-------------\n%s\n' "$DETAIL"
    else
      printf 'All checks pass: expected services running and healthy, every\n'
      printf 'requested host binding actually bound and only on %s,\n' "$ALLOWED_HOST_IPS"
      printf 'no container restarted, all six entrances answering, Ollama on\n'
      printf 'loopback only, host metrics served, disk and scrape targets fine.\n\n'
    fi
    printf 'Last lines of nexus-reconcile.log\n---------------------------------\n%s\n\n' "${RECONCILE_TAIL:-<no log>}"
    printf 'Where to look\n-------------\n'
    printf '  docs/runbooks/first-deploy.md 1.1  the acceptance run and the four reconcile outcomes\n'
    printf '  docs/runbooks/first-deploy.md 7    the requested-versus-actual port table\n'
    printf '  docs/architecture/deployment.md 9  why a failed bind does not restart anything\n'
  } > "$BODY"

  if send_mail "$EVENT_SUBJECT" "$BODY"; then
    log "$(sent_word) $EVENT_KIND to $ALERT_TO"
  else
    log "ERROR: could not send the $EVENT_KIND mail; the state below was not delivered"
    log "state was: $SIGNATURE"
    [ -n "$DETAIL" ] && printf '%s' "$DETAIL"
    RC=1
  fi
fi

# --- the daily digest -------------------------------------------------------

if [ "$SEND_DIGEST" -eq 1 ]; then
  WARN_COUNT="$(printf '%s' "$WARNINGS" | grep -c '^' 2>/dev/null)"
  [ -n "$WARNINGS" ] || WARN_COUNT=0

  if [ "$SIGNATURE" != "OK" ]; then
    DIGEST_SUBJECT="[nexus] daily on $HOST: FAILING ($(printf '%s' "$FAILURES" | tr '\n' ' '))"
  elif [ "$WARN_COUNT" -gt 0 ]; then
    DIGEST_SUBJECT="[nexus] daily on $HOST: OK, $WARN_COUNT warning(s)"
  else
    DIGEST_SUBJECT="[nexus] daily on $HOST: all clear"
  fi

  log "digest: $SIGNATURE, $WARN_COUNT warning(s)"

  {
    printf 'host      %s\n' "$HOST"
    printf 'time      %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'uptime    %sh\n' "$((UP / 3600))"
    printf 'state     %s\n' "$SIGNATURE"
    printf '\n'

    if [ -n "$DETAIL" ]; then
      printf 'Failing now\n-----------\n%s\n' "$DETAIL"
    fi

    printf 'Warnings\n--------\n'
    if [ -n "$WARNINGS" ]; then
      printf '%s' "$WARNINGS"
    else
      printf '  none\n'
    fi
    printf '\n'

    # "Figures" and not "Checked and fine". These lines print unconditionally,
    # so when one of them is also the subject of a warning above, calling the
    # section "fine" makes the mail contradict itself — a digest saying the
    # GeoLite2 database is stale and then that it is fine teaches the reader to
    # trust neither half. They are readings; the warnings are the judgement.
    printf 'Figures\n-------\n'
    printf '  - host disk %s%%, Docker VM disk %s%%, %s GB memory available, %s GB swap\n' \
      "${DISK_PCT:-?}" "${DOCKER_DISK_PCT:-?}" "${MEM_AVAIL:-?}" "${SWAP_USED:-?}"
    printf '  - GeoLite2 database %s days old\n' "${GEOIP_AGE_DAYS:-?}"
    [ -n "$RECLAIM_GB" ] && printf '  - %s GB of Docker space reclaimable\n' "$RECLAIM_GB"
    [ -n "$NOTES" ] && printf '%s' "$NOTES"
    printf '\n'

    printf 'Last 24 hours\n-------------\n'
    if [ "$PROM_OK" -eq 1 ]; then
      D_REQ="$(prom_get value 'sum(increase(nexus_http_requests_total[24h])) or vector(0)')"
      D_ERR="$(prom_get value 'sum(increase(nexus_http_requests_total{status=~"5.."}[24h])) or vector(0)')"
      D_P95="$(prom_get value 'histogram_quantile(0.95, sum by (le) (rate(nexus_http_request_duration_seconds_bucket[24h])))')"
      D_TOK="$(prom_get value 'sum(increase(nexus_inference_tokens_total[24h])) or vector(0)')"
      D_CAP="$(prom_get pairs 'sum by (capability) (increase(nexus_inference_requests_total[24h]))' capability)"
      printf '  requests        %s\n' "$(fmt_int "${D_REQ:-}")"
      printf '  of those 5xx    %s\n' "$(fmt_int "${D_ERR:-}")"
      printf '  p95 latency     %s s\n' "$(fmt_sec "${D_P95:-}")"
      printf '  tokens produced %s\n' "$(fmt_int "${D_TOK:-}")"
      if [ -n "$D_CAP" ]; then
        printf '  completions by capability\n'
        printf '%s\n' "$D_CAP" | while read -r cap val; do
          printf '    %-24s %s\n' "$cap" "$(fmt_int "$val")"
        done
      else
        printf '  completions     none\n'
      fi
    else
      printf '  Prometheus was not reachable, so there are no application figures.\n'
    fi
    printf '\n'

    printf 'State changes in the last 24 hours\n----------------------------------\n'
    EVENTS="$(/usr/bin/python3 - "$HEALTH_LOG" <<'PY' 2>/dev/null
import datetime, sys
try:
    with open(sys.argv[1]) as fh:
        lines = fh.readlines()
except Exception:
    sys.exit(0)
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
out = []
for line in lines:
    stamp, _, rest = line.partition(" ")
    if not rest.strip():
        continue
    try:
        when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        continue
    # State changes and errors only. `log` also writes a "mailed <kind> to ..."
    # line for every mail, and those doubled the list while the [-20:] cap threw
    # away the oldest real transitions — the delivery receipts crowding out the
    # events they were receipts for.
    if not rest.startswith(("failing:", "recovered:", "baseline:", "ERROR")):
        continue
    if when >= cutoff:
        # Date as well as time: the window is 24 hours, so it spans two dates,
        # and a bare "22:44" above a "21:02" reads as out of order.
        out.append("  %s %s" % (when.strftime("%m-%d %H:%M"), rest.rstrip()))
print("\n".join(out[-20:]))
PY
)"
    if [ -n "$EVENTS" ]; then
      printf '%s\n' "$EVENTS"
    else
      printf '  none\n'
    fi
    printf '\n'

    printf 'Last lines of nexus-reconcile.log\n---------------------------------\n%s\n\n' "${RECONCILE_TAIL:-<no log>}"
    printf 'This mail arrives daily from %02d:00. If a day passes without one,\n' "$DIGEST_HOUR"
    printf 'the machine or this daemon is the thing to look at first.\n'
  } > "$BODY"

  if send_mail "$DIGEST_SUBJECT" "$BODY"; then
    log "$(sent_word) digest to $ALERT_TO"
    # Only now is the day spent. A failure leaves the previous date in place, so
    # the next run five minutes later tries again.
    write_state "$SIGNATURE" "$DIGEST_DATE" "$RESTART_SNAPSHOT"
  else
    log "ERROR: could not send the digest; it will be retried on the next run"
    RC=1
  fi
fi

exit $RC
