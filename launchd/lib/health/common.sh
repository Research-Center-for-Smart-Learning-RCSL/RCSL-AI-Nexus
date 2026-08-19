# Sourced stage: common.
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
BACKUP_AGE_H=""
BACKUP_FIGURES=""

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
