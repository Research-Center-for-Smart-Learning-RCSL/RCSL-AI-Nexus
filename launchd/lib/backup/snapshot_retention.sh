# Sourced stage: snapshot retention.
STAGE="retention"
log "applying retention: ${KEEP_DAILY}d ${KEEP_WEEKLY}w ${KEEP_MONTHLY}m"
if ! restic forget --prune \
      --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" ; then
  die "retention failed; the repository may be holding more than the policy says"
fi

# --- 5. does the repository still make sense --------------------------------
#
# Structure only: `restic check` without `--read-data` verifies that every
# snapshot's metadata resolves and that no pack is missing from the index. It
# does not read the data back, so it cannot detect a silently corrupted pack.
# Reading everything back is what the rehearsed restore is for, and that is a
# person with a runbook rather than a nightly job — see restore.md section 4.
# Saying which of the two this is matters, because "check passed" is exactly the
# sentence somebody will later remember as "the backup was verified".

STAGE="verify"
if ! restic check ; then
  die "the repository failed its structural check"
fi

# --- 6. figures and state ---------------------------------------------------

STAGE="state"
SNAP_COUNT="$(restic snapshots --json 2>/dev/null | /usr/bin/python3 -c '
import json,sys
try: print(len(json.load(sys.stdin)))
except Exception: print("-")
')"
REPO_BYTES="$(restic stats --mode raw-data --json 2>/dev/null | /usr/bin/python3 -c '
import json,sys
try: print(json.load(sys.stdin).get("total_size","-"))
except Exception: print("-")
')"
FIGURES="${SNAP_COUNT:--} ${REPO_BYTES:--} $RESTIC_REPO"

NOW="$(date '+%Y-%m-%dT%H:%M:%S%z')"
write_state "$NOW" "ok" "$FIGURES"
cleanup_work
STAGE="done"
log "backup complete: $SNAP_COUNT snapshots, $REPO_BYTES bytes of raw data in $RESTIC_REPO"
exit $RC
