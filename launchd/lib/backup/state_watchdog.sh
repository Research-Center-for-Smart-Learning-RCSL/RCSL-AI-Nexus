# Sourced stage: state watchdog.
log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

STAGE="startup"
RC=0

PREV_SUCCESS=""
if [ -f "$STATE_FILE" ]; then
  PREV_SUCCESS="$(sed -n '1p' "$STATE_FILE" 2>/dev/null)"
fi

write_state() {
  # $1 last successful completion (or empty), $2 outcome, $3 figures
  [ "$DRY_RUN" != "0" ] && return 0
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  printf '%s\n%s\n%s\n' "$1" "$2" "$3" > "$STATE_FILE"
}

# Any exit that is not the happy path still has to leave the state file saying
# what stage it died in, including a kill from the watchdog below. Without this
# a hung run leaves yesterday's `ok` in place and the freshness check reads a
# stale success as a current one.
FIGURES="- - -"
on_exit() {
  local code=$?
  if [ "$STAGE" != "done" ]; then
    write_state "$PREV_SUCCESS" "failed:$STAGE" "$FIGURES"
    log "ERROR: exiting at stage '$STAGE' with code $code; last success was ${PREV_SUCCESS:-<never>}"
  fi
  exit $code
}
trap on_exit EXIT
trap 'exit 143' TERM INT

# The watchdog polls instead of sleeping once, and both halves of that are
# repairs to the obvious version. The obvious version is
# `( sleep "$MAX_RUN_SECONDS"; kill -TERM $$ ) &` with a `kill` in the exit
# trap, and it is wrong twice.
#
# It inherits this script's stdout, so the pipe stays open after the script has
# exited: `bash backup.sh | tail` hangs for two hours against a script that
# finished in seconds. Found on 2026-08-18 by running exactly that. Under
# launchd stdout is a file, so this would never have shown up there — it would
# have shown up as a `sleep 7200` process left behind by every nightly run.
#
# And the `kill` in the trap does not do what it reads as. `$!` is the
# subshell's pid; `sleep` is its child, so killing the subshell orphans the
# sleep rather than ending it. Two of them were still running when this was
# found.
#
# So: no kill, and nothing to get wrong. `$$` is not rewritten inside a
# subshell, so `kill -0 $$` asks whether this script is still alive; when it is
# not, the loop ends by itself within one poll. The residue after any exit is at
# most a 30-second sleep, and the deadline is still enforced to the same
# precision that matters for a two-hour ceiling.
START_EPOCH="$(date +%s)"
( while kill -0 $$ 2>/dev/null; do
    sleep 30
    if [ $(( $(date +%s) - START_EPOCH )) -gt "$MAX_RUN_SECONDS" ]; then
      kill -TERM $$ 2>/dev/null
      exit 0
    fi
  done ) >/dev/null 2>&1 &

die() { log "ERROR: $*"; exit 1; }

# --- preflight --------------------------------------------------------------
#
# Every one of these can fail in a way that produces a *successful-looking*
# backup, which is why they are checks and not assumptions.
