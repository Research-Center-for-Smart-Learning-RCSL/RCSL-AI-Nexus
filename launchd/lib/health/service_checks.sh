# Sourced stage: service checks.
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
  fail "docker" "The docker daemon does not answer. Colima must be running (online.rcsl.colima.plist); check \`colima status\`."
fi

# --- 4. every expected service is running -----------------------------------
#
# Compared against the list above rather than against whatever `ps` returns, so
# a container that is entirely gone is a failure and not an absence.
#
# `--status running` is load-bearing. `docker compose ps` without it excludes
# only *stopped* containers — `--all` is documented as adding those — so paused,
# restarting and created ones are listed, and this check would have counted them
# as running. Not hypothetical: Docker Desktop's Resource Saver paused containers
# on this machine before the Colima migration (2026-07-26), and the 19:04
# shutdown path issued an `/unpause`, so it had done it. `postgres`, `redis` and
# `prometheus` have no probe in check 6, which makes this their only coverage:
# paused, they would have been silent here and silent everywhere. The reconciler
# already asked the question this way; the two now agree.

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
