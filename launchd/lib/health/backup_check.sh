# Sourced stage: backup check.
BACKUP_STATE_FILE="/opt/homebrew/var/nexus-backup.state"
BACKUP_WARN_HOURS=30
BACKUP_FAIL_HOURS=72

if [ ! -f "$BACKUP_STATE_FILE" ]; then
  # The state file is written by every exit path backup.sh has, so its absence
  # is not ambiguous: no run has ever completed. Either the plist was never
  # loaded or the job has never once reached its first line.
  fail "backup-never-run" "No backup has ever completed on this machine: $BACKUP_STATE_FILE does not exist. Either online.rcsl.backup.plist is not loaded, or the job has never fired. Until this changes there is no copy of the knowledge base or the database anywhere. See docs/runbooks/restore.md section 1."
else
  BACKUP_LAST_OK="$(sed -n '1p' "$BACKUP_STATE_FILE" 2>/dev/null)"
  BACKUP_OUTCOME="$(sed -n '2p' "$BACKUP_STATE_FILE" 2>/dev/null)"
  BACKUP_FIGURES="$(sed -n '3p' "$BACKUP_STATE_FILE" 2>/dev/null)"

  if [ -z "$BACKUP_LAST_OK" ]; then
    BACKUP_AGE_H=""
  else
    BACKUP_AGE_H="$(/usr/bin/python3 -c '
import datetime, sys
try:
    when = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%S%z")
except (ValueError, IndexError):
    sys.exit(1)
now = datetime.datetime.now(datetime.timezone.utc)
print(int((now - when).total_seconds() // 3600))
' "$BACKUP_LAST_OK" 2>/dev/null)"
  fi

  if [ -z "$BACKUP_LAST_OK" ]; then
    fail "backup-no-success" "The backup daemon has run and has never succeeded once (last outcome: ${BACKUP_OUTCOME:-unknown}). There is no copy of the knowledge base or the database anywhere. The stage it dies at is the suffix of that outcome; the detail is in $(dirname "$HEALTH_LOG")/nexus-backup.log."
  elif [ -z "$BACKUP_AGE_H" ]; then
    # A line that does not parse as a timestamp is not a pass. This is the third
    # answer the file's header argues every check should be able to give.
    warn "the backup state file's first line (${BACKUP_LAST_OK}) is not a timestamp this can read, so the age of the last backup is unknown rather than fine"
  elif [ "$BACKUP_AGE_H" -gt "$BACKUP_FAIL_HOURS" ] 2>/dev/null; then
    fail "backup-stale" "The last successful backup was ${BACKUP_AGE_H} hours ago (${BACKUP_LAST_OK}), past the ${BACKUP_FAIL_HOURS}-hour limit, and the last run said '${BACKUP_OUTCOME:-unknown}'. A daily job that has missed three days is not going to repair itself. See $(dirname "$HEALTH_LOG")/nexus-backup.log."
  elif [ "$BACKUP_AGE_H" -gt "$BACKUP_WARN_HOURS" ] 2>/dev/null; then
    warn "the last successful backup was ${BACKUP_AGE_H} hours ago (over ${BACKUP_WARN_HOURS}), last run '${BACKUP_OUTCOME:-unknown}'; one missed night, and a second would make it tier 1"
  elif [ "${BACKUP_OUTCOME:-}" != "ok" ]; then
    warn "the last backup run failed at stage '${BACKUP_OUTCOME#failed:}' but the one before it succeeded ${BACKUP_AGE_H}h ago, so this is one bad night rather than a broken chain"
  else
    note "backup: last succeeded ${BACKUP_AGE_H}h ago, ${BACKUP_FIGURES:-no figures recorded}"
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
